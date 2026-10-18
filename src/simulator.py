"""M2 — Layer B, SIMULATED pack-verification scans: event contract, benign and clone scenarios, live demo feed.

Every pack, source, location and label here is synthetic. Benign behavior says nothing about chemical quality.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import random

from src.common import EPISODES_PER_SCENARIO, SEED, SPLITS, digest

CITIES = [("Chennai", "Tamil Nadu", 13.08, 80.27), ("Delhi", "Delhi", 28.61, 77.21),
          ("Bengaluru", "Karnataka", 12.97, 77.59), ("Coimbatore", "Tamil Nadu", 11.02, 76.96)]
SEEN_SCENARIOS = ["benign_repeat", "legitimate_distribution", "legitimate_travel", "clone_copy", "clone_burst"]
HELDOUT_SCENARIOS = ["delayed_sync", "slow_copy"]
CLONE_SCENARIOS = {"clone_copy", "clone_burst", "slow_copy"}


def candidate_id(product, batch_no, manufacturer_key):
    # Text signatures deliberately do not claim verified legal identity.
    return digest([product.strip().casefold(), batch_no.strip().casefold(), manufacturer_key.strip().casefold()])[:24]


def distance_km(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    delta = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371 * 2 * math.asin(min(1, math.sqrt(delta)))


@dataclass(frozen=True)
class ScanEvent:
    """One delivery. event_id identifies it; pack_id is an observed code, not physical-pack proof."""
    event_id: str
    pack_id: str
    product: str
    batch_no: str
    manufacturer_key: str
    event_time: str
    source_id: str
    latitude: float
    longitude: float
    simulated: bool

    @classmethod
    def parse(cls, payload):
        if not isinstance(payload, dict) or set(payload) != set(cls.__dataclass_fields__):
            raise ValueError("Event must contain exactly the documented ScanEvent fields.")
        for name in ("event_id", "pack_id", "product", "batch_no", "source_id", "manufacturer_key"):
            value = payload[name]
            if not isinstance(value, str) or len(value) > 2000:
                raise ValueError(f"Invalid {name}.")
            if name != "manufacturer_key" and not value.strip():
                raise ValueError(f"Empty {name}.")
        if not isinstance(payload["simulated"], bool):
            raise ValueError("simulated must be a boolean.")
        try:
            timestamp = datetime.fromisoformat(payload["event_time"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Event time must include a UTC offset.")
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("Invalid timezone-aware event_time.") from exc
        for name, limit in (("latitude", 90), ("longitude", 180)):
            value = payload[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -limit <= value <= limit:
                raise ValueError(f"Invalid {name}.")
        values = dict(payload)
        values["event_time"] = timestamp.astimezone(timezone.utc).isoformat()
        values["latitude"], values["longitude"] = float(values["latitude"]), float(values["longitude"])
        return cls(**values)

    @property
    def timestamp(self):
        return datetime.fromisoformat(self.event_time).timestamp()

    @property
    def candidate(self):
        return candidate_id(self.product, self.batch_no, self.manufacturer_key)


def references(df):
    reference = df[df["product"].str.strip().ne("") & df["batch_no"].str.strip().ne("")]
    if reference.empty:
        raise ValueError("No product/batch reference pairs available.")
    return reference.drop_duplicates(["product", "batch_no", "manufacturer_name_normalized"]).to_dict("records")


def scan_corpus(df, episodes_per_scenario=EPISODES_PER_SCENARIO, seed=SEED):
    """Labeled episodes on real CDSCO reference batches. Held-out families appear only in test."""
    if isinstance(episodes_per_scenario, bool) or not isinstance(episodes_per_scenario, int) or episodes_per_scenario < 2:
        raise ValueError("episodes_per_scenario must be an integer of at least two.")
    refs = references(df)
    rng = random.Random(seed)
    episodes = []
    for split in SPLITS:
        scenarios = SEEN_SCENARIOS + (HELDOUT_SCENARIOS if split == "test" else [])
        count = episodes_per_scenario if split == "train" else max(2, episodes_per_scenario//3)
        for scenario in scenarios:
            for index in range(count):
                eid = f"{split}-{scenario}-{index}"
                ref = rng.choice(refs)
                start = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=len(episodes))
                city_a, city_b = rng.sample(CITIES, 2)
                if scenario == "legitimate_travel":
                    city_a, city_b = rng.sample([city for city in CITIES if city[0] != "Delhi"], 2)
                source_count = rng.choice([1, 2, 3])
                count_events = rng.randint(2, 5)
                if scenario in {"legitimate_distribution", "clone_burst"}:
                    count_events = rng.randint(12, 30)
                payloads, districts = [], {}
                for k in range(count_events):
                    city, pack, seconds = city_a, f"PACK-{eid}", k*rng.randint(60, 240)
                    if scenario == "legitimate_distribution":
                        pack, city = f"PACK-{eid}-{k}", rng.choice(CITIES)
                    elif scenario in {"clone_copy", "slow_copy", "legitimate_travel"}:
                        city = city_a if k == 0 else city_b
                        # Slow copies and legitimate travel overlap; the label is the generator's scenario.
                        seconds = k * (rng.randint(30, 240) if scenario == "clone_copy" else rng.randint(3600, 7200))
                    elif scenario == "clone_burst":
                        seconds = k*rng.randint(1, 5)
                    event = dict(event_id=f"EVENT-{eid}-{k}", pack_id=pack, product=ref["product"],
                                 batch_no=ref["batch_no"], manufacturer_key=ref["manufacturer_name_normalized"],
                                 event_time=(start+timedelta(seconds=seconds)).isoformat(),
                                 source_id=f"SOURCE-{eid}-{k % source_count}",
                                 latitude=city[2], longitude=city[3], simulated=True)
                    payloads.append(event)
                    districts[event["event_id"]] = {"district": city[0], "state": city[1], "location_status": "synthetic_city_centroid"}
                    if scenario in {"benign_repeat", "delayed_sync"} and k == 0:
                        payloads.append(dict(event))  # Exact delivery retry, not a cloned pack.
                    if scenario == "legitimate_travel" and k == 1:
                        break
                if scenario == "delayed_sync":
                    payloads.reverse()  # Arrival order differs; features use observation time.
                episodes.append({"example_id": digest([seed, eid])[:24], "episode_id": eid, "split": split,
                                 "scenario": scenario, "label": int(scenario in CLONE_SCENARIOS), "events": payloads,
                                 "districts": districts, "simulated": True,
                                 "observation_end": max(ScanEvent.parse(e).timestamp for e in payloads)})
    packs = {s: {e["pack_id"] for ep in episodes if ep["split"] == s for e in ep["events"]} for s in SPLITS}
    if packs["train"] & packs["validation"] or packs["train"] & packs["test"] or packs["validation"] & packs["test"]:
        raise ValueError("Pack identities overlap scan splits.")
    return episodes


def demo_feed(df, seed=SEED, start=datetime(2026, 9, 15, 9, tzinfo=timezone.utc)):
    """Scripted, deterministic morning of simulated scans on real reference batches.

    Background: legitimate distribution (different packs, many districts). Then a benign repeat with an exact
    delivery retry, a copied pack seen in Chennai and Delhi four minutes apart, and a repeated-pack burst.
    """
    rng = random.Random(seed)
    refs = [r for r in references(df) if r["manufacturer_name_normalized"].strip() and r["source_category"] != "spurious"]
    counts = df[df["source_category"].ne("spurious")]["manufacturer_name_normalized"].value_counts()
    repeat = [r for r in refs if counts.get(r["manufacturer_name_normalized"], 0) >= 3]
    single = [r for r in refs if counts.get(r["manufacturer_name_normalized"], 0) == 1]
    batches = rng.sample(repeat, 12) + rng.sample(single, 12)
    events = []

    def scan(ref, minute, pack, city, source):
        events.append(dict(event_id=f"DEMO-{len(events):04d}", pack_id=pack, product=ref["product"], batch_no=ref["batch_no"],
                           manufacturer_key=ref["manufacturer_name_normalized"],
                           event_time=(start + timedelta(minutes=minute)).isoformat(), source_id=source,
                           latitude=city[2], longitude=city[3], simulated=True))
        return events[-1]

    for i, ref in enumerate(batches):
        for k in range(rng.randint(2, 3)):
            scan(ref, rng.randint(0, 150), f"PACK-D{i}-{k}", rng.choice(CITIES), f"PHARMACY-{rng.randint(1, 40):02d}")
    # Real spurious-list references often lack manufacturer text. Show that evidence gap in the
    # simulated feed without inventing a manufacturer identity or treating no history as safety.
    missing_identity = [r for r in references(df) if r["source_category"] == "spurious"
                        and not r["manufacturer_name_normalized"].strip()]
    for i, ref in enumerate(rng.sample(missing_identity, min(2, len(missing_identity)))):
        scan(ref, 70 + 20*i, f"PACK-UNAVAILABLE-{i}", rng.choice(CITIES), f"PHARMACY-{rng.randint(1, 40):02d}")
    repeat_ref, clone_ref, burst_ref = batches[0], batches[12], batches[13]
    chennai, delhi, bengaluru = CITIES[0], CITIES[1], CITIES[2]
    scan(repeat_ref, 160, "PACK-REPEAT", chennai, "PHARMACY-07")
    events.append(dict(scan(repeat_ref, 163, "PACK-REPEAT", chennai, "PHARMACY-07")))
    scan(clone_ref, 175, "PACK-CLONE", chennai, "PHARMACY-11")
    scan(clone_ref, 179, "PACK-CLONE", delhi, "PHARMACY-31")
    for k in range(12):
        scan(burst_ref, 190 + k*0.15, "PACK-BURST", bengaluru, f"PHARMACY-{20 + k % 2}")
    return sorted(events, key=lambda e: (e["event_time"], e["event_id"]))
