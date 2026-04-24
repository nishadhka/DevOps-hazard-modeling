#!/usr/bin/env python3
"""
Download DEM for a region from Google Earth Engine.

Sources
-------
- Copernicus GLO-30 DEM (default): 30 m native, global, 1-2 m vertical
  accuracy. Best for RIM2D base terrain.
- MERIT Hydro elv (--target merit): 90 m native, hydrologically conditioned
  (sinks filled, river networks enforced). Use for Wflow or if you need
  pre-burned drainage.

Both are fetched via GEE `getDownloadURL`, which has a **50 MB per image
cap** — for very large bboxes (> ~20 000 km²) the download will fail; split
the bbox or use GEE Tasks export instead.

Size guide (Copernicus 30 m)
----------------------------
    area_km²       download
    --------       --------
    1 000 (city)   ~2 MB
    10 000         ~20 MB
    55 000 (BDI)   ~110 MB      # still fine via getDownloadURL
    500 000 (KEN)  ~1 GB        # will fail, split into tiles

Size guide (MERIT 90 m)
-----------------------
    3× smaller than GLO-30 at the same bbox.

Outputs
-------
    <out>/tif/dem.tif              (Copernicus GLO-30)
    <out>/tif/merit_elv_90m.tif    (MERIT Hydro, if --target merit)

Usage
-----
    python download_dem.py --bbox 36.60,-1.402,37.10,-1.098 --out ./runs/nbo \
                           --scale 30 --crs EPSG:32737
    python download_dem.py --bbox 28.83,-4.50,30.89,-2.29  --out ./runs/bdi \
                           --scale 90 --target merit
"""

import argparse
import sys

from common import (add_common_args, parse_region, init_ee, ee_bbox,
                    download_ee_tif, print_size_estimate)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap)
    ap.add_argument("--target", choices=["copernicus", "merit"],
                    default="copernicus",
                    help="Which DEM to download (default: copernicus).")
    args = ap.parse_args()
    r = parse_region(args)

    mb_per_1000km2 = 2.0 if args.target == "copernicus" else 0.8
    print_size_estimate(r, f"DEM ({args.target})", mb_per_1000km2)
    if r.dry_run:
        return 0

    ee = init_ee(r.sa_key)
    bbox = ee_bbox(ee, r)

    if args.target == "copernicus":
        image = (ee.ImageCollection("COPERNICUS/DEM/GLO30")
                   .filterBounds(bbox).select("DEM").mosaic())
        out = r.tif_dir / "dem.tif"
        download_ee_tif(image, bbox, out, scale=r.scale, crs=r.crs)
    else:
        image = ee.Image("MERIT/Hydro/v1_0_1").select("elv")
        out = r.tif_dir / "merit_elv_90m.tif"
        download_ee_tif(image, bbox, out, scale=90, crs=r.crs)

    print(f"[done] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
