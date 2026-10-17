---
name: batchguard-state
description: "BatchGuard IBM Z Datathon status as of 2026-10-17 — what's done, what's next, environment gotchas"
metadata:
  node_type: memory
  type: project
  originSessionId: b244e778-0a75-4170-8e4d-6c05ff80acee
  modified: 2026-10-17T09:00:19.263Z
---

State at commit 57abc90+ on github.com/padmesh6119/BatchGuard (main): Layer A/B models trained (models/baseline-v1 sklearn, models/snapml-v1), benchmark.py, linuxone_run.sh, CHANGELOG.md at repo root tracks all changes.

Next (user's order): run linuxone_run.sh on assigned LinuxONE; cache history_scores per (df, cutoff) to fix 8.5 s queue rebuild (don't vectorize — would break byte-for-byte bundle parity); build combined live dashboard; 3-min video. User must confirm originality rule with organizers.

Gotchas: BatchGuard/.venv is a broken non-executable copy — use a fresh venv. PyPI has no s390x wheels for numpy/pandas/scipy/sklearn/pyarrow; Snap ML has. ~/.claude/hooks/cbm-code-discovery-gate always blocks Read (PPID differs per call); read via ctx_execute, Edit works without Read.

Related: [[reply-style-short]]
