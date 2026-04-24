#!/usr/bin/env python3
"""
Convert an Overture Maps building GeoJSON into a RIM2D-ready NetCDF raster.

This is the "heavy lift" conversion referenced in the reference case
`rim2d/ken/nbo_2026/setup_v1.py`: Overture publishes buildings as polygons,
but RIM2D consumes them as a cell-value raster aligned to the DEM grid.

Two output modes
----------------
    --mode fraction  (default)  : cell value = area fraction covered by any
                                   building (0.0-1.0). This is what RIM2D
                                   uses as `buildings.nc` — blocks flow and
                                   boosts sealed surface fraction.
    --mode binary               : 1 where any building touches the cell,
                                   else 0. Lighter, but loses density info.

The rasterization is streaming (reads GeoJSON with shapely line-by-line via
geopandas and rasterizes in chunks) so memory stays bounded even for a
100 MB GeoJSON with millions of features.

Inputs
------
    <out>/tif/buildings.geojson     (from download_buildings.py)
    <out>/tif/dem.tif               (from download_dem.py) — reference grid

Output
------
    <out>/input/buildings.nc

Usage
-----
    python rasterize_buildings.py --out ./runs/nbo
    python rasterize_buildings.py --out ./runs/nbo --mode binary
"""

import argparse
import sys
from pathlib import Path

import numpy as np

from common import tif_to_rim2d_arrays, write_rim2d_nc


def rasterize(geojson_path: Path, ref_tif: Path, mode: str = "fraction"):
    import geopandas as gpd
    import rasterio
    from rasterio.features import rasterize as _rasterize

    print(f"[rasterize] reading {geojson_path.name}...")
    gdf = gpd.read_file(geojson_path)
    print(f"[rasterize] {len(gdf)} features loaded")

    with rasterio.open(ref_tif) as src:
        dst_transform = src.transform
        dst_crs       = src.crs
        dst_width     = src.width
        dst_height    = src.height

    # Reproject geometries into the reference CRS (usually UTM, not WGS84)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    if gdf.crs != dst_crs:
        print(f"[rasterize] reprojecting {gdf.crs} → {dst_crs}")
        gdf = gdf.to_crs(dst_crs)

    if mode == "binary":
        # Single pass — 1 where polygon touches, 0 otherwise
        shapes = ((geom, 1) for geom in gdf.geometry if geom is not None)
        raster = _rasterize(
            shapes, out_shape=(dst_height, dst_width),
            transform=dst_transform, fill=0, dtype=np.uint8,
        )
        out = raster.astype(np.float32)
    else:
        # Fractional coverage via all-touched=False + subpixel sampling by
        # rasterising at 5× and downsampling with mean.
        # Memory-efficient: chunk the features in groups of 50 000.
        subx = 5
        sub_h = dst_height * subx
        sub_w = dst_width  * subx
        sub_transform = rasterio.Affine(
            dst_transform.a / subx, dst_transform.b, dst_transform.c,
            dst_transform.d, dst_transform.e / subx, dst_transform.f,
        )
        coverage = np.zeros((sub_h, sub_w), dtype=np.uint8)
        geoms = list(gdf.geometry)
        CHUNK = 50_000
        for i in range(0, len(geoms), CHUNK):
            shapes = ((g, 1) for g in geoms[i:i+CHUNK] if g is not None)
            chunk = _rasterize(
                shapes, out_shape=(sub_h, sub_w),
                transform=sub_transform, fill=0, dtype=np.uint8,
                all_touched=False,
            )
            np.maximum(coverage, chunk, out=coverage)
            print(f"[rasterize] chunk {i//CHUNK + 1}/"
                  f"{-(-len(geoms)//CHUNK)}")
        # Downsample 5× → mean = area fraction per cell
        out = coverage.reshape(dst_height, subx, dst_width, subx).mean(axis=(1,3))
        out = out.astype(np.float32)

    # Flip to RIM2D y-ascending (south at y[0])
    out = out[::-1, :].copy()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path,
                    help="Output directory (same --out used for downloads).")
    ap.add_argument("--mode", choices=["fraction", "binary"], default="fraction",
                    help="Output raster mode (default: fraction).")
    ap.add_argument("--input-geojson", type=Path,
                    help="Override buildings GeoJSON path.")
    ap.add_argument("--ref-tif", type=Path,
                    help="Override reference DEM TIF path.")
    args = ap.parse_args()

    geojson = args.input_geojson or (args.out / "tif" / "buildings.geojson")
    ref_tif = args.ref_tif       or (args.out / "tif" / "dem.tif")
    if not geojson.exists():
        sys.exit(f"ERROR: {geojson} not found. Run download_buildings.py first.")
    if not ref_tif.exists():
        sys.exit(f"ERROR: {ref_tif} not found. Run download_dem.py first.")

    raster = rasterize(geojson, ref_tif, mode=args.mode)

    _, x, y = tif_to_rim2d_arrays(ref_tif)
    out_path = args.out / "input" / "buildings.nc"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_rim2d_nc(raster, x, y, out_path,
                   long_name=f"building {args.mode}", units="1")
    n_bldg = int(np.sum(raster > 0))
    size_mb = out_path.stat().st_size / 1e6
    print(f"[done] {out_path} — {n_bldg} cells with buildings "
          f"({100 * n_bldg / raster.size:.1f}%), {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
