#!/usr/bin/env python3
"""
Download GPM IMERG V07 half-hourly rainfall for a region and period,
regrid to the RIM2D target grid, and write one NetCDF per timestep.

*** Size warning ***
RIM2D consumes rainfall as one NetCDF per 30-minute timestep. A 30-day
event at 30 m over a 55 km × 34 km domain produces:

    30 days × 48 steps/day = 1440 files × ~40 KB each = ~60 MB total

But the file count matters more than the total bytes — some filesystems
slow dramatically past a few thousand files in one directory. For event
simulations keep the period to hours or days, NOT months.

GEE `getRegion()` is used to pull the native 0.1° IMERG grid, then
regridded to the RIM2D UTM grid via nearest-neighbour (matches
`download_imerg_v1.py` in the reference case).

Inputs required (from previous steps)
-------------------------------------
    <out>/tif/dem.tif         # reference grid (run download_dem.py first)

Output
------
    <out>/input/rain/imerg_t{1..N}.nc     # one per 30-min step

Usage
-----
    python download_imerg.py --bbox 36.6,-1.402,37.1,-1.098 \
           --start 2026-03-06 --end 2026-03-07 \
           --out ./runs/nbo --scale 30 --crs EPSG:32737
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from common import (add_common_args, parse_region, init_ee, ee_bbox,
                    tif_to_rim2d_arrays, write_rim2d_nc)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap, temporal=True)
    ap.add_argument("--rain-prefix", default="imerg_t",
                    help="Output file prefix (default: imerg_t).")
    args = ap.parse_args()
    r = parse_region(args)

    # Estimate timestep count and file count
    d0 = datetime.strptime(r.start, "%Y-%m-%d")
    d1 = datetime.strptime(r.end, "%Y-%m-%d")
    days = (d1 - d0).days
    n_steps = days * 48
    print(f"[size] IMERG V07: {days} days × 48 steps/day = {n_steps:,} files "
          f"(≈{n_steps * 40 / 1024:.1f} MB total)")
    if n_steps > 5000:
        print(f"[size] WARNING — {n_steps:,} files may slow your filesystem. "
              f"Consider splitting by day.")
    if r.dry_run:
        return 0

    dem_tif = r.tif_dir / "dem.tif"
    if not dem_tif.exists():
        sys.exit(f"ERROR: {dem_tif} not found. Run download_dem.py first "
                 f"so IMERG can be regridded to the target grid.")

    rain_dir = r.input_dir / "rain"
    rain_dir.mkdir(parents=True, exist_ok=True)

    ee = init_ee(r.sa_key)
    bbox_ee = ee_bbox(ee, r)

    print(f"[imerg] fetching {r.start} to {r.end} …")
    col = (ee.ImageCollection("NASA/GPM_L3/IMERG_V07")
             .filterDate(r.start, r.end)
             .filterBounds(bbox_ee)
             .select("precipitation"))
    n_img = col.size().getInfo()
    print(f"[imerg] {n_img} images in collection")
    if n_img == 0:
        sys.exit("ERROR: no IMERG images in collection for this bbox/period.")

    # Pull the full space-time block in one getRegion call (server-side subset).
    GEE_SCALE_M = 11132   # ~0.1° at equator
    raw = col.getRegion(bbox_ee, scale=GEE_SCALE_M).getInfo()
    header, rows = raw[0], raw[1:]
    i_lon  = header.index("longitude")
    i_lat  = header.index("latitude")
    i_time = header.index("time")
    i_val  = header.index("precipitation")

    # Group by timestep
    by_time = {}
    for row in rows:
        t = row[i_time]
        by_time.setdefault(t, []).append(row)
    times = sorted(by_time.keys())
    print(f"[imerg] {len(times)} distinct timesteps")

    # Reference grid (RIM2D y-ascending)
    dem, x_ref, y_ref = tif_to_rim2d_arrays(dem_tif)

    # Build a rough lon/lat grid for the reference x/y to do nearest-neighbour
    # mapping from IMERG's native 0.1° grid. We assume CRS is a metric UTM.
    from rasterio import open as rio_open
    from rasterio.warp import transform as rio_transform
    with rio_open(dem_tif) as src:
        dst_crs = src.crs
    # Mesh centres → lon/lat via pyproj
    xm, ym = np.meshgrid(x_ref, y_ref)
    lon_ref, lat_ref = rio_transform(dst_crs, "EPSG:4326",
                                     xm.ravel().tolist(), ym.ravel().tolist())
    lon_ref = np.asarray(lon_ref).reshape(xm.shape)
    lat_ref = np.asarray(lat_ref).reshape(ym.shape)

    # For each timestep, nearest-neighbour IMERG cells → reference grid
    for idx, t in enumerate(times, start=1):
        out_path = rain_dir / f"{args.rain_prefix}{idx}.nc"
        if out_path.exists():
            continue
        pts = by_time[t]
        arr = np.array(pts, dtype=object)
        lons  = arr[:, i_lon].astype(float)
        lats  = arr[:, i_lat].astype(float)
        vals  = np.array([float(v) if v is not None else np.nan
                          for v in arr[:, i_val]])
        # Build a dict keyed on (lon_snap, lat_snap) at 0.1° resolution
        def snap(a): return np.round(a * 10) / 10
        lkp = {}
        for ln, la, v in zip(snap(lons), snap(lats), vals):
            lkp[(ln, la)] = v
        lon_s = snap(lon_ref)
        lat_s = snap(lat_ref)
        # Vector lookup
        rainfall = np.full(lon_ref.shape, np.nan)
        for i in range(lon_ref.shape[0]):
            for j in range(lon_ref.shape[1]):
                rainfall[i, j] = lkp.get((lon_s[i, j], lat_s[i, j]), np.nan)
        write_rim2d_nc(rainfall, x_ref, y_ref, out_path,
                       long_name="precipitation rate", units="mm hr-1")
        if idx % 48 == 0 or idx == len(times):
            print(f"[imerg] wrote {idx}/{len(times)} files")

    print(f"[done] wrote {len(times)} IMERG files to {rain_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
