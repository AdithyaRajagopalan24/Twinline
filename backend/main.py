import math
import os

import pandas as pd
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

import state_store
from db import engine, init_schema
from topology import load_topology
from AImodule1 import StationAnomalyDetector
from AImodule2 import BottleneckPredictor
from kpi_business_value import compute_business_value_kpis

init_schema()

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# Load a trained bottleneck model if one exists; otherwise BottleneckPredictor falls back to its heuristic formula.
BOTTLENECK_MODEL_PATH = os.getenv(
    "TWINLINE_BOTTLENECK_MODEL_PATH",
    os.path.join(_BACKEND_DIR, "bottleneck_model.json")
)
_bottleneck_model_path = BOTTLENECK_MODEL_PATH if os.path.exists(BOTTLENECK_MODEL_PATH) else None
if _bottleneck_model_path:
    print(f"[TwinLine] Loading trained bottleneck model from {_bottleneck_model_path}")
else:
    print(f"[TwinLine] No trained bottleneck model found at {BOTTLENECK_MODEL_PATH} — "
          f"BottleneckPredictor will use its heuristic formula. Run train_bottleneck_model.py "
          f"to train and save a model, then restart the backend.")

# Load an offline-trained anomaly baseline if one exists; otherwise fall back to per-request statistics.
ANOMALY_BASELINE_PATH = os.getenv(
    "TWINLINE_ANOMALY_BASELINE_PATH",
    os.path.join(_BACKEND_DIR, "anomaly_baseline.joblib")
)
if os.path.exists(ANOMALY_BASELINE_PATH):
    detector = StationAnomalyDetector.load(ANOMALY_BASELINE_PATH)
    print(f"[TwinLine] Loaded offline-trained anomaly baseline from {ANOMALY_BASELINE_PATH} "
          f"({len(detector.baselines)} station(s)).")
else:
    detector = StationAnomalyDetector()
    print(f"[TwinLine] No trained anomaly baseline found at {ANOMALY_BASELINE_PATH} — "
          f"StationAnomalyDetector will fall back to per-request statistics until you run "
          f"train_anomaly_baseline.py and restart the backend.")

# Real station sequence + upstream/downstream neighbors, loaded once at startup.
G, TOPOLOGY = load_topology()

predictor = BottleneckPredictor(model_path=_bottleneck_model_path)


class Event(BaseModel):
    timestamp_utc: str
    station_id: str
    vehicle_id: str | None = None
    station_status: str = "Running"
    machine_state: str = "Running"
    cycle_time: float = 0
    utilization: float = 0
    vibration: float = 0
    temperature: float = 0
    current_wip: float = 0
    takt_time: float = 60
    standard_cycle_time: float = 60
    station_capacity: float = 20


app = FastAPI(title="TwinLine MVP")


def _clean(obj):
    """
    Recursively replaces NaN/Infinity floats with None.

    Some historical rows have NaN in numeric columns (e.g. blank cycle_time
    on FAULT rows in the raw CSVs), and plain json.dumps — which Starlette
    uses with allow_nan=False — raises ValueError on those instead of
    silently emitting invalid JSON. This sanitizes any dict/list/DataFrame
    output before it reaches a JSONResponse.
    """
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


@app.post("/ingest")
def ingest(e: Event):
    d = e.model_dump()
    sid = d["station_id"]
    d["station_status"] = (d.get("station_status") or "Running").strip().title()
    recent = state_store.get_recent_events(sid, limit=200)

    derived = state_store.compute_serving_features(d, hist=recent)

    neighbors = TOPOLOGY.get(sid, {})
    upstream_wip = state_store.get_latest_wip(neighbors.get("upstream"))
    downstream_wip = state_store.get_latest_wip(neighbors.get("downstream"))

    payload = {**d, "sensor_readings": {"vibration": d["vibration"], "temperature": d["temperature"]}}
    try:
        an = detector.evaluate(payload, recent)
    except Exception:
        an = {"station_health_score": 100, "anomaly_score": 0, "anomaly_type": "Normal", "severity": "Low"}

    bp = {
        **d,
        "previous_wip": derived["previous_wip"],
        "upstream_wip": upstream_wip,
        "downstream_wip": downstream_wip,
        "utilization_moving_avg": derived["utilization_moving_avg"],
        "cycle_time_moving_avg": derived["cycle_time_moving_avg"],
        "recent_downtime_sec": derived["recent_downtime_sec"],
    }
    try:
        pred = predictor.predict_station(bp)
    except Exception:
        pred = {
            "bottleneck_probability": 0, "predicted_time_to_bottleneck_min": None,
            "current_wip": d["current_wip"], "expected_wip": d["current_wip"],
            "expected_throughput_impact_vph": 0, "recommended_intervention": "Monitor"
        }

    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO station_events VALUES
            (:timestamp_utc,:station_id,:vehicle_id,:station_status,:machine_state,:cycle_time,
             :utilization,:vibration,:temperature,:current_wip,:takt_time,:standard_cycle_time,:station_capacity)"""),
            d)
        conn.execute(text("""INSERT INTO anomaly_results VALUES
            (:timestamp_utc,:station_id,:health_score,:anomaly_score,:anomaly_type,:severity)"""), {
            "timestamp_utc": d["timestamp_utc"], "station_id": sid,
            "health_score": an.get("station_health_score", 100), "anomaly_score": an.get("anomaly_score", 0),
            "anomaly_type": an.get("anomaly_type", "Normal"), "severity": an.get("severity", "Low")
        })
        conn.execute(text("""INSERT INTO bottleneck_predictions VALUES
            (:timestamp_utc,:station_id,:bottleneck_probability,:predicted_time_to_bottleneck_min,
             :current_wip,:expected_wip,:expected_throughput_impact_vph,:recommended_intervention)"""), {
            "timestamp_utc": d["timestamp_utc"], "station_id": sid,
            "bottleneck_probability": pred.get("bottleneck_probability", 0),
            "predicted_time_to_bottleneck_min": pred.get("predicted_time_to_bottleneck_min"),
            "current_wip": pred.get("current_wip", 0), "expected_wip": pred.get("expected_wip", 0),
            "expected_throughput_impact_vph": pred.get("expected_throughput_impact_vph", 0),
            "recommended_intervention": pred.get("recommended_intervention", "Monitor")
        })

    return {"station": sid, "anomaly": an, "prediction": pred}


@app.get("/stations")
def stations():
    try:
        result = state_store.get_all_latest_states()
        return JSONResponse(content=_clean(jsonable_encoder(result)))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e), "type": type(e).__name__})

@app.get("/history")
def history(points_per_station: int = 60):
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text("""
                SELECT timestamp_utc, station_id, cycle_time, vibration, temperature,
                       current_wip, takt_time, station_status
                FROM station_events
                ORDER BY timestamp_utc DESC
                LIMIT :limit
            """), conn, params={"limit": max(points_per_station, 1) * 50})

        if df.empty:
            return []

        df = df.sort_values("timestamp_utc")
        df["step"] = df.groupby("station_id").cumcount()
        df = df.groupby("station_id", group_keys=False).tail(points_per_station)
        df["timestamp_utc"] = df["timestamp_utc"].astype(str)
        return _clean(df.to_dict("records"))
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e), "type": type(e).__name__})

@app.get("/alerts")
def alerts():
    with engine.connect() as conn:
        df = pd.read_sql(text(
            "SELECT * FROM anomaly_results WHERE anomaly_score > 0.15 ORDER BY timestamp_utc DESC LIMIT 50"
        ), conn)
    return _clean(df.to_dict("records"))


@app.get("/predictions")
def predictions():
    # DISTINCT ON is for latest row per station_id.
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT DISTINCT ON (station_id) *
            FROM bottleneck_predictions
            ORDER BY station_id, timestamp_utc DESC
        """), conn)
    return _clean(df.to_dict("records"))


@app.get("/line-summary")
def summary():
    with engine.connect() as conn:
        station_count = conn.execute(text("SELECT COUNT(DISTINCT station_id) FROM station_events")).scalar()
        if not station_count:
            return {"stations": 0, "avg_health": 100, "total_wip": 0, "avg_cycle_time": 0}
        row = conn.execute(text("""
            SELECT AVG(health_score), SUM(current_wip), AVG(cycle_time)
            FROM anomaly_results a LEFT JOIN station_events s USING(timestamp_utc, station_id)
        """)).fetchone()
    return {
        "stations": station_count,
        "avg_health": round(row[0] or 100, 1),
        "total_wip": round(row[1] or 0, 1),
        "avg_cycle_time": round(row[2] or 0, 1)
    }


@app.get("/kpi")
def kpi(hours: int = 24):
    """
    Business-value KPIs (downtime, throughput, peak WIP) — before vs. after
    TwinLine's early-warning intervention — computed from everything ingested
    in the last `hours` hours. Wraps kpi_business_value.compute_business_value_kpis.
    """
    empty = {
        "downtime_before_sec": 0, "downtime_after_sec": 0, "downtime_reduction_pct": 0,
        "throughput_before_vph": 0, "throughput_after_vph": 0, "throughput_improvement_pct": 0,
        "peak_wip_before": 0, "peak_wip_after": 0, "peak_wip_reduction_pct": 0,
        "per_station": []
    }

    with engine.connect() as conn:
        raw = pd.read_sql(text("""
            SELECT timestamp_utc, station_id, cycle_time, takt_time,
                   standard_cycle_time, current_wip, station_status
            FROM station_events
            WHERE timestamp_utc >= NOW() - INTERVAL '1 hour' * :hours
        """), conn, params={"hours": hours})
        anomalies = pd.read_sql(text("""
            SELECT timestamp_utc AS timestamp, station_id, severity
            FROM anomaly_results
            WHERE timestamp_utc >= NOW() - INTERVAL '1 hour' * :hours
        """), conn, params={"hours": hours})

    if raw.empty:
        return empty

    # anomaly_results doesn't store alert_triggered directly, but AImodule1 sets
    # severity != "Low" exactly when alert_triggered is True — so this is equivalent.
    anomalies["alert_triggered"] = anomalies["severity"].fillna("Low") != "Low"

    try:
        kpis = compute_business_value_kpis(anomaly_results=anomalies, raw_timeline=raw)
    except Exception:
        return empty

    return {
        "downtime_before_sec": round(kpis.downtime_before_sec, 1),
        "downtime_after_sec": round(kpis.downtime_after_sec, 1),
        "downtime_reduction_pct": round(kpis.downtime_reduction_pct, 1),
        "throughput_before_vph": round(kpis.throughput_before_vph, 2),
        "throughput_after_vph": round(kpis.throughput_after_vph, 2),
        "throughput_improvement_pct": round(kpis.throughput_improvement_pct, 1),
        "peak_wip_before": round(kpis.peak_wip_before, 1),
        "peak_wip_after": round(kpis.peak_wip_after, 1),
        "peak_wip_reduction_pct": round(kpis.peak_wip_reduction_pct, 1),
        "per_station": _clean(kpis.per_station.round(1).to_dict("records")),
    }