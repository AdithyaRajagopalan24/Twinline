"""
Cloud SQL (PostgreSQL) connection module for the TwinLine backend.

Configuration follows the same DB_HOST/DB_USER/DB_PASS/DB_NAME/DB_PORT
convention used elsewhere in this project.

Local development: point these env vars at the local `db` service defined in
docker-compose.yml (or any local Postgres instance).

Cloud Run / production: point DB_HOST at your Cloud SQL instance's IP (when
using a VPC connector) or at `127.0.0.1` when running the Cloud SQL Auth
Proxy as a sidecar, and supply real credentials via Secret Manager / env
vars — never hardcode them.
"""

import os

from sqlalchemy import create_engine, text

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "password")
DB_NAME = os.getenv("DB_NAME", "twinline_db")
DB_PORT = os.getenv("DB_PORT", "5432")

DB_SOCKET_DIR = os.getenv("DB_SOCKET_DIR")

if DB_SOCKET_DIR:
    _CONNECTION_STRING = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@/{DB_NAME}?host={DB_SOCKET_DIR}"
else:
    _CONNECTION_STRING = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(_CONNECTION_STRING, pool_pre_ping=True, connect_args={"connect_timeout": 5})


def init_schema() -> None:
    """Creates the TwinLine tables if they don't already exist. Safe to call on every startup."""
    with engine.begin() as conn:
        conn.execute(text("""CREATE TABLE IF NOT EXISTS station_events(
            timestamp_utc TIMESTAMP, station_id VARCHAR, vehicle_id VARCHAR, station_status VARCHAR,
            machine_state VARCHAR, cycle_time DOUBLE PRECISION, utilization DOUBLE PRECISION,
            vibration DOUBLE PRECISION, temperature DOUBLE PRECISION, current_wip DOUBLE PRECISION,
            takt_time DOUBLE PRECISION, standard_cycle_time DOUBLE PRECISION,
            station_capacity DOUBLE PRECISION)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS anomaly_results(
            timestamp_utc TIMESTAMP, station_id VARCHAR, health_score DOUBLE PRECISION,
            anomaly_score DOUBLE PRECISION, anomaly_type VARCHAR, severity VARCHAR)"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS bottleneck_predictions(
            timestamp_utc TIMESTAMP, station_id VARCHAR, bottleneck_probability DOUBLE PRECISION,
            predicted_time_to_bottleneck_min DOUBLE PRECISION, current_wip DOUBLE PRECISION,
            expected_wip DOUBLE PRECISION, expected_throughput_impact_vph DOUBLE PRECISION,
            recommended_intervention VARCHAR)"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_station_events_ts ON station_events (timestamp_utc)"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_station_events_station_ts "
            "ON station_events (station_id, timestamp_utc DESC)"
        ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_anomaly_results_ts ON anomaly_results (timestamp_utc)"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_bottleneck_predictions_station_ts "
            "ON bottleneck_predictions (station_id, timestamp_utc)"
        ))
