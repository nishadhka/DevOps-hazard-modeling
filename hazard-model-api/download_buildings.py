#!/usr/bin/env python3
"""
Download Overture Maps building footprints for a region.

This is the single largest input for an urban RIM2D case. Overture releases
global building footprints as cloud-native Parquet on S3; the `overturemaps`
CLI streams it with a server-side bbox filter so only the polygons inside
your region are materialised — but the result is still a fat GeoJSON.

*** Size warning ***
Building density drives the size far more than area:

    bbox type                   buildings        GeoJSON size
    ---------                   ---------        ------------
    urban core (55 km², NBO)    ~200 000         ~100 MB
    peri-urban (500 km²)        ~600 000         ~350 MB
    country, cities only        ~2-10 M          ~1-5 GB
    whole country (rural+urban) ~10-50 M         ~5-30 GB

Rule: for RIM2D, crop the bbox to the hydraulic domain (a city or basin),
NEVER a whole country. For Wflow at 1 km, you probably only need a binary
urban mask — consider using `download_worldcover.py` class 50 (built-up)
instead of this script.

Source
------
    overturemaps CLI (Python, pip install overturemaps)
    Release pinned by the CLI; latest as of writing is 2025-01-22.

Output
------
    <out>/tif/buildings.geojson

Next step
---------
    rasterize_buildings.py converts the GeoJSON → 30 m fractional-cover
    NetCDF that RIM2D ingests as `buildings.nc`.

Usage
-----
    python download_buildings.py --bbox 36.6,-1.402,37.1,-1.098 --out ./runs/nbo
    python download_buildings.py --bbox 28.83,-4.50,30.89,-2.29 --out ./runs/bdi \
                                  --dry-run
"""

import argparse
import subprocess
import sys

from common import add_common_args, parse_region, bbox_area_km2


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap)
    ap.add_argument("--type", default="building",
                    choices=["building", "building_part"],
                    help="Overture feature type (default: building).")
    args = ap.parse_args()
    r = parse_region(args)

    # Size heuristic: urban 100 MB/1000 km², rural ~5 MB/1000 km². Use a
    # middle-of-the-road 30 MB/1000 km² for warning.
    area = bbox_area_km2(r)
    est_mb = area / 1000.0 * 30.0
    print(f"[size] Overture buildings: bbox ≈ {area:,.0f} km² → "
          f"~{est_mb:,.0f} MB (ranges 5-100× depending on urban density)")
    if area > 5000:
        print(f"[size] WARNING — bbox exceeds 5 000 km². Confirm you really "
              f"need buildings over the full domain.")
    if r.dry_run:
        return 0

    out = r.tif_dir / ("buildings.geojson" if args.type == "building"
                       else f"overture_{args.type}.geojson")
    if out.exists():
        size_mb = out.stat().st_size / 1e6
        print(f"[cache] {out.name} already exists ({size_mb:.1f} MB) — skipping.")
        return 0

    bbox_str = f"{r.west},{r.south},{r.east},{r.north}"
    cmd = [
        "overturemaps", "download",
        "--bbox", bbox_str,
        "-t", args.type,
        "-f", "geojson",
        "-o", str(out),
    ]
    print(f"[overture] {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit("ERROR: `overturemaps` CLI not found. Install via "
                 "`pip install overturemaps`.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: overturemaps failed with exit code {e.returncode}")

    size_mb = out.stat().st_size / 1e6
    print(f"[done] {out} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
