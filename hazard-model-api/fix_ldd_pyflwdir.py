#!/usr/bin/env python3
"""
Fix the Local Drain Direction (LDD) in a Wflow staticmaps.nc using pyflwdir.

Context
-------
The D8-→-LDD conversion in `prepare_wflow_staticmaps.py` can create cycles
(two cells pointing at each other) which crash Wflow at the first timestep
with a BoundsError. This script re-derives LDD directly from the DEM using
pyflwdir's D8 algorithm, which guarantees an acyclic graph, then recomputes
the derived river-network variables (wflow_river, RiverLength, StreamOrder).

Ported from `../wflow-jl/shared/fix_ldd_pyflwdir.py`. Only change: input
path is a CLI flag instead of the hard-coded `data/input/staticmaps.nc`.

Usage
-----
    python fix_ldd_pyflwdir.py --staticmaps ./runs/bdi/staticmaps.nc \
                                --river-threshold 10.0
"""

import argparse
import sys

import numpy as np
import xarray as xr


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--staticmaps", required=True,
                    help="Path to staticmaps.nc (will be updated in place).")
    ap.add_argument("--river-threshold", type=float, default=10.0,
                    help="Upstream-area threshold for river mask, km² "
                         "(default 10).")
    args = ap.parse_args()

    try:
        import pyflwdir
    except ImportError:
        sys.exit("ERROR: pyflwdir not installed (`pip install pyflwdir`).")

    ds = xr.open_dataset(args.staticmaps)
    dem = ds["wflow_dem"].values
    lat = ds["lat"].values
    lon = ds["lon"].values
    ny, nx = len(lat), len(lon)
    mask = ~np.isnan(dem)
    print(f"[ldd-fix] grid {ny}×{nx}, active {mask.sum():,} cells")

    dem_filled = np.where(mask, dem, -9999).astype(np.float32)
    cell_deg = abs(lat[1] - lat[0])
    cell_m   = cell_deg * 111000

    latlon   = lat[0] > lat[-1]   # Wflow stores lat descending usually
    transform = (cell_deg, 0, lon.min(),
                 0, -cell_deg if latlon else cell_deg,
                 lat.max() if latlon else lat.min())

    flw = pyflwdir.from_dem(
        data=dem_filled, nodata=-9999, transform=transform, latlon=latlon,
    )
    ldd_new = flw.to_array("ldd").astype(np.float32)
    ldd_new[~mask] = np.nan

    upa = flw.upstream_area(unit="km2")
    river_new = np.where((upa >= args.river_threshold) & mask, 1.0,
                         np.nan).astype(np.float32)

    stream_order = flw.stream_order()
    stream_order = np.where(river_new == 1, stream_order,
                            np.nan).astype(np.float32)

    ds.close()
    with xr.open_dataset(args.staticmaps) as src:
        out = src.load()
    out["wflow_ldd"]   = (("lat", "lon"), ldd_new)
    out["wflow_river"] = (("lat", "lon"), river_new)
    if "StreamOrder" in out.data_vars:
        out["StreamOrder"] = (("lat", "lon"), stream_order)
    out.to_netcdf(args.staticmaps)
    print(f"[done] updated {args.staticmaps}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
