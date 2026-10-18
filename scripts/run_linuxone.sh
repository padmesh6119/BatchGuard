#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
task_python="${BATCHGUARD_PYTHON:-python3}"
if [[ "$(uname -m)" != "s390x" ]]; then
  echo "LinuxONE run stopped: this host is not s390x. No LinuxONE result was written." >&2
  exit 2
fi
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
"$task_python" -m unittest discover -s tests
"$task_python" -m src.fusion run
"$task_python" -m src.capacity_audit --backends sklearn snapml
"$task_python" -m src.temporal_audit
"$task_python" -m src.availability_audit
"$task_python" -m src.source_audit audit
"$task_python" -m src.fusion benchmark
"$task_python" -m src.scale_benchmark --events 5000 --repeats 2 --profile routine --backend sklearn
"$task_python" -m src.scale_benchmark --events 5000 --repeats 2 --profile repeat_heavy --backend sklearn
"$task_python" -m src.readiness
"$task_python" -m app.dashboard
echo "LinuxONE execution complete. Review outputs/benchmark_linuxone.json and outputs/scale_linuxone_*.json."
