"""Cross-check local analytical records against captured official CDSCO responses.

Network retrieval is explicit. Snapshots prove what was served when fetched,
not the original publication date or the legal identity of a manufacturer.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import unicodedata
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from src import layer_a
from src.common import ROOT, OUTPUTS, file_hash, write_json

ORIGIN = "https://cdscoonline.gov.in"
DIRECTORY = ROOT / "data" / "official"
FIELDS = {
    "nsq": {"product": "str_product_name", "batch_no": "str_batch_no",
            "manufacture_date_raw": "dt_manufacturing_date", "expiry_date_raw": "dt_expiry_date",
            "manufacturer_raw": "str_manufactured_by", "failure_type": "str_nsq_result",
            "reporting_source_raw": "str_reporting_source", "reporting_lab": "str_reported_by_lab_or_state",
            "reporting_month": "dt_reporting_month_year"},
    "spurious": {"product": "product_name_from_dtl", "batch_no": "str_batch_no",
                 "manufacture_date_raw": "dt_manufacturing_date", "expiry_date_raw": "dt_expiry_date",
                 "manufacturer_name_raw": "str_spurious_manufacturer_name", "manufactured_by_raw": "str_spurious_manufactured_by",
                 "nsq_remark": "str_nsq_remarks", "firm_reply": "str_firm_reply",
                 "reporting_source_raw": "str_reporting_source", "reporting_lab": "str_reported_by_lab_or_state",
                 "reporting_month": "dt_reporting_month_year"}}


def text(value):
    value = "" if value is None else str(value)
    return " ".join(unicodedata.normalize("NFKC", html.unescape(value)).casefold().split())


def field_text(field, value):
    value = text(value)
    prefixes = {"manufacture_date_raw": "manufacturing date:", "expiry_date_raw": "expiry date:",
                "manufacturer_name_raw": "manufacturer name:", "manufactured_by_raw": "manufactured by:",
                "nsq_remark": "nsq remark:", "firm_reply": "firm reply:"}
    prefix = prefixes.get(field)
    if prefix and value.startswith(prefix):
        value = value[len(prefix):].strip()
    if prefix and value in {"n/a", "na"}:
        value = ""
    if field in {"manufacture_date_raw", "expiry_date_raw", "reporting_month"}:
        for fmt in ("%b-%Y", "%B-%Y", "%m/%Y", "%Y-%m", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                date = datetime.strptime(value, fmt)
            except ValueError:
                continue
            if date.day == 1 and date.hour == date.minute == date.second == 0:
                return date.strftime("%Y-%m")
    return value


def decode_response(raw):
    try:
        decoded, encoding = raw.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        # The portal serves some registered-symbol bytes outside UTF-8.
        # Preserve the original bytes, and record this explicit fallback.
        decoded, encoding = raw.decode("cp1252"), "cp1252-fallback"
    value = json.loads(decoded)
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or not isinstance(value.get("aaData"), list):
        raise ValueError("Official response must contain an aaData list")
    return value["aaData"], encoding


def month_label(month):
    return datetime.strptime(month, "%Y-%m").strftime("%b-%Y").upper()


def check_rows(rows, kind, month):
    for row in rows:
        if not isinstance(row, dict) or set(FIELDS[kind].values()) - set(row):
            raise ValueError("Official response schema changed")
        if text(row["dt_reporting_month_year"]) != text(month_label(month)):
            raise ValueError("Official response contains a different reporting month")


def fetch(directory=DIRECTORY):
    directory = Path(directory)
    df = layer_a.load_dataset()
    responses = []
    for month in sorted(df["collection_month"].unique()):
        for kind in ("nsq", "spurious"):
            endpoint = "filteredNsqDrugTable" if kind == "nsq" else "filteredSpuriousDrugTable"
            url = ORIGIN + "/CDSCO/" + endpoint + "?" + urlencode({"month": month_label(month), "source": "All", "tab": kind})
            request = Request(url, headers={"User-Agent": "BatchGuard-source-audit/1.0", "Accept": "application/json"})
            with urlopen(request, timeout=30) as response:
                if urlsplit(response.geturl()).hostname != "cdscoonline.gov.in":
                    raise ValueError("Official endpoint redirected to another host")
                raw = response.read(10_000_001)
                if len(raw) > 10_000_000:
                    raise ValueError("Official response exceeded the audit size limit")
                headers = {name: response.headers.get(name) for name in ("Date", "Last-Modified", "Content-Type")}
            rows, encoding = decode_response(raw)
            check_rows(rows, kind, month)
            import hashlib
            sha = hashlib.sha256(raw).hexdigest()
            relative = "responses/" + sha + ".json"
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            responses.append({"month": month, "kind": kind, "url": url, "path": relative,
                              "sha256": sha, "rows": len(rows), "decoding": encoding,
                              "retrieved_at": datetime.now(timezone.utc).isoformat(), "http_headers": headers})
            print(f"Captured {month} {kind}: {len(rows)} records", flush=True)
    manifest = {"origin": ORIGIN, "responses": responses,
                "publication_date_status": "unavailable: response retrieval time is not original publication time"}
    write_json(directory / "manifest.json", manifest)
    return manifest


def compare(local, official, kind, month):
    check_rows(official, kind, month)
    mapping = FIELDS[kind]
    expected = {"spurious"} if kind == "spurious" else {"central_nsq", "state_nsq"}
    part = local[local["collection_month"].eq(month) & local["source_category"].isin(expected)]
    source = Counter(tuple(field_text(field, row[remote]) for field, remote in mapping.items()) for row in official)
    remaining = source.copy()
    unmatched, discrepancies = [], []
    for row in part.to_dict("records"):
        key = tuple(field_text(field, row.get(field, "")) for field in mapping)
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            unmatched.append(row["build_record_id"])
            candidates = [source_row for source_row in official
                          if text(source_row[mapping["product"]]) == text(row["product"])
                          and text(source_row[mapping["batch_no"]]) == text(row["batch_no"])]
            detail = {"record_id": row["build_record_id"], "exact_identity_candidates": len(candidates)}
            if len(candidates) == 1:
                detail["field_differences"] = {field: {"local": row.get(field, ""), "official": candidates[0][remote]}
                                                for field, remote in mapping.items()
                                                if field_text(field, row.get(field, "")) != field_text(field, candidates[0][remote])}
            discrepancies.append(detail)
    matched = len(part) - len(unmatched)
    return {"month": month, "kind": kind, "local_records": len(part), "official_records": len(official),
            "exact_field_matches": matched, "unmatched_local_record_ids": unmatched,
            "discrepancies": discrepancies,
            "official_records_not_represented": len(official) - matched,
            "compared_fields": list(mapping),
            "normalization": "Unicode NFKC, HTML entities, case/whitespace, labeled spurious-cell prefixes/missing markers, and explicit first-of-month Excel timestamps to month precision; no fuzzy identity or batch matching"}


def audit(directory=DIRECTORY, output=OUTPUTS / "source_audit.json"):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("origin") != ORIGIN:
        raise ValueError("Unrecognized source origin")
    local = layer_a.load_dataset()
    expected = {(m, kind) for m in local["collection_month"].unique() for kind in FIELDS}
    seen, comparisons = set(), []
    for entry in manifest["responses"]:
        key = (entry["month"], entry["kind"])
        if key not in expected or key in seen:
            raise ValueError("Unexpected or duplicated month/category in official manifest")
        seen.add(key)
        if len(entry["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in entry["sha256"]):
            raise ValueError("Invalid captured-response hash")
        expected_path = "responses/" + entry["sha256"] + ".json"
        if entry["path"] != expected_path or file_hash(directory / expected_path) != entry["sha256"]:
            raise ValueError("Captured official response hash mismatch")
        if urlsplit(entry["url"]).hostname != "cdscoonline.gov.in":
            raise ValueError("Captured response URL is not the official host")
        records, encoding = decode_response((directory / expected_path).read_bytes())
        comparison = compare(local, records, entry["kind"], entry["month"])
        comparisons.append({**comparison, "url": entry["url"], "response_sha256": entry["sha256"],
                            "retrieved_at": entry["retrieved_at"], "decoding": encoding})
    if seen != expected:
        raise ValueError("Official captures do not cover every local month and category")
    result = {"status": "live official-portal cross-check; supplied workbook download origin remains unverified",
              "processed_manifest_sha256": file_hash(layer_a.DATA_PROCESSED / "manifest.json"),
              "official_manifest_sha256": file_hash(directory / "manifest.json"),
              "records": len(local), "exact_field_matches": sum(c["exact_field_matches"] for c in comparisons),
              "unmatched_local_records": sum(len(c["unmatched_local_record_ids"]) for c in comparisons),
              "official_records_not_represented": sum(c["official_records_not_represented"] for c in comparisons),
              "comparisons": comparisons,
              "limits": ["Matching records confirm portal content at retrieval; no original release date is inferred.",
                         "Extra official rows can include documented duplicate exclusions or later source revisions.",
                         "Reporting month is not publication date. Response Date/Last-Modified headers are not record release dates.",
                         "Reported manufacturer text is not verified legal identity; these data contain no scan outcomes or tested/sold denominator."]}
    write_json(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fetch", "audit"))
    parser.add_argument("--directory", type=Path, default=DIRECTORY)
    parser.add_argument("--output", type=Path, default=OUTPUTS / "source_audit.json")
    args = parser.parse_args()
    try:
        result = fetch(args.directory) if args.command == "fetch" else audit(args.directory, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.command == "audit":
        print(json.dumps({k: result[k] for k in ("records", "exact_field_matches", "unmatched_local_records", "official_records_not_represented")}))
