#!/usr/bin/env python3
"""
Compute HAND (Height Above Nearest Drainage) from a DEM using pyflwdir.

HAND is used by RIM2D v1 to build an initial water depth (IWD) field: cells
near drainage get a small seed depth, everywhere else starts dry. This is
one of three IWD strategies in the reference case — the others are
WorldCover stream-burn (v3) and TDX-Hydro geometry burn (v5/v6).

Algorithm
---------
1. Fill sinks in the DEM (pyflwdir `fill_depressions`).
2. Derive D8 flow direction + flow accumulation.
3. Define the drainage network as cells with accumulation ≥ threshold.
4. HAND(cell) = elevation(cell) − elevation(nearest downstream drainage).

Inputs
------
    <out>/tif/dem.tif               (from download_dem.py)

Output
------
    <out>/input/hnd.nc                 # HAND in metres
    <out>/input/flwacc.nc              # flow accumulation (cell count)
    <out>/input/drainage_mask.nc       # 1 where acc ≥ threshold, else 0

Usage
-----
    python compute_hand.py --out ./runs/nbo --acc-thresh 500
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from common import tif_to_rim2d_arrays, write_rim2d_nc


def compute_hand_from_dem(dem: np.ndarray, nodata: float = -9999.0,
                          acc_thresh: int = 500, dx: float = 30.0):
    """Return (hnd, drain_mask, flwacc, dem_filled) at the same grid."""
    import pyflwdir
    # pyflwdir expects y-descending arrays (north at row 0). Our inputs are
    # y-ascending — flip in and out.
    dem_yd = dem[::-1, :].copy()
    mask = np.isfinite(dem_yd)
    filled = np.where(mask, dem_yd, nodata).astype(np.float32)

    flw = pyflwdir.from_dem(
        data=filled, nodata=nodata,
        transform=pyflwdir.Affine(dx, 0, 0, 0, -dx, 0),
        latlon=False,
    )
    d8       = flw.to_array("d8")
    flwacc   = flw.upstream_area(unit="cell").astype(np.float32)
    drain_m  = (flwacc >= acc_thresh).astype(np.uint8)
    hnd      = flw.hand(drain=drain_m.astype(bool), elevtn=filled)

    # flip back to y-ascending
    return (hnd[::-1, :].copy(),
            drain_m[::-1, :].copy(),
            flwacc[::-1, :].copy(),
            filled[::-1, :].copy())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--dem-tif", type=Path,
                    help="Override input DEM TIF.")
    ap.add_argument("--acc-thresh", type=int, default=500,
                    help="Flow-accumulation threshold for drainage (cells).")
    ap.add_argument("--dx", type=float, default=30.0,
                    help="DEM cell size in metres (default 30).")
    args = ap.parse_args()

    dem_tif = args.dem_tif or (args.out / "tif" / "dem.tif")
    if not dem_tif.exists():
        sys.exit(f"ERROR: {dem_tif} not found.")

    dem, x, y = tif_to_rim2d_arrays(dem_tif)
    print(f"[hand] DEM shape {dem.shape}, range {np.nanmin(dem):.1f}–"
          f"{np.nanmax(dem):.1f} m, threshold {args.acc_thresh} cells")

    hnd, drain, acc, filled = compute_hand_from_dem(
        dem, acc_thresh=args.acc_thresh, dx=args.dx,
    )

    input_dir = args.out / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    write_rim2d_nc(hnd,  x, y, input_dir / "hnd.nc",
                   long_name="height above nearest drainage", units="m")
    write_rim2d_nc(acc.astype(np.float64), x, y, input_dir / "flwacc.nc",
                   long_name="flow accumulation", units="cells")
    write_rim2d_nc(np.where(drain > 0, 1.0, 0.0), x, y,
                   input_dir / "drainage_mask.nc",
                   long_name="drainage mask", units="1")
    print(f"[done] wrote hnd.nc, flwacc.nc, drainage_mask.nc to {input_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
