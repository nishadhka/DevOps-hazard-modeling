#!/usr/bin/env python3
"""
Shared helpers imported by every download_*.py and prepare_*.py script.

Contents:
- `add_common_args` / `parse_region` : uniform CLI across all scripts
- `init_ee`                          : Earth Engine service account auth
- `download_ee_tif`                  : GEE image -> GeoTIFF via getDownloadURL
- `tif_to_rim2d_arrays`              : load GeoTIFF in RIM2D y-ascending layout
- `write_rim2d_nc`                   : NetCDF3_CLASSIC with 'Band1' var (RIM2D convention)
- `regrid_rasterio`                  : fast reprojection to a reference grid
- `bbox_area_km2`                    : rough km² for size warnings

The code is lifted from `../rim2d/ken/nbo_2026/setup_v1.py` and
`../rim2d/ken/nbo_2026/download_imerg_v1.py`, then generalised over --bbox.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@dataclass
class Region:
    """Region descriptor parsed from --bbox / --out / --scale / --crs."""
    bbox: tuple[float, float, float, float]       # west, south, east, north (lon/lat)
    out:  Path
    scale: int = 30                                # target pixel size in metres
    crs:   str = "EPSG:4326"
    start: str | None = None                       # ISO date, if temporal
    end:   str | None = None
    sa_key: str | None = None
    dry_run: bool = False

    @property
    def west(self):  return self.bbox[0]
    @property
    def south(self): return self.bbox[1]
    @property
    def east(self):  return self.bbox[2]
    @property
    def north(self): return self.bbox[3]

    @property
    def tif_dir(self) -> Path:
        d = self.out / "tif"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def input_dir(self) -> Path:
        d = self.out / "input"
        d.mkdir(parents=True, exist_ok=True)
        return d


def add_common_args(ap: argparse.ArgumentParser, temporal: bool = False) -> None:
    """Add the shared flags. `temporal=True` also adds --start / --end."""
    ap.add_argument("--bbox", required=True,
                    help="WEST,SOUTH,EAST,NORTH in lon/lat WGS84 (comma-separated).")
    ap.add_argument("--out", required=True, type=Path,
                    help="Output directory (created if missing).")
    ap.add_argument("--scale", type=int, default=30,
                    help="Target pixel size in metres (default 30).")
    ap.add_argument("--crs", default="EPSG:4326",
                    help="Target CRS (default EPSG:4326).")
    ap.add_argument("--sa-key", default=os.environ.get("GEE_SA_KEY"),
                    help="GEE service account key JSON path (or env GEE_SA_KEY).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print size estimate and exit without downloading.")
    if temporal:
        ap.add_argument("--start", required=True, help="YYYY-MM-DD inclusive.")
        ap.add_argument("--end",   required=True, help="YYYY-MM-DD exclusive.")


def parse_region(args: argparse.Namespace) -> Region:
    parts = [float(x) for x in args.bbox.split(",")]
    if len(parts) != 4:
        sys.exit(f"--bbox must be W,S,E,N (got {args.bbox!r})")
    w, s, e, n = parts
    if not (w < e and s < n):
        sys.exit(f"--bbox must satisfy west<east, south<north (got {parts})")
    args.out.mkdir(parents=True, exist_ok=True)
    return Region(
        bbox=(w, s, e, n),
        out=args.out,
        scale=args.scale,
        crs=args.crs,
        start=getattr(args, "start", None),
        end=getattr(args, "end", None),
        sa_key=args.sa_key,
        dry_run=args.dry_run,
    )


# ---------------------------------------------------------------------------
# Size estimation
# ---------------------------------------------------------------------------

def bbox_area_km2(r: Region) -> float:
    """Rough bbox area in km² using local degree-to-km scaling at mid-latitude."""
    lat_mid = 0.5 * (r.south + r.north)
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * math.cos(math.radians(lat_mid))
    return (r.east - r.west) * km_per_deg_lon * (r.north - r.south) * km_per_deg_lat


def print_size_estimate(r: Region, source: str, mb_per_1000km2: float) -> None:
    area = bbox_area_km2(r)
    est_mb = area / 1000.0 * mb_per_1000km2
    print(f"[size] {source}: bbox ≈ {area:,.0f} km² → ~{est_mb:,.1f} MB")
    if est_mb > 500:
        print(f"[size] WARNING — estimate > 500 MB. Consider a smaller bbox "
              f"or narrower bands.")


# ---------------------------------------------------------------------------
# Earth Engine
# ---------------------------------------------------------------------------

def init_ee(sa_key: str | None = None):
    """Initialise EE with a service account. Returns the `ee` module."""
    import ee
    if sa_key is None:
        sa_key = os.environ.get("GEE_SA_KEY")
    if sa_key and Path(sa_key).exists():
        with open(sa_key) as f:
            key = json.load(f)
        creds = ee.ServiceAccountCredentials(key["client_email"], sa_key)
        ee.Initialize(credentials=creds)
        print(f"[gee] initialised as {key['client_email']}")
    else:
        # fall back to user auth (e.g. `earthengine authenticate` already run)
        ee.Initialize()
        print("[gee] initialised with default credentials")
    return ee


def ee_bbox(ee, r: Region):
    return ee.Geometry.Rectangle([r.west, r.south, r.east, r.north])


def download_ee_tif(image, bbox_ee, path: Path, scale: int, crs: str) -> None:
    """Download a single EE image to GeoTIFF via getDownloadURL."""
    if path.exists():
        print(f"[gee] cached: {path.name}")
        return
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
    size_mb = path.stat().st_size / 1e6
    print(f"[gee] downloaded: {path.name} ({size_mb:.1f} MB)")


# ---------------------------------------------------------------------------
# Raster IO — RIM2D conventions
# ---------------------------------------------------------------------------

def tif_to_rim2d_arrays(tif_path: Path):
    """Load GeoTIFF as (data, x, y) in RIM2D y-ascending layout (south at y[0])."""
    import rasterio
    with rasterio.open(tif_path) as src:
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


def write_rim2d_nc(data, x, y, nc_path: Path, fill_value: float = -9999.0,
                   long_name: str = "", units: str = "") -> None:
    """Write CF-1.5 NETCDF3_CLASSIC with a single `Band1` variable — RIM2D format."""
    import netCDF4
    arr = np.where(np.isnan(data), fill_value, data).astype(np.float32)
    nrows, ncols = arr.shape
    ds = netCDF4.Dataset(str(nc_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.history = f"Generated by hazard-model-api/{Path(__file__).name}"
    ds.createDimension("x", ncols)
    ds.createDimension("y", nrows)
    xv = ds.createVariable("x", "f8", ("x",))
    xv[:] = x;  xv.long_name = "x coordinate";  xv.units = "m"
    yv = ds.createVariable("y", "f8", ("y",))
    yv[:] = y;  yv.long_name = "y coordinate";  yv.units = "m"
    bv = ds.createVariable("Band1", "f4", ("y", "x"),
                           fill_value=np.float32(fill_value))
    bv[:] = arr
    if long_name:
        bv.long_name = long_name
    if units:
        bv.units = units
    ds.close()


def regrid_rasterio(src_tif: Path, ref_tif: Path, method: str = "bilinear"):
    """
    Fast reprojection of src_tif onto the grid defined by ref_tif.
    Returns a 2-D numpy array in RIM2D y-ascending convention.
    """
    import rasterio
    from rasterio.warp import reproject, Resampling
    resampling = {
        "bilinear": Resampling.bilinear,
        "nearest":  Resampling.nearest,
        "average":  Resampling.average,
    }[method]
    with rasterio.open(ref_tif) as ref:
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
            resampling=resampling,
        )
    dst_data = dst_data[::-1, :].copy()
    dst_data[~np.isfinite(dst_data)] = np.nan
    return dst_data
