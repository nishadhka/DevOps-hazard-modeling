#!/usr/bin/env python3
"""
Step 1 — Nile Channel Masking
==============================
Removes Nile riverbed cells from the RIM2D v11 max water depth output before
sending to CLIMADA for impact analysis. Cells where MERIT river width > 50 m
are set to NaN; they represent the Nile channel itself, not urban flooding.

Input:
    output/nile_v11_wd_max.nc          Raw RIM2D output (297 x 386, UTM 32636)
    ../tif/merit_wth.tif               MERIT river width raster (same CRS)

Output:
    output/nile_v11_wd_max_urban.nc    Channel-masked flood depth

Usage:
    micromamba run -n zarrv3 python analysis/step1_nile_channel_mask.py
"""

from pathlib import Path

import numpy as np
import rasterio
import rasterio.crs
import xarray as xr
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject

# -- Paths --------------------------------------------------------------------
V11_DIR = Path("/data/rim2d/nile_highres/v11")
INPUT_WD = V11_DIR / "output" / "nile_v11_wd_max.nc"
INPUT_WTH = Path("/data/rim2d/nile_highres/tif/merit_wth.tif")
OUTPUT_URBAN = V11_DIR / "output" / "nile_v11_wd_max_urban.nc"

# Channel width threshold: cells with MERIT width > this are Nile channel.
# The Nile is ~500-600 m wide at Abu Hamad; wadis are < 30 m.
CHANNEL_WIDTH_THRESHOLD_M = 50.0


def main():
    # -- Load v11 water depth grid ----------------------------------------
    ds = xr.open_dataset(INPUT_WD)
    wd = ds["max_water_depth"].values.copy()
    xs = ds["x"].values
    ys = ds["y"].values
    ny, nx = wd.shape

    # Reconstruct raster transform from coordinate arrays (UTM 32636, 30 m cells)
    dx = xs[1] - xs[0]
    dy = ys[1] - ys[0]
    xmin = xs[0] - dx / 2
    ymin = ys[0] - dy / 2
    xmax = xs[-1] + dx / 2
    ymax = ys[-1] + dy / 2

    dst_crs = rasterio.crs.CRS.from_epsg(32636)
    dst_transform = from_bounds(xmin, ymin, xmax, ymax, nx, ny)

    print(f"v11 grid: {ny}×{nx}, cell size {dx:.0f} m")
    print(f"  x: {xmin:.0f} – {xmax:.0f}  |  y: {ymin:.0f} – {ymax:.0f}")
    print(f"Flooded cells (>0.1 m) before masking: {np.sum(wd > 0.1)}")

    # -- Reproject MERIT width to v11 grid --------------------------------
    with rasterio.open(INPUT_WTH) as src:
        wth_reproj = np.zeros((ny, nx), dtype=np.float32)
        reproject(
            source=src.read(1).astype(np.float32),
            destination=wth_reproj,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.max,  # conservative: use max width per cell
        )

    nile_channel = wth_reproj > CHANNEL_WIDTH_THRESHOLD_M
    print(f"\nNile channel cells identified (width > {CHANNEL_WIDTH_THRESHOLD_M:.0f} m): "
          f"{nile_channel.sum()}")
    print(f"  Of these with depth > 0.1 m: {np.sum(nile_channel & (wd > 0.1))}")
    print(f"  Of these with depth > 2.0 m: {np.sum(nile_channel & (wd > 2.0))}")

    # -- Apply mask -------------------------------------------------------
    wd_urban = wd.copy()
    wd_urban[nile_channel] = np.nan

    print(f"\nFlooded cells (>0.1 m) after masking: {np.nansum(wd_urban > 0.1)} "
          f"(removed {np.sum(wd > 0.1) - np.nansum(wd_urban > 0.1)})")
    print(f"Max depth: {np.nanmax(wd_urban):.2f} m  (was {np.nanmax(wd):.2f} m)")

    # -- Save -------------------------------------------------------------
    ds_out = xr.Dataset(
        {"max_water_depth": (["y", "x"], wd_urban)},
        coords={"x": ds.x, "y": ds.y},
    )
    ds_out["max_water_depth"].attrs = {
        "units": "m",
        "long_name": "maximum water depth, Nile channel masked",
        "channel_mask": f"MERIT river width > {CHANNEL_WIDTH_THRESHOLD_M:.0f} m set to NaN",
    }
    ds_out.attrs = {
        "Conventions": "CF-1.5",
        "description": (
            "RIM2D v11 compound flood max depth. "
            "Nile riverbed cells (MERIT width > 50 m) are set to NaN. "
            "Use for CLIMADA urban impact analysis."
        ),
        "source": f"{INPUT_WD.name} + {INPUT_WTH.name}",
    }
    ds_out.to_netcdf(OUTPUT_URBAN)
    print(f"\nSaved: {OUTPUT_URBAN}")
    ds.close()


if __name__ == "__main__":
    main()
