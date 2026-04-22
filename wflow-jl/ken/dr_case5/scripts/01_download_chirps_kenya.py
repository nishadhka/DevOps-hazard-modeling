#!/usr/bin/env python3
"""
Step 1: Download CHIRPS Precipitation Data for Kenya (2020-2023)

CHIRPS: Climate Hazards Group InfraRed Precipitation with Station data
Source: https://data.chc.ucsb.edu/products/CHIRPS-2.0/
Period: 2020-01-01 to 2023-12-31 (1461 days)
Reference: https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import urllib.request
import gzip
import shutil
import time
import json

print("="*70)
print("DOWNLOAD CHIRPS PRECIPITATION DATA - KENYA (2020-2023)")
print("="*70)

# Paths
BASE_DIR = Path(__file__).parent.parent
CHIRPS_DIR = BASE_DIR / 'data' / 'chirps'
CHIRPS_DAILY = CHIRPS_DIR / 'daily'
CHIRPS_DAILY.mkdir(exist_ok=True, parents=True)

# Kenya bounds (national)
KENYA_BOUNDS = {
    'west': 34.0,
    'east': 41.9,
    'south': -4.7,
    'north': 5.0
}

print(f"\nOutput directory: {CHIRPS_DIR}")
print(f"Region: Kenya ({KENYA_BOUNDS['west']}, {KENYA_BOUNDS['south']}) to ({KENYA_BOUNDS['east']}, {KENYA_BOUNDS['north']})")
print(f"Period: 2020-01-01 to 2023-12-31 (1461 days)")
print(f"Reference: https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/")

# CHIRPS base URL
BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_daily/tifs/p05/"

def download_chirps_day(year, month, day, output_dir):
    """Download one day of CHIRPS data."""
    date_str = f"{year}.{month:02d}.{day:02d}"
    filename = f"chirps-v2.0.{date_str}.tif.gz"
    url = f"{BASE_URL}{year}/{filename}"
    
    gz_path = output_dir / filename
    tif_path = output_dir / f"chirps-v2.0.{date_str}.tif"
    
    # Skip if already downloaded
    if tif_path.exists():
        return tif_path
    
    try:
        # Download .gz file
        print(f"  Downloading {filename}...", end='', flush=True)
        urllib.request.urlretrieve(url, gz_path)
        
        # Extract .gz
        with gzip.open(gz_path, 'rb') as f_in:
            with open(tif_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Remove .gz file
        gz_path.unlink()
        
        print(" ✓")
        return tif_path
        
    except Exception as e:
        print(f" ✗ Error: {e}")
        if gz_path.exists():
            gz_path.unlink()
        return None

# Download data
start_date = datetime(2020, 1, 1)
end_date = datetime(2023, 12, 31)
current_date = start_date

downloaded = []
failed = []

print(f"\nDownloading {(end_date - start_date).days + 1} days of data...")
print("This will take approximately 60-90 minutes...")

start_time = time.time()

while current_date <= end_date:
    tif_path = download_chirps_day(
        current_date.year,
        current_date.month,
        current_date.day,
        CHIRPS_DAILY
    )
    
    if tif_path:
        downloaded.append((current_date, tif_path))
    else:
        failed.append(current_date)
    
    current_date += timedelta(days=1)
    
    # Progress update every 50 days
    if len(downloaded) % 50 == 0:
        elapsed = time.time() - start_time
        print(f"\n  Progress: {len(downloaded)}/1461 files ({elapsed/60:.1f} minutes elapsed)")

elapsed = time.time() - start_time

print("\n" + "="*70)
print("DOWNLOAD COMPLETE!")
print("="*70)
print(f"✓ Downloaded: {len(downloaded)} files")
print(f"✗ Failed: {len(failed)} files")
print(f"Time: {elapsed/60:.1f} minutes")

# Save download info
download_info = {
    'source': 'CHIRPS v2.0',
    'region': 'Kenya',
    'bounds': KENYA_BOUNDS,
    'period': f"{start_date.date()} to {end_date.date()}",
    'total_days': (end_date - start_date).days + 1,
    'downloaded': len(downloaded),
    'failed': len(failed),
    'download_time_minutes': round(elapsed / 60, 2),
    'output_directory': str(CHIRPS_DAILY),
    'reference': 'https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/'
}

with open(CHIRPS_DIR / 'download_info.json', 'w') as f:
    json.dump(download_info, f, indent=2, default=str)

print(f"\n✓ Download info saved: {CHIRPS_DIR / 'download_info.json'}")

if failed:
    print(f"\n✗ Failed dates:")
    for date in failed[:10]:  # Show first 10
        print(f"  - {date.date()}")
    if len(failed) > 10:
        print(f"  ... and {len(failed) - 10} more")

print("\n" + "="*70)
print("NEXT STEP: Download ERA5 data using 02_download_era5_kenya.py")
print("="*70)
