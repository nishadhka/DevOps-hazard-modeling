#!/usr/bin/env python3
"""
Nairobi v3b — Dynamic World (Sentinel-2) Surface Roughness.

Downloads Google Dynamic World (10m, S2-based) for the Nairobi domain,
composites over a date range around the flood event, remaps land-cover
classes to Manning's n, and writes roughness.nc to v3b/input/.

All other inputs are copied from v3/input/ (stream-burned DEM, IWD,
buildings, sealed/pervious, sewershed).

Produces a 3-panel comparison plot:
  Panel 1 — Dynamic World land-cover class map
  Panel 2 — Dynamic World Manning's n (v3b)
  Panel 3 — ESA WorldCover Manning's n (v1/v3, for comparison)

Outputs → v3b/input/
  roughness.nc      Manning's n from Dynamic World (30m, resampled)
  + copies of: dem.nc, iwd.nc, channel_mask.nc, buildings.nc,
               sealed_surface.nc, pervious_surface.nc, sewershed_v1_full.nc

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python setup_v3b.py
"""

import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

import ee
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import netCDF4
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BBOX = {"west": 36.6, "south": -1.402004, "east": 37.1, "north": -1.098036}

SCALE = 30          # output resolution (m) — match v1/v3
CRS   = "EPSG:32737"

SA_KEY = (
    "/data/08-2023/working_notes_jupyter/ignore_nka_gitrepos/"
    "cno-e4drr/devops/earth-engine-service-account/keys/"
    "earthengine-sa-20260130-key.json"
)

# Date range for Dynamic World composite — 3 months around flood event
DW_START = "2025-12-01"
DW_END   = "2026-03-07"   # up to flood event date

WORK_DIR  = Path(__file__).resolve().parent
V3_INPUT  = WORK_DIR / "v3" / "input"
V3B_DIR   = WORK_DIR / "v3b"
INPUT_DIR = V3B_DIR / "input"
TIF_DIR   = V3B_DIR / "tif"
VIS_DIR   = V3B_DIR / "visualizations"

DPI = 150

# ---------------------------------------------------------------------------
# Dynamic World class → Manning's n mapping
#
# DW classes (0-8):
#   0 water, 1 trees, 2 grass, 3 flooded_vegetation,
#   4 crops, 5 shrub_and_scrub, 6 built, 7 bare, 8 snow_and_ice
#
# Manning's n values follow standard urban hydraulics literature:
#   - Built / impervious: 0.013–0.025 (streets, rooftops)
#   - Bare soil:          0.025–0.033
#   - Grass / low veg:    0.030–0.035
#   - Crops:              0.035–0.040
#   - Shrub:              0.040–0.050
#   - Trees / forest:     0.060–0.100
#   - Water:              0.020–0.025
#   - Flooded veg:        0.045–0.060
# ---------------------------------------------------------------------------

DW_CLASSES = [0,     1,     2,     3,     4,     5,     6,     7,     8    ]
DW_NAMES   = ["Water","Trees","Grass","Flooded veg","Crops","Shrub","Built","Bare","Snow/ice"]
DW_MANNING = [0.025,  0.080,  0.035,  0.055,       0.038,  0.045,  0.013,  0.028, 0.010]

# WorldCover Manning's n (for comparison panel) — from setup_v1.py
WC_FROM = [10,    20,    30,    40,    50,    60,    70,    80,    90,    95,    100]
WC_TO   = [0.050, 0.040, 0.035, 0.035, 0.025, 0.030, 0.020, 0.025, 0.040, 0.040, 0.030]

# DW class colours (approximate Dynamic World palette)
DW_COLORS = ["#419BDF","#397D49","#88B053","#7A87C6",
             "#E49635","#DFC35A","#C4281B","#A59B8F","#B39FE1"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def init_ee():
    with open(SA_KEY) as f:
        key_data = json.load(f)
    credentials = ee.ServiceAccountCredentials(key_data["client_email"], SA_KEY)
    ee.Initialize(credentials=credentials)
    print(f"EE initialized: {key_data['client_email']}")


def download_ee_tif(image, bbox_ee, path, scale=SCALE, crs=CRS):
    url = image.getDownloadURL({
        "scale": scale,
        "region": bbox_ee,
        "format": "GEO_TIFF",
        "crs": crs,
    })
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        urllib.request.urlretrieve(url, tmp_path)
        shutil.move(tmp_path, str(path))
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    print(f"  Downloaded: {path.name}  →  {path}")


def tif_to_rim2d_arrays(tif_path):
    with rasterio.open(str(tif_path)) as src:
        data      = src.read(1).astype(np.float64)
        transform = src.transform
        nodata    = src.nodata
    nrows, ncols = data.shape
    x     = transform.c + transform.a * (np.arange(ncols) + 0.5)
    y_top = transform.f + transform.e * (np.arange(nrows) + 0.5)
    y     = y_top[::-1]
    data  = data[::-1, :].copy()
    if nodata is not None:
        data[np.isclose(data, nodata)] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data, x, y


def regrid_to_dem(src_tif, dem_tif, method=Resampling.nearest):
    """Reproject src_tif to match dem_tif grid. Returns y-ascending array."""
    with rasterio.open(dem_tif) as ref:
        dst_transform = ref.transform
        dst_crs       = ref.crs
        dst_width     = ref.width
        dst_height    = ref.height
    with rasterio.open(src_tif) as src:
        src_data = src.read(1).astype(np.float64)
        dst_data = np.zeros((dst_height, dst_width), dtype=np.float64)
        reproject(
            source=src_data, destination=dst_data,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=dst_transform, dst_crs=dst_crs,
            resampling=method,
        )
    dst_data = dst_data[::-1, :].copy()
    dst_data[~np.isfinite(dst_data)] = np.nan
    return dst_data


def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    data[data < -9000] = np.nan
    return data, x, y


def write_rim2d_nc(data, x, y, nc_path, varname="Band1"):
    fill = -9999.0
    arr  = np.where(np.isnan(data), fill, data).astype(np.float32)
    nrows, ncols = arr.shape
    ds = netCDF4.Dataset(str(nc_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.history     = "Generated by setup_v3b.py (Nairobi v3b — Dynamic World roughness)"
    ds.createDimension("x", ncols)
    ds.createDimension("y", nrows)
    xv = ds.createVariable("x", "f8", ("x",)); xv[:] = x
    xv.long_name = "x coordinate"; xv.standard_name = "projection_x_coordinate"; xv.units = "m"
    yv = ds.createVariable("y", "f8", ("y",)); yv[:] = y
    yv.long_name = "y coordinate"; yv.standard_name = "projection_y_coordinate"; yv.units = "m"
    bv = ds.createVariable(varname, "f4", ("y", "x"), fill_value=np.float32(fill))
    bv[:] = arr
    ds.close()


# ---------------------------------------------------------------------------
# Step 1 — Download Dynamic World composite from GEE
# ---------------------------------------------------------------------------

def step1_download_dw():
    print("=" * 60)
    print("Step 1 — Download Dynamic World (Sentinel-2) from GEE")
    print(f"  Date range : {DW_START} → {DW_END}")
    print(f"  Resolution : {SCALE} m  (resampled from 10m DW)")
    print("=" * 60)

    TIF_DIR.mkdir(parents=True, exist_ok=True)
    dw_tif = TIF_DIR / "dw_label.tif"

    if dw_tif.exists():
        print(f"  Cached: {dw_tif} — skipping download")
        return dw_tif

    init_ee()
    bbox_ee = ee.Geometry.Rectangle(
        [BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"]]
    )

    # Mode composite: most frequent class per pixel over date range
    dw = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(bbox_ee)
        .filterDate(DW_START, DW_END)
        .select("label")
        .reduce(ee.Reducer.mode())
        .rename("label")
    )

    download_ee_tif(dw, bbox_ee, dw_tif, scale=SCALE, crs=CRS)
    return dw_tif


# ---------------------------------------------------------------------------
# Step 2 — Remap DW classes to Manning's n
# ---------------------------------------------------------------------------

def step2_remap_manning(dw_tif, dem_tif):
    print()
    print("=" * 60)
    print("Step 2 — Remap Dynamic World classes → Manning's n")
    print("=" * 60)

    # Regrid DW label (10m) to match DEM grid (30m) using nearest-neighbour
    dw_label = regrid_to_dem(dw_tif, dem_tif, method=Resampling.nearest)
    dw_label_int = np.nan_to_num(dw_label, nan=-1).astype(np.int16)

    # Print class distribution
    print(f"  {'Class':>5}  {'Name':<20}  {'Manning n':>9}  {'Cells':>8}  {'%':>5}")
    print("  " + "-" * 55)
    total = dw_label_int.size
    for cls, name, n in zip(DW_CLASSES, DW_NAMES, DW_MANNING):
        count = int(np.sum(dw_label_int == cls))
        pct   = 100.0 * count / total
        print(f"  {cls:>5}  {name:<20}  {n:>9.3f}  {count:>8,}  {pct:>5.1f}%")
    unknown = int(np.sum(dw_label_int == -1))
    print(f"  {'?':>5}  {'NoData':<20}  {'—':>9}  {unknown:>8,}  {100*unknown/total:>5.1f}%")

    # Build Manning's n raster
    manning = np.full(dw_label_int.shape, np.nan, dtype=np.float64)
    for cls, n in zip(DW_CLASSES, DW_MANNING):
        manning[dw_label_int == cls] = n

    # Fill NoData with median (avoid gaps at domain edges)
    median_n = float(np.nanmedian(manning))
    manning  = np.where(np.isnan(manning), median_n, manning)
    print(f"\n  Manning's n range : {np.nanmin(manning):.3f} – {np.nanmax(manning):.3f}")
    print(f"  NoData filled with median n = {median_n:.3f}")

    return dw_label_int, manning


# ---------------------------------------------------------------------------
# Step 3 — Save outputs
# ---------------------------------------------------------------------------

def step3_save(manning, x, y):
    print()
    print("=" * 60)
    print("Step 3 — Save v3b inputs")
    print("=" * 60)

    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    write_rim2d_nc(manning, x, y, INPUT_DIR / "roughness.nc")
    print("  Written: roughness.nc  (Dynamic World Manning's n)")

    # Copy remaining inputs from v3 (stream-burned DEM + IWD)
    copy_list = [
        "dem.nc", "iwd.nc", "channel_mask.nc",
        "buildings.nc", "sealed_surface.nc",
        "pervious_surface.nc", "sewershed_v1_full.nc",
    ]
    for fname in copy_list:
        src = V3_INPUT / fname
        dst = INPUT_DIR / fname
        if src.exists():
            shutil.copy2(str(src), str(dst))
            print(f"  Copied:  {fname}  (from v3/input)")
        else:
            print(f"  WARNING: {fname} not found in v3/input — skipped")


# ---------------------------------------------------------------------------
# Step 4 — Comparison visualization
# ---------------------------------------------------------------------------

def step4_visualize(dw_label_int, dw_manning, dem, x, y):
    print()
    print("=" * 60)
    print("Step 4 — Comparison visualization")
    print("=" * 60)

    VIS_DIR.mkdir(parents=True, exist_ok=True)

    # Load WorldCover roughness from v1 for comparison
    wc_roughness, _, _ = load_nc(WORK_DIR / "v1" / "input" / "roughness.nc")

    # Hillshade
    from matplotlib.colors import LightSource
    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(np.nan_to_num(dem, nan=0), vert_exag=3, dx=30, dy=30)

    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    ext  = [float(x_km[0]), float(x_km[-1]),
            float(y_km[0]), float(y_km[-1])]

    fig, axes = plt.subplots(1, 3, figsize=(22, 8))

    # --- Panel 1: Dynamic World classes ---
    ax = axes[0]
    cmap_dw = mcolors.ListedColormap(DW_COLORS)
    dw_disp = np.where(dw_label_int >= 0, dw_label_int, np.nan).astype(float)
    im1 = ax.imshow(dw_disp, origin="lower", extent=ext,
                    cmap=cmap_dw, vmin=-0.5, vmax=8.5,
                    interpolation="nearest")
    cbar1 = fig.colorbar(im1, ax=ax, shrink=0.7, ticks=DW_CLASSES)
    cbar1.ax.set_yticklabels(DW_NAMES, fontsize=7)
    ax.set_title(f"Dynamic World Land Cover\n({DW_START} → {DW_END} mode composite)",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    # --- Panel 2: DW Manning's n ---
    ax = axes[1]
    ax.imshow(hs, origin="lower", extent=ext, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.5)
    n_cmap = plt.cm.RdYlGn
    im2 = ax.imshow(dw_manning, origin="lower", extent=ext,
                    cmap=n_cmap, vmin=0.010, vmax=0.090,
                    alpha=0.85, interpolation="nearest")
    fig.colorbar(im2, ax=ax, shrink=0.7, label="Manning's n")
    n_mean = float(np.nanmean(dw_manning))
    ax.set_title(f"v3b — Dynamic World Manning's n\n"
                 f"(mean = {n_mean:.3f},  range {np.nanmin(dw_manning):.3f}–{np.nanmax(dw_manning):.3f})",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    # --- Panel 3: WorldCover Manning's n ---
    ax = axes[2]
    ax.imshow(hs, origin="lower", extent=ext, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.5)
    im3 = ax.imshow(wc_roughness, origin="lower", extent=ext,
                    cmap=n_cmap, vmin=0.010, vmax=0.090,
                    alpha=0.85, interpolation="nearest")
    fig.colorbar(im3, ax=ax, shrink=0.7, label="Manning's n")
    wc_mean = float(np.nanmean(wc_roughness[wc_roughness > -9000]))
    ax.set_title(f"v1/v3 — ESA WorldCover Manning's n\n"
                 f"(mean = {wc_mean:.3f})",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    for ax in axes:
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))

    fig.suptitle(
        "Nairobi Surface Roughness Comparison\n"
        "Dynamic World (Sentinel-2, v3b)  vs  ESA WorldCover (v1/v3)",
        fontsize=13, fontweight="bold"
    )
    fig.tight_layout()
    out = VIS_DIR / "v3b_roughness_comparison.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Nairobi v3b — Dynamic World Surface Roughness Setup")
    print(f"  Domain  : {BBOX}")
    print(f"  DW date : {DW_START} → {DW_END}")
    print(f"  Scale   : {SCALE} m")
    print("=" * 60)

    # Step 1 — download DW
    dw_tif = step1_download_dw()

    # Load DEM grid from v3 to align everything
    dem_tif = WORK_DIR / "v1" / "tif" / "dem.tif"
    if not dem_tif.exists():
        raise FileNotFoundError(
            f"DEM tif not found at {dem_tif}. Run setup_v1.py first."
        )
    dem, x, y = tif_to_rim2d_arrays(dem_tif)

    # Step 2 — remap to Manning's n
    dw_label_int, dw_manning = step2_remap_manning(dw_tif, dem_tif)

    # Step 3 — save inputs
    step3_save(dw_manning, x, y)

    # Step 4 — compare plot
    step4_visualize(dw_label_int, dw_manning, dem, x, y)

    print()
    print("=" * 60)
    print("v3b setup complete.")
    print(f"  Inputs : {INPUT_DIR}/")
    print(f"  Plots  : {VIS_DIR}/")
    print()
    print("Key differences vs v1/v3 (WorldCover):")
    print("  - Built areas: n=0.013 (DW)  vs  n=0.025 (WC) — faster urban flow")
    print("  - Trees:       n=0.080 (DW)  vs  n=0.050 (WC) — more resistance")
    print("  - Grass:       n=0.035 (DW)  vs  n=0.035 (WC) — same")
    print()
    print("Next steps:")
    print("  1. Inspect v3b/visualizations/v3b_roughness_comparison.png")
    print("  2. Copy simulation_v3ss.def → v3b/ and update paths")
    print("  3. Run RIM2D from v3b/")
    print("=" * 60)


if __name__ == "__main__":
    main()
