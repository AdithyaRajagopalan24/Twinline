"""
Shared, DB-backed live state for the digital twin.

All station history and derived features (previous_wip, moving averages,
recent downtime, neighbor WIP) are read from Postgres on every request
rather than kept in per-process memory, so every backend instance sees the
same picture and nothing resets on restart.

Feature definitions here mirror featureEngineering.py's
TwinLineFeaturePipeline (rolling window of RECENT_WINDOW events including
the current reading; previous_wip = last known reading before this one) so
a model trained via train_bottleneck_model.py sees the same feature
distributions online as it did offline.
"""

import numpy as np
import pandas as pd
from sqlalchemy import text

from db import engine

RECENT_WINDOW = 10
DOWNTIME_LOOKBACK_MIN = 60
DOWN_STATUSES = {"Fault", "Blocked", "Starved"}


def get_recent_events(station_id: str, limit: int = 50) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(
            text("""SELECT * FROM station_events WHERE station_id = :sid
                    ORDER BY timestamp_utc DESC LIMIT :limit"""),
            conn, params={"sid": station_id, "limit": limit},
        )
    return df.iloc[::-1].reset_index(drop=True)


def get_latest_wip(station_id: str | None) -> float:
    if not station_id:
        return 0.0
    with engine.connect() as conn:
        row = conn.execute(
            text("""SELECT current_wip FROM station_events WHERE station_id = :sid
                    ORDER BY timestamp_utc DESC LIMIT 1"""),
            {"sid": station_id},
        ).fetchone()
    return float(row[0]) if row else 0.0


def _recent_downtime_sec(hist: pd.DataFrame, now_ts) -> float:
    """Approximates downtime within the last DOWNTIME_LOOKBACK_MIN minutes from a station's own event history."""
    if len(hist) < 2:
        return 0.0

    ts = pd.to_datetime(hist["timestamp_utc"], utc=True)
    now_ts = pd.Timestamp(now_ts)
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    cutoff = now_ts - pd.Timedelta(minutes=DOWNTIME_LOOKBACK_MIN)

    mask = (ts >= cutoff).to_numpy()
    hist = hist[mask].reset_index(drop=True)
    ts = ts[mask].reset_index(drop=True)
    if len(hist) < 2:
        return 0.0

    gaps = ts.diff().dt.total_seconds().fillna(0.0)
    was_down = hist["station_status"].shift(1).isin(DOWN_STATUSES)
    return float(gaps[was_down].sum())


def compute_serving_features(current_event: dict, hist: pd.DataFrame = None) -> dict:
    sid = current_event["station_id"]
    if hist is None:
        hist = get_recent_events(sid, limit=RECENT_WINDOW - 1)

    window_hist = hist.tail(RECENT_WINDOW - 1)
    cycle_times = window_hist["cycle_time"].astype(float).tolist() + [float(current_event["cycle_time"])]
    utils = window_hist["utilization"].astype(float).tolist() + [float(current_event["utilization"])]
    previous_wip = float(hist["current_wip"].iloc[-1]) if not hist.empty else float(current_event["current_wip"])

    return {
        "previous_wip": previous_wip,
        "cycle_time_moving_avg": float(np.mean(cycle_times)),
        "utilization_moving_avg": float(np.mean(utils)),
        "recent_downtime_sec": _recent_downtime_sec(hist, current_event["timestamp_utc"]),
    }


def get_all_latest_states() -> dict:
    """Latest known row per station, keyed by station_id."""
    with engine.connect() as conn:
        df = pd.read_sql(text("""
            SELECT DISTINCT ON (station_id) *
            FROM station_events
            ORDER BY station_id, timestamp_utc DESC
        """), conn)
    if df.empty:
        return {}
    df["timestamp_utc"] = df["timestamp_utc"].astype(str)
    return {rec["station_id"]: rec for rec in df.to_dict("records")}
