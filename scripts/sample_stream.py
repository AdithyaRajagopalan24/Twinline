"""
Continuously streams demo entries into the TwinLine /ingest endpoint so the
dashboard has something moving without you running curl by hand.

Cycles through:
  - 3 normal entries (S01, S03, S06 — healthy cycle time / vibration / temp)
  - 1 "Station Fault / downtime" anomaly (S05, station_status=Fault)     -> scenario B
  - 1 "Multi-sensor anomaly" (S08, elevated vibration + temperature)    -> scenario D

Usage
-----
    python scripts/demo_stream.py --api https://twinline-backend-XXXX.asia-south1.run.app/ingest
    python scripts/demo_stream.py --api http://localhost:8000/ingest --delay 2
    python scripts/demo_stream.py --api ... --cycles 3   # stop after 3 full loops instead of forever

Leave this running in a VS Code terminal (locally) while your GCP dashboard
tab is open with autorefresh on — every entry it posts will show up on the
next refresh cycle.
"""
import argparse
import itertools
import time
from datetime import datetime, timezone

import requests

p = argparse.ArgumentParser()
p.add_argument("--api", default="http://localhost:8000/ingest", help="Full URL to the /ingest endpoint")
p.add_argument("--delay", type=float, default=3.0, help="Seconds between entries")
p.add_argument("--cycles", type=int, default=0, help="Number of loops through the sequence (0 = run forever)")
args = p.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Normal entries — values in line with the healthy ranges in data/normal_data/shopfloor_stream.csv
NORMAL = [
    dict(station_id="S01", cycle_time=59.8, utilization=0.87, vibration=1.21, temperature=48.9,
         current_wip=8, takt_time=60.0, standard_cycle_time=58.1, station_capacity=20,
         station_status="Running", machine_state="Active"),
    dict(station_id="S03", cycle_time=58.4, utilization=0.83, vibration=1.21, temperature=50.2,
         current_wip=6, takt_time=60.0, standard_cycle_time=58.43, station_capacity=20,
         station_status="Running", machine_state="Active"),
    dict(station_id="S06", cycle_time=57.1, utilization=0.88, vibration=1.20, temperature=49.6,
         current_wip=5, takt_time=60.0, standard_cycle_time=57.5, station_capacity=20,
         station_status="Running", machine_state="Active"),
]

# Anomaly type 1 (scenario B — station downtime/fault): utilization drops to 0,
# station_status="Fault" -> AImodule1 flags this "Station Fault" / Critical severity.
ANOMALY_DOWNTIME = dict(
    station_id="S05", cycle_time=0, utilization=0.0, vibration=1.26, temperature=52.4,
    current_wip=14, takt_time=60.0, standard_cycle_time=57.0, station_capacity=20,
    station_status="Fault", machine_state="Fault",
)

# Anomaly type 2 (scenario D — sensor anomaly): station keeps running but vibration
# and temperature drift well above normal -> flagged as a multi-sensor anomaly.
ANOMALY_SENSOR = dict(
    station_id="S08", cycle_time=57.6, utilization=0.88, vibration=2.05, temperature=59.8,
    current_wip=9, takt_time=60.0, standard_cycle_time=58.0, station_capacity=20,
    station_status="Running", machine_state="Active",
)

SEQUENCE = [*NORMAL, ANOMALY_DOWNTIME, *NORMAL[:2], ANOMALY_SENSOR]
_ANOMALY_IDS = {id(ANOMALY_DOWNTIME), id(ANOMALY_SENSOR)}

vehicle_counter = itertools.count(1)
cycle = 0

print(f"Streaming to {args.api} every {args.delay}s "
      f"({'forever' if args.cycles == 0 else f'{args.cycles} cycle(s)'}). Ctrl+C to stop.\n")

while True:
    for base in SEQUENCE:
        payload = dict(base)
        payload["timestamp_utc"] = now_iso()
        payload["vehicle_id"] = f"VH{next(vehicle_counter):05d}"

        try:
            r = requests.post(args.api, json=payload, timeout=10)
            status = r.status_code
        except requests.RequestException as exc:
            status = f"ERROR ({exc})"

        tag = "ANOMALY" if id(base) in _ANOMALY_IDS else "normal "
        print(f"[{tag}] {payload['station_id']:>4}  status={payload['station_status']:<8} "
              f"cycle_time={payload['cycle_time']:<6} vib={payload['vibration']:<6} "
              f"temp={payload['temperature']:<6} -> {status}")

        time.sleep(args.delay)

    cycle += 1
    if args.cycles and cycle >= args.cycles:
        break

print("\nDone.")
