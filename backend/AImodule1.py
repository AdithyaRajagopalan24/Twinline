import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timezone
from sklearn.ensemble import IsolationForest


class StationAnomalyDetector:
    def __init__(self, z_threshold: float = 3.0, contamination: float = 0.05):
        self.z_threshold = z_threshold
        self.contamination = contamination
        self.baselines: dict = {}
        self.models: dict = {}
        self.is_fitted = False

    def _extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = pd.DataFrame(index=df.index)
        features["cycle_time"] = df["cycle_time"].astype(float)
        features["utilization"] = df["utilization"].astype(float)
        features["current_wip"] = df["current_wip"].astype(float)

        if "sensor_readings" in df.columns:
            features["vibration"] = df["sensor_readings"].apply(
                lambda x: x.get("vibration", 0.0) if isinstance(x, dict) else 0.0
            )
            features["temperature"] = df["sensor_readings"].apply(
                lambda x: x.get("temperature", 0.0) if isinstance(x, dict) else 0.0
            )
        else:
            features["vibration"] = df["vibration"].astype(float) if "vibration" in df.columns else 0.0
            features["temperature"] = df["temperature"].astype(float) if "temperature" in df.columns else 0.0

        return features

    def fit_baseline(self, baseline_df: pd.DataFrame) -> None:
        """Fits one baseline + one IsolationForest per station_id found in baseline_df."""
        if baseline_df.empty:
            raise ValueError("Baseline data cannot be empty.")
        if "station_id" not in baseline_df.columns:
            raise ValueError("Baseline data must include a station_id column to fit per-station baselines.")

        for station_id, group in baseline_df.groupby("station_id"):
            features = self._extract_features(group)
            if len(features) < 2:
                continue
            self.baselines[station_id] = {
                "cycle_time_mean": float(features["cycle_time"].mean()),
                "cycle_time_std": float(max(features["cycle_time"].std(), 1e-6)),
                "wip_mean": float(features["current_wip"].mean()),
                "wip_std": float(max(features["current_wip"].std(), 1e-6)),
            }
            model = IsolationForest(n_estimators=150, contamination=self.contamination, random_state=42)
            model.fit(features)
            self.models[station_id] = model

        self.is_fitted = len(self.baselines) > 0

    def save(self, path: str) -> None:
        joblib.dump({
            "z_threshold": self.z_threshold,
            "contamination": self.contamination,
            "baselines": self.baselines,
            "models": self.models,
        }, path)

    @classmethod
    def load(cls, path: str) -> "StationAnomalyDetector":
        obj = joblib.load(path)
        detector = cls(z_threshold=obj.get("z_threshold", 3.0), contamination=obj.get("contamination", 0.05))
        detector.baselines = obj.get("baselines", {})
        detector.models = obj.get("models", {})
        detector.is_fitted = len(detector.baselines) > 0
        return detector

    def _calculate_z_score(self, value: float, mean: float, std: float) -> float:
        return (value - mean) / std

    def evaluate(self, current_event: dict, recent_window_df: pd.DataFrame) -> dict:
        station_id = current_event["station_id"]
        cycle_time = float(current_event["cycle_time"])
        takt_time = float(current_event["takt_time"])
        utilization = float(current_event["utilization"])
        current_wip = float(current_event.get("current_wip", 0.0))
        station_status = current_event.get("station_status", "Running")
        sensor_readings = current_event.get("sensor_readings", {})
        vibration = float(sensor_readings.get("vibration", 0.0))
        temperature = float(sensor_readings.get("temperature", 0.0))

        baseline = self.baselines.get(station_id)
        model = self.models.get(station_id)

        if baseline is not None:
            ct_mean = baseline["cycle_time_mean"]
            ct_std = baseline["cycle_time_std"]
            wip_mean = baseline["wip_mean"]
            wip_std = baseline["wip_std"]
        elif recent_window_df is not None and len(recent_window_df) >= 2:
            ct_mean = recent_window_df["cycle_time"].mean()
            ct_std = max(recent_window_df["cycle_time"].std(), 1e-6)
            wip_mean = recent_window_df["current_wip"].mean()
            wip_std = max(recent_window_df["current_wip"].std(), 1e-6)
        else:
            ct_mean = current_event.get("standard_cycle_time", cycle_time)
            ct_std = max(abs(ct_mean) * 0.05, 1e-6)
            wip_mean = current_wip
            wip_std = 1.0

        z_cycle_time = self._calculate_z_score(cycle_time, ct_mean, ct_std)
        z_wip = self._calculate_z_score(current_wip, wip_mean, wip_std)

        input_features = pd.DataFrame([{
            "cycle_time": cycle_time,
            "utilization": utilization,
            "current_wip": current_wip,
            "vibration": vibration,
            "temperature": temperature
        }])

        ml_anomaly = model.predict(input_features)[0] == -1 if model is not None else False

        z_cycle_component = min(abs(z_cycle_time) / self.z_threshold, 1.0)
        z_wip_component = min(abs(z_wip) / self.z_threshold, 1.0)
        ml_component = 1.0 if ml_anomaly else 0.0

        anomaly_score = float(np.clip(
            0.50 * z_cycle_component + 0.20 * z_wip_component + 0.30 * ml_component,
            0.0, 1.0
        ))

        anomaly_type, severity = "Normal", "Low"

        if station_status == "Fault":
            anomaly_type, severity = "Station Fault", "Critical"
        elif station_status == "Blocked":
            anomaly_type, severity = "Station Blocked", "High"
        elif station_status == "Starved":
            anomaly_type, severity = "Station Starved", "High"
        elif cycle_time > takt_time:
            anomaly_type = "Cycle-Time Drift"
            severity = "High" if cycle_time / takt_time >= 1.20 else "Medium"
        elif abs(z_cycle_time) >= self.z_threshold:
            anomaly_type, severity = "Statistical Cycle-Time Anomaly", "Medium"
        elif abs(z_wip) >= self.z_threshold:
            anomaly_type, severity = "WIP Anomaly", "Medium"
        elif ml_anomaly:
            anomaly_type, severity = "Multi-Sensor Operational Anomaly", "Medium"

        health_score = 100.0 - anomaly_score * 50.0

        if cycle_time > takt_time:
            health_score -= ((cycle_time - takt_time) / takt_time) * 30.0

        if station_status == "Fault":
            health_score -= 50.0

        health_score = float(np.clip(round(health_score, 1), 0.0, 100.0))
        health_status = "Green" if health_score >= 80 else "Yellow" if health_score >= 50 else "Red"

        return {
            # Use the event's own timestamp when available, else fall back to "now".
            "timestamp": current_event.get("timestamp_utc") or datetime.now(timezone.utc).isoformat(),
            "station_id": station_id,
            "station_health_score": health_score,
            "health_status": health_status,
            "anomaly_score": round(anomaly_score, 3),
            "z_score_cycle_time": round(z_cycle_time, 2),
            "z_score_wip": round(z_wip, 2),
            "anomaly_type": anomaly_type,
            "severity": severity,
            "alert_triggered": severity != "Low"
        }
