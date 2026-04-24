#!/usr/bin/env python3
"""
Download ERA5-Land hourly air temperature and potential evaporation for a
region, aggregate to daily, and export GeoTIFFs that Wflow can ingest.

Variables
---------
    temperature_2m               (K → °C daily mean)
    potential_evaporation        (m, hourly accum → mm, daily sum)

Native grid is 0.1° (~11 km). Aggregation happens server-side in GEE via
`reduce` over each UTC day so only the daily product is downloaded.

Size guide (0.1° @ daily)
-------------------------
    area_km²    per day    2 years
    --------    -------    -------
    55 000      ~20 KB     ~15 MB
    500 000     ~180 KB    ~130 MB

Output
------
    <out>/era5/t2m_YYYYMMDD.tif   (daily mean °C)
    <out>/era5/pet_YYYYMMDD.tif   (daily sum mm)

Usage
-----
    python download_era5.py --bbox 28.83,-4.50,30.89,-2.29 \
           --out ./runs/bdi --start 2021-01-01 --end 2023-01-01
"""

import argparse
import sys
from datetime import date, timedelta

from common import (add_common_args, parse_region, init_ee, ee_bbox,
                    download_ee_tif, bbox_area_km2)


def daterange(start: str, end: str):
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    d = d0
    while d < d1:
        yield d
        d += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap, temporal=True)
    args = ap.parse_args()
    r = parse_region(args)

    days = (date.fromisoformat(r.end) - date.fromisoformat(r.start)).days
    area = bbox_area_km2(r)
    est_mb = (area / 1000.0) * 0.001 * 2 * days   # 2 vars
    print(f"[size] ERA5-Land daily: {days} days × 2 vars × bbox ≈ "
          f"{area:,.0f} km² → ~{est_mb:.1f} MB")
    if r.dry_run:
        return 0

    out_dir = r.out / "era5"
    out_dir.mkdir(parents=True, exist_ok=True)

    ee = init_ee(r.sa_key)
    bbox = ee_bbox(ee, r)

    col = ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY").filterBounds(bbox)

    for i, d in enumerate(daterange(r.start, r.end), start=1):
        date_str = d.strftime("%Y%m%d")
        day_start = d.isoformat()
        day_end   = (d + timedelta(days=1)).isoformat()
        day_col = col.filterDate(day_start, day_end)

        # Daily mean temperature in Celsius
        t2m = (day_col.select("temperature_2m").mean()
                    .subtract(273.15).rename("t2m"))
        download_ee_tif(t2m, bbox, out_dir / f"t2m_{date_str}.tif",
                        scale=11000, crs=r.crs)

        # Daily sum of potential evaporation (hourly values are m, sign
        # convention negative for evaporation → flip to positive mm)
        pet = (day_col.select("potential_evaporation").sum()
                    .multiply(-1000).rename("pet"))
        download_ee_tif(pet, bbox, out_dir / f"pet_{date_str}.tif",
                        scale=11000, crs=r.crs)

        if i % 30 == 0 or i == days:
            print(f"[era5] {i}/{days} days done")

    print(f"[done] {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
