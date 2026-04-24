#!/usr/bin/env python3
"""
Download ESA WorldCover 2021 + GHSL built-up surface for a region.

ESA WorldCover v200 (2021)
--------------------------
- Native 10 m, served here at --scale (default 30 m) to match RIM2D.
- 11 classes (10=trees, 20=shrub, ..., 80=permanent water, ...).
- Feeds:
    * RIM2D roughness (class → Manning's n via manning_lookup.csv)
    * RIM2D channel mask (class 80 = permanent water → stream burn)
    * Wflow landuse

GHSL built-up surface 2020 (--ghsl, default on)
-----------------------------------------------
- Native 100 m global built-up fraction from JRC.
- Produces sealed/pervious fractions at 100 m (regridded later by the
  RIM2D case builder).

Size guide
----------
    area_km²       WorldCover TIF    GHSL TIFs (sealed+pervious)
    --------       --------------    ---------------------------
    1 000          ~1 MB             ~0.4 MB
    55 000         ~30 MB            ~10 MB
    500 000        ~300 MB (may hit 50 MB cap — split bbox)

Outputs
-------
    <out>/tif/worldcover_classes.tif        (raw classes)
    <out>/tif/roughness.tif                  (classes -> Manning's n, float)
    <out>/tif/sealed_100m.tif                (if --ghsl)
    <out>/tif/pervious_100m.tif              (if --ghsl)

Usage
-----
    python download_worldcover.py --bbox 36.6,-1.402,37.1,-1.098 \
                                   --out ./runs/nbo --scale 30 --crs EPSG:32737
"""

import argparse
import csv
import sys
from pathlib import Path

from common import (add_common_args, parse_region, init_ee, ee_bbox,
                    download_ee_tif, print_size_estimate)


def load_manning_lookup(path: Path):
    """Return (classes, n_values) as parallel integer / float lists."""
    classes, n_vals = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            classes.append(int(row["worldcover_class"]))
            n_vals.append(float(row["manning_n"]))
    return classes, n_vals


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap)
    ap.add_argument("--ghsl", action=argparse.BooleanOptionalAction, default=True,
                    help="Also download GHSL sealed/pervious surface (default on).")
    ap.add_argument("--manning-lookup", type=Path,
                    default=Path(__file__).parent / "manning_lookup.csv",
                    help="CSV of WorldCover class -> Manning's n.")
    args = ap.parse_args()
    r = parse_region(args)

    print_size_estimate(r, "ESA WorldCover", 0.5)
    if args.ghsl:
        print_size_estimate(r, "GHSL sealed/pervious", 0.4)
    if r.dry_run:
        return 0

    ee = init_ee(r.sa_key)
    bbox = ee_bbox(ee, r)

    # Raw classes (needed for channel mask)
    print("\n[wc] classes...")
    wc = ee.Image("ESA/WorldCover/v200/2021").select("Map")
    download_ee_tif(wc, bbox, r.tif_dir / "worldcover_classes.tif",
                    scale=r.scale, crs=r.crs)

    # Class -> Manning's n (stored ×1000 as integer, then divided to float)
    print("\n[wc] roughness...")
    classes, n_vals = load_manning_lookup(args.manning_lookup)
    n_int = [int(round(v * 1000)) for v in n_vals]
    roughness = wc.remap(classes, n_int).divide(1000).toFloat()
    download_ee_tif(roughness, bbox, r.tif_dir / "roughness.tif",
                    scale=r.scale, crs=r.crs)

    if args.ghsl:
        print("\n[ghsl] built-up surface @ 100 m...")
        ghsl = (ee.Image("JRC/GHSL/P2023A/GHS_BUILT_S/2020")
                .select("built_surface").unmask(0))
        sealed = ghsl.divide(10000).clamp(0, 1).toFloat()
        pervious = ee.Image(1).subtract(sealed).toFloat()
        download_ee_tif(sealed,   bbox, r.tif_dir / "sealed_100m.tif",
                        scale=100, crs=r.crs)
        download_ee_tif(pervious, bbox, r.tif_dir / "pervious_100m.tif",
                        scale=100, crs=r.crs)

    print("\n[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
