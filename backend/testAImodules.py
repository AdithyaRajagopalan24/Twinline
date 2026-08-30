import os
import pandas as pd
from featureEngineering import TwinLineFeaturePipeline
from AImodule1 import StationAnomalyDetector
from AImodule2 import BottleneckPredictor

# station_master.csv / shopfloor_stream.csv / mes_events.csv live under
# data/normal_data, downtime_events.csv lives under data/anomaly_data.
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "..", "data")
_NORMAL_DIR = os.path.join(_DATA_DIR, "normal_data")
_ANOMALY_DIR = os.path.join(_DATA_DIR, "anomaly_data")


def run_twinline_inference():
    print("Initializing Feature Pipeline.")
    pipeline = TwinLineFeaturePipeline(
        master_csv=os.path.join(_NORMAL_DIR, 'station_master.csv'),
        shopfloor_csv=os.path.join(_NORMAL_DIR, 'shopfloor_stream.csv'),
        mes_csv=os.path.join(_NORMAL_DIR, 'mes_events.csv'),
        downtime_csv=os.path.join(_ANOMALY_DIR, 'downtime_events.csv')
    )

    print("Generating AI Payloads.")
    payloads = pipeline.generate_ai_payloads()

    print(f"Generated {len(payloads)} payload pairs. Initializing AI Modules.")


    anomaly_detector = StationAnomalyDetector(z_threshold=3.0, contamination=0.05)
    bottleneck_predictor = BottleneckPredictor(forecast_horizon_min=10)
    baseline_df = pipeline.build_digital_twin_state()
    anomaly_detector.fit_baseline(baseline_df)
    print("Running Inference Loop.")
    module1_results = []
    module2_results = []

    for mod1_payload, mod2_payload in payloads:
        anomaly_result = anomaly_detector.evaluate(
            current_event=mod1_payload,
            recent_window_df=pd.DataFrame()
        )
        module1_results.append(anomaly_result)

        bottleneck_result = bottleneck_predictor.predict_station(
            station_payload=mod2_payload
        )
        module2_results.append(bottleneck_result)

    df_anomalies = pd.DataFrame(module1_results)
    df_bottlenecks = pd.DataFrame(module2_results)

    print("\nTop Anomalies")
    print(df_anomalies[df_anomalies['alert_triggered'] == True].head())

    print("\nHighest Bottleneck Risks")
    print(df_bottlenecks.sort_values(by='bottleneck_probability', ascending=False).head())

    df_anomalies.to_csv('anomaly_outputs.csv', index=False)
    df_bottlenecks.to_csv('bottleneck_outputs.csv', index=False)
    print("\nResults saved as file")

if __name__ == "__main__":
    run_twinline_inference()