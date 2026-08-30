import pandas as pd
import numpy as np

class TwinLineFeaturePipeline:
    def __init__(self, master_csv, shopfloor_csv, mes_csv, downtime_csv):
        self.master_df = pd.read_csv(master_csv).drop_duplicates(subset=['station_id'])
        self.shopfloor_df = pd.read_csv(shopfloor_csv)
        self.shopfloor_df['timestamp_utc'] = pd.to_datetime(
            self.shopfloor_df['timestamp_utc'], format='ISO8601'
        )
        self.shopfloor_df.sort_values('timestamp_utc', inplace=True)

        self.mes_df = pd.read_csv(mes_csv)
        self.mes_df['timestamp_utc'] = pd.to_datetime(
            self.mes_df['timestamp_utc'], format='ISO8601'
        )
        self.mes_df.sort_values('timestamp_utc', inplace=True)

        self.downtime_df = pd.read_csv(downtime_csv)
        self.downtime_df['timestamp_start'] = pd.to_datetime(
            self.downtime_df['timestamp_start'], format='ISO8601'
        )
    def build_digital_twin_state(self, window_size=10):
        """Merges disparate data streams into a unified state representation."""
        df = pd.merge(self.shopfloor_df, self.master_df, on='station_id', how='left')

        df = pd.merge_asof(
            df.sort_values('timestamp_utc'),
            self.mes_df[['timestamp_utc', 'station_id', 'wip']].sort_values('timestamp_utc'),
            by='station_id',
            on='timestamp_utc',
            direction='backward'
        )
        df.rename(columns={'wip': 'current_wip'}, inplace=True)
        df['current_wip'] = df['current_wip'].fillna(0)

        df['cycle_time_moving_avg'] = df.groupby('station_id')['cycle_time'].transform(
            lambda x: x.rolling(window=window_size, min_periods=1).mean()
        )
        df['utilization_moving_avg'] = df.groupby('station_id')['utilization'].transform(
            lambda x: x.rolling(window=window_size, min_periods=1).mean()
        )

        df['previous_wip'] = df.groupby('station_id')['current_wip'].shift(1).fillna(df['current_wip'])

        return df

    def calculate_recent_downtime(self, current_time, station_id, lookback_minutes=60):
        """Aggregates downtime duration within a specified historical window."""
        lookback_time = current_time - pd.Timedelta(minutes=lookback_minutes)
        recent_faults = self.downtime_df[
            (self.downtime_df['station_id'] == station_id) &
            (self.downtime_df['timestamp_start'] >= lookback_time) &
            (self.downtime_df['timestamp_start'] <= current_time)
        ]
        return recent_faults['duration_seconds'].sum()

    def _build_wip_lookup(self, twin_state: pd.DataFrame) -> dict:
        """
        Builds a per-station time series of (timestamp, current_wip) so upstream/
        downstream WIP can be looked up as-of the current row's timestamp, instead
        of using each station's single final WIP value for every row.
        """
        wip_lookup = {}
        for station, group in twin_state[['timestamp_utc', 'station_id', 'current_wip']].groupby('station_id'):
            g = group.sort_values('timestamp_utc')
            # Keep as a pandas DatetimeIndex so we have tz info.
            wip_lookup[station] = (pd.DatetimeIndex(g['timestamp_utc']), g['current_wip'].to_numpy())
        return wip_lookup

    def _wip_as_of(self, wip_lookup: dict, station, current_time) -> float:
        """Looks up the most recent known WIP for `station` at or before `current_time`."""
        if station is None or (isinstance(station, float) and np.isnan(station)):
            return 0.0
        series = wip_lookup.get(station)
        if series is None:
            return 0.0
        timestamps, values = series
        idx = timestamps.searchsorted(current_time, side='right') - 1
        if idx < 0:
            return 0.0
        return float(values[idx])

    def generate_ai_payloads(self):
        """Constructs the exact dictionary structures expected by AI Modules 1 and 2."""
        twin_state = self.build_digital_twin_state()
        wip_lookup = self._build_wip_lookup(twin_state)

        payloads = []
        for _, row in twin_state.iterrows():
            current_time = row['timestamp_utc']
            station = row['station_id']

            upstream_wip = self._wip_as_of(wip_lookup, row.get('upstream_station'), current_time)
            downstream_wip = self._wip_as_of(wip_lookup, row.get('downstream_station'), current_time)
            downtime_sec = self.calculate_recent_downtime(current_time, station)

            module1_payload = {
                "station_id": station,
                "timestamp_utc": current_time.isoformat(),
                "cycle_time": row['cycle_time'],
                "takt_time": row['takt_time'],
                "standard_cycle_time": row['standard_cycle_time'],
                "utilization": row['utilization'],
                "current_wip": row['current_wip'],
                "station_status": row['station_status'],
                "sensor_readings": {
                    "vibration": row['vibration'],
                    "temperature": row['temperature']
                }
            }

            module2_payload = {
                "station_id": station,
                "cycle_time": row['cycle_time'],
                "takt_time": row['takt_time'],
                "current_wip": row['current_wip'],
                "previous_wip": row['previous_wip'],
                "utilization": row['utilization'],
                "station_capacity": row['station_capacity'],
                "upstream_wip": upstream_wip,
                "downstream_wip": downstream_wip,
                "utilization_moving_avg": row['utilization_moving_avg'],
                "cycle_time_moving_avg": row['cycle_time_moving_avg'],
                "recent_downtime_sec": downtime_sec
            }

            payloads.append((module1_payload, module2_payload))

        return payloads


if __name__ == "__main__":
    pipeline = TwinLineFeaturePipeline(
        'station_master.csv', 'shopfloor_stream.csv',
        'mes_events.csv', 'downtime_events.csv'
    )
    payloads = pipeline.generate_ai_payloads()
    print(f"Generated {len(payloads)} payload pairs.")