# TwinLine AI

> **A real-time digital twin for vehicle assembly lines — see it, predict it, prevent it.**
>
> ![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
> ![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi)
> ![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-FF4B4B?logo=streamlit)
> ![Postgres](https://img.shields.io/badge/DB-PostgreSQL%2016-4169E1?logo=postgresql)

A digital twin that ingests live station events from a vehicle assembly
line, builds a real station-topology graph, scores every event for
anomalies and bottleneck risk with two offline-trained models, and streams
the result to a live Streamlit dashboard — backed by Postgres so state
survives restarts and multiple backend instances agree on what's happening.

Built by **Team InnovAstra (IIT Madras)** for the **Accenture Innovation
Challenge 2026**.

**Live demo:** https://twinline-dashboard-521007461820.asia-south1.run.app/

---

## Quick Start

**Docker (recommended — one command):**

```bash
docker-compose up --build
```

This starts Postgres, the FastAPI backend (`:8000`), and the Streamlit
dashboard (`:8501`). Open the dashboard:

```bash
open http://localhost:8501
```

The dashboard will be empty until events are flowing — feed it with the
replay script (see [Demo](#demo) below):

```bash
python scripts/publish_csv.py --csv data/anomaly_data/shopfloor_with_wip_scenarios.csv
```

**Local setup (no Docker):** see [Run locally](#run-locally) below.

No API keys needed — everything runs on synthetic data and locally-trained
models.

---

## What this is

TwinLine is **two stateless services sharing one Postgres database**, not a
single monolith and not (yet) the multi-module agentic platform described in
the strategic proposal — see
[`docs/architecture.md`](./docs/architecture.md) for the current-vs-target
breakdown, and [`docs/business-proposal.md`](./docs/business-proposal.md)
for the full strategic case.

- **Backend** (`backend/`) — FastAPI. Ingests station events, runs two
  offline-trained models (anomaly detection, bottleneck prediction) against
  each one, persists everything to Postgres, and serves read endpoints.
- **Dashboard** (`dashboard/`) — Streamlit. Polls the backend every 4
  seconds and renders live station state, anomaly alerts, bottleneck
  predictions, and before/after business KPIs.

### What's implemented vs. proposed

| Capability | Status |
|---|---|
| Anomaly detection (per-station IsolationForest baselines) | ✅ Implemented |
| Bottleneck prediction (XGBoost) | ✅ Implemented |
| Live Line Dashboard + Prediction Cockpit | ✅ Implemented |
| Before/after business-KPI computation (downtime, throughput, WIP) | ✅ Implemented |
| Defect prediction, material/stockout prediction, root-cause analysis | ❌ Proposed — see roadmap in `docs/business-proposal.md` |
| Streaming ingestion (GCP Pub/Sub + Dataflow), agentic layer, IAM/audit logging | ❌ Proposed — see `docs/architecture.md` |

---

## Architecture

```text
CSV replay / synthetic generator ──HTTP POST──▶ FastAPI backend (:8000)
                                                        │
                                        ┌───────────────┼────────────────┐
                                        ▼               ▼                ▼
                              Derive features   Topology lookup    Persist raw
                              (state_store.py)  (topology.py,      event
                                        │        NetworkX graph)        │
                                        ▼                                │
                          ┌─────────────┴─────────────┐                 │
                          ▼                            ▼                 │
              Anomaly detection              Bottleneck prediction       │
              (AImodule1.py,                 (AImodule2.py,              │
              IsolationForest)               XGBoost)                    │
                          │                            │                 │
                          └─────────────┬──────────────┘                 │
                                        ▼                                ▼
                                PostgreSQL (station_events, anomaly_results,
                                            bottleneck_predictions)
                                        │
                                        ▼
                     Streamlit dashboard (:8501) — polls every 4s
                     Live Line Dashboard · Live Diagnostics ·
                     Prediction Cockpit · Business KPIs
```

Full breakdown — data flow step by step, DB schema, design decisions, and
the target/vision architecture — is in
[`docs/architecture.md`](./docs/architecture.md).

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python 3.11) |
| Anomaly detection | scikit-learn (`IsolationForest`), trained offline |
| Bottleneck prediction | XGBoost (`XGBClassifier`), trained offline |
| Topology | NetworkX (station sequence graph) |
| Database | PostgreSQL 16 (SQLAlchemy) |
| Dashboard | Streamlit + Plotly, `streamlit-autorefresh` |
| Containerization | Docker, `docker-compose` |
| Deployment | Google Cloud Run (backend + dashboard), Cloud SQL, Secret Manager |

---

## Run locally

### Prerequisites

- Python 3.9+ (backend and dashboard both use plain `pip install -r requirements.txt`)
- A local PostgreSQL instance, or the `db` service from `docker-compose.yml`

### Four-terminal manual start

**Terminal 1 — Postgres** (reuse the compose service, or run your own):

```bash
docker run --rm -p 5432:5432 -e POSTGRES_PASSWORD=password -e POSTGRES_DB=twinline_db postgres:16-alpine
```

**Terminal 2 — Backend:**

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

**Terminal 3 — Dashboard:**

```bash
cd dashboard
pip install -r requirements.txt
streamlit run app.py
```

**Terminal 4 — Feed it data** (from the project root):

```bash
python scripts/publish_csv.py --csv data/anomaly_data/shopfloor_with_wip_scenarios.csv
```

Run the two training steps below **once first** — they write
`bottleneck_model.json` and `anomaly_baseline.joblib` into `backend/`, which
the server loads automatically on startup. Without them, the backend still
runs fine, just in heuristic/fallback mode (see
[Model training](#model-training) and `docs/architecture.md`).

### Ports

| Service | Port | URL |
|---|---|---|
| Backend (FastAPI) | 8000 | http://localhost:8000 |
| Dashboard (Streamlit) | 8501 | http://localhost:8501 |
| PostgreSQL | 5432 | `postgresql://postgres:password@localhost:5432/twinline_db` |

---

## Run with Docker

```bash
docker-compose up --build
```

This builds and starts three services defined in `docker-compose.yml`:
`db` (Postgres 16, with a health check gating backend startup), `backend`
(FastAPI on `:8000`), and `dashboard` (Streamlit on `:8501`, pointed at the
backend via `TWINLINE_API=http://backend:8000`).

```bash
# Stop containers
docker-compose down

# Stop and wipe the database volume (fresh start)
docker-compose down -v
```

Note: the model-training scripts below run against `backend/`'s local
filesystem and aren't part of the Docker build — train them (or copy in
already-trained artifacts) before building the backend image if you want
Docker to run with real models instead of the fallback heuristics.

---

## Model training

Both AI modules are trained **offline** from the synthetic normal-operation
data and loaded as artifacts at backend startup. Neither trains online from
live traffic — see `docs/architecture.md` for exactly how the fallback
behavior works and why.

### Bottleneck model (do this before deploying)

Without a trained model, `BottleneckPredictor` falls back to a heuristic
formula.

```bash
cd backend
python train_bottleneck_model.py \
  --master ../data/normal_data/station_master.csv \
  --shopfloor ../data/normal_data/shopfloor_stream.csv \
  --mes ../data/normal_data/mes_events.csv \
  --downtime ../data/anomaly_data/downtime_events.csv \
  --out bottleneck_model.json
```

### Anomaly baseline (do this before demoing/deploying)

Without a trained baseline, `StationAnomalyDetector` falls back to
per-request statistics only (no IsolationForest component).

```bash
cd backend
python train_anomaly_baseline.py \
  --master ../data/normal_data/station_master.csv \
  --shopfloor ../data/normal_data/shopfloor_stream.csv \
  --mes ../data/normal_data/mes_events.csv \
  --downtime ../data/anomaly_data/downtime_events.csv \
  --out anomaly_baseline.joblib
```

**Restart the backend after either step** — its startup log states which
mode it's running in (trained model vs. fallback), so you can confirm
before presenting or deploying.

---

## API reference

| Method & path | Purpose |
|---|---|
| `POST /ingest` | Ingest one station event; runs anomaly + bottleneck scoring and returns both inline |
| `GET /stations` | Latest known state per station |
| `GET /history?points_per_station=N` | Recent time series per station, for charting |
| `GET /alerts` | Recent anomaly results with `anomaly_score > 0.15` |
| `GET /predictions` | Latest bottleneck prediction per station |
| `GET /line-summary` | Line-wide rollup: station count, avg health, total WIP, avg cycle time |
| `GET /kpi?hours=N` | Before/after business-value KPIs (downtime, throughput, peak WIP) over the trailing window |

### Manual test request

```bash
curl -s -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp_utc": "2026-09-20T10:00:00Z",
    "station_id": "S01",
    "cycle_time": 58.0,
    "utilization": 0.9,
    "current_wip": 5,
    "station_status": "Running"
  }'
```

Every field besides `timestamp_utc` and `station_id` has a default (see the
`Event` model in `backend/main.py`), so this is the minimal viable payload.
The response includes both the anomaly evaluation and bottleneck prediction
for that event, computed inline.

For a continuous stream of realistic traffic instead of one-off calls, use
`scripts/sample_stream.py` or `scripts/publish_csv.py` — see
[Demo](#demo) below.

---

## Demo

### Demo flow

1. Start the backend + dashboard (Docker or the four-terminal setup above).
2. Feed it the anomalous scenario data:

```bash
python scripts/publish_csv.py --csv data/anomaly_data/shopfloor_with_wip_scenarios.csv
```

3. Open the dashboard and walk through the four tabs as events arrive:
   - **Live Line Dashboard** — live per-station state
   - **Live Diagnostics** — real-time anomaly alerts
   - **Prediction Cockpit** — bottleneck probabilities and recommended interventions
   - **Business KPIs** — downtime/throughput/peak-WIP, before vs. after

For a slower, talk-through-friendly stream instead of a fast CSV replay,
use `scripts/sample_stream.py`, which cycles through a fixed sequence of
normal and anomalous events with a configurable delay:

```bash
python scripts/sample_stream.py --api http://localhost:8000/ingest --delay 2
```

### Dashboard pages

| Tab | Shows |
|---|---|
| Live Line Dashboard | Live station state table — utilization, WIP, cycle time, vibration, temperature |
| Live Diagnostics | Real-time anomaly alerts |
| Prediction Cockpit | Bottleneck probabilities and recommended interventions per station |
| Business KPIs | Downtime / throughput / peak-WIP before-vs-after, line-wide and per-station |

---

## Deployment

Deployed on **Google Cloud Run** (backend + dashboard as separate services)
backed by **Cloud SQL** (PostgreSQL) and **Secret Manager** for the DB
password. See [`scripts/deploy_gcp_cloudrun.sh`](./scripts/deploy_gcp_cloudrun.sh)
for the exact `gcloud run deploy` commands, and
[`docs/DEPLOYMENT_AND_DEMO_PROCEDURE.md`](./docs/DEPLOYMENT_AND_DEMO_PROCEDURE.md)
for the full deployment/demo walkthrough.

```bash
./scripts/deploy_gcp_cloudrun.sh PROJECT_ID CLOUDSQL_INSTANCE [REGION] [DB_NAME] [DB_USER]
```

The backend connects to Cloud SQL over its Unix socket
(`DB_SOCKET_DIR=/cloudsql/...`) rather than a TCP host, which is why
`backend/db.py` supports both connection styles — see `docs/architecture.md`
for the local-vs-Cloud-Run configuration differences.

---

## Repository structure

| Folder | Purpose | Key contents |
|---|---|---|
| `backend/` | Core backend and digital twin logic | FastAPI app (`main.py`), AI modules, topology graph, DB layer, offline training scripts |
| `dashboard/` | Factory monitoring and visualization | Streamlit app, live metrics, anomaly alerts, bottleneck predictions |
| `data/` | Factory simulation and test data | Normal-operation data, anomaly/failure scenarios, synthetic dataset generator |
| `docs/` | Project documentation | Architecture, business proposal, deployment/demo procedure, diagrams |
| `scripts/` | Data generation and simulation utilities | CSV replay, continuous demo stream, Cloud Run deploy script |
| `Videos/` | Video demo submissions | Round 1 and Round 2 links |

### Root files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Local dev environment: Postgres + backend + dashboard |
| `sampleCases.txt` | Ad-hoc sample `/ingest` curl calls used during testing |
| `Roadmap.png` | Project roadmap (see also `docs/TwinLine_Maturity_Roadmap.png`) |
| `Draft_ArchitectureDiagram` | Early architecture sketch, superseded by `docs/TwinLine_Architecture.png` |

---

## Testing

`backend/testAImodules.py` is a manual inference smoke-test — it runs the
feature pipeline and both AI modules end-to-end against the synthetic
normal-operation data and writes `anomaly_outputs.csv` /
`bottleneck_outputs.csv` for inspection. It is not an automated test suite
(no pytest, no CI); run it directly to sanity-check the models after a
training run:

```bash
cd backend
python testAImodules.py
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Backend won't start / connection refused | Ensure Postgres is running and reachable at `DB_HOST`/`DB_PORT` (or `DB_SOCKET_DIR` on Cloud Run) |
| Predictions look flat / always heuristic | Check the backend startup log — it states whether `bottleneck_model.json` / `anomaly_baseline.joblib` were found, or whether it fell back |
| Dashboard shows no data | Confirm the backend is reachable at `TWINLINE_API` and that you've run a replay script (`publish_csv.py` / `sample_stream.py`) |
| `/history` or `/kpi` returns empty | No events ingested yet in the queried window — run a replay script first |
| Docker build fails on backend | `xgboost`/`scikit-learn` wheels can be slow on first build — this is expected, not a failure |
| Port 8000 or 8501 already in use | `lsof -ti:8000 -ti:8501 \| xargs kill -9` (Mac/Linux), or stop the conflicting process on Windows |

---

## Team

**Team InnovAstra, IIT Madras**

- **Adithya Rajagopalan** — pre-final year Mechanical Engineering, IIT Madras
- **Harish Kumar** — Mechanical Engineering undergraduate, IIT Madras

Video submissions: [Round 1](https://youtu.be/8xOx5ZAUogM) ·
[Round 2](https://youtu.be/ztIH7ZVQhQQ)

---

## See also

- [`docs/architecture.md`](./docs/architecture.md) — current prototype vs.
  target architecture, in technical detail
- [`docs/business-proposal.md`](./docs/business-proposal.md) — the
  strategic case, personas, risks, roadmap, and business KPIs
- [`docs/DEPLOYMENT_AND_DEMO_PROCEDURE.md`](./docs/DEPLOYMENT_AND_DEMO_PROCEDURE.md)
  — step-by-step deployment and demo walkthrough
