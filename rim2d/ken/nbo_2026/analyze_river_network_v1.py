#!/usr/bin/env python3
"""
Analyze TDX-Hydro river network — group segments into rivers and
produce forecast-usable reach IDs (GEOGloWS/TDX linkno).

Approach:
  1. Load existing river_network_tdx_v2.geojson (linkno + stream_order + geometry)
  2. Try to fetch NEXT_DOWN from TIPG API (with retry); fall back to
     geometric connectivity if API is unavailable.
  3. Build a directed graph: segment → downstream neighbour
  4. Trace connected chains → group into named rivers
  5. For each river chain, pick the most-downstream segment as
     the representative GEOGloWS reach_id for streamflow forecasting
  6. Output:
       v1/input/river_reach_ids.csv   — summary table
       v1/input/river_network_tdx_v2_connected.geojson — with river_id field
       v1/visualizations/v1_river_chains.png — map

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python analyze_river_network_v1.py
"""

import json
import csv
import time
from pathlib import Path
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import requests

# ---------------------------------------------------------------------------
WORK_DIR   = Path(__file__).resolve().parent
V1_INPUT   = WORK_DIR / "v1" / "input"
VIS_DIR    = WORK_DIR / "v1" / "visualizations"
GEOJSON_IN = V1_INPUT / "river_network_tdx_v2.geojson"

API_BASE      = "https://tipg-tiler-template.replit.app"
COLLECTION    = "public.ea_river_networks_tdx_v2"
ITEMS_URL     = f"{API_BASE}/collections/{COLLECTION}/items"
GEOGLOWS_BASE = "https://geoglows.ecmwf.int/api/v2"
DOMAIN_BBOX   = {"west": 36.6, "south": -1.402004, "east": 37.1, "north": -1.098036}

SNAP_TOL   = 0.001   # degrees — tolerance for endpoint snapping (~110m)
DPI        = 150

ORDER_COLORS = {2: "#74b9ff", 3: "#0984e3", 4: "#6c5ce7", 5: "#d63031"}
ORDER_LW     = {2: 0.5, 3: 1.0, 4: 1.8, 5: 3.0}

# ---------------------------------------------------------------------------
# Step 1 — Load existing GeoJSON
# ---------------------------------------------------------------------------

def load_geojson():
    with open(str(GEOJSON_IN)) as f:
        gj = json.load(f)
    segments = []
    for feat in gj["features"]:
        p      = feat["properties"]
        geom   = feat["geometry"]
        coords = geom["coordinates"]
        # Normalise to list of (lon,lat) points
        if geom["type"] == "LineString":
            pts = coords
        elif geom["type"] == "MultiLineString":
            pts = [pt for line in coords for pt in line]
        else:
            continue
        segments.append({
            "linkno":       int(p["linkno"]),
            "stream_order": int(p["stream_order"]),
            "coords":       pts,
            "start":        tuple(pts[0]),
            "end":          tuple(pts[-1]),
            "geometry":     geom,
        })
    print(f"Loaded {len(segments)} segments from {GEOJSON_IN.name}")
    return segments, gj


# ---------------------------------------------------------------------------
# Step 2 — Try to fetch NEXT_DOWN from TIPG
# ---------------------------------------------------------------------------

def fetch_next_down(linknos, timeout=20, max_retries=2):
    """
    Try to get NEXT_DOWN for each linkno from TIPG API.
    Returns dict {linkno: next_down} or None if API unavailable.
    """
    print("\nTrying TIPG API for NEXT_DOWN...")
    bbox_str = (f"{DOMAIN_BBOX['west']},{DOMAIN_BBOX['south']},"
                f"{DOMAIN_BBOX['east']},{DOMAIN_BBOX['north']}")
    params = {
        "bbox":       bbox_str,
        "limit":      500,
        "properties": "linkno,next_down,strmorder",
        "f":          "json",
    }
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(ITEMS_URL, params=params, timeout=timeout)
            r.raise_for_status()
            feats = r.json().get("features", [])
            result = {}
            for feat in feats:
                p  = feat.get("properties", {})
                ln = p.get("linkno") or p.get("LINKNO")
                nd = p.get("next_down") or p.get("NEXT_DOWN")
                if ln and nd:
                    result[int(ln)] = int(nd)
            if result:
                print(f"  TIPG OK — {len(result)} NEXT_DOWN values retrieved")
                return result
            else:
                print(f"  TIPG returned no NEXT_DOWN (attempt {attempt})")
        except Exception as e:
            print(f"  TIPG attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(3)
    print("  TIPG unavailable — falling back to geometric connectivity")
    return None


# ---------------------------------------------------------------------------
# Step 3a — Build connectivity from NEXT_DOWN (if available)
# ---------------------------------------------------------------------------

def connectivity_from_api(segments, next_down_map):
    """Map linkno → downstream linkno using API NEXT_DOWN."""
    linkno_set = {s["linkno"] for s in segments}
    downstream = {}
    for seg in segments:
        ln = seg["linkno"]
        nd = next_down_map.get(ln)
        # Only keep if downstream is also within our domain
        if nd and nd in linkno_set:
            downstream[ln] = nd
        else:
            downstream[ln] = None   # outlet / exits domain
    return downstream


# ---------------------------------------------------------------------------
# Step 3b — Build connectivity from geometry (endpoint snapping)
# ---------------------------------------------------------------------------

def connectivity_from_geometry(segments):
    """
    For each segment, find which segment's START is closest to this END.
    If within SNAP_TOL degrees, mark as downstream neighbour.
    Segments flow from start → end (consistent with TDX convention: upstream→downstream).
    """
    print(f"\nBuilding geometric connectivity (snap tolerance={SNAP_TOL}°)...")
    # Index start points for fast lookup
    start_index = {}   # rounded_coords → linkno
    for seg in segments:
        key = (round(seg["start"][0], 4), round(seg["start"][1], 4))
        start_index[key] = seg["linkno"]

    downstream = {}
    for seg in segments:
        end_key = (round(seg["end"][0], 4), round(seg["end"][1], 4))
        # Direct match
        dn = start_index.get(end_key)
        if dn is None:
            # Search within tolerance
            ex, ey = seg["end"]
            best_dist = SNAP_TOL
            for other in segments:
                if other["linkno"] == seg["linkno"]:
                    continue
                sx, sy = other["start"]
                d = ((sx - ex)**2 + (sy - ey)**2) ** 0.5
                if d < best_dist:
                    best_dist = d
                    dn = other["linkno"]
        downstream[seg["linkno"]] = dn  # None = outlet
    n_connected = sum(1 for v in downstream.values() if v is not None)
    print(f"  Connected pairs: {n_connected} / {len(segments)}")
    return downstream


# ---------------------------------------------------------------------------
# Step 4 — Trace chains → group into rivers
# ---------------------------------------------------------------------------

def trace_river_chains(segments, downstream):
    """
    Walk from each segment downstream until we reach an outlet or
    a segment already assigned. Groups of connected segments share
    a river_id. The most downstream segment becomes the representative
    reach_id.
    """
    seg_map = {s["linkno"]: s for s in segments}
    visited = {}   # linkno → river_id
    rivers  = {}   # river_id → {linknos, outlet_linkno, max_order}
    river_id_counter = [0]

    def trace(start_ln):
        path = []
        ln   = start_ln
        seen = set()
        while ln and ln not in visited and ln not in seen:
            seen.add(ln)
            path.append(ln)
            ln = downstream.get(ln)
        return path, ln  # path = chain, ln = where we stopped

    # Start traces from headwaters (segments with no upstream)
    has_upstream = set(v for v in downstream.values() if v is not None)
    headwaters   = [s["linkno"] for s in segments
                    if s["linkno"] not in has_upstream]

    for hw in headwaters:
        if hw in visited:
            continue
        path, stopped_at = trace(hw)
        # Assign all to same river chain
        rid = river_id_counter[0]
        river_id_counter[0] += 1
        for ln in path:
            visited[ln] = rid
        orders = [seg_map[ln]["stream_order"] for ln in path if ln in seg_map]
        rivers[rid] = {
            "linknos":       path,
            "outlet_linkno": path[-1],
            "n_segments":    len(path),
            "max_order":     max(orders) if orders else 0,
            "min_order":     min(orders) if orders else 0,
        }

    # Assign any unvisited segments (isolated / loop cases)
    for seg in segments:
        if seg["linkno"] not in visited:
            rid = river_id_counter[0]
            river_id_counter[0] += 1
            visited[seg["linkno"]] = rid
            rivers[rid] = {
                "linknos":       [seg["linkno"]],
                "outlet_linkno": seg["linkno"],
                "n_segments":    1,
                "max_order":     seg["stream_order"],
                "min_order":     seg["stream_order"],
            }

    print(f"\nTraced {len(rivers)} river chains from {len(segments)} segments")
    return rivers, visited


# ---------------------------------------------------------------------------
# Step 4b — Validate reach IDs against GEOGloWS forecast API
# ---------------------------------------------------------------------------

def check_geoglows_forecast(reach_ids, delay=1.0):
    """
    Test each reach_id against GEOGloWS v2 forecast endpoint.
    Returns dict {reach_id: {'valid': bool, 'max_q': float, 'date': str}}
    Uses path-style URL: /api/v2/forecast/{river_id}/
    """
    import pandas as pd
    from io import StringIO

    print("\nChecking GEOGloWS forecast availability...")
    results = {}
    for rid in reach_ids:
        try:
            r = requests.get(
                f"{GEOGLOWS_BASE}/forecast/{rid}/",
                timeout=20
            )
            if r.status_code == 200:
                df = pd.read_csv(StringIO(r.text), parse_dates=[0])
                max_q = float(df["flow_median"].max())
                date  = str(df.iloc[0, 0].date()) if len(df) > 0 else "?"
                results[rid] = {"valid": True,  "max_q": max_q, "date": date}
                print(f"  {rid}  OK  max_Q={max_q:.2f} m³/s")
            else:
                results[rid] = {"valid": False, "max_q": None, "date": None}
                print(f"  {rid}  HTTP {r.status_code}")
        except Exception as e:
            results[rid] = {"valid": False, "max_q": None, "date": None}
            print(f"  {rid}  ERROR: {str(e)[:50]}")
        time.sleep(delay)
    return results


# ---------------------------------------------------------------------------
# Step 5 — Build summary table
# ---------------------------------------------------------------------------

def build_summary(rivers, segments, geoglows_check=None):
    seg_map = {s["linkno"]: s for s in segments}
    if geoglows_check is None:
        geoglows_check = {}

    rows = []
    for rid, info in sorted(rivers.items(),
                             key=lambda x: -x[1]["max_order"]):
        outlet_ln  = info["outlet_linkno"]
        outlet_seg = seg_map.get(outlet_ln, {})
        outlet_end = outlet_seg.get("end", (None, None))

        # Approximate river length (sum of segment great-circle lengths)
        total_len_km = 0.0
        for ln in info["linknos"]:
            s = seg_map.get(ln)
            if s and len(s["coords"]) >= 2:
                for i in range(len(s["coords"]) - 1):
                    dx = (s["coords"][i+1][0] - s["coords"][i][0]) * 111.0 * np.cos(np.radians(-1.25))
                    dy = (s["coords"][i+1][1] - s["coords"][i][1]) * 111.0
                    total_len_km += (dx**2 + dy**2)**0.5

        gcheck = geoglows_check.get(outlet_ln, {})
        rows.append({
            "river_id":            rid,
            "reach_id_geoglows":   outlet_ln,
            "max_stream_order":    info["max_order"],
            "min_stream_order":    info["min_order"],
            "n_segments":          info["n_segments"],
            "length_km":           round(total_len_km, 2),
            "outlet_lon":          round(outlet_end[0], 5) if outlet_end[0] else "",
            "outlet_lat":          round(outlet_end[1], 5) if outlet_end[0] else "",
            "geoglows_valid":      gcheck.get("valid", ""),
            "forecast_max_q_m3s":  round(gcheck["max_q"], 2) if gcheck.get("max_q") is not None else "",
            "forecast_date":       gcheck.get("date", ""),
            "all_linknos":         ";".join(str(ln) for ln in info["linknos"]),
        })

    return rows


# ---------------------------------------------------------------------------
# Step 6 — Save outputs
# ---------------------------------------------------------------------------

def save_csv(rows, out_path):
    fields = ["river_id","reach_id_geoglows","max_stream_order",
              "min_stream_order","n_segments","length_km",
              "outlet_lon","outlet_lat",
              "geoglows_valid","forecast_max_q_m3s","forecast_date",
              "all_linknos"]
    with open(str(out_path), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"  Saved: {out_path.name}")


def save_geojson_with_river_id(gj_orig, visited, out_path):
    for feat in gj_orig["features"]:
        ln = int(feat["properties"]["linkno"])
        feat["properties"]["river_id"] = visited.get(ln, -1)
    with open(str(out_path), "w") as f:
        json.dump(gj_orig, f)
    print(f"  Saved: {out_path.name}")


# ---------------------------------------------------------------------------
# Step 7 — Visualize
# ---------------------------------------------------------------------------

def visualize(segments, rivers, visited, rows):
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    # Assign a colour per river chain (cycle through palette)
    palette = plt.cm.tab20.colors
    river_color = {rid: palette[i % len(palette)]
                   for i, rid in enumerate(rivers.keys())}

    fig, axes = plt.subplots(1, 2, figsize=(20, 10))

    # Panel 1 — coloured by stream order
    ax = axes[0]
    ax.set_facecolor("#f0f0f0")
    for seg in segments:
        o = seg["stream_order"]
        coords = seg["coords"]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        ax.plot(xs, ys, color=ORDER_COLORS.get(o, "#999"),
                lw=ORDER_LW.get(o, 0.5), alpha=0.9)
    handles = [mpatches.Patch(color=ORDER_COLORS[o],
               label=f"Order {o}") for o in sorted(ORDER_COLORS)]
    ax.legend(handles=handles, loc="lower right", fontsize=9)
    ax.set_title(f"TDX-Hydro Network ({len(segments)} segments)\nColoured by stream order",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_aspect("equal")

    # Panel 2 — coloured by river chain, outlet marked
    ax = axes[1]
    ax.set_facecolor("#f0f0f0")
    seg_map = {s["linkno"]: s for s in segments}

    # Only label rivers with max_order >= 3
    labeled = set()
    for seg in segments:
        ln  = seg["linkno"]
        rid = visited.get(ln, -1)
        col = river_color.get(rid, "#aaa")
        o   = seg["stream_order"]
        coords = seg["coords"]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        ax.plot(xs, ys, color=col, lw=ORDER_LW.get(o, 0.5), alpha=0.85)

    # Mark outlets for main rivers (max_order >= 4)
    for row in rows:
        if row["max_stream_order"] >= 4 and row["outlet_lon"]:
            ax.plot(row["outlet_lon"], row["outlet_lat"],
                    "v", color="black", markersize=7, zorder=10)
            ax.annotate(f"ID:{row['reach_id_geoglows']}\nOrd{row['max_stream_order']} "
                        f"({row['n_segments']}seg, {row['length_km']:.0f}km)",
                        (row["outlet_lon"], row["outlet_lat"]),
                        textcoords="offset points", xytext=(6, -12),
                        fontsize=6.5, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", fc="white",
                                  ec="gray", alpha=0.85))

    ax.set_title(f"River chains ({len(rivers)} groups)\n"
                 "▼ = outlet reach_id (GEOGloWS forecast point)",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_aspect("equal")

    fig.suptitle("Nairobi TDX-Hydro v2 — River Chain Analysis\n"
                 "reach_id_geoglows = most-downstream linkno per chain "
                 "(usable for GEOGloWS streamflow forecasts)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = VIS_DIR / "v1_river_chains.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # 1 — load
    segments, gj_orig = load_geojson()

    # 2 — try TIPG for NEXT_DOWN
    linknos       = [s["linkno"] for s in segments]
    next_down_map = fetch_next_down(linknos)

    # 3 — connectivity
    if next_down_map:
        downstream = connectivity_from_api(segments, next_down_map)
        method = "TIPG API"
    else:
        downstream = connectivity_from_geometry(segments)
        method = "geometric endpoint snapping"

    print(f"  Connectivity method: {method}")

    # 4 — trace chains
    rivers, visited = trace_river_chains(segments, downstream)

    # 4b — check GEOGloWS forecasts for order 4-5 outlets only
    outlet_ids_high = [
        info["outlet_linkno"]
        for info in rivers.values()
        if info["max_order"] >= 4
    ]
    geoglows_check = check_geoglows_forecast(outlet_ids_high)

    # 5 — summary table
    rows = build_summary(rivers, segments, geoglows_check=geoglows_check)

    # Print table
    print()
    print(f"{'river_id':>8}  {'reach_id':>12}  {'ord':>4}  "
          f"{'segs':>5}  {'len_km':>7}  {'outlet_lon':>10}  {'outlet_lat':>10}")
    print("-" * 75)
    for r in rows:
        print(f"{r['river_id']:>8}  {r['reach_id_geoglows']:>12}  "
              f"{r['max_stream_order']:>4}  {r['n_segments']:>5}  "
              f"{r['length_km']:>7.1f}  {str(r['outlet_lon']):>10}  "
              f"{str(r['outlet_lat']):>10}")

    # 6 — save
    save_csv(rows, V1_INPUT / "river_reach_ids.csv")
    save_geojson_with_river_id(
        gj_orig, visited,
        V1_INPUT / "river_network_tdx_v2_connected.geojson"
    )

    # 7 — visualize
    visualize(segments, rivers, visited, rows)

    print()
    print("=" * 60)
    print("Summary:")
    print(f"  Total segments   : {len(segments)}")
    print(f"  River chains     : {len(rivers)}")
    print(f"  Connectivity     : {method}")
    print()
    print("Forecast reach IDs (order 4-5 outlets):")
    for r in rows:
        if r["max_stream_order"] >= 4:
            print(f"  reach_id={r['reach_id_geoglows']}  "
                  f"order={r['max_stream_order']}  "
                  f"len={r['length_km']:.0f}km  "
                  f"outlet=({r['outlet_lon']},{r['outlet_lat']})")
    print()
    print("GEOGloWS API example:")
    top = next((r for r in rows if r["max_stream_order"] >= 5), rows[0])
    print(f"  https://geoglows.ecmwf.int/api/v2/forecast/"
          f"{top['reach_id_geoglows']}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
