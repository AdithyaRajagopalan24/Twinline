# TwinLine AI

## 1. Objective
Demonstrate vehicle assembly-line monitoring and bottleneck prevention via Digital Twin.

## 2. Scope mapping
Data sources: Shopfloor streaming data, MES events and reference/master data.
Digital Twin: FastAPI + NetworkX (built from the real station sequence in
station_master.csv) + PostgreSQL (Cloud SQL) — Postgres is the shared truth
for live state.
AI: Anomaly Detection (per-station IsolationForest baselines, trained offline)
and Bottleneck Prediction (XGBoost, trained offline).
Dashboards: Live Line Dashboard and Prediction Cockpit.

## 3. Installation
Create a Python environment and install backend and dashboard requirements.

## 4. Start the Digital Twin
Run `uvicorn main:app --reload` inside backend.

## 5. Start Streamlit
Run `streamlit run app.py` inside dashboard.

## 5a. Train the bottleneck model (do this beforehand)
`BottleneckPredictor` uses a heuristic formula until it's given a trained
XGBoost model. Train one from the historical CSVs before the demo:
```bash
cd backend
python train_bottleneck_model.py \
  --master ../data/normal_data/station_master.csv \
  --shopfloor ../data/normal_data/shopfloor_stream.csv \
  --mes ../data/normal_data/mes_events.csv \
  --downtime ../data/anomaly_data/downtime_events.csv \
  --out bottleneck_model.json
```
Restart the backend — its startup log states whether it loaded the trained
model or fell back to the heuristic, so you can confirm which mode is live
before presenting.

## 5b. Train the anomaly baseline (do this before the demo)
`StationAnomalyDetector` falls back to per-request statistics only (no
IsolationForest component) until it's given an offline-trained, per-station
baseline:
```bash
cd backend
python train_anomaly_baseline.py \
  --master ../data/normal_data/station_master.csv \
  --shopfloor ../data/normal_data/shopfloor_stream.csv \
  --mes ../data/normal_data/mes_events.csv \
  --downtime ../data/anomaly_data/downtime_events.csv \
  --out anomaly_baseline.joblib
```
Restart the backend — its startup log confirms how many stations got a
trained baseline before you present.

## 7. Business-value demonstration
Run a baseline and anomalous replay, then compare:
- downtime
- vehicles/hour
- peak WIP