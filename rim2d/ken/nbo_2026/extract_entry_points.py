#!/usr/bin/env python3
"""
Extract wadi entry point coordinates (lat/lon) with names.

Finds entry points at domain edges (same logic as visualize_wadi_entry.py),
converts UTM → lat/lon, assigns names, and saves to CSV + GeoJSON.

Usage:
    micromamba run -n zarrv3 python extract_entry_points.py
"""

import json
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
from pyproj import Transformer

WORK_DIR  = Path(__file__).parent
INPUT_DIR = WORK_DIR / "input"
VIS_DIR   = WORK_DIR / "visualizations"
CRS_UTM   = "EPSG:32636"   # UTM zone 36N

WADI_ACC_THRESH = 50       # same as visualize_wadi_entry.py


def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = ds["x"][:].data.copy()
    y = ds["y"][:].data.copy()
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    data[data < -9000] = np.nan
    return data, x, y


def find_edge_entries(flwacc, channel, threshold=WADI_ACC_THRESH):
    """Find wadi entry points at all four domain edges (same as visualize_wadi_entry.py)."""
    nrows, ncols = flwacc.shape
    ch = channel > 0
    entries = []

    for r in [nrows - 1]:                           # north
        for c in range(ncols):
            if flwacc[r, c] >= threshold and not ch[r, c]:
                entries.append(("north", r, c, float(flwacc[r, c])))

    for r in [0]:                                    # south
        for c in range(ncols):
            if flwacc[r, c] >= threshold and not ch[r, c]:
                entries.append(("south", r, c, float(flwacc[r, c])))

    for r in range(nrows):                           # west
        if flwacc[r, 0] >= threshold and not ch[r, 0]:
            entries.append(("west", r, 0, float(flwacc[r, 0])))

    for r in range(nrows):                           # east
        if flwacc[r, ncols - 1] >= threshold and not ch[r, ncols - 1]:
            entries.append(("east", r, ncols - 1, float(flwacc[r, ncols - 1])))

    return entries


def assign_names(entries, ch_top_row):
    """
    Assign short readable names to entry points.

    Convention:
      N1, N2 … — north-side entries (above channel, upstream desert catchment)
      S1, S2 … — south-side entries (below channel row)
      W1, W2 … — west edge entries
      E1, E2 … — east edge entries

    Within each group, sorted by flow accumulation descending (N1 = largest).
    """
    groups = {"north": [], "south": [], "west": [], "east": []}
    for e in entries:
        edge, r, c, acc = e
        # Distinguish north vs south by channel position
        if edge == "north" and r > ch_top_row:
            groups["north"].append(e)
        elif edge in ("south", "north"):
            groups["south"].append(e)
        else:
            groups[edge].append(e)

    named = []
    prefix_map = {"north": "N", "south": "S", "west": "W", "east": "E"}
    for group, prefix in prefix_map.items():
        sorted_group = sorted(groups[group], key=lambda x: -x[3])
        for i, (edge, r, c, acc) in enumerate(sorted_group, 1):
            named.append({
                "name":       f"{prefix}{i}",
                "edge":       edge,
                "group":      group,
                "row":        r,
                "col":        c,
                "flow_acc":   acc,
            })
    return named


def main():
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading inputs...")
    dem,     x, y = load_nc(INPUT_DIR / "dem.nc")
    channel, _, _ = load_nc(INPUT_DIR / "channel_mask.nc")
    flwacc,  _, _ = load_nc(INPUT_DIR / "flwacc_30m.nc")

    nrows, ncols = dem.shape
    ch = channel > 0
    ch_rows = np.where(ch)[0]
    ch_top_row = int(ch_rows.max()) if len(ch_rows) else nrows // 2

    # UTM → lat/lon transformer
    to_latlon = Transformer.from_crs(CRS_UTM, "EPSG:4326", always_xy=True)

    print(f"Grid: {ncols} × {nrows}  |  Channel top row: {ch_top_row}")

    # Find entries and assign names
    entries = find_edge_entries(flwacc, channel)
    named   = assign_names(entries, ch_top_row)

    # Add UTM + lat/lon coordinates and elevation
    records = []
    for pt in named:
        r, c = pt["row"], pt["col"]
        utm_x = float(x[c])
        utm_y = float(y[r])
        lon, lat = to_latlon.transform(utm_x, utm_y)
        elev = float(dem[r, c]) if np.isfinite(dem[r, c]) else np.nan
        records.append({
            "name":     pt["name"],
            "group":    pt["group"],
            "edge":     pt["edge"],
            "lat":      round(lat, 6),
            "lon":      round(lon, 6),
            "utm_x_m":  round(utm_x, 1),
            "utm_y_m":  round(utm_y, 1),
            "elev_m":   round(elev, 1),
            "flow_acc": int(pt["flow_acc"]),
            "row":      r,
            "col":      c,
        })

    df = pd.DataFrame(records)

    # ── Print table ──────────────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"WADI ENTRY POINTS — {len(df)} total")
    print(f"{'='*80}")
    print(f"\n{'Name':<6} {'Group':<7} {'Lat':>10} {'Lon':>10} "
          f"{'Elev (m)':>9} {'Flow acc':>10}  Description")
    print("-" * 80)

    group_desc = {
        "north": "upstream desert catchment → settlement (flash flood path)",
        "south": "Nile-side / southern boundary",
        "west":  "western edge inflow",
        "east":  "eastern edge inflow",
    }
    for _, row in df.iterrows():
        desc = group_desc.get(row["group"], "")
        print(f"{row['name']:<6} {row['group']:<7} {row['lat']:>10.6f} "
              f"{row['lon']:>10.6f} {row['elev_m']:>9.1f} "
              f"{row['flow_acc']:>10,}  {desc}")

    # ── Group summaries ───────────────────────────────────────────────────────
    print(f"\n{'Group summary':}")
    for grp, sub in df.groupby("group"):
        print(f"  {grp:6s}: {len(sub)} entry point(s), "
              f"max flow_acc={sub['flow_acc'].max():,}, "
              f"elev {sub['elev_m'].min():.0f}–{sub['elev_m'].max():.0f} m")

    # ── Save CSV ─────────────────────────────────────────────────────────────
    csv_path = VIS_DIR / "wadi_entry_points.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSaved CSV:     {csv_path}")

    # ── Save GeoJSON ─────────────────────────────────────────────────────────
    features = []
    for _, row in df.iterrows():
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["lon"], row["lat"]],
            },
            "properties": {
                "name":     row["name"],
                "group":    row["group"],
                "edge":     row["edge"],
                "elev_m":   row["elev_m"],
                "flow_acc": row["flow_acc"],
                "utm_x_m":  row["utm_x_m"],
                "utm_y_m":  row["utm_y_m"],
            },
        })
    geojson = {"type": "FeatureCollection", "features": features}
    gj_path = VIS_DIR / "wadi_entry_points.geojson"
    with open(gj_path, "w") as f:
        json.dump(geojson, f, indent=2)
    print(f"Saved GeoJSON: {gj_path}")
    print(f"\nGeoJSON can be loaded in QGIS or viewed at geojson.io")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
