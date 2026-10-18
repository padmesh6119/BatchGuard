#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
task_python="${BATCHGUARD_PYTHON:-python3}"
if [[ "$(uname -m)" != "s390x" ]]; then
  echo "This launcher requires s390x. Use python -m app.server for local execution." >&2
  exit 2
fi
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
"$task_python" scripts/preflight_linuxone.py
if [[ "${1:-}" == "--validate" ]]; then
  if [[ ! -f scripts/run_linuxone.sh || ! -d tests ]]; then
    echo "Full validation is available in the development checkout. Use this runtime upload without --validate." >&2
    exit 2
  fi
  bash scripts/run_linuxone.sh
elif [[ $# -gt 0 ]]; then
  echo "Usage: bash scripts/launch_linuxone.sh [--validate]" >&2
  exit 2
fi
echo "Connect from your laptop: ssh -L 8000:127.0.0.1:8000 USER@HOST"
echo "Open http://127.0.0.1:8000. The runtime receipt will describe this actual host."
exec "$task_python" -m app.server --port 8000 --authority
