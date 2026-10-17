"""Shared paths, seeds, label constants and small helpers used by every layer."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"
MODELS = OUTPUTS / "models"
EVIDENCE = ROOT / "evidence"

SEED = 2026
EPISODES_PER_SCENARIO = 100
SPLITS = ("train", "validation", "test")
NSQ = ("central_nsq", "state_nsq")
SPURIOUS = "spurious"
HISTORY_TASK = "next_month_report_recurrence"
SCAN_TASK = "simulated_clone_episode"
BANNER = "Layer A: REAL CDSCO data. Layer B: SIMULATED scans. Scan anomalies are not proof of counterfeit."


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def is_linuxone():
    return platform.machine().lower() == "s390x"


def host_label():
    return "linuxone" if is_linuxone() else "laptop"


def cpu_facts():
    facts = {"logical_cpus": os.cpu_count(),
             "affinity_cpus": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None}
    try:
        lines = Path("/proc/cpuinfo").read_text().splitlines()
    except OSError:
        return facts
    for line in lines:
        key, _, value = line.partition(":")
        key = key.strip()
        if key in {"model name", "vendor_id", "features"} and key not in facts:
            facts[key] = value.strip()
        if key.startswith("processor 0") and "machine =" in value:
            facts["machine_type"] = value.split("machine =")[-1].strip()
    # Availability only; it does not show that a workload used the accelerator.
    facts["nnpa_facility_listed"] = "nnpa" in facts.get("features", "").split()
    return facts


def environment():
    packages = {}
    for name in ("numpy", "scipy", "pandas", "openpyxl", "scikit-learn", "snapml", "streamlit"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not installed"
    return {"host": host_label(), "machine": platform.machine(), "system": platform.system(),
            "release": platform.release(), "python": platform.python_version(),
            "platform": platform.platform(), "packages": packages, "cpu": cpu_facts()}


def model_grid(backend, seed=SEED):
    """Small fixed grids; selection uses validation average precision only."""
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if backend == "snapml":
        from snapml import BoostingMachineClassifier, LogisticRegression as SnapLogisticRegression
        return {
            **{f"snap_logistic_r{r}": make_pipeline(StandardScaler(), SnapLogisticRegression(
                regularizer=r, fit_intercept=True, random_state=seed)) for r in (0.1, 1.0, 10.0)},
            **{f"snap_boosting_d{d}": BoostingMachineClassifier(
                num_round=150, max_depth=d, learning_rate=0.05, random_state=seed, n_jobs=1) for d in (2, 3)},
        }
    if backend == "sklearn":
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.linear_model import LogisticRegression
        return {
            **{f"logistic_c{c}": make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=5000))
               for c in (0.1, 1.0, 10.0)},
            **{f"hist_gbm_d{d}": HistGradientBoostingClassifier(
                max_depth=d, learning_rate=0.05, max_iter=150, min_samples_leaf=20, random_state=seed) for d in (2, 3)},
        }
    raise ValueError("backend must be sklearn or snapml.")


def probability(model, rows, columns=None):
    frame = pd.DataFrame(rows)
    if columns is not None:
        frame = frame[columns]
    return model.predict_proba(np.asarray(frame, dtype=np.float32))[:, 1] if len(frame) else np.array([])


def fit_and_select(x, y, xv, yv, backend, seed=SEED):
    """Fit every grid candidate on train; keep the best validation AP (ties keep the earlier, simpler one)."""
    import time
    from sklearn.metrics import average_precision_score
    scores, fitted, seconds = {}, {}, {}
    for name, model in model_grid(backend, seed).items():
        start = time.perf_counter()
        model.fit(np.asarray(x, dtype=np.float32), np.asarray(y, dtype=np.float32))
        seconds[name] = time.perf_counter()-start
        scores[name] = float(average_precision_score(yv, probability(model, xv)))
        fitted[name] = model
    selected = max(scores, key=lambda name: (scores[name], -list(scores).index(name)))
    return fitted[selected], {"selected": selected, "candidate_validation_average_precision": scores,
                              "fit_seconds": seconds}


def selection_weights(scores, budget):
    """Expected selection at a budget; tied scores share remaining slots (exact random tie-break)."""
    scores = pd.Series(np.asarray(scores, dtype=float))
    weights = pd.Series(0.0, index=scores.index)
    remaining = min(budget, len(scores))
    for value in sorted(scores.unique(), reverse=True):
        if remaining <= 0:
            break
        tied = scores.index[scores.eq(value)]
        take = min(remaining, len(tied))
        weights[tied] = take/len(tied)
        remaining -= take
    return weights.to_numpy()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False, default=float) + "\n")
