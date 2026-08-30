
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd

def cycle_time_drift(df, station="S05"):
    df=df.copy()
    idx=df.index[df.station_id.eq(station)]
    if len(idx)==0: return df
    a,b=int(len(idx)*.35),int(len(idx)*.55)
    sel=idx[a:b]
    if len(sel):
        df.loc[sel,"cycle_time"]=np.linspace(
            df.loc[sel,"cycle_time"].iloc[0],75.0,len(sel))
    return df

def station_downtime(df, station="S05", duration_rows=120):
    df=df.copy()
    idx=df.index[df.station_id.eq(station)]
    if len(idx)==0: return df,pd.DataFrame()
    sel=idx[int(len(idx)*.60):int(len(idx)*.60)+duration_rows]
    df.loc[sel,"station_status"]="FAULT"
    df.loc[sel,"machine_state"]="FAULT"
    df.loc[sel,"utilization"]=0.0
    df.loc[sel,"vehicle_present"]=False
    df.loc[sel,"cycle_time"]=np.nan
    event=pd.DataFrame([{
        "timestamp_start":df.loc[sel,"timestamp_utc"].iloc[0],
        "timestamp_end":df.loc[sel,"timestamp_utc"].iloc[-1],
        "station_id":station,
        "duration_seconds":(
            df.loc[sel,"timestamp_utc"].iloc[-1]-
            df.loc[sel,"timestamp_utc"].iloc[0]).total_seconds(),
        "reason":"SIMULATED_STATION_DOWNTIME"}])
    return df,event

def sensor_anomaly(df, station="S08", duration_rows=100):
    df=df.copy()
    idx=df.index[df.station_id.eq(station)]
    if len(idx)==0: return df
    sel=idx[int(len(idx)*.70):int(len(idx)*.70)+duration_rows]
    df.loc[sel,"vibration"]=np.linspace(
        df.loc[sel,"vibration"].iloc[0]*1.2,
        df.loc[sel,"vibration"].iloc[0]*3.0,len(sel))
    df.loc[sel,"temperature"]=np.linspace(
        df.loc[sel,"temperature"].iloc[0]+2,
        df.loc[sel,"temperature"].iloc[0]+18,len(sel))
    return df

def derive_wip(df, master):
    x=df.copy()
    m=master.set_index("station_id")
    x["takt_time"]=x.station_id.map(m["takt_time"])
    x["cycle_time_to_takt_ratio"]=x.cycle_time/x.takt_time
    parts=[]
    for sid,g in x.groupby("station_id",sort=False):
        g=g.sort_values("timestamp_utc").copy()
        excess=(g.cycle_time_to_takt_ratio.fillna(0)-1).clip(lower=0)
        wip=2+excess.rolling(20,min_periods=1).sum()*2
        wip+=g.station_status.eq("FAULT").astype(int).rolling(
            20,min_periods=1).sum()*1.5
        g["wip"]=wip.clip(0,100).round().astype(int)
        parts.append(g)
    return pd.concat(parts).sort_values(["timestamp_utc","station_id"])

def run(inp,out):
    inp,out=Path(inp),Path(out)
    shop=pd.read_csv(inp/"shopfloor_stream.csv",parse_dates=["timestamp_utc"])
    mes=pd.read_csv(inp/"mes_events.csv",parse_dates=["timestamp_utc"])
    twin=pd.read_csv(inp/"digital_twin_state.csv",parse_dates=["timestamp_utc"])
    master=pd.read_csv(inp/"station_master.csv")

    shop=cycle_time_drift(shop)
    shop,downtime=station_downtime(shop)
    shop=sensor_anomaly(shop)
    derived=derive_wip(shop,master)

    twin2=twin.drop(columns=[
        "cycle_time","utilization","station_status",
        "machine_state","vehicle_present","wip"],errors="ignore")
    twin2=twin2.merge(
        derived[["timestamp_utc","station_id","cycle_time","utilization",
                 "station_status","machine_state","vehicle_present","wip"]],
        on=["timestamp_utc","station_id"],how="left")

    manifest=pd.DataFrame([
        ["A","Cycle-time drift","S05","Cycle time gradually rises above takt"],
        ["B","Station downtime","S05","Station enters FAULT; utilization becomes zero"],
        ["C","WIP buildup","S05/upstream","WIP grows as processing capacity falls behind takt"],
        ["D","Sensor anomaly","S08","Vibration and temperature rise abnormally"]
    ],columns=["scenario","name","station","effect"])

    out.mkdir(parents=True,exist_ok=True)
    shop.to_csv(out/"shopfloor_anomalous.csv",index=False)
    mes.to_csv(out/"mes_events_normal.csv",index=False)
    derived.to_csv(out/"shopfloor_with_wip_scenarios.csv",index=False)
    twin2.to_csv(out/"digital_twin_state_anomalous.csv",index=False)
    downtime.to_csv(out/"downtime_events.csv",index=False)
    manifest.to_csv(out/"scenario_manifest.csv",index=False)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",default="twinline_normal_data")
    p.add_argument("--output-dir",default="twinline_anomaly_data")
    a=p.parse_args()
    run(a.input_dir,a.output_dir)
