# TwinLine AI 

## Team InnovAstra
We are Team InnovAstra from IIT Madras. 

I’m Adithya, a pre-final year Mechanical Engineering student at IIT Madras, exploring the intersection of engineering, AI, and technology. I’ve worked on projects spanning agentic AI, digital twins, simulation, and embedded systems, with hands-on hackathon experience building AI-powered applications. I’m here to build, learn fast, and hopefully turn a crazy idea into something that actually works. Besides academics, I'm an avid keyboard and guitar player.

I'm Harish Kumar, a Mechanical Engineering undergraduate at IIT Madras with a strong interest in technology, programming, and solving real-world problems. I enjoy building projects with Python, exploring engineering and manufacturing systems, and continuously learning new technologies. Beyond academics, I enjoy solving coding problems and working on hands-on projects. Fun fact: I enjoy switching between designing mechanical systems and debugging Python code—which are surprisingly similar forms of suffering.

## File Structure 



## Public Link

https://twinline-dashboard-521007461820.asia-south1.run.app/

## Architecture
Synthetic Data Generator -> FastAPI Digital Twin -> real station topology (NetworkX graph built from station_master.csv) + PostgreSQL/Cloud SQL history -> Anomaly Detection + Bottleneck Prediction -> Streamlit Live Line Dashboard + Prediction Cockpit.

All live state (latest station readings, previous_wip, moving averages,
recent downtime, upstream/downstream WIP) is read from Postgres/Cloud SQL on
every request rather than kept in per-instance memory, so the backend runs
safely under Cloud Run's default autoscaling (multiple instances, scale to
zero when idle).

## What is included
- Anomaly and bottleneck AI modules, trained offline per station
- Feature engineering / KPI utilities
- Normal and anomalous synthetic datasets
- FastAPI integration backend backed by Postgres/Cloud SQL
- Real station topology graph (NetworkX) for upstream/downstream WIP lookups
- Streamlit dashboard reading the same backend
- CSV replay script for a reproducible demo
- Optional MQTT adapter placeholder and GCP migration notes

## Storage
The backend stores history in PostgreSQL (Cloud SQL in production; a local
Postgres container for local dev — see docker-compose.yml). Connection
settings come from env vars (DB_HOST, DB_USER, DB_PASS, DB_NAME, DB_PORT, or
DB_SOCKET_DIR for Cloud Run's Cloud SQL Unix socket) — see backend/db.py and
docs/DEPLOYMENT_CONFIGURATION.md.

## Local run
Run the two training steps below once first (they write bottleneck_model.json
and anomaly_baseline.joblib into backend/, which the server loads automatically
on startup) — otherwise the backend still runs, just in heuristic/fallback mode.

Terminal 1 (start a local Postgres, or reuse `docker compose up db` from the project root):
docker run --rm -p 5432:5432 -e POSTGRES_PASSWORD=password -e POSTGRES_DB=twinline_db postgres:16-alpine

Terminal 2:
cd backend
pip install -r requirements.txt
uvicorn main:app --reload

Terminal 3:
cd dashboard
pip install -r requirements.txt
streamlit run app.py

Terminal 4 (from project root):
python scripts/publish_csv.py --csv data/anomaly_data/shopfloor_with_wip_scenarios.csv

## Training the bottleneck model (do this before deploying)
By default BottleneckPredictor falls back to a heuristic formula because no
trained model is loaded. To use the real XGBoost model instead:
cd backend
python train_bottleneck_model.py \
  --master ../data/normal_data/station_master.csv \
  --shopfloor ../data/normal_data/shopfloor_stream.csv \
  --mes ../data/normal_data/mes_events.csv \
  --downtime ../data/anomaly_data/downtime_events.csv \
  --out bottleneck_model.json
Restart the backend afterwards so it automatically loads backend/bottleneck_model.json
if present (see the startup log line confirming which mode it's running in).

## Training the anomaly baseline (do this before demoing/deploying)
By default StationAnomalyDetector has no learned baseline and falls back to
per-request statistics only (no IsolationForest component). To fit real
per-station baselines from the normal-operation data:
cd backend
python train_anomaly_baseline.py \
  --master ../data/normal_data/station_master.csv \
  --shopfloor ../data/normal_data/shopfloor_stream.csv \
  --mes ../data/normal_data/mes_events.csv \
  --downtime ../data/anomaly_data/downtime_events.csv \
  --out anomaly_baseline.joblib
Restart the backend afterwards — it automatically loads backend/anomaly_baseline.joblib
if present (see the startup log line confirming which mode it's running in,
and how many stations got a baseline).

## Demo sequence
Use the anomalous CSV. The replay feeds live events into the Digital Twin. Open Streamlit and show:
1. station states
2. anomaly alerts
3. bottleneck probabilities and intervention recommendations

## Deployment
See `docs/DEPLOYMENT_CONFIGURATION.md`. The package includes the Streamlit frontend, FastAPI backend, Dockerfiles, Docker Compose (with a local Postgres service), and a Cloud Run deployment script that provisions the Cloud SQL connection.
