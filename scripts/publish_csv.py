import argparse,os,time,requests,math,pandas as pd

p=argparse.ArgumentParser()
p.add_argument("--csv",required=True)
p.add_argument("--api",default="http://localhost:8000/ingest")
p.add_argument("--delay",type=float,default=.15)
p.add_argument("--master",default=os.path.join(os.path.dirname(__file__),"..","data","normal_data","station_master.csv"),
               help="Reference/master data CSV used to look up per-station takt_time, "
                    "standard_cycle_time and station_capacity. The replay CSV itself "
                    "doesn't carry these columns, so without this lookup every station "
                    "silently gets the same flat default values regardless of what the "
                    "master data actually specifies.")
a=p.parse_args(); df=pd.read_csv(a.csv)


def _num(value, default):
    """pd.to_numeric(..., errors='coerce') turns blanks into NaN, and `NaN or default`
    silently returns NaN (NaN is truthy in Python) instead of falling back — this
    coerces properly so blank/invalid cells actually become the default."""
    n = pd.to_numeric(value, errors="coerce")
    return float(default) if (n is None or (isinstance(n, float) and math.isnan(n))) else float(n)


master_lookup={}
try:
    master_df=pd.read_csv(a.master)
    master_lookup=master_df.set_index("station_id")[
        ["takt_time","standard_cycle_time","station_capacity"]
    ].to_dict("index")
except Exception as e:
    print(f"Warning: could not load master data from {a.master} ({e}). "
          f"Falling back to flat defaults (takt_time=60, standard_cycle_time=60, station_capacity=20) for all stations.")

for _,r in df.iterrows():
    d=r.to_dict()
    sid=str(d["station_id"])
    ref=master_lookup.get(sid,{})
    payload={"timestamp_utc":str(d.get("timestamp_utc")),"station_id":sid,
      "vehicle_id":str(d.get("vehicle_id",d.get("vehicle_id / vehicle_present",""))),
      "station_status":str(d.get("station_status","Running")).title(),"machine_state":str(d.get("machine_state","Running")),
      "cycle_time":_num(d.get("cycle_time"),60),
      "utilization":_num(d.get("utilization"),0),
      "vibration":_num(d.get("vibration"),0),
      "temperature":_num(d.get("temperature"),0),
      "current_wip":_num(d.get("wip",d.get("current_wip")),0),
      "takt_time":_num(d.get("takt_time",ref.get("takt_time")),60),
      "standard_cycle_time":_num(d.get("standard_cycle_time",ref.get("standard_cycle_time")),60),
      "station_capacity":_num(d.get("station_capacity",ref.get("station_capacity")),20)}
    requests.post(a.api,json=payload,timeout=5); time.sleep(a.delay)