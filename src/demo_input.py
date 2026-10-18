"""Strict, public demo CSV contract. Relative times are rebased only for simulations."""
import csv
from datetime import datetime, timezone
import io
import math

from src.common import ROOT
from src.simulator import ScanEvent

DEMO_CSV = ROOT / 'data' / 'demo' / 'inspection_case.csv'
FIELDS = ('stage', 'event_id', 'pack_id', 'product', 'batch_no', 'manufacturer_key',
          'seconds_before_start', 'source_id', 'latitude', 'longitude', 'simulated')


def parse_demo_csv(text, now, namespace):
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > 24000:
        raise ValueError('Demo CSV must be nonempty and at most 24000 UTF-8 bytes')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), strict=True)
    if reader.fieldnames != list(FIELDS):
        raise ValueError('CSV header must be: ' + ','.join(FIELDS))
    result = []
    seen_conflict = False
    try:
        for line, row in enumerate(reader, 2):
            if len(result) >= 100 or None in row or any(value is None for value in row.values()):
                raise ValueError(f'Invalid CSV row {line}')
            stage = row.pop('stage')
            if stage not in {'baseline', 'conflict', 'retry'} or row['simulated'].lower() != 'true':
                raise ValueError(f'Row {line}: fixed-case inputs must be simulated and have a known stage')
            if stage == 'baseline' and seen_conflict:
                raise ValueError('Baseline rows must precede conflict and retry rows')
            seen_conflict |= stage != 'baseline'
            offset = float(row.pop('seconds_before_start'))
            if not math.isfinite(offset) or not 0 <= offset <= 21600:
                raise ValueError(f'Row {line}: seconds_before_start must be within 0–21600')
            row.update(latitude=float(row['latitude']), longitude=float(row['longitude']), simulated=True,
                       event_time=datetime.fromtimestamp(now-offset, timezone.utc).isoformat(),
                       event_id=f'{namespace}:{row["event_id"]}', pack_id=f'{namespace}:{row["pack_id"]}')
            event = ScanEvent.parse(row)
            result.append((stage, dict(event.__dict__)))
    except (csv.Error, OverflowError) as exc:
        raise ValueError('Invalid demo CSV: ' + str(exc)) from exc
    baseline = [event for stage, event in result if stage == 'baseline']
    conflicts = [event for stage, event in result if stage == 'conflict']
    retries = [event for stage, event in result if stage == 'retry']
    if len(baseline) != 12 or len(conflicts) != 2 or len(retries) != 1:
        raise ValueError('Fixed case requires 12 baseline rows, 2 conflict rows and 1 retry row')
    if len({ScanEvent.parse(e).candidate for e in baseline}) != 12:
        raise ValueError('Baseline must contain 12 distinct batch candidates')
    if ScanEvent.parse(conflicts[0]).candidate != ScanEvent.parse(conflicts[1]).candidate:
        raise ValueError('Conflict rows must concern the same batch candidate')
    if ScanEvent.parse(conflicts[0]).candidate not in {ScanEvent.parse(e).candidate for e in baseline}:
        raise ValueError('The conflict candidate must already appear in the baseline')
    if retries[0] not in conflicts:
        raise ValueError('Retry must exactly repeat a conflict row')
    return result
