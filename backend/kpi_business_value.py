"""
Computes the before/after business-value KPIs:
downtime reduction, throughput improvement, and peak-WIP
reduction attributable to TwinLine's early warning.

The simulator produces one ground-truth timeline per scenario run (e.g. S05
drifting into a fault). "Before" is simply what happened in
that timeline. "After" is a dufferent replay of the
same timeline: whenever Module 1 raises an alert, an intervention is assumed
to happen `intervention_lag_minutes` later, and from that point on the
station's cycle time is pulled back toward its standard cycle time instead of
continuing to drift/fault, for `intervention_effect_minutes`.

Usage
-----
    from kpi_business_value import compute_business_value_kpis

    kpis = compute_business_value_kpis(
        anomaly_results=df_anomalies,   # output of AImodule1.evaluate(), one row per event
        raw_timeline=raw_df,            # the underlying station/timestamp/cycle_time/takt_time/wip data
        intervention_lag_minutes=2.0,
        intervention_effect_minutes=15.0,
    )
    print(kpis.summary())
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class BusinessValueKPIs:
    downtime_before_sec: float
    downtime_after_sec: float
    throughput_before_vph: float
    throughput_after_vph: float
    peak_wip_before: float
    peak_wip_after: float
    per_station: pd.DataFrame = field(repr=False)

    @property
    def downtime_reduction_pct(self) -> float:
        if self.downtime_before_sec <= 0:
            return 0.0
        return (self.downtime_before_sec - self.downtime_after_sec) / self.downtime_before_sec * 100.0

    @property
    def throughput_improvement_pct(self) -> float:
        if self.throughput_before_vph <= 0:
            return 0.0
        return (self.throughput_after_vph - self.throughput_before_vph) / self.throughput_before_vph * 100.0

    @property
    def peak_wip_reduction_pct(self) -> float:
        if self.peak_wip_before <= 0:
            return 0.0
        return (self.peak_wip_before - self.peak_wip_after) / self.peak_wip_before * 100.0

    def summary(self) -> str:
        return (
            f"Downtime:   {self.downtime_before_sec:,.0f}s -> {self.downtime_after_sec:,.0f}s "
            f"({self.downtime_reduction_pct:+.1f}%)\n"
            f"Throughput: {self.throughput_before_vph:.2f} -> {self.throughput_after_vph:.2f} vph "
            f"({self.throughput_improvement_pct:+.1f}%)\n"
            f"Peak WIP:   {self.peak_wip_before:.1f} -> {self.peak_wip_after:.1f} "
            f"({self.peak_wip_reduction_pct:+.1f}%)"
        )


def _simulate_intervention(
    station_df: pd.DataFrame,
    intervention_lag_minutes: float,
    intervention_effect_minutes: float,
) -> pd.DataFrame:

    df = station_df.sort_values("timestamp_utc").reset_index(drop=True)
    after = df["cycle_time"].to_numpy(dtype=float).copy()
    standard = df["standard_cycle_time"].to_numpy(dtype=float)
    timestamps = pd.DatetimeIndex(df["timestamp_utc"])

    alert_times = df.loc[df["alert_triggered"] == True, "timestamp_utc"]
    lag = pd.Timedelta(minutes=intervention_lag_minutes)
    effect_window = pd.Timedelta(minutes=intervention_effect_minutes)

    for alert_time in alert_times:
        recovery_start = alert_time + lag
        recovery_end = recovery_start + effect_window
        mask = (timestamps >= recovery_start) & (timestamps <= recovery_end)
        if not mask.any():
            continue
        idx = np.where(mask)[0]
        n = len(idx)
        # Linear ramp from whatever the cycle time was at recovery start back to standard.
        start_val = after[idx[0]]
        target_val = standard[idx[0]] if not np.isnan(standard[idx[0]]) else start_val
        ramp = np.linspace(start_val, target_val, n)
        after[idx] = np.minimum(after[idx], ramp)

    df["cycle_time_after"] = after
    return df


def compute_business_value_kpis(
    anomaly_results: pd.DataFrame,
    raw_timeline: pd.DataFrame,
    intervention_lag_minutes: float = 2.0,
    intervention_effect_minutes: float = 15.0,
    fault_status_values=("Fault",),
) -> BusinessValueKPIs:

    raw = raw_timeline.copy()
    raw["timestamp_utc"] = pd.to_datetime(raw["timestamp_utc"])

    anomalies = anomaly_results.copy()
    anomalies["timestamp_utc"] = pd.to_datetime(anomalies["timestamp"])
    alert_lookup = anomalies[["station_id", "timestamp_utc", "alert_triggered"]]

    merged = pd.merge_asof(
        raw.sort_values("timestamp_utc"),
        alert_lookup.sort_values("timestamp_utc"),
        by="station_id",
        on="timestamp_utc",
        direction="nearest",
        tolerance=pd.Timedelta(minutes=1),
    )
    merged["alert_triggered"] = merged["alert_triggered"].fillna(False)

    per_station_rows = []
    all_after_frames = []

    for station, group in merged.groupby("station_id"):
        after_df = _simulate_intervention(group, intervention_lag_minutes, intervention_effect_minutes)
        all_after_frames.append(after_df)

        step_sec = _median_step_seconds(after_df["timestamp_utc"])

        downtime_before = (after_df["station_status"].isin(fault_status_values)).sum() * step_sec
        recovered_mask = after_df["cycle_time_after"] <= after_df["takt_time"]
        downtime_after = ((after_df["station_status"].isin(fault_status_values)) & ~recovered_mask).sum() * step_sec

        peak_wip_before = after_df["current_wip"].max()
        # Approximate WIP-after as scaling with the cycle-time reduction achieved.
        ct_ratio = np.divide(
            after_df["cycle_time_after"], after_df["cycle_time"],
            out=np.ones(len(after_df)), where=after_df["cycle_time"] > 0
        )
        peak_wip_after = (after_df["current_wip"] * np.minimum(ct_ratio, 1.0)).max()

        per_station_rows.append({
            "station_id": station,
            "downtime_before_sec": downtime_before,
            "downtime_after_sec": downtime_after,
            "peak_wip_before": peak_wip_before,
            "peak_wip_after": peak_wip_after,
        })

    per_station = pd.DataFrame(per_station_rows)
    full_after = pd.concat(all_after_frames, ignore_index=True)

    throughput_before = _throughput_vph(full_after, "cycle_time")
    throughput_after = _throughput_vph(full_after, "cycle_time_after")

    return BusinessValueKPIs(
        downtime_before_sec=per_station["downtime_before_sec"].sum(),
        downtime_after_sec=per_station["downtime_after_sec"].sum(),
        throughput_before_vph=throughput_before,
        throughput_after_vph=throughput_after,
        peak_wip_before=per_station["peak_wip_before"].sum(),
        peak_wip_after=per_station["peak_wip_after"].sum(),
        per_station=per_station,
    )


def _median_step_seconds(timestamps: pd.Series) -> float:
    diffs = timestamps.sort_values().diff().dropna().dt.total_seconds()
    return float(diffs.median()) if len(diffs) else 0.0


def _throughput_vph(df: pd.DataFrame, cycle_time_col: str) -> float:
    """Bottleneck-station throughput: line rate is capped by its slowest station."""
    avg_ct_by_station = df.groupby("station_id")[cycle_time_col].mean()
    slowest_avg_ct = avg_ct_by_station.max()
    return 3600.0 / slowest_avg_ct if slowest_avg_ct > 0 else 0.0


if __name__ == "__main__":
    import pandas as pd
    from featureEngineering import TwinLineFeaturePipeline
    from AImodule1 import StationAnomalyDetector

    pipeline = TwinLineFeaturePipeline(
        "station_master.csv", "shopfloor_stream.csv", "mes_events.csv", "downtime_events.csv"
    )
    payloads = pipeline.generate_ai_payloads()
    baseline_df = pipeline.build_digital_twin_state()

    detector = StationAnomalyDetector()
    detector.fit_baseline(baseline_df)

    results = [detector.evaluate(m1, pd.DataFrame()) for m1, _ in payloads]
    df_anomalies = pd.DataFrame(results)

    raw_timeline = pipeline.build_digital_twin_state()

    kpis = compute_business_value_kpis(
        anomaly_results=df_anomalies,
        raw_timeline=raw_timeline,
        intervention_lag_minutes=2.0,
        intervention_effect_minutes=15.0,
    )
    print(kpis.summary())
    print("\nPer-station breakdown:")
    print(kpis.per_station.to_string(index=False))
