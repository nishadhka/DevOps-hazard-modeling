#!/usr/bin/env python3
"""
Download MERIT Hydro (v1.0.1) bands for a region from GEE.

MERIT Hydro is a hydrologically conditioned global dataset at 90 m, used by:
- Wflow (elv + dir + upa → LDD + river network + stream order)
- RIM2D v1/v6 (elv → HAND gap-fill for IWD; wth → optional channel width)

Bands (see https://developers.google.com/earth-engine/datasets/catalog/MERIT_Hydro_v1_0_1)
    elv   hydrologically conditioned elevation (metres)
    dir   D8 flow direction (1=E 2=SE 4=S 8=SW 16=W 32=NW 64=N 128=NE; 0=pit)
    upa   upstream drainage area (km²)
    wth   river width (metres; only at river cells)

Size guide (all 4 bands at 90 m)
--------------------------------
    area_km²       download
    --------       --------
    1 000          ~7 MB
    55 000 (BDI)   ~220 MB
    500 000 (KEN)  ~2 GB  — will hit 50 MB cap, split bbox

Outputs
-------
    <out>/tif/merit_elv_90m.tif
    <out>/tif/merit_dir_90m.tif
    <out>/tif/merit_upa_90m.tif
    <out>/tif/merit_wth_90m.tif

Usage
-----
    python download_merit_hydro.py --bbox 36.6,-1.402,37.1,-1.098 --out ./runs/nbo
    python download_merit_hydro.py --bbox 28.83,-4.50,30.89,-2.29 --out ./runs/bdi \
                                    --bands elv,dir,upa
"""

import argparse
import sys

from common import (add_common_args, parse_region, init_ee, ee_bbox,
                    download_ee_tif, print_size_estimate)

ALL_BANDS = ("elv", "dir", "upa", "wth")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap)
    ap.add_argument("--bands", default="elv,dir,upa,wth",
                    help=f"Comma-separated subset of {ALL_BANDS} (default: all).")
    args = ap.parse_args()
    r = parse_region(args)

    bands = [b.strip() for b in args.bands.split(",")]
    for b in bands:
        if b not in ALL_BANDS:
            sys.exit(f"Unknown MERIT band {b!r}; pick from {ALL_BANDS}")

    print_size_estimate(r, f"MERIT Hydro ({len(bands)} bands @ 90 m)",
                        mb_per_1000km2=1.8 * len(bands))
    if r.dry_run:
        return 0

    ee = init_ee(r.sa_key)
    bbox = ee_bbox(ee, r)

    merit = ee.Image("MERIT/Hydro/v1_0_1")
    for band in bands:
        print(f"\n[merit] band={band}...")
        out = r.tif_dir / f"merit_{band}_90m.tif"
        download_ee_tif(merit.select(band), bbox, out, scale=90, crs=r.crs)

    print("\n[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
