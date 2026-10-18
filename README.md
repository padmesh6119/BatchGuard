# BatchGuard

Medicine inspection prioritization with source evidence and recorded human decisions.
Reports are real; demo scans are simulated. A scan alert is not proof of counterfeit
or unsafe medicine. Actual LinuxONE execution is pending access.

## Run on IBM LinuxONE

Extract the upload ZIP, open a terminal in `BatchGuard`, and use the host's Python
environment with the packages listed in `requirements.txt` available.

```sh
python3 scripts/preflight_linuxone.py
bash scripts/launch_linuxone.sh
```

The launcher requires an actual `s390x` host and starts the central approval demo
service on `127.0.0.1:8000`. Set `BATCHGUARD_PYTHON=/path/to/python` to choose an environment.
From your laptop, open an SSH tunnel, then browse to **http://127.0.0.1:8000**:

```sh
ssh -L 8000:127.0.0.1:8000 USER@HOST
```

Click **Start demo**. The included CSV drives a checked inspection shortlist.
Demo decisions are labelled; no inspection is dispatched. Reviewer IDs are
self-declared. Keep this demonstration service bound to loopback.

For local preview: `python3 -m app.server`. For offline preview, open
`outputs/dashboard.html` (recorded demo; no live model execution).

If transferred models are incompatible with the host package versions, rebuild:

```sh
python3 -m src.fusion run
python3 -m app.dashboard
```

Supporting docs, PPT/video material, screenshots, private state, Git history and
local virtual environments are excluded from the IBM upload. Font and map source
notices are retained under `app/fonts/` and `app/maps/`.
