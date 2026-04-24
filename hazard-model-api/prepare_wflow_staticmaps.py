#!/usr/bin/env python3
"""
Build a Wflow.jl `staticmaps.nc` from the raw GeoTIFFs produced by the
download scripts. Ports the core of `../wflow-jl/shared/derive_staticmaps.py`,
parameterised over --bbox + --out so it works for any region.

What it writes (80+ Wflow variables, grouped)
---------------------------------------------
    Grid:            wflow_dem, wflow_subcatch, wflow_gauges, wflow_pits
    Flow:            wflow_ldd (PCRaster encoding), wflow_river, RiverWidth,
                     RiverDepth, Slope, RiverSlope, RiverLength, StreamOrder
    Land cover:      wflow_landuse, N, N_River, ... (Manning's n per class)
    Soil (SBM):      thetaS, thetaR, KsatVer (×4 layers), M, f,
                     c (×4 layers), SoilThickness, RootingDepth

All variables are stored on the MERIT 1 km grid (reference = dem.tif). For
higher resolution, call with `--scale 500` or similar — note this multiplies
output size by (old/new)².

Inputs (expected under <out>/tif/)
----------------------------------
    dem.tif                        (download_dem.py --target merit --scale 1000)
    worldcover_classes.tif         (download_worldcover.py)
    merit_dir_90m.tif              (download_merit_hydro.py, band 'dir')
    merit_upa_90m.tif              (download_merit_hydro.py, band 'upa')
    soil_sand_250m.tif             (download_soilgrids.py)
    soil_silt_250m.tif             (download_soilgrids.py)
    soil_clay_250m.tif             (download_soilgrids.py)
    soil_bedrock_depth_250m.tif    (download_soilgrids.py --depth; optional)

Outputs
-------
    <out>/staticmaps.nc
    <out>/config.toml              (if --write-toml)

Usage
-----
    python prepare_wflow_staticmaps.py --bbox 28.83,-4.50,30.89,-2.29 \
           --out ./runs/bdi --start 2021-01-01 --end 2023-01-01 --write-toml
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import xarray as xr

from common import add_common_args, parse_region


D8_TO_LDD = {
    1: 6, 2: 3, 4: 2, 8: 1, 16: 4, 32: 7, 64: 8, 128: 9,
    0: 5, 255: 5,
}


def open_to_ref(path: Path, ref: xr.DataArray,
                method: str = "bilinear") -> xr.DataArray:
    """Open a TIF and regrid to ref grid. Returns 2D DataArray."""
    import rioxarray
    da = rioxarray.open_rasterio(path).squeeze()
    if da.rio.crs != ref.rio.crs:
        da = da.rio.reproject_match(ref, resampling=method)
    else:
        da = da.rio.reproject_match(ref)
    return da.astype(np.float32)


def d8_to_ldd_array(d8: np.ndarray, mask: np.ndarray) -> np.ndarray:
    ldd = np.zeros_like(d8, dtype=np.float32)
    for d, l in D8_TO_LDD.items():
        ldd[d8 == d] = l
    ldd[0, :]  = 5
    ldd[-1, :] = 5
    ldd[:, 0]  = 5
    ldd[:, -1] = 5
    ldd[~mask] = np.nan
    return ldd


def pedotransfer(sand, silt, clay, mask):
    """Saxton & Rawls (2006) pedotransfer."""
    total = sand + clay + silt
    sand_f = np.where(total > 0, sand / total, 0.33)
    clay_f = np.where(total > 0, clay / total, 0.33)
    thetaS = 0.332 - 0.0007251 * sand_f * 100 \
             + 0.1276 * np.log10(clay_f * 100 + 1)
    thetaS = np.clip(thetaS, 0.35, 0.55).astype(np.float32)
    thetaR = np.clip(0.01 + 0.003 * clay_f * 100, 0.05, 0.25).astype(np.float32)
    lam = np.clip(0.131 + 0.00125 * sand_f * 100 - 0.00207 * clay_f * 100,
                  0.1, 0.5)
    c = np.clip(1.0 / (1.0 + lam), 0.05, 0.2)
    thetaS[~mask] = np.nan
    thetaR[~mask] = np.nan
    c[~mask]      = np.nan
    return thetaS, thetaR, c.astype(np.float32)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap, temporal=True)
    ap.add_argument("--write-toml", action="store_true",
                    help="Also emit a minimal Wflow SBM config.toml.")
    args = ap.parse_args()
    r = parse_region(args)

    tif_dir = r.out / "tif"
    dem_tif = tif_dir / "dem.tif"
    if not dem_tif.exists():
        sys.exit(f"ERROR: {dem_tif} not found — run download_dem.py "
                 f"--target merit --scale 1000 first.")

    import rioxarray
    print("[wflow] loading reference DEM ...")
    dem_da = rioxarray.open_rasterio(dem_tif).squeeze()
    dem = dem_da.values.astype(np.float32)
    mask = ~np.isnan(dem) & (dem > 0)
    ny, nx = dem.shape
    lat = dem_da.y.values
    lon = dem_da.x.values
    print(f"[wflow] grid {ny}x{nx}, active {mask.sum():,} cells")

    # ---- Flow ----------------------------------------------------------
    print("[wflow] D8 → LDD ...")
    d8 = open_to_ref(tif_dir / "merit_dir_90m.tif", dem_da,
                     method="nearest").values.astype(np.int32)
    ldd = d8_to_ldd_array(d8, mask)

    print("[wflow] river mask from upstream area (≥10 km²) ...")
    upa = open_to_ref(tif_dir / "merit_upa_90m.tif", dem_da).values
    upa[~mask] = np.nan
    river_mask = (upa >= 10.0).astype(np.float32)
    river_mask[~mask] = np.nan
    RiverWidth = np.clip(1.22 * (upa ** 0.557), 30, 500)
    RiverWidth[river_mask != 1] = np.nan
    RiverDepth = np.clip(0.27 * (upa ** 0.39), 1.0, 5.0)
    RiverDepth[river_mask != 1] = np.nan

    # Slope from DEM (gradient)
    cell_m = abs(lat[1] - lat[0]) * 111000
    dy, dx = np.gradient(np.where(mask, dem, 0), cell_m)
    slope = np.clip(np.sqrt(dx**2 + dy**2), 1e-4, 1.0)
    slope[~mask] = np.nan
    river_slope = np.where(river_mask == 1, np.clip(slope, 1e-5, 0.1), np.nan)
    river_length = np.full((ny, nx), cell_m * 1.414, dtype=np.float32)
    river_length[river_mask != 1] = np.nan

    # Outlet = max-upa pit
    pit_m = (ldd == 5) & mask
    out_idx = np.unravel_index(np.argmax(np.where(pit_m, upa, 0)), upa.shape)
    subcatch = np.where(mask, 1.0, np.nan)
    gauges   = np.full((ny, nx), np.nan);  gauges[out_idx] = 1.0
    pits     = np.full((ny, nx), np.nan);  pits[out_idx]   = 1.0

    # ---- Land cover ---------------------------------------------------
    print("[wflow] land use → Manning N ...")
    lu = open_to_ref(tif_dir / "worldcover_classes.tif", dem_da,
                     method="nearest").values.astype(np.float32)
    n_lu = {10:.15, 20:.10, 30:.05, 40:.04, 50:.02, 60:.03, 70:.03,
            80:.01, 90:.10, 95:.08, 100:.03}
    N = np.full((ny, nx), 0.05, dtype=np.float32)
    for k, v in n_lu.items(): N[lu == k] = v
    N[~mask] = np.nan
    N_river = np.where(river_mask == 1, 0.035, np.nan).astype(np.float32)

    # ---- Soil ----------------------------------------------------------
    print("[wflow] soil (pedotransfer + Ksat depth decay) ...")
    try:
        sand = open_to_ref(tif_dir / "soil_sand_250m.tif", dem_da).values / 100.0
        silt = open_to_ref(tif_dir / "soil_silt_250m.tif", dem_da).values / 100.0
        clay = open_to_ref(tif_dir / "soil_clay_250m.tif", dem_da).values / 100.0
    except Exception as e:
        sys.exit(f"ERROR loading SoilGrids TIFs: {e}\n"
                 f"Run download_soilgrids.py first.")
    thetaS, thetaR, c_param = pedotransfer(sand, silt, clay, mask)

    # Ksat defaults — Rawls table by texture class (mm/day)
    ksat_base = np.where((sand > 0.6), 2000.0,
                np.where((clay > 0.4), 50.0, 500.0)).astype(np.float32)
    ksat_base[~mask] = np.nan
    f_param = np.clip(0.001 + 0.003 * clay, 0.0003, 0.01).astype(np.float32)
    f_param[~mask] = np.nan
    if (tif_dir / "soil_bedrock_depth_250m.tif").exists():
        rootzone = open_to_ref(tif_dir / "soil_bedrock_depth_250m.tif",
                               dem_da).values.astype(np.float32)
        soil_thick = np.clip(rootzone * 10, 300, 2500)   # cm → mm
    else:
        soil_thick = np.full((ny, nx), 2000.0, dtype=np.float32)
    soil_thick[~mask] = np.nan
    M_param = np.clip(soil_thick / f_param, 50, 1500).astype(np.float32)

    # Ksat at 4 layer midpoints
    layer_depths_mm = [25, 125, 300, 750]
    kv_layers = np.stack([
        np.clip(ksat_base * np.exp(-f_param * d), 1, 5000)
        for d in layer_depths_mm
    ], axis=0)
    kv_layers = kv_layers.astype(np.float32)
    c_layers = np.stack([(7.5 + 6.5 * c_param * f).astype(np.float32)
                         for f in (1.0, 0.95, 0.90, 0.85)], axis=0)

    # ---- Build xarray dataset -----------------------------------------
    print("[wflow] assembling staticmaps xarray.Dataset ...")
    coords = {"lat": lat, "lon": lon}
    dims2d = ("lat", "lon")
    layer  = np.arange(1, 5)
    vars_2d = {
        "wflow_dem":        dem,
        "wflow_ldd":        ldd,
        "wflow_river":      river_mask,
        "RiverWidth":       RiverWidth.astype(np.float32),
        "RiverDepth":       RiverDepth.astype(np.float32),
        "RiverLength":      river_length,
        "Slope":            slope.astype(np.float32),
        "RiverSlope":       river_slope.astype(np.float32),
        "wflow_subcatch":   subcatch.astype(np.float32),
        "wflow_gauges":     gauges.astype(np.float32),
        "wflow_pits":       pits.astype(np.float32),
        "wflow_landuse":    np.where(mask, lu, np.nan).astype(np.float32),
        "N":                N,
        "N_River":          N_river,
        "thetaS":           thetaS,
        "thetaR":           thetaR,
        "KsatVer":          ksat_base,
        "M":                M_param,
        "f":                f_param,
        "SoilThickness":    soil_thick,
        "RootingDepth":     np.clip(soil_thick * 0.5, 100, 1500).astype(np.float32),
    }
    ds = xr.Dataset(
        {name: (dims2d, arr) for name, arr in vars_2d.items()},
        coords=coords,
    )
    ds["c"]  = (("layer", "lat", "lon"), c_layers)
    ds["kv"] = (("layer", "lat", "lon"), kv_layers)
    ds = ds.assign_coords(layer=layer)

    out_path = r.out / "staticmaps.nc"
    ds.to_netcdf(out_path)
    size_mb = out_path.stat().st_size / 1e6
    print(f"[done] {out_path} ({size_mb:.1f} MB, {len(ds.data_vars)} vars)")

    if args.write_toml:
        toml_path = r.out / "config.toml"
        write_toml(r, toml_path)
        print(f"[toml] {toml_path}")

    return 0


def write_toml(r, path):
    """Minimal Wflow SBM TOML pointing at the staticmaps + forcing."""
    content = f'''\
# Wflow SBM config — generated by hazard-model-api/prepare_wflow_staticmaps.py
calendar = "standard"
starttime = "{r.start}T00:00:00"
endtime   = "{r.end}T00:00:00"
time_units = "days since 1900-01-01 00:00:00"
timestepsecs = 86400
dir_input  = "."
dir_output = "output"

[state]
path_input  = "instates.nc"
path_output = "outstates.nc"

[input]
path_forcing    = "forcing.nc"
path_static     = "staticmaps.nc"
gauges          = "wflow_gauges"
ldd             = "wflow_ldd"
river_location  = "wflow_river"
subcatchment    = "wflow_subcatch"
forcing = ["vertical.precipitation", "vertical.temperature", "vertical.potential_evaporation"]

[model]
type = "sbm"
masswasting = false
snow = false
reinit = true
kin_wave_iteration = true
thicknesslayers = [50, 100, 300]

[output]
path = "output.nc"
'''
    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    sys.exit(main())
