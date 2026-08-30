"""
Trains AImodule1's StationAnomalyDetector offline on historical "normal"
operation data. Fits one baseline (mean/std for z-scores) and one
IsolationForest per station from the full normal-operation history, and
saves them to a single file that main.py loads once at startup — the same
pattern used for the bottleneck model.

Usage
-----
    python train_anomaly_baseline.py \
        --master ../data/normal_data/station_master.csv \
        --shopfloor ../data/normal_data/shopfloor_stream.csv \
        --mes ../data/normal_data/mes_events.csv \
        --downtime ../data/anomaly_data/downtime_events.csv \
        --out anomaly_baseline.joblib

Deliberately trained only on data/normal_data/ (not the anomaly_data/
scenarios) — IsolationForest and a mean/std baseline are both meant to learn
what "normal" looks like, so folding in the anomalous runs would just teach
the model to call anomalies normal.
"""

import argparse

from AImodule1 import StationAnomalyDetector
from featureEngineering import TwinLineFeaturePipeline


def main():
    parser = argparse.ArgumentParser(description="Train StationAnomalyDetector's per-station baselines.")
    parser.add_argument("--master", default="station_master.csv")
    parser.add_argument("--shopfloor", default="shopfloor_stream.csv")
    parser.add_argument("--mes", default="mes_events.csv")
    parser.add_argument("--downtime", default="downtime_events.csv")
    parser.add_argument("--z-threshold", type=float, default=3.0)
    parser.add_argument("--contamination", type=float, default=0.05)
    parser.add_argument("--out", default="anomaly_baseline.joblib")
    args = parser.parse_args()

    pipeline = TwinLineFeaturePipeline(args.master, args.shopfloor, args.mes, args.downtime)
    twin_state = pipeline.build_digital_twin_state()

    detector = StationAnomalyDetector(z_threshold=args.z_threshold, contamination=args.contamination)
    detector.fit_baseline(twin_state)

    print(f"Fitted baselines for {len(detector.baselines)} station(s): {sorted(detector.baselines)}")
    for station_id, baseline in sorted(detector.baselines.items()):
        print(f"  {station_id}: cycle_time ~ N({baseline['cycle_time_mean']:.2f}, {baseline['cycle_time_std']:.2f}), "
              f"wip ~ N({baseline['wip_mean']:.2f}, {baseline['wip_std']:.2f})")

    detector.save(args.out)
    print(f"\nSaved trained anomaly baseline to {args.out}")
    print(f"Load it in production with: StationAnomalyDetector.load('{args.out}')")


if __name__ == "__main__":
    main()
