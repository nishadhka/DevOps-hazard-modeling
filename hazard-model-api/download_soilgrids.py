#!/usr/bin/env python3
"""
Download ISRIC SoilGrids 250 m properties for a region (via the GEE mirror).

SoilGrids feeds Wflow SBM with the texture + soil depth parameters. We pull
the surface layer (0-5 cm) means by default; override via --depth.

Variables (GEE asset `projects/soilgrids-isric/*_mean`)
-------------------------------------------------------
    sand      %
    silt      %
    clay      %
    bdod      bulk density (cg/cm³)
    ocd       organic carbon density (hg/m³)
    cec       cation exchange capacity (mmol(c)/kg)
    phh2o     pH in H2O
    BDTICM    absolute depth to bedrock (cm)        (fetched if --depth)

Derived after download (handled by prepare_wflow_staticmaps.py)
    ksat      saturated hydraulic conductivity (via pedotransfer)
    porosity  from texture + bdod

Size guide
----------
    area_km²    8 props @ 250 m
    --------    ---------------
    55 000      ~450 MB
    500 000     ~4 GB       — will hit GEE 50 MB cap, split bbox

Output
------
    <out>/tif/soil_{prop}_250m.tif

Usage
-----
    python download_soilgrids.py --bbox 28.83,-4.50,30.89,-2.29 --out ./runs/bdi \
                                  --props sand,silt,clay,bdod
"""

import argparse
import sys

from common import (add_common_args, parse_region, init_ee, ee_bbox,
                    download_ee_tif, print_size_estimate)

DEFAULT_PROPS = ("sand", "silt", "clay", "bdod")
ALL_PROPS     = ("sand", "silt", "clay", "bdod", "ocd", "cec", "phh2o")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap)
    ap.add_argument("--props", default=",".join(DEFAULT_PROPS),
                    help=f"Comma-separated subset of {ALL_PROPS} "
                         f"(default: {','.join(DEFAULT_PROPS)}).")
    ap.add_argument("--depth", action="store_true",
                    help="Also fetch BDTICM (depth to bedrock).")
    args = ap.parse_args()
    r = parse_region(args)

    props = [p.strip() for p in args.props.split(",")]
    for p in props:
        if p not in ALL_PROPS:
            sys.exit(f"Unknown SoilGrids property {p!r}; pick from {ALL_PROPS}")

    mb_per_1000 = 5.0 * (len(props) + (1 if args.depth else 0))
    print_size_estimate(r, f"SoilGrids 250 m ({len(props)} props)", mb_per_1000)
    if r.dry_run:
        return 0

    ee = init_ee(r.sa_key)
    bbox = ee_bbox(ee, r)

    for prop in props:
        asset_id = f"projects/soilgrids-isric/{prop}_mean"
        image = ee.Image(asset_id).select("sol_" + prop + "_0-5cm_mean") \
                  if False else ee.Image(asset_id).select(0)
        # NOTE: GEE SoilGrids-ISRIC mirror band naming varies; fall back to band 0
        out = r.tif_dir / f"soil_{prop}_250m.tif"
        try:
            download_ee_tif(image, bbox, out, scale=250, crs=r.crs)
        except Exception as e:
            print(f"[warn] {prop}: {e}")

    if args.depth:
        print("\n[soilgrids] BDTICM (depth to bedrock)...")
        bd = ee.Image("projects/soilgrids-isric/BDTICM_M").select(0)
        download_ee_tif(bd, bbox, r.tif_dir / "soil_bedrock_depth_250m.tif",
                        scale=250, crs=r.crs)

    print("[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
