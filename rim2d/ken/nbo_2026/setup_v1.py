#!/usr/bin/env python3
"""
Setup script for v1 — Nairobi compound flood simulation (pluvial + river inflow).

Domain: Nairobi region, lat -1.402 to -1.098, lon 36.6 to 37.1
CRS:    UTM Zone 37S (EPSG:32737), 30m resolution
Period: April 1 – April 30, 2025 (30 days — Nairobi long rains)

Downloads GEE data (Copernicus DEM, ESA WorldCover, GHSL, MERIT Hydro),
computes native 30m HND, burns river channels using satellite water mask,
creates roughness / buildings / sewershed, and writes simulation_v1.def.

River inflow BCs are generated in the next step (run_v1_river_inflow.py)
after reviewing visualize_v1.py --inputs.

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python setup_v1.py
"""

import json
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

import ee
import netCDF4
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

# Add nile_highres to path for shared modules
sys.path.insert(0, str(Path(__file__).parent.parent / "nile_highres"))
from compute_hnd import compute_hand_from_dem


def regrid_rasterio(src_tif, dem_tif, method=Resampling.bilinear):
    """
    Fast reprojection of src_tif to match the dem_tif grid using rasterio.
    Returns a 2-D numpy array in RIM2D y-ascending convention.
    Much faster than xesmf for large grids (seconds vs hours).
    """
    with rasterio.open(dem_tif) as ref:
        dst_transform = ref.transform
        dst_crs       = ref.crs
        dst_width     = ref.width
        dst_height    = ref.height

    with rasterio.open(src_tif) as src:
        src_data = src.read(1).astype(np.float64)
        dst_data = np.zeros((dst_height, dst_width), dtype=np.float64)
        reproject(
            source=src_data,
            destination=dst_data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=method,
        )

    # Flip to y-ascending (south at index 0) — same as tif_to_rim2d_arrays
    dst_data = dst_data[::-1, :].copy()
    dst_data[~np.isfinite(dst_data)] = np.nan
    return dst_data

# ============================================================
# CONFIGURATION
# ============================================================

# Nairobi domain bounding box (lat/lon)
BBOX = {"west": 36.6, "south": -1.402004, "east": 37.1, "north": -1.098036}

SCALE = 30   # metres
CRS   = "EPSG:32737"   # UTM Zone 37S

SA_KEY = (
    "/data/08-2023/working_notes_jupyter/ignore_nka_gitrepos/"
    "cno-e4drr/devops/earth-engine-service-account/keys/"
    "earthengine-sa-20260130-key.json"
)

WORK_DIR   = Path(__file__).parent          # /data/rim2d/nbo_2026
V1_DIR     = WORK_DIR / "v1"
INPUT_DIR  = V1_DIR / "input"
OUTPUT_DIR = V1_DIR / "output"
TIF_DIR    = V1_DIR / "tif"

# Simulation parameters — 30 days (Nairobi April 2025 long rains)
SIM_DUR    = 2592000   # 30 days in seconds
TSTEP_IN   = 1800      # 30-min boundary time step
N_RAIN     = 1440      # 30 days × 48 half-hours
PLUVIAL_DT = 1800      # 30-min rainfall time step

# Native HND — higher threshold for tropical terrain (more pronounced drainage)
DRAIN_ACC_THRESH = 500

# Stream-burn parameters (satellite channel mask from ESA WorldCover class 80)
BURN_DEPTH    = 3.0   # metres to lower DEM at water pixels
NORMAL_DEPTH  = 3.0   # initial water depth in channel

# Manning's n remap (ESA WorldCover class -> roughness)
MANNING_FROM = [10,    20,    30,    40,    50,    60,    70,    80,    90,    95,    100]
MANNING_TO   = [0.050, 0.040, 0.035, 0.035, 0.025, 0.030, 0.020, 0.025, 0.040, 0.040, 0.030]

MERIT_SCALE = 90   # metres
GHSL_SCALE  = 100  # metres


# ============================================================
# HELPER FUNCTIONS
# ============================================================

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
    print(f"  Downloaded: {path.name}")


def tif_to_rim2d_arrays(tif_path):
    import rasterio
    with rasterio.open(tif_path) as src:
        data      = src.read(1).astype(np.float64)
        transform = src.transform
        nodata    = src.nodata
    nrows, ncols = data.shape
    x      = transform.c + transform.a * (np.arange(ncols) + 0.5)
    y_top  = transform.f + transform.e * (np.arange(nrows) + 0.5)
    y      = y_top[::-1]
    data   = data[::-1, :].copy()
    if nodata is not None:
        data[np.isclose(data, nodata)] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data, x, y


def write_rim2d_nc(data, x, y, nc_path, fill_value=-9999.0):
    arr   = np.where(np.isnan(data), fill_value, data).astype(np.float32)
    nrows, ncols = arr.shape
    ds    = netCDF4.Dataset(str(nc_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.history     = "Generated by setup_v1.py (Nairobi)"
    ds.createDimension("x", ncols)
    ds.createDimension("y", nrows)
    xvar  = ds.createVariable("x", "f8", ("x",))
    xvar[:] = x;  xvar.long_name = "x coordinate";  xvar.units = "m"
    yvar  = ds.createVariable("y", "f8", ("y",))
    yvar[:] = y;  yvar.long_name = "y coordinate";  yvar.units = "m"
    band  = ds.createVariable("Band1", "f4", ("y", "x"),
                              fill_value=np.float32(fill_value))
    band[:] = arr
    ds.close()


# ============================================================
# STEP 1 — Download from Google Earth Engine
# ============================================================

def step1_download_gee():
    if (TIF_DIR / "dem.tif").exists() and (TIF_DIR / "worldcover_classes.tif").exists():
        print("\nGEE TIFs already downloaded — skipping step 1.")
        return
    init_ee()
    bbox_ee = ee.Geometry.Rectangle(
        [BBOX["west"], BBOX["south"], BBOX["east"], BBOX["north"]]
    )
    TIF_DIR.mkdir(parents=True, exist_ok=True)

    print("\n1. Downloading DEM (Copernicus GLO-30)...")
    dem = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
           .filterBounds(bbox_ee).select("DEM").mosaic())
    download_ee_tif(dem, bbox_ee, TIF_DIR / "dem.tif")

    print("\n2. Downloading roughness (ESA WorldCover -> Manning's n)...")
    worldcover = ee.Image("ESA/WorldCover/v200/2021").select("Map")
    manning_int = [int(round(v * 1000)) for v in MANNING_TO]
    roughness   = (worldcover.remap(MANNING_FROM, manning_int)
                   .divide(1000).toFloat())
    download_ee_tif(roughness, bbox_ee, TIF_DIR / "roughness.tif")

    print("\n2b. Downloading raw WorldCover classes...")
    download_ee_tif(ee.Image("ESA/WorldCover/v200/2021").select("Map"),
                    bbox_ee, TIF_DIR / "worldcover_classes.tif")

    print("\n3. Downloading GHSL (sealed/pervious at native 100m)...")
    ghsl     = (ee.Image("JRC/GHSL/P2023A/GHS_BUILT_S/2020")
                .select("built_surface").unmask(0))
    sealed   = ghsl.divide(10000).clamp(0, 1).toFloat()
    pervious = ee.Image(1).subtract(sealed).toFloat()
    download_ee_tif(sealed,   bbox_ee, TIF_DIR / "sealed_100m.tif",  scale=GHSL_SCALE)
    download_ee_tif(pervious, bbox_ee, TIF_DIR / "pervious_100m.tif", scale=GHSL_SCALE)

    print("\n4. Downloading MERIT Hydro (elv, wth at native 90m)...")
    merit = ee.Image("MERIT/Hydro/v1_0_1")
    for band in ("elv", "wth"):
        download_ee_tif(merit.select(band), bbox_ee,
                        TIF_DIR / f"merit_{band}_90m.tif", scale=MERIT_SCALE)

    print("\nAll GEE downloads complete.")


# ============================================================
# STEP 2 — Process: HND, burn, NetCDF
# ============================================================

def step2_process_data():
    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Always need DEM + x/y for downstream steps
    print("\nReading DEM...")
    dem, x, y = tif_to_rim2d_arrays(TIF_DIR / "dem.tif")
    nrows, ncols = dem.shape
    dem_mask     = np.isnan(dem)
    dx           = abs(float(x[1] - x[0])) if ncols > 1 else SCALE
    print(f"  Grid: {ncols} x {nrows}, dx={dx:.1f}m")
    print(f"  DEM range: {np.nanmin(dem):.1f} – {np.nanmax(dem):.1f} m")

    # HND — skip if already written
    if (INPUT_DIR / "hnd_30m.nc").exists():
        print("\nHND already computed — loading from disk...")
    else:
        print("\nComputing native 30m HND (pyflwdir)...")
        hnd, drain_mask, flwacc, dem_filled = compute_hand_from_dem(
            dem, nodata=-9999.0, drain_acc_thresh=DRAIN_ACC_THRESH, dx=dx
        )
        write_rim2d_nc(hnd,                      x, y, INPUT_DIR / "hnd_30m.nc")
        write_rim2d_nc(flwacc.astype(np.float64), x, y, INPUT_DIR / "flwacc_30m.nc")
        write_rim2d_nc(np.where(drain_mask, 1.0, 0.0), x, y,
                       INPUT_DIR / "drainage_mask_30m.nc")
        print("  Written: hnd_30m.nc, flwacc_30m.nc, drainage_mask_30m.nc")

    # Channel mask / burned DEM / IWD — skip if already written
    if (INPUT_DIR / "iwd.nc").exists():
        print("Channel mask / burned DEM / IWD already written — loading channel_mask...")
        ds = netCDF4.Dataset(str(INPUT_DIR / "channel_mask.nc"))
        channel_mask = np.array(ds["Band1"][:], dtype=np.float32)
        ds.close()
        burned_dem = dem.copy()
        burned_dem[channel_mask > 0] -= BURN_DEPTH
    else:
        print("\nCreating channel mask (ESA WorldCover class 80 = permanent water)...")
        wc, _, _ = tif_to_rim2d_arrays(TIF_DIR / "worldcover_classes.tif")
        if wc.shape != dem.shape:
            tmp = np.zeros(dem.shape)
            h = min(wc.shape[0], nrows);  w = min(wc.shape[1], ncols)
            tmp[:h, :w] = wc[:h, :w]
            wc = tmp
        channel_mask = (wc == 80).astype(np.float32)
        n_water = int(np.sum(channel_mask))
        print(f"  Water cells (class 80): {n_water} ({100*n_water/dem.size:.1f}%)")
        write_rim2d_nc(channel_mask, x, y, INPUT_DIR / "channel_mask.nc")

        print(f"\nBurning river channel into DEM (burn_depth={BURN_DEPTH}m)...")
        burned_dem = dem.copy()
        burned_dem[channel_mask > 0] -= BURN_DEPTH
        write_rim2d_nc(burned_dem, x, y, INPUT_DIR / "dem.nc")
        print("  Written: dem.nc")

        print(f"\nCreating IWD (depth={NORMAL_DEPTH}m at channel cells)...")
        iwd = np.where(channel_mask > 0, NORMAL_DEPTH, 0.0)
        write_rim2d_nc(iwd, x, y, INPUT_DIR / "iwd.nc")
        print("  Written: iwd.nc")
    iwd = np.where(channel_mask > 0, NORMAL_DEPTH, 0.0)

    print("\nRegridding GHSL sealed/pervious (100m -> 30m) via rasterio...")
    for name, dest_name in [("sealed", "sealed_surface"), ("pervious", "pervious_surface")]:
        d30 = regrid_rasterio(TIF_DIR / f"{name}_100m.tif", TIF_DIR / "dem.tif")
        d30 = np.clip(np.nan_to_num(d30, nan=0.0), 0.0, 1.0)
        write_rim2d_nc(d30, x, y, INPUT_DIR / f"{dest_name}.nc")
        print(f"  Written: {dest_name}.nc")

    print("\nConverting roughness...")
    roughness, _, _ = tif_to_rim2d_arrays(TIF_DIR / "roughness.tif")
    if roughness.shape != dem.shape:
        tmp = np.full(dem.shape, np.nan)
        h = min(roughness.shape[0], nrows);  w = min(roughness.shape[1], ncols)
        tmp[:h, :w] = roughness[:h, :w]
        roughness = tmp
    write_rim2d_nc(roughness, x, y, INPUT_DIR / "roughness.nc")
    print("  Written: roughness.nc")

    print("\nRasterizing Nairobi building footprints (nbo.geojson)...")
    sys.path.insert(0, str(Path(__file__).parent.parent / "nile_highres"))
    from rasterize_buildings import rasterize_overture_buildings
    buildings = rasterize_overture_buildings(
        WORK_DIR / "nbo.geojson",
        TIF_DIR / "dem.tif",
    )
    write_rim2d_nc(buildings, x, y, INPUT_DIR / "buildings.nc")
    n_bldg = int(np.sum(buildings > 0))
    print(f"  Building cells: {n_bldg} ({100*n_bldg/buildings.size:.1f}%)")
    print("  Written: buildings.nc")

    print("\nCreating full-domain sewershed (all 1.0)...")
    sewershed = np.ones_like(dem, dtype=np.float64)
    sewershed[dem_mask] = np.nan
    write_rim2d_nc(sewershed, x, y, INPUT_DIR / "sewershed_v1_full.nc")
    print("  Written: sewershed_v1_full.nc")

    print("\nEnhancing sealed surface at building cells...")
    sealed_data = regrid_rasterio(TIF_DIR / "sealed_100m.tif", TIF_DIR / "dem.tif")
    sealed_data = np.clip(np.nan_to_num(sealed_data, nan=0.0), 0.0, 1.0)
    sealed_data[buildings > 0] = 1.0
    write_rim2d_nc(sealed_data, x, y, INPUT_DIR / "sealed_surface.nc")
    print("  Written: sealed_surface.nc (overwrite with enhanced version)")

    return dem, burned_dem, iwd, channel_mask, x, y, dem_mask


# ============================================================
# STEP 3 — Outflow placeholder
# ============================================================

def step3_create_outflow():
    with open(INPUT_DIR / "outflowlocs.txt", "w") as f:
        f.write("0\n0\n")
    print("\nWritten: outflowlocs.txt (empty)")


# ============================================================
# STEP 4 — Write simulation_v1.def
# ============================================================

def step4_write_simdef():
    ds    = netCDF4.Dataset(str(INPUT_DIR / "dem.nc"))
    ncols = len(ds["x"][:])
    nrows = len(ds["y"][:])
    ds.close()

    rain_base  = "imerg_v1_t"
    n_outputs  = SIM_DUR // 21600          # every 6 hours
    out_times  = [i * 21600 for i in range(1, n_outputs + 1)]
    out_timing = " ".join(str(t) for t in out_times)

    simdef = f"""\
# RIM2D model definition file (version 2.0)
# Nairobi v1 — compound flood (pluvial + river inflow)
# Domain: lat -1.402 to -1.098, lon 36.6 to 37.1 — UTM Zone 37S
# Grid: {ncols} x {nrows}, cellsize ~30m
# Period: April 2025 (30 days, Nairobi long rains)

###### INPUT RASTERS ######
**DEM**
input/dem.nc
**buildings**
input/buildings.nc
**IWD**
file
input/iwd.nc
**roughness**
file
input/roughness.nc
**pervious_surface**
input/pervious_surface.nc
**sealed_surface**
input/sealed_surface.nc
**sewershed**
input/sewershed_v1_full.nc

###### BOUNDARIES ######
**fluvial_boundary**
input/inflowlocs_v1.txt

# RAINFALL — April 2025 IMERG (actual, no amplification)
**pluvial_raster_nr**
{N_RAIN}
**pluvial_dt**
{PLUVIAL_DT}
**pluvial_start**
0
**pluvial_base_fn**
input/rain/{rain_base}

###### OUTPUT FILE SPECIFICATIONS ######
**output_base_fn**
output/nbo_v1_
**out_cells**
input/outflowlocs.txt
**out_timing_nr**
{n_outputs}
**out_timing**
{out_timing}

###### MODEL PARAMETERS ######
**dt**
1
**sim_dur**
{SIM_DUR}
**inf_rate**
0
**sewer_cap**
0
**sewer_threshold**
0.002
**alpha**
0.4
**theta**
0.8

###### FLAGS ######
**verbose**
.TRUE.
**routing**
.TRUE.
**superverbose**
.FALSE.
**neg_wd_corr**
.TRUE.
**sew_sub**
.FALSE.
none
**fluv_bound**
.TRUE.
input/fluvbound_mask_v1.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""

    defpath = V1_DIR / "simulation_v1.def"
    with open(str(defpath), "w") as f:
        f.write(simdef)
    print(f"\nWritten: {defpath.name} (grid {ncols}x{nrows})")


# ============================================================
# MAIN
# ============================================================

def main():
    V1_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Nairobi v1 — Compound Flood Setup")
    print(f"  Domain: W={BBOX['west']}, S={BBOX['south']}, "
          f"E={BBOX['east']}, N={BBOX['north']}")
    print(f"  Scale: {SCALE}m, CRS: {CRS}")
    print(f"  Duration: {SIM_DUR/86400:.0f} days ({SIM_DUR}s)")
    print(f"  Rain files: {N_RAIN}")
    print("=" * 60)

    step1_download_gee()
    step2_process_data()
    step3_create_outflow()
    step4_write_simdef()

    print("\n" + "=" * 60)
    print("v1 terrain setup complete!")
    print("Next steps:")
    print("  1. python download_imerg_v1.py          # download April 2025 IMERG")
    print("  2. python run_v1_river_inflow.py         # detect rivers + generate BCs")
    print("  3. python visualize_v1.py --inputs       # verify inputs (STOP HERE)")
    print("  4. review river entry points, adjust if needed")
    print("  5. cd v1 && ../../bin/RIM2D simulation_v1.def --def flex")
    print("=" * 60)


if __name__ == "__main__":
    main()
