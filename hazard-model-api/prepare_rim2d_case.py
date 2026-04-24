#!/usr/bin/env python3
"""
Assemble a runnable RIM2D case from the raw downloads.

Given a region out_dir populated by `download_*.py` + `rasterize_buildings.py`
+ `compute_hand.py`, this script:
1. Regrids sealed/pervious/WorldCover roughness to the DEM grid.
2. Builds the IWD (initial water depth) by the chosen method.
3. Writes `input/` NetCDFs in RIM2D's convention.
4. Emits `simulation_<version>.def`.

IWD methods (choose with --iwd)
--------------------------------
    worldcover   ESA WorldCover class 80 → 3 m channel burn + IWD seed.
                 Simplest. Works anywhere with visible rivers.
    hnd          Use HAND computed by compute_hand.py — drainage cells
                 get a small seed. Needs compute_hand.py run first.
    tdx          TDX-Hydro v2 segments burned by stream-order width/depth.
                 Needs download_river_network.py run first.
    hnd_tdx      TDX burn for mapped channels + HND drainage gap-fill.
                 Best quality; matches NBO v6.

Inputs expected in <out>/tif/
    dem.tif
    worldcover_classes.tif          (for worldcover + hnd_tdx)
    roughness.tif
    sealed_100m.tif, pervious_100m.tif
    river_network_tdx.geojson       (for tdx + hnd_tdx)

Inputs expected in <out>/input/
    buildings.nc                    (rasterize_buildings.py)
    hnd.nc, flwacc.nc              (compute_hand.py; for hnd + hnd_tdx)

Outputs
-------
    <out>/<version>/input/{dem,buildings,roughness,sealed,pervious,sewershed,
                          iwd,channel_mask}.nc
    <out>/<version>/input/outflowlocs.txt
    <out>/<version>/output/
    <out>/<version>/simulation_<version>.def

Usage
-----
    python prepare_rim2d_case.py --bbox 36.6,-1.402,37.1,-1.098 \
           --out ./runs/nbo --start 2026-03-06 --end 2026-03-07 \
           --scale 30 --crs EPSG:32737 --version v1 --iwd worldcover
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from common import (add_common_args, parse_region, tif_to_rim2d_arrays,
                    write_rim2d_nc, regrid_rasterio)


BURN_DEPTH   = 3.0   # metres — stream-burn depth
NORMAL_DEPTH = 3.0   # metres — IWD seed at channel cells
ORDER_WIDTH  = {2: 15, 3: 30, 4: 60, 5: 120, 6: 180, 7: 240}     # m
ORDER_DEPTH  = {2: 0.5, 3: 1.0, 4: 1.5, 5: 2.5, 6: 3.5, 7: 4.5}  # m
HND_BURN_DEPTH = 0.3   # headwater gap-fill depth for hnd_tdx


def build_worldcover_iwd(dem, wc_tif, ref_tif):
    wc, _, _ = tif_to_rim2d_arrays(wc_tif)
    if wc.shape != dem.shape:
        tmp = np.zeros_like(dem)
        h = min(wc.shape[0], dem.shape[0])
        w = min(wc.shape[1], dem.shape[1])
        tmp[:h, :w] = wc[:h, :w]
        wc = tmp
    channel_mask = (wc == 80).astype(np.float32)
    burned = dem.copy()
    burned[channel_mask > 0] -= BURN_DEPTH
    iwd = np.where(channel_mask > 0, NORMAL_DEPTH, 0.0)
    return burned, iwd, channel_mask


def build_tdx_iwd(dem, ref_tif, tdx_gj, x, y):
    """Burn TDX-Hydro segments by stream order into dem, build iwd + mask."""
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize

    gdf = gpd.read_file(tdx_gj)
    with rasterio.open(ref_tif) as src:
        dst_crs       = src.crs
        dst_transform = src.transform
        dst_shape     = (src.height, src.width)

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    if gdf.crs != dst_crs:
        gdf = gdf.to_crs(dst_crs)

    burned = dem.copy()
    iwd    = np.zeros_like(dem)
    mask   = np.zeros_like(dem, dtype=np.float32)

    for order, width_m in ORDER_WIDTH.items():
        depth_m = ORDER_DEPTH[order]
        sub = gdf[gdf.get("stream_order", 0) == order]
        if sub.empty:
            continue
        # Buffer segments by width/2 (in CRS units = metres)
        buf = sub.geometry.buffer(width_m / 2.0)
        shapes = ((g, 1) for g in buf if g is not None)
        raster = rasterize(shapes, out_shape=dst_shape,
                           transform=dst_transform, fill=0, dtype=np.uint8,
                           all_touched=True)
        raster = raster[::-1, :]   # y-ascending
        touched = raster > 0
        burned[touched] -= depth_m
        iwd[touched]    = np.maximum(iwd[touched], depth_m)
        mask[touched]   = 1.0
        print(f"[tdx] order {order}: {touched.sum():,} cells "
              f"(w={width_m}m, d={depth_m}m)")
    return burned, iwd, mask


def write_simdef(version: str, version_dir: Path, nrows: int, ncols: int,
                 sim_dur_s: int, n_rain: int, rain_dt_s: int,
                 rain_prefix: str):
    n_outputs  = max(sim_dur_s // 21600, 1)        # every 6 h
    out_times  = [i * 21600 for i in range(1, n_outputs + 1)]
    out_timing = " ".join(str(t) for t in out_times)
    content = f"""\
# RIM2D model definition — {version}
# Grid: {ncols} x {nrows}
# Written by hazard-model-api/prepare_rim2d_case.py

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
input/sewershed.nc

###### RAINFALL ######
**pluvial_raster_nr**
{n_rain}
**pluvial_dt**
{rain_dt_s}
**pluvial_start**
0
**pluvial_base_fn**
input/rain/{rain_prefix}

###### OUTPUT ######
**output_base_fn**
output/case_{version}_
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
{sim_dur_s}
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
.FALSE.
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    path = version_dir / f"simulation_{version}.def"
    with open(path, "w") as f:
        f.write(content)
    print(f"[def] wrote {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap, temporal=True)
    ap.add_argument("--version", default="v1",
                    help="Case tag (default: v1) — controls output dir name.")
    ap.add_argument("--iwd", choices=["worldcover", "hnd", "tdx", "hnd_tdx"],
                    default="worldcover",
                    help="IWD method (default: worldcover).")
    ap.add_argument("--rain-dt-s", type=int, default=1800,
                    help="Rainfall timestep in seconds (default 1800 = 30 min).")
    ap.add_argument("--rain-prefix", default="imerg_t",
                    help="Rainfall file prefix (default: imerg_t, matches download_imerg.py).")
    args = ap.parse_args()
    r = parse_region(args)

    tif_dir   = r.out / "tif"
    ref_tif   = tif_dir / "dem.tif"
    if not ref_tif.exists():
        sys.exit(f"ERROR: {ref_tif} not found — run download_dem.py first.")

    version_dir = r.out / args.version
    input_dir   = version_dir / "input"
    output_dir  = version_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[prep] reading reference DEM …")
    dem, x, y = tif_to_rim2d_arrays(ref_tif)
    dem_mask  = np.isnan(dem)
    nrows, ncols = dem.shape

    # ---------- IWD ----------
    print(f"[prep] IWD method: {args.iwd}")
    if args.iwd == "worldcover":
        wc_tif = tif_dir / "worldcover_classes.tif"
        if not wc_tif.exists():
            sys.exit("ERROR: worldcover_classes.tif missing (download_worldcover.py).")
        burned, iwd, chan = build_worldcover_iwd(dem, wc_tif, ref_tif)
    elif args.iwd == "tdx":
        tdx_gj = tif_dir / "river_network_tdx.geojson"
        if not tdx_gj.exists():
            sys.exit("ERROR: river_network_tdx.geojson missing.")
        burned, iwd, chan = build_tdx_iwd(dem, ref_tif, tdx_gj, x, y)
    elif args.iwd == "hnd":
        hnd_nc = input_dir.parent.parent / "input" / "hnd.nc"
        if not hnd_nc.exists():
            sys.exit("ERROR: hnd.nc missing — run compute_hand.py first.")
        import netCDF4
        ds = netCDF4.Dataset(hnd_nc);  hnd = np.array(ds["Band1"][:]);  ds.close()
        chan = (hnd <= 0.5).astype(np.float32)
        burned = dem.copy();  burned[chan > 0] -= BURN_DEPTH
        iwd    = np.where(chan > 0, NORMAL_DEPTH, 0.0)
    else:  # hnd_tdx
        tdx_gj = tif_dir / "river_network_tdx.geojson"
        hnd_nc = r.out / "input" / "hnd.nc"
        if not tdx_gj.exists() or not hnd_nc.exists():
            sys.exit("ERROR: hnd_tdx requires both TDX geojson and hnd.nc.")
        burned, iwd, chan = build_tdx_iwd(dem, ref_tif, tdx_gj, x, y)
        import netCDF4
        ds = netCDF4.Dataset(hnd_nc);  hnd = np.array(ds["Band1"][:]);  ds.close()
        gap = (hnd <= 0.0) & (chan < 1)
        burned[gap] -= HND_BURN_DEPTH
        iwd[gap]    = np.maximum(iwd[gap], HND_BURN_DEPTH)
        chan[gap]   = 1.0

    write_rim2d_nc(burned, x, y, input_dir / "dem.nc",         long_name="elevation burned", units="m")
    write_rim2d_nc(iwd,    x, y, input_dir / "iwd.nc",         long_name="initial water depth", units="m")
    write_rim2d_nc(chan,   x, y, input_dir / "channel_mask.nc", long_name="channel mask", units="1")

    # ---------- roughness ----------
    print("[prep] roughness …")
    rough, _, _ = tif_to_rim2d_arrays(tif_dir / "roughness.tif")
    if rough.shape != dem.shape:
        tmp = np.full_like(dem, np.nan)
        h = min(rough.shape[0], nrows);  w = min(rough.shape[1], ncols)
        tmp[:h, :w] = rough[:h, :w];  rough = tmp
    write_rim2d_nc(rough, x, y, input_dir / "roughness.nc",
                   long_name="Manning's n", units="s m-1/3")

    # ---------- sealed / pervious (100 m → DEM grid) ----------
    print("[prep] sealed / pervious (100 m → target grid) …")
    sealed = regrid_rasterio(tif_dir / "sealed_100m.tif", ref_tif)
    sealed = np.clip(np.nan_to_num(sealed, nan=0.0), 0.0, 1.0)
    # Boost sealed fraction to 1 where buildings exist
    bld_nc = r.out / "input" / "buildings.nc"
    if bld_nc.exists():
        import netCDF4
        ds = netCDF4.Dataset(bld_nc); bld = np.array(ds["Band1"][:]); ds.close()
        sealed[bld > 0] = 1.0
    write_rim2d_nc(sealed, x, y, input_dir / "sealed_surface.nc",
                   long_name="sealed fraction", units="1")
    perv = regrid_rasterio(tif_dir / "pervious_100m.tif", ref_tif)
    perv = np.clip(np.nan_to_num(perv, nan=0.0), 0.0, 1.0)
    write_rim2d_nc(perv, x, y, input_dir / "pervious_surface.nc",
                   long_name="pervious fraction", units="1")

    # ---------- buildings pass-through ----------
    bld_src = r.out / "input" / "buildings.nc"
    if bld_src.exists():
        import shutil
        shutil.copy(bld_src, input_dir / "buildings.nc")

    # ---------- sewershed: default full-domain = 1 ----------
    sew = np.ones_like(dem)
    sew[dem_mask] = np.nan
    write_rim2d_nc(sew, x, y, input_dir / "sewershed.nc",
                   long_name="sewershed mask", units="1")

    # ---------- outflowlocs (empty default) ----------
    with open(input_dir / "outflowlocs.txt", "w") as f:
        f.write("0\n0\n")

    # ---------- simulation.def ----------
    d0 = datetime.strptime(r.start, "%Y-%m-%d")
    d1 = datetime.strptime(r.end, "%Y-%m-%d")
    sim_dur_s = int((d1 - d0).total_seconds())
    n_rain    = sim_dur_s // args.rain_dt_s
    write_simdef(args.version, version_dir, nrows, ncols,
                 sim_dur_s, n_rain, args.rain_dt_s, args.rain_prefix)

    print(f"\n[done] case ready under {version_dir}")
    print(f"       run: cd {version_dir} && ../../rim2d/bin/RIM2D "
          f"simulation_{args.version}.def --def flex")
    return 0


if __name__ == "__main__":
    sys.exit(main())
