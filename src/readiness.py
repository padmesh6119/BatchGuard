"""Report which delivery claims have supporting artifacts; never manufacture evidence."""
import json

from src import layer_a
from src.common import DATA_RAW, OUTPUTS, file_hash, write_json
from src.field_model import load_card


def build(output=OUTPUTS / "delivery_status.json"):
    df = layer_a.load_dataset()
    manifest = json.loads((layer_a.DATA_PROCESSED / "manifest.json").read_text())
    bad_sources = [name for name, sha in manifest["sources"].items()
                   if not (DATA_RAW / name).is_file() or file_hash(DATA_RAW / name) != sha]
    linuxone_path = OUTPUTS / "benchmark_linuxone.json"
    linuxone = json.loads(linuxone_path.read_text()) if linuxone_path.is_file() else None
    linuxone_recorded = bool(linuxone and linuxone.get("environment", {}).get("machine") == "s390x"
                            and linuxone.get("backends"))
    field_path = OUTPUTS / "field_model" / "field_model_card.json"
    source_path = OUTPUTS / "source_audit.json"
    source = json.loads(source_path.read_text()) if source_path.is_file() else None
    if source and source.get("processed_manifest_sha256") != file_hash(layer_a.DATA_PROCESSED / "manifest.json"):
        source = None
    field_ready, field_error = False, "No adjudicated field model artifact"
    if field_path.is_file():
        try:
            card = load_card(field_path.parent)
            field_ready = card["field_review_ready"]
            field_error = "; ".join(card["readiness_reasons"])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            field_error = str(exc)
    result = {"delivery": "research prototype with local durable decisions",
              "source_workbook_integrity": {"passed": not bad_sources, "mismatches": bad_sources},
              "official_source_crosscheck": None if source is None else {
                  "matched_records": source["exact_field_matches"], "unmatched_records": source["unmatched_local_records"],
                  "official_records_not_represented": source["official_records_not_represented"]},
              "publication_lag_sensitivity_report": (OUTPUTS / "availability_audit.json").is_file(),
              "retrospective_capacity_report": (OUTPUTS / "capacity_audit.json").is_file(),
              "rolling_history_audit": (OUTPUTS / "temporal_audit.json").is_file(),
              "linuxone_benchmark_recorded": linuxone_recorded,
              "field_review_ready": field_ready, "field_model_detail": field_error,
              "publication_dates_missing": int(df["release_date"].str.strip().eq("").sum()),
              "records": len(df),
              "external_evidence_still_needed": [
                  "A real LinuxONE run and comparable workload measurements" if not linuxone_recorded else "A platform comparison including allocation, cost and reliability",
                  "Independently adjudicated real scan outcomes" if not field_ready else "Independent prospective scan validation",
                  "A domain expert's recorded workflow review and measured task times",
                  "Verified publication dates, legal manufacturer identity and representative testing denominators"],
              "service_boundary": "Loopback-only team demonstration; reviewer IDs are declared, not authenticated. Public deployment requires authenticated access and operational controls.",
              "audit_boundary": "SQLite persists all changes. Hash chaining detects changes against a separately retained head; it is not a signature or an immutable external log."}
    write_json(output, result)
    return result


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
