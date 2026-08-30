"""
Loads the line's real station topology (sequence, upstream/downstream
neighbors) from station_topology.csv — a copy of
data/normal_data/station_master.csv shipped alongside the backend so it's
baked into the Docker image without needing the full data/ folder.

If you change the line layout, regenerate current file from the master data:
    cp ../data/normal_data/station_master.csv station_topology.csv
"""

import csv
import os

import networkx as nx

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_TOPOLOGY_CSV = os.path.join(_BACKEND_DIR, "station_topology.csv")


def load_topology(path: str = None):
    """
    Returns (graph, neighbors):
      - graph: nx.DiGraph with a real upstream -> downstream edge per station
      - neighbors: {station_id: {"upstream": id_or_None, "downstream": id_or_None}}

    Falls back to an empty graph/dict if the topology file is missing,
    rather than failing startup, so the service stays usable even without it
    (upstream/downstream WIP will just read as 0).
    """
    path = path or os.getenv("TWINLINE_TOPOLOGY_CSV", _DEFAULT_TOPOLOGY_CSV)
    graph = nx.DiGraph()
    neighbors = {}

    if not os.path.exists(path):
        print(f"[TwinLine] No station topology file found at {path} — "
              f"upstream_wip/downstream_wip will default to 0 for all stations.")
        return graph, neighbors

    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            sid = row["station_id"]
            upstream = (row.get("upstream_station") or "").strip() or None
            downstream = (row.get("downstream_station") or "").strip() or None
            graph.add_node(sid)
            if upstream:
                graph.add_edge(upstream, sid)
            if downstream:
                graph.add_edge(sid, downstream)
            neighbors[sid] = {"upstream": upstream, "downstream": downstream}

    print(f"[TwinLine] Loaded station topology for {len(neighbors)} stations from {path}")
    return graph, neighbors
