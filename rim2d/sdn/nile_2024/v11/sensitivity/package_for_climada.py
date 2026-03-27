#!/usr/bin/env python3
"""
Package sensitivity ensemble outputs for CLIMADA team.
=======================================================
Applies Nile channel masking (Step 1) to every scenario output and assembles
all flood maps + metadata into a single folder ready to share.

Output folder: sensitivity/climada_package/
  nile_v11_compound_wd_max.nc       Baseline (already-run v11, Nile-masked)
  nile_culverts_only_wd_max.nc      No compound flooding
  nile_halfblock_wd_max.nc          50% Nile backwater
  nile_intens2x_wd_max.nc           IMERG 2x intensification
  nile_intens3p5x_wd_max.nc         IMERG 3.5x
  nile_intens7x_wd_max.nc           IMERG 7x
  ensemble_metadata.json             Parameters for each scenario
  README.txt                         Instructions for CLIMADA team

Usage:
    micromamba run -n zarrv3 python sensitivity/package_for_climada.py
"""

import json
import shutil
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
SENS_DIR = V11_DIR / "sensitivity"
PKG_DIR  = SENS_DIR / "climada_package"
MERIT_WTH = Path("/data/rim2d/nile_highres/tif/merit_wth.tif")
CHANNEL_WIDTH_THRESHOLD_M = 50.0

# Scenarios: (label, path to wd_max.nc)
SCENARIOS = [
    ("compound",      V11_DIR / "output" / "nile_v11_wd_max.nc"),
    ("culverts_only", SENS_DIR / "culverts_only" / "output" / "nile_culverts_only_wd_max.nc"),
    ("halfblock",     SENS_DIR / "halfblock"     / "output" / "nile_halfblock_wd_max.nc"),
    ("intens2x",      SENS_DIR / "intens2x"      / "output" / "nile_intens2x_wd_max.nc"),
    ("intens3p5x",    SENS_DIR / "intens3p5x"    / "output" / "nile_intens3p5x_wd_max.nc"),
    ("intens7x",      SENS_DIR / "intens7x"      / "output" / "nile_intens7x_wd_max.nc"),
]

SCENARIO_DESCRIPTIONS = {
    "compound":      "Baseline compound flood: Culvert1 (25 km²) + Culvert2 (35 km²) + "
                     "WesternWadi (75 km², Nile-blocked). IMERG 5x intensification.",
    "culverts_only": "Culvert overflow only: Culvert1 + Culvert2. No western wadi / no compound "
                     "flooding mechanism. IMERG 5x. Lower bound on flood extent.",
    "halfblock":     "Partial compound flood: all 3 inflows but western wadi at 50% Nile "
                     "blocking. Intermediate scenario. IMERG 5x.",
    "intens2x":      "All 3 inflows. IMERG sub-pixel intensification factor = 2x. "
                     "Conservative rainfall estimate.",
    "intens3p5x":    "All 3 inflows. IMERG sub-pixel intensification factor = 3.5x. "
                     "Mid-range rainfall estimate.",
    "intens7x":      "All 3 inflows. IMERG sub-pixel intensification factor = 7x. "
                     "Upper bound rainfall (extreme sub-pixel concentration).",
}


def build_channel_mask(ds):
    """Reproject MERIT river width to ds grid; return boolean mask (True = Nile channel)."""
    xs = ds["x"].values
    ys = ds["y"].values
    ny, nx = len(ys), len(xs)
    dx = xs[1] - xs[0]
    dy = ys[1] - ys[0]
    xmin, ymin = xs[0] - dx / 2, ys[0] - dy / 2
    xmax, ymax = xs[-1] + dx / 2, ys[-1] + dy / 2
    dst_crs = rasterio.crs.CRS.from_epsg(32636)
    dst_transform = from_bounds(xmin, ymin, xmax, ymax, nx, ny)
    with rasterio.open(MERIT_WTH) as src:
        wth_reproj = np.zeros((ny, nx), dtype=np.float32)
        reproject(
            source=src.read(1).astype(np.float32),
            destination=wth_reproj,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.max,
        )
    return wth_reproj > CHANNEL_WIDTH_THRESHOLD_M


def apply_mask_and_save(label, src_path, dst_path, channel_mask):
    ds = xr.open_dataset(src_path)
    wd = ds["max_water_depth"].values.copy()
    wd[channel_mask] = np.nan

    ds_out = xr.Dataset(
        {"max_water_depth": (["y", "x"], wd)},
        coords={"x": ds.x, "y": ds.y},
    )
    ds_out["max_water_depth"].attrs = {
        "units": "m",
        "long_name": "maximum water depth (Nile channel masked)",
    }
    ds_out.attrs = {
        "Conventions": "CF-1.5",
        "scenario": label,
        "description": SCENARIO_DESCRIPTIONS[label],
        "channel_mask": f"MERIT river width > {CHANNEL_WIDTH_THRESHOLD_M:.0f} m set to NaN",
        "model": "RIM2D v11, Abu Hamad Sudan, Aug 2024 flood event",
        "crs": "EPSG:32636 (UTM Zone 36N)",
        "cell_size_m": "30",
    }
    ds_out.to_netcdf(dst_path)
    ds.close()

    n_flooded = int(np.nansum(wd > 0.1))
    max_depth = float(np.nanmax(wd))
    print(f"  [{label}] flooded >0.1m: {n_flooded:,} cells | max depth: {max_depth:.2f} m")
    return n_flooded, max_depth


def write_readme(pkg_dir, summary):
    lines = [
        "RIM2D v11 Flood Ensemble — Abu Hamad, Sudan (Aug 2024)",
        "=" * 55,
        "",
        "Prepared for CLIMADA impact uncertainty & sensitivity analysis.",
        "All files are NetCDF (CF-1.5), UTM Zone 36N (EPSG:32636), 30 m resolution.",
        "Nile riverbed cells (MERIT width > 50 m) are set to NaN in all files.",
        "",
        "Files",
        "-----",
    ]
    for label, nc_name, n_flooded, max_depth in summary:
        lines.append(f"  {nc_name}")
        lines.append(f"    {SCENARIO_DESCRIPTIONS[label]}")
        lines.append(f"    Flooded > 0.1 m: {n_flooded:,} cells  |  Max depth: {max_depth:.2f} m")
        lines.append("")
    lines += [
        "Variable",
        "--------",
        "  max_water_depth   [m]   Maximum flood depth over full simulation",
        "",
        "Suggested CLIMADA usage",
        "-----------------------",
        "  from climada.hazard import Flood",
        "  haz = Flood.from_raster('nile_<scenario>_wd_max.nc', ...)",
        "",
        "  Run impact model for each scenario file to produce an ensemble.",
        "  See ensemble_metadata.json for parameter values per scenario.",
        "",
        "Contact",
        "-------",
        "  Abuhamad ICPAC / RIM2D simulation team",
        "  Flood model: RIM2D (GFZ Helmholtz Centre)",
        "  Boundary conditions: IMERG v7 + GEOGloWS Nile discharge",
    ]
    (pkg_dir / "README.txt").write_text("\n".join(lines))


def main():
    PKG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output folder: {PKG_DIR}\n")

    # Load channel mask from baseline (same grid for all scenarios)
    ds_base = xr.open_dataset(SCENARIOS[0][1])
    print("Building Nile channel mask from MERIT river width ...")
    channel_mask = build_channel_mask(ds_base)
    print(f"  Channel cells masked: {channel_mask.sum():,}")
    ds_base.close()

    summary = []
    meta_all = {}

    for label, src_path in SCENARIOS:
        dst_name = f"nile_{label}_wd_max.nc"
        dst_path = PKG_DIR / dst_name

        if not src_path.exists():
            print(f"  [MISSING] {label}: {src_path} — skipping (run RIM2D first)")
            continue

        print(f"\nProcessing: {label}")
        n_flooded, max_depth = apply_mask_and_save(label, src_path, dst_path, channel_mask)
        summary.append((label, dst_name, n_flooded, max_depth))
        meta_all[label] = {
            "description": SCENARIO_DESCRIPTIONS[label],
            "file": dst_name,
            "flooded_cells_gt01m": n_flooded,
            "max_depth_m": round(max_depth, 2),
        }

    # Copy ensemble metadata
    src_meta = SENS_DIR / "ensemble_metadata.json"
    if src_meta.exists():
        with open(src_meta) as f:
            scen_params = json.load(f)
        for k in meta_all:
            if k in scen_params:
                meta_all[k].update(scen_params[k])

    with open(PKG_DIR / "ensemble_metadata.json", "w") as f:
        json.dump(meta_all, f, indent=2)

    write_readme(PKG_DIR, summary)

    print(f"\nPackage complete: {PKG_DIR}")
    print(f"  Files: {len(list(PKG_DIR.glob('*.nc')))} NetCDF, ensemble_metadata.json, README.txt")


if __name__ == "__main__":
    main()
