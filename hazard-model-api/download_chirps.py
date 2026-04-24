#!/usr/bin/env python3
"""
Download CHIRPS v2 daily precipitation TIFs for a region and period.

CHIRPS (Climate Hazards Group InfraRed Precipitation with Station data) is
5.5 km daily rainfall, 1981-present, Africa + global. Feeds Wflow directly.

The CHIRPS FTP/HTTPS archive stores one .tif.gz per day per continent; we
download Africa tiles and **clip server-side is not available** — the file
arrives global for Africa-wide (~4 MB each), then the Wflow staticmaps
pipeline clips when stacking.

*** Size warning ***
Total = days × 4 MB (Africa-wide tile). For all East Africa drought cases
(2020-2023, 1461 days) this is ~6 GB of raw gz. For a 2-year run:

    730 days × 4 MB gz → ~3 GB on disk compressed, ~12 GB decompressed

Output
------
    <out>/chirps/daily/chirps-v2.0.YYYY.MM.DD.tif     (one per day)

Source
------
    https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_daily/tifs/p05/

Usage
-----
    python download_chirps.py --bbox 28.83,-4.50,30.89,-2.29 \
           --out ./runs/bdi --start 2021-01-01 --end 2023-01-01
"""

import argparse
import gzip
import shutil
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from common import add_common_args, parse_region

BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_daily/tifs/p05/"


def daterange(start: str, end: str):
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    d = d0
    while d < d1:
        yield d
        d += timedelta(days=1)


def download_day(d: date, out_dir: Path, retries: int = 3) -> Path | None:
    fn_gz  = f"chirps-v2.0.{d.year}.{d.month:02d}.{d.day:02d}.tif.gz"
    fn_tif = f"chirps-v2.0.{d.year}.{d.month:02d}.{d.day:02d}.tif"
    gz_path  = out_dir / fn_gz
    tif_path = out_dir / fn_tif
    if tif_path.exists():
        return tif_path
    url = f"{BASE_URL}{d.year}/{fn_gz}"
    for attempt in range(1, retries + 1):
        try:
            urllib.request.urlretrieve(url, gz_path)
            with gzip.open(gz_path, "rb") as gz, open(tif_path, "wb") as out:
                shutil.copyfileobj(gz, out)
            gz_path.unlink(missing_ok=True)
            return tif_path
        except Exception as e:
            print(f"  [retry {attempt}/{retries}] {d} failed: {e}")
            time.sleep(2 * attempt)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_common_args(ap, temporal=True)
    args = ap.parse_args()
    r = parse_region(args)

    days = (date.fromisoformat(r.end) - date.fromisoformat(r.start)).days
    print(f"[size] CHIRPS daily: {days} days × ~4 MB gz (continental tile) "
          f"→ ~{days * 4 / 1024:.1f} GB compressed")
    if days > 1000:
        print(f"[size] WARNING — > 1000 days. Consider splitting the run "
              f"into multiple years.")
    if r.dry_run:
        return 0

    out_dir = r.out / "chirps" / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_ok, n_fail = 0, 0
    for i, d in enumerate(daterange(r.start, r.end), start=1):
        tif = download_day(d, out_dir)
        if tif is None:
            print(f"[chirps] FAIL {d}")
            n_fail += 1
        else:
            n_ok += 1
        if i % 100 == 0:
            print(f"[chirps] {i}/{days} — ok={n_ok} fail={n_fail}")

    print(f"[done] ok={n_ok}, fail={n_fail}, out={out_dir}")
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
