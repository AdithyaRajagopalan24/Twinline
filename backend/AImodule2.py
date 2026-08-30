import numpy as np
import pandas as pd
import xgboost as xgb


class BottleneckPredictor:

    def __init__(self, model_path: str = None, forecast_horizon_min: int = 10):
        self.forecast_horizon_min = forecast_horizon_min
        self.model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            eval_metric="logloss",
            random_state=42
        )
        self.is_trained = False
        if model_path:
            self.model.load_model(model_path)
            self.is_trained = True

    def extract_derived_features(self, df: pd.DataFrame) -> pd.DataFrame:
        features = pd.DataFrame(index=df.index)
        cycle_time = df["cycle_time"].astype(float)
        takt_time = df["takt_time"].astype(float)
        current_wip = df["current_wip"].astype(float)
        previous_wip = df["previous_wip"].astype(float)
        utilization = df["utilization"].astype(float)

        features["ct_to_takt_ratio"] = cycle_time / takt_time.replace(0, np.nan)
        features["distance_from_takt"] = cycle_time - takt_time
        features["wip_growth_rate"] = current_wip - previous_wip
        features["upstream_wip"] = df["upstream_wip"].astype(float)
        features["downstream_wip"] = df["downstream_wip"].astype(float)
        features["utilization_trend"] = utilization - df["utilization_moving_avg"].astype(float)
        features["cycle_time_trend"] = cycle_time - df["cycle_time_moving_avg"].astype(float)
        features["recent_downtime_sec"] = df["recent_downtime_sec"].astype(float)
        features["cycle_time"] = cycle_time
        features["utilization"] = utilization
        features["current_wip"] = current_wip
        features["station_capacity"] = df["station_capacity"].astype(float)

        features = features.replace([np.inf, -np.inf], np.nan)
        features = features.fillna(0.0)
        return features

    def train(self, historical_df: pd.DataFrame, target: pd.Series) -> None:
        X = self.extract_derived_features(historical_df)
        self.model.fit(X, target)
        self.is_trained = True

    def predict_station(self, station_payload: dict) -> dict:
        df = pd.DataFrame([station_payload])
        X = self.extract_derived_features(df)
        if self.is_trained:
            bottleneck_probability = float(self.model.predict_proba(X)[0][1])
        else:
            bottleneck_probability = self._heuristic_probability(station_payload)

        bottleneck_probability = float(np.clip(bottleneck_probability, 0.0, 1.0))
        current_wip = float(station_payload["current_wip"])
        previous_wip = float(station_payload["previous_wip"])
        station_capacity = float(station_payload["station_capacity"])
        takt_time = float(station_payload["takt_time"])
        cycle_time = float(station_payload["cycle_time"])
        wip_growth = current_wip - previous_wip

        time_to_bottleneck = self._estimate_time_to_bottleneck(
            current_wip=current_wip, station_capacity=station_capacity,
            wip_growth_rate=wip_growth, bottleneck_probability=bottleneck_probability
        )
        expected_wip = self._estimate_future_wip(current_wip=current_wip, wip_growth_rate=wip_growth)
        nominal_throughput = 3600.0 / takt_time if takt_time > 0 else 0.0
        current_throughput = 3600.0 / cycle_time if cycle_time > 0 else 0.0
        potential_throughput_loss = max(nominal_throughput - current_throughput, 0.0)
        expected_throughput_impact = bottleneck_probability * potential_throughput_loss

        return {
            "station_id": station_payload["station_id"],
            "bottleneck_probability": round(bottleneck_probability, 3),
            "predicted_time_to_bottleneck_min": time_to_bottleneck,
            "current_wip": round(current_wip, 1),
            "expected_wip": round(expected_wip, 1),
            "nominal_throughput_vph": round(nominal_throughput, 2),
            "current_throughput_vph": round(current_throughput, 2),
            "expected_throughput_impact_vph": round(expected_throughput_impact, 2),
            "recommended_intervention": self._get_intervention(bottleneck_probability, station_payload["station_id"])
        }

    def _heuristic_probability(self, payload: dict) -> float:
        cycle_time = float(payload["cycle_time"])
        takt_time = float(payload["takt_time"])
        current_wip = float(payload["current_wip"])
        previous_wip = float(payload["previous_wip"])
        utilization = float(payload["utilization"])

        ct_ratio = cycle_time / takt_time if takt_time > 0 else 1.0
        wip_growth = max(current_wip - previous_wip, 0.0)
        ct_risk = np.clip((ct_ratio - 1.0) / 0.25, 0.0, 1.0)
        wip_risk = np.clip(wip_growth / 3.0, 0.0, 1.0)
        utilization_risk = np.clip((utilization - 0.80) / 0.20, 0.0, 1.0)
        probability = 0.50 * ct_risk + 0.30 * wip_risk + 0.20 * utilization_risk
        return float(np.clip(probability, 0.0, 1.0))

    def _estimate_time_to_bottleneck(self, current_wip: float, station_capacity: float,
                                      wip_growth_rate: float, bottleneck_probability: float):
        remaining_capacity = station_capacity - current_wip
        if bottleneck_probability < 0.40 or remaining_capacity <= 0 or wip_growth_rate <= 0:
            return None
        time_minutes = remaining_capacity / wip_growth_rate
        return round(max(time_minutes, 0.0), 1)

    def _estimate_future_wip(self, current_wip: float, wip_growth_rate: float):
        future_wip = current_wip + max(wip_growth_rate, 0.0) * self.forecast_horizon_min
        return max(future_wip, current_wip)

    def _get_intervention(self, probability: float, station_id: str) -> str:
        if probability >= 0.75:
            return f"CRITICAL: Prioritize {station_id}. Prepare maintenance or line-buffer intervention."
        if probability >= 0.40:
            return f"ATTENTION: Monitor {station_id} and upstream WIP. Investigate rising cycle time."
        return "Line operating within normal parameters."
