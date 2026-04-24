#!/usr/bin/env python3
"""
Download Overture Maps road segments for a region.

Roads feed two optional RIM2D steps:
- Visualization overlay (always safe to produce).
- Manning's n override: impervious tertiary/primary roads get n ≈ 0.015,
  which can refine urban flow paths. The reference case `download_roads_v1.py`
  only uses roads for visualization; the override is not enabled by default.

*** Size warning ***
Roads grow roughly linearly with urbanised area:

    bbox type                segments     GeoJSON size
    ---------                --------     ------------
    city (55 km²)            ~50 000      ~30 MB
    country with roads       ~500 000     ~300 MB
    whole country            ~2 M         ~1-2 GB

Source
------
    overturemaps CLI, feature type `segment` (includes roads + railways).

Output
------
    <out>/tif/roads.geojson

Usage
-----
    python download_roads.py --bbox 36.6,-1.402,37.1,-1.098 --out ./runs/nbo
"""

import argparse
import subprocess
import sys

from common import add_common_args, parse_region, bbox_area_km2


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap)
    args = ap.parse_args()
    r = parse_region(args)

    area = bbox_area_km2(r)
    est_mb = area / 1000.0 * 15.0
    print(f"[size] Overture roads: bbox ≈ {area:,.0f} km² → ~{est_mb:,.0f} MB")
    if area > 10000:
        print(f"[size] WARNING — bbox exceeds 10 000 km². Consider splitting "
              f"by sub-domain.")
    if r.dry_run:
        return 0

    out = r.tif_dir / "roads.geojson"
    if out.exists():
        size_mb = out.stat().st_size / 1e6
        print(f"[cache] {out.name} already exists ({size_mb:.1f} MB) — skipping.")
        return 0

    bbox_str = f"{r.west},{r.south},{r.east},{r.north}"
    cmd = [
        "overturemaps", "download",
        "--bbox", bbox_str,
        "-t", "segment",
        "-f", "geojson",
        "-o", str(out),
    ]
    print(f"[overture] {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit("ERROR: `overturemaps` CLI not found. "
                 "Install via `pip install overturemaps`.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: overturemaps failed with exit code {e.returncode}")

    size_mb = out.stat().st_size / 1e6
    print(f"[done] {out} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
