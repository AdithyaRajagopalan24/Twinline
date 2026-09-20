# data/

Synthetic factory data for a 12-station vehicle assembly line — 1,000
vehicles' worth of readings across ~15 hours of simulated production
(2026-08-26 04:00 → 18:59 UTC), used to train TwinLine's models and to
replay demo traffic into the backend. Nothing in this folder is real plant
data.

## The 12 stations

| ID | Name | ID | Name |
|---|---|---|---|
| S01 | Body Frame | S07 | Electrical |
| S02 | Underbody | S08 | Interior |
| S03 | Front Axle | S09 | Glass |
| S04 | Rear Axle | S10 | Wheel & Brake |
| S05 | Powertrain | S11 | Final Assembly |
| S06 | Cooling System | S12 | End of Line |

Sequence, upstream/downstream neighbors, `takt_time`, `standard_cycle_time`,
and `station_capacity` per station live in `normal_data/station_master.csv`
— this is the single source of truth for line topology (`backend/topology.py`
loads a copy of it at startup) and is what the training scripts join
against.

## `normal_data/` — healthy-line data, what the models train on

| File | Rows | Consumed by | Columns |
|---|---|---|---|
| `station_master.csv` | 12 | `topology.py`, all training scripts, `publish_csv.py` (master lookup) | `station_id, station_name, station_sequence, upstream_station, downstream_station, takt_time, standard_cycle_time, station_capacity` |
| `shopfloor_stream.csv` | 12,000 | `train_anomaly_baseline.py`, `train_bottleneck_model.py`, `testAImodules.py` (via `TwinLineFeaturePipeline`) | `timestamp_utc, station_id, vehicle_id, vehicle_present, station_status, machine_state, cycle_time, utilization, vibration, temperature, torque, pressure` |
| `mes_events.csv` | 12,000 | same as above | `timestamp_utc, vehicle_id, production_order, station_id, event_type, cycle_time, wip, production_status` |
| `digital_twin_state.csv` | 12,000 | `scenario_engine.py` only (as the base twin state it perturbs) | `timestamp_utc, station_id, station_sequence, upstream_station, downstream_station, vehicle_id, vehicle_present, station_status, machine_state, cycle_time, standard_cycle_time, takt_time, takt_deviation, cycle_time_to_takt_ratio, utilization, wip, queue, throughput_vehicles_per_hour, station_capacity, material_status` |
| `master_snapshot.csv` | 10,000 | *not consumed by any script* — a point-in-time station-config snapshot (`snapshot_id`, `configuration_status`), kept for reference | `snapshot_id, snapshot_timestamp_utc, station_id, station_sequence, upstream_station, downstream_station, takt_time, standard_cycle_time, station_capacity, configuration_status` |

`shopfloor_stream.csv` is the one that matters most day-to-day: it's the
sensor-level feed (cycle time, utilization, vibration, temperature, torque,
pressure) that both AI modules are trained against, and its schema is the
same one `scripts/publish_csv.py` expects when replaying a CSV into
`/ingest`.

## `anomaly_data/` — the demo/failure scenarios

Four named scenarios, defined in `scenario_manifest.csv`:

| Scenario | Name | Station | Effect |
|---|---|---|---|
| A | Cycle-time drift | S05 (Powertrain) | Cycle time gradually rises above takt |
| B | Station downtime | S05 (Powertrain) | Station enters `FAULT`; utilization drops to zero |
| C | WIP buildup | S05 / upstream | WIP grows as processing capacity falls behind takt |
| D | Sensor anomaly | S08 (Interior) | Vibration and temperature rise abnormally |

Scenario C isn't injected directly — it's a *derived* side effect of A and
B: `scenario_engine.py`'s `derive_wip()` grows WIP wherever the
cycle-time-to-takt ratio exceeds 1 or a station is in `FAULT`, so the WIP
buildup at S05 emerges naturally from the drift and downtime scenarios
already injected there.

| File | Rows | Role |
|---|---|---|
| `scenario_manifest.csv` | 4 | The table above, as data |
| `shopfloor_with_wip_scenarios.csv` | 12,000 | **The main demo file** — `shopfloor_stream.csv` with scenarios A, B, D injected and WIP derived (scenario C). This is what `train_bottleneck_model.py`/`train_anomaly_baseline.py`'s `--downtime` sibling data represents, and what you feed to `scripts/publish_csv.py` for the standard demo (see root `README.md` → Demo) |
| `downtime_events.csv` | 1 | The single station-downtime event (scenario B) generated at S05, with start/end timestamps and duration — consumed by `featureEngineering.py`/training scripts as the downtime signal |
| `shopfloor_anomalous.csv` | 12,000 | `shopfloor_stream.csv` with scenarios A, B, D injected but **before** WIP is derived — intermediate output, not consumed by any script |
| `digital_twin_state_anomalous.csv` | 12,000 | `digital_twin_state.csv` with the same scenarios merged in — intermediate output, not consumed by any script |
| `mes_events_normal.csv` | 12,000 | A passthrough copy of `normal_data/mes_events.csv` — MES events aren't perturbed by any scenario — not consumed by any script |

**Only `shopfloor_with_wip_scenarios.csv` and `downtime_events.csv` are
actually used** (by the training scripts and the demo replay). The other
anomaly-data files are `scenario_engine.py`'s intermediate/reference
outputs, kept so you can inspect what each stage of the injection did.

## `scenario_engine.py` — regenerating the anomaly data

Reads the four `normal_data/` files above, injects scenarios A/B/D into the
shopfloor stream, derives WIP (scenario C), and writes all six
`anomaly_data/` files in one pass:

```bash
cd data
python scenario_engine.py --input-dir normal_data --output-dir anomaly_data
```

The script's own `--input-dir`/`--output-dir` defaults
(`twinline_normal_data` / `twinline_anomaly_data`) don't match this repo's
actual folder names — always pass both flags explicitly, as above.

Only run this if you want to regenerate the anomaly data (e.g. after
changing `normal_data/shopfloor_stream.csv`, or to move the injected
stations/timing). The checked-in `anomaly_data/` files are already the
output of this script — you don't need to run it to use the demo.

## See also

- [`../docs/architecture.md`](../docs/architecture.md) — how this data feeds
  the training pipeline and the online feature pipeline
- Root [`README.md`](../README.md) → Model training, Demo — how to train
  against `normal_data/` and replay `anomaly_data/` into the backend
