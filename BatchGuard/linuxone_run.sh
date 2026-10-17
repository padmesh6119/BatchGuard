#!/usr/bin/env bash
# Matched BatchGuard workload on the assigned LinuxONE: verify, train, evaluate, benchmark, compare.
# Every command and its output is kept under reports/linuxone/<UTC stamp>-<machine>/ as evidence.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=reports/linuxone/${STAMP}-$(uname -m)
mkdir -p "$OUT"
exec > >(tee "$OUT/run.log") 2>&1

REQUIRE=--require-s390x
if [ "${ALLOW_NON_S390X:-0}" = "1" ]; then REQUIRE=; echo "WARNING: rehearsal on $(uname -m); results are not LinuxONE results."; fi

echo "== host"
date -u; uname -a; (lscpu || true); (free -m || true); (cat /etc/os-release || true)
$PY replay.py platform $REQUIRE | tee "$OUT/platform.json"
$PY - <<'EOF' | tee "$OUT/packages.txt"
import importlib
for name in ("numpy", "scipy", "pandas", "openpyxl", "sklearn", "snapml"):
    try:
        module = importlib.import_module(name)
        print(name, getattr(module, "__version__", "installed"))
    except ImportError as exc:
        print(name, "NOT INSTALLED", exc)
EOF

echo "== tests"
$PY -m unittest discover -s tests -v

echo "== train and evaluate (same bundle, seed and code as the laptop run)"
$PY train_models.py --output "$OUT/models-sklearn" --backend sklearn
$PY benchmark.py compare --reference models/baseline-v1 --candidate "$OUT/models-sklearn" --output "$OUT/compare-sklearn.json"
if $PY -c "import snapml" 2>/dev/null; then
  $PY train_models.py --output "$OUT/models-snapml" --backend snapml
  $PY benchmark.py compare --reference models/snapml-v1 --candidate "$OUT/models-snapml" --output "$OUT/compare-snapml.json"
else
  echo "Snap ML not installed; skipped. Install with: $PY -m pip install snapml"
fi

echo "== benchmark"
$PY benchmark.py run --models "$OUT/models-sklearn" --output "$OUT/benchmarks" $REQUIRE
if [ -d "$OUT/models-snapml" ]; then
  $PY benchmark.py run --models "$OUT/models-snapml" --output "$OUT/benchmarks" $REQUIRE
fi
mkdir -p reports/benchmarks
cp "$OUT"/benchmarks/*.json reports/benchmarks/

echo "== done: $OUT"
echo "Commit $OUT and reports/benchmarks/ so the dashboard platform panel shows these measured LinuxONE results."
