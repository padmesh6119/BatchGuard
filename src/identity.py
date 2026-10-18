"""Find reviewable manufacturer-text variants, without silently merging identities."""
from collections import defaultdict
from difflib import SequenceMatcher
import re

from src.common import digest


def validate_reviews(reviews):
    """Reject contradictory reviewed links; never treat a similarity as approval."""
    parent = {}

    def root(name):
        parent.setdefault(name, name)
        if parent[name] != name:
            parent[name] = root(parent[name])
        return parent[name]

    for review in reviews:
        if review["decision"] == "same_entity":
            parent[root(review["left"])] = root(review["right"])
    for review in reviews:
        if review["decision"] == "different_entities" and root(review["left"]) == root(review["right"]):
            raise ValueError("Name reviews conflict: a same-entity path joins an explicitly different pair")


def text_key(value):
    return " ".join(re.findall(r"[A-Z0-9]+", value.upper()))


def suggestions(df, before, limit=50):
    past = df[df["collection_month"].lt(before)]
    past = past[past["manufacturer_name_normalized"].str.strip().ne("")]
    groups = {name: group for name, group in past.groupby("manufacturer_name_normalized")}
    blocks = defaultdict(list)
    for name in sorted(groups):
        key = text_key(name)
        if key:
            blocks[key.split()[0][:5]].append(name)
    pairs = []
    for names in blocks.values():
        for i, left in enumerate(names):
            for right in names[i+1:]:
                a, b = text_key(left), text_key(right)
                similarity = SequenceMatcher(None, a, b, autojunk=False).ratio()
                if similarity < .9:
                    continue
                # Conflicting postal codes warrant separate investigation, not an alias proposal.
                post_a, post_b = set(re.findall(r"\b\d{6}\b", a)), set(re.findall(r"\b\d{6}\b", b))
                if post_a and post_b and post_a.isdisjoint(post_b):
                    continue
                combined = past[past["manufacturer_name_normalized"].isin([left, right])]
                pairs.append({"pair_id": digest([left, right])[:24], "left": left, "right": right,
                              "similarity": round(similarity, 4), "status": "unreviewed",
                              "records": len(combined), "first_month": combined["collection_month"].min(),
                              "last_month": combined["collection_month"].max(),
                              "record_ids": sorted(combined["build_record_id"].unique()),
                              "source_files": sorted(combined["source_file"].unique()),
                              "reason": "Similar manufacturer text; legal identity has not been established."})
    pairs.sort(key=lambda pair: (-pair["similarity"], -pair["records"], pair["pair_id"]))
    return pairs[:limit]
