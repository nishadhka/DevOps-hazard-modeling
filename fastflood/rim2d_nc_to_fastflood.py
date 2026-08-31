#!/usr/bin/env python3
"""Convert RIM2D case NetCDF inputs (from HF E4DRR/rim2d-simulations) into
GeoTIFFs that FastFlood can consume.

RIM2D `.nc` files (variable `Band1`, dims y,x) carry UTM-metre x/y coords but
NO embedded CRS. We derive the UTM EPSG from the case centroid longitude, build
a north-up GeoTIFF transform from the coords, and write:

  dem.tif        elevation (m)            <- dem.nc
  man.tif        Manning's n              <- roughness.nc
  inf.tif        infiltration (mm/hr)     <- pervious_surface.nc * KSAT
  rain_mmhr.tif  event-mean intensity     <- sum(rain/imerg_t*.nc)/duration

FastFlood applies rain*dur as the event total, and rain frames are per-30-min
mm/hr rates, so:
  event_total_mm   = sum(frame_mm_hr) * 0.5
  duration_h       = n_frames * 0.5
  mean_intensity   = event_total_mm / duration_h   (written to rain_mmhr.tif)
Passing `-rain rain_mmhr.tif -dur <duration_h>` then reproduces true spatial totals.

Usage:
  rim2d_nc_to_fastflood.py <case_input_dir> <out_dir> <lon_centroid> <lat_centroid> [ksat_mmhr]
"""
import sys, glob, math
from pathlib import Path
import numpy as np
import xarray as xr
import rasterio
from rasterio.transform import from_origin

def utm_epsg(lon, lat):
    zone = int((lon + 180) / 6) + 1
    return (32700 if lat < 0 else 32600) + zone

def read_band(path):
    ds = xr.open_dataset(path)
    da = ds["Band1"]
    x = ds["x"].values; y = ds["y"].values
    return da.values, x, y

def write_tif(path, arr, x, y, epsg, nodata=None):
    dx = float(x[1] - x[0]); dy = float(y[1] - y[0])
    # coords are cell centres, y ascending -> flip to north-up (row0 = north)
    north = float(y.max()) + abs(dy) / 2.0
    west  = float(x.min()) - abs(dx) / 2.0
    transform = from_origin(west, north, abs(dx), abs(dy))
    data = arr[::-1, :].astype("float32")  # flip y so row 0 is northernmost
    prof = dict(driver="GTiff", height=data.shape[0], width=data.shape[1],
                count=1, dtype="float32", crs=f"EPSG:{epsg}", transform=transform,
                compress="deflate")
    if nodata is not None:
        prof["nodata"] = nodata
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(data, 1)

def main():
    inp = Path(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    lon = float(sys.argv[3]); lat = float(sys.argv[4])
    ksat = float(sys.argv[5]) if len(sys.argv) > 5 else 12.0
    epsg = utm_epsg(lon, lat)
    print(f"case centroid ({lon},{lat}) -> EPSG:{epsg}, KSAT={ksat} mm/hr")

    dem, x, y = read_band(inp / "dem.nc")
    write_tif(out / "dem.tif", dem, x, y, epsg, nodata=-9999.0)

    man, _, _ = read_band(inp / "roughness.nc")
    write_tif(out / "man.tif", man, x, y, epsg)

    perv, _, _ = read_band(inp / "pervious_surface.nc")
    inf = np.clip(perv, 0, 1) * ksat            # pervious fraction -> mm/hr
    write_tif(out / "inf.tif", inf, x, y, epsg)

    frames = sorted(glob.glob(str(inp / "rain" / "imerg_t*.nc")),
                    key=lambda p: int(p.split("_t")[-1].split(".")[0]))
    n = len(frames)
    total_mm = np.zeros_like(dem, dtype="float64")
    for f in frames:
        r, _, _ = read_band(f)
        total_mm += np.nan_to_num(r) * 0.5      # mm/hr over 30 min -> mm
    dur_h = n * 0.5
    mean_int = total_mm / dur_h                  # mm/hr
    write_tif(out / "rain_mmhr.tif", mean_int, x, y, epsg)

    dm = dem[np.isfinite(dem)]
    print(f"grid {dem.shape[1]}x{dem.shape[0]}  DEM {dm.min():.0f}-{dm.max():.0f} m")
    print(f"rain frames={n}  duration={dur_h:.1f} h")
    print(f"event total mm: mean={total_mm.mean():.1f} max={total_mm.max():.1f}")
    print(f"mean intensity mm/hr: mean={mean_int.mean():.2f} max={mean_int.max():.2f}")
    print(f"DUR_H={dur_h:.1f}")   # parseable by the runner

if __name__ == "__main__":
    main()
