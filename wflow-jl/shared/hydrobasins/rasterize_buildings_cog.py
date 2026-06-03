"""Rasterise Overture building footprints to a Cloud-Optimized GeoTIFF (COG).

Why: per-region Overture building GeoJSON is 50 MB – 1.5 GB and OOMs
geopandas (rwa 1.8 M polygons → ~10 GB RAM). A 5 m / 1 m uint8 COG is a
few MB – tens of MB on disk and renders via a single `ax.imshow`.

Pipeline (memory-bounded):
  1. read GeoParquet in 20 k-row batches (`pq.iter_batches`)
  2. reproject each batch to local UTM (zone from bbox centroid)
  3. accumulate into a single uint8 raster via `rasterio.features.rasterize`
     with `out=target` (no per-batch allocation)
  4. write as COG: LZW, blocksize 512, nodata=0 → sparse blocks elide on disk.

Inputs:
  rim2d/regions.geojson                   ← 11 case-study bboxes
  runs/rim2d_buildings_data/{iso}_{id}_buildings.parquet  ← Overture cache

Output:
  runs/rim2d_buildings_cog/{iso}_{id}_buildings_{res}m.tif

  uv run python -m shared.hydrobasins.rasterize_buildings_cog
  uv run python -m shared.hydrobasins.rasterize_buildings_cog --res 1.0
  uv run python -m shared.hydrobasins.rasterize_buildings_cog --iso eri,dji --res 1
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyarrow.parquet as pq
import pyproj
import rasterio
import shapely
from rasterio.features import rasterize
from rasterio.transform import from_origin

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
REGIONS_GEOJSON = REPO / "rim2d" / "regions.geojson"
PARQUET_DIR = HERE.parents[1] / "runs" / "rim2d_buildings_data"
OUT = HERE.parents[1] / "runs" / "rim2d_buildings_cog"


def utm_crs_for(lat: float, lon: float) -> str:
    """Local UTM EPSG code for (lat, lon). Northern: 326xx, Southern: 327xx."""
    zone = int((lon + 180.0) / 6.0) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def utm_grid(bbox_4326: tuple, utm: str, res: float) -> tuple:
    """Project the bbox corners to UTM, snap to whole pixels, return
    (transform, width, height, (xmin, ymin, xmax, ymax)) in UTM."""
    w, s, e, n = bbox_4326
    tr = pyproj.Transformer.from_crs("EPSG:4326", utm, always_xy=True)
    pts = [tr.transform(*p) for p in [(w, s), (e, s), (w, n), (e, n)]]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    xmin, ymin, xmax, ymax = min(xs), min(ys), max(xs), max(ys)
    xmin = math.floor(xmin / res) * res
    ymin = math.floor(ymin / res) * res
    xmax = math.ceil(xmax / res) * res
    ymax = math.ceil(ymax / res) * res
    width  = int(round((xmax - xmin) / res))
    height = int(round((ymax - ymin) / res))
    transform = from_origin(xmin, ymax, res, res)
    return transform, width, height, (xmin, ymin, xmax, ymax)


def rasterize_region(parquet_path: Path, bbox_4326: tuple, out_path: Path,
                     res: float, batch: int = 20_000) -> dict:
    """Stream parquet → batch-rasterise into uint8 → write COG."""
    cx = 0.5 * (bbox_4326[0] + bbox_4326[2])
    cy = 0.5 * (bbox_4326[1] + bbox_4326[3])
    utm = utm_crs_for(cy, cx)
    transform, W, H, utm_bb = utm_grid(bbox_4326, utm, res)
    target = np.zeros((H, W), dtype=np.uint8)
    pf = pq.ParquetFile(parquet_path)
    nrows = pf.metadata.num_rows
    t0 = time.time()
    drawn = 0
    for arrow_batch in pf.iter_batches(batch_size=batch, columns=["geometry"]):
        wkb = arrow_batch["geometry"].to_numpy(zero_copy_only=False)
        geoms = shapely.from_wkb(wkb)
        gs = gpd.GeoSeries(list(geoms), crs="EPSG:4326").to_crs(utm)
        valid = [(g, 1) for g in gs if g is not None and not g.is_empty]
        if valid:
            rasterize(valid, out=target, transform=transform,
                      all_touched=True, default_value=1, dtype=np.uint8)
        drawn += len(arrow_batch)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path, "w", driver="COG",
        height=H, width=W, count=1, dtype="uint8",
        crs=utm, transform=transform,
        compress="LZW", predictor=2, blocksize=512, nodata=0,
        BIGTIFF="IF_SAFER",
    ) as dst:
        dst.write(target, 1)
    size_mb = out_path.stat().st_size / 1e6
    built_px = int((target > 0).sum())
    return {
        "utm": utm, "W": W, "H": H, "res_m": res,
        "nrows": nrows, "drawn": drawn, "built_px": built_px,
        "built_pct": 100.0 * built_px / max(1, W * H),
        "out_mb": size_mb, "elapsed_s": time.time() - t0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", default=None,
                    help="Comma-separated ISO3 subset (default: all 11)")
    ap.add_argument("--res", type=float, default=5.0,
                    help="Output pixel size in metres (default 5.0)")
    args = ap.parse_args()
    regions = gpd.read_file(REGIONS_GEOJSON).to_crs("EPSG:4326")
    if args.iso:
        want = {s.strip().upper() for s in args.iso.split(",")}
        regions = regions[regions["country"].isin(want)]
    print(f"rasterise {len(regions)} regions @ {args.res:g} m → {OUT}\n")
    OUT.mkdir(parents=True, exist_ok=True)
    res_tag = f"{args.res:g}".replace(".", "p")
    print(f"{'iso':>3} {'id':>2}  {'region':<26s}  {'utm':>10}  "
          f"{'W':>6}  {'H':>6}  {'#bld':>11}  {'built%':>7}  "
          f"{'COG_MB':>7}  {'sec':>5}")
    for _, row in regions.iterrows():
        iso = str(row["country"])
        rid = str(row["id"])
        pq_path = PARQUET_DIR / f"{iso.lower()}_{rid}_buildings.parquet"
        if not pq_path.exists():
            print(f"  {iso}: no parquet cache — skip")
            continue
        out_path = OUT / f"{iso.lower()}_{rid}_buildings_{res_tag}m.tif"
        try:
            s = rasterize_region(pq_path, row.geometry.bounds, out_path,
                                 res=args.res)
        except Exception as e:
            print(f"{iso:>3} {rid:>2}  FAILED ({type(e).__name__}: "
                  f"{str(e)[:80]})")
            continue
        print(f"{iso:>3} {rid:>2}  {row['region']:<26s}  {s['utm']:>10}  "
              f"{s['W']:>6}  {s['H']:>6}  {s['drawn']:>11,}  "
              f"{s['built_pct']:>6.2f}%  {s['out_mb']:>7.2f}  "
              f"{s['elapsed_s']:>5.1f}")


if __name__ == "__main__":
    main()
