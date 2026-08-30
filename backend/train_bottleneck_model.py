"""
Trains AImodule2's BottleneckPredictor on historical simulator output.

Why this exists
----------------
BottleneckPredictor currently falls back to `_heuristic_probability` for every
prediction because nothing ever calls `.train()` with real labels. This script
closes that gap for the POC:

1. Runs the feature pipeline over historical CSVs to get the same derived
   features BottleneckPredictor uses at inference time.
2. Builds a *weak label* per (station, timestamp): "did this station actually
   become a bottleneck within the next `horizon_minutes`?" We don't have a
   human-annotated ground truth, so the label is defined from data the
   simulator already produces (station_status == 'Blocked'/'Starved'/'Fault',
   or cycle_time exceeding takt_time) looked FORWARD in time from each row.
   This keeps the model's job honest: predict the future event from present
   features, rather than fitting the same heuristic that produces the label.
3. Trains XGBoost on those (features, label) pairs and saves it so
   BottleneckPredictor(model_path=...) can load it directly.

Usage
-----
    python train_bottleneck_model.py \
        --master station_master.csv \
        --shopfloor shopfloor_stream.csv \
        --mes mes_events.csv \
        --downtime downtime_events.csv \
        --horizon-minutes 10 \
        --out bottleneck_model.json

Replace the CSV paths with your simulator's actual historical export before
running this for real. On a handful of stations / a few thousand rows the
heuristic label will be sparse — the more scenario runs (drift, fault, WIP
buildup) you feed in, the better the learned model will generalize versus
the heuristic it's meant to replace.
"""

import argparse

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split

from AImodule2 import BottleneckPredictor
from featureEngineering import TwinLineFeaturePipeline


def build_labeled_dataset(pipeline: TwinLineFeaturePipeline, horizon_minutes: int = 10) -> pd.DataFrame:
    """
    Returns a DataFrame with one row per (station, timestamp) containing the
    same derived features BottleneckPredictor uses, plus a `label` column:
    1 if the station becomes a bottleneck (Blocked/Starved/Fault, or
    cycle_time > takt_time) at any point in the next `horizon_minutes`.
    """
    twin_state = pipeline.build_digital_twin_state()
    wip_lookup = pipeline._build_wip_lookup(twin_state)

    rows = []
    for _, row in twin_state.iterrows():
        rows.append({
            "station_id": row["station_id"],
            "timestamp_utc": row["timestamp_utc"],
            "cycle_time": row["cycle_time"],
            "takt_time": row["takt_time"],
            "current_wip": row["current_wip"],
            "previous_wip": row["previous_wip"],
            "utilization": row["utilization"],
            "station_capacity": row["station_capacity"],
            "upstream_wip": pipeline._wip_as_of(wip_lookup, row.get("upstream_station"), row["timestamp_utc"]),
            "downstream_wip": pipeline._wip_as_of(wip_lookup, row.get("downstream_station"), row["timestamp_utc"]),
            "utilization_moving_avg": row["utilization_moving_avg"],
            "cycle_time_moving_avg": row["cycle_time_moving_avg"],
            "recent_downtime_sec": pipeline.calculate_recent_downtime(row["timestamp_utc"], row["station_id"]),
            "station_status": row.get("station_status", "Running"),
        })
    df = pd.DataFrame(rows).sort_values(["station_id", "timestamp_utc"]).reset_index(drop=True)

    is_bottleneck_now = (
        df["station_status"].isin(["Blocked", "Starved", "Fault"])
        | (df["cycle_time"] > df["takt_time"])
    )
    df["is_bottleneck_now"] = is_bottleneck_now

    horizon = pd.Timedelta(minutes=horizon_minutes)
    labels = np.zeros(len(df), dtype=int)
    for station, group in df.groupby("station_id"):
        idx = group.index.to_numpy()
        times = group["timestamp_utc"].to_numpy()
        flags = group["is_bottleneck_now"].to_numpy()
        # For each row, look forward up to `horizon` and OR the flags.
        j = 0
        n = len(idx)
        window_hit = np.zeros(n, dtype=bool)
        end = 0
        for i in range(n):
            if end < i:
                end = i
            while end < n and (times[end] - times[i]) <= horizon:
                end += 1
            window_hit[i] = flags[i:end].any()
        labels[idx] = window_hit.astype(int)

    df["label"] = labels
    return df


def main():
    parser = argparse.ArgumentParser(description="Train BottleneckPredictor's XGBoost model.")
    parser.add_argument("--master", default="station_master.csv")
    parser.add_argument("--shopfloor", default="shopfloor_stream.csv")
    parser.add_argument("--mes", default="mes_events.csv")
    parser.add_argument("--downtime", default="downtime_events.csv")
    parser.add_argument("--horizon-minutes", type=int, default=10)
    parser.add_argument("--out", default="bottleneck_model.json")
    parser.add_argument("--test-size", type=float, default=0.25)
    args = parser.parse_args()

    pipeline = TwinLineFeaturePipeline(args.master, args.shopfloor, args.mes, args.downtime)
    labeled_df = build_labeled_dataset(pipeline, horizon_minutes=args.horizon_minutes)

    print(f"Labeled dataset: {len(labeled_df)} rows, "
          f"{labeled_df['label'].mean():.1%} positive (bottleneck within {args.horizon_minutes} min).")

    if labeled_df["label"].nunique() < 2:
        raise SystemExit(
            "Only one class present in the labels. Feed in simulator runs that actually "
            "contain bottleneck scenarios (drift, fault, WIP buildup) before training."
        )

    predictor = BottleneckPredictor(forecast_horizon_min=args.horizon_minutes)

    # BottleneckPredictor.train() extracts features internally from the raw
    # dataframe, so split the raw labeled rows, not pre-extracted features.
    train_df, test_df, y_train, y_test = train_test_split(
        labeled_df, labeled_df["label"], test_size=args.test_size,
        random_state=42, stratify=labeled_df["label"]
    )

    predictor.train(train_df, y_train)

    X_test = predictor.extract_derived_features(test_df)
    y_pred = predictor.model.predict(X_test)
    y_proba = predictor.model.predict_proba(X_test)[:, 1]

    print("\nHold-out performance:")
    print(classification_report(y_test, y_pred, digits=3))
    if y_test.nunique() == 2:
        print(f"ROC AUC: {roc_auc_score(y_test, y_proba):.3f}")

    predictor.model.save_model(args.out)
    print(f"\nSaved trained model to {args.out}")
    print(f"Load it in production with: BottleneckPredictor(model_path='{args.out}')")


if __name__ == "__main__":
    main()
