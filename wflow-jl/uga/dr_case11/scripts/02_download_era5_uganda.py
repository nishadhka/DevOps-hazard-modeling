#!/usr/bin/env python3
"""
Step 2: Download ERA5 Climate Data for Uganda (2021-2022)

ERA5: ECMWF Reanalysis v5 (Temperature and PET)
Source: Copernicus Climate Data Store (CDS)
Period: 2021-01-01 to 2022-12-31
Reference: https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/

IMPORTANT: Requires CDS API setup:
1. Register at: https://cds.climate.copernicus.eu/
2. Install cdsapi: pip install cdsapi
3. Setup ~/.cdsapirc with your API key
"""

import sys
from pathlib import Path
from datetime import datetime
import json
import time
import xarray as xr

print("="*70)
print("DOWNLOAD ERA5 CLIMATE DATA - UGANDA (2021-2022)")
print("="*70)

# Try to import cdsapi
try:
    import cdsapi
    print("✓ cdsapi module found")
    HAS_CDS = True
except ImportError:
    print("✗ cdsapi not installed")
    print("\nTo install: pip install cdsapi")
    print("Then setup ~/.cdsapirc with your CDS API credentials")
    print("Register at: https://cds.climate.copernicus.eu/")
    HAS_CDS = False

# Paths
BASE_DIR = Path(__file__).parent.parent
ERA5_DIR = BASE_DIR / 'data' / 'era5'
ERA5_DIR.mkdir(exist_ok=True, parents=True)

# Uganda bounds (Karamoja subregion focus)
UGANDA_BOUNDS = {
    'north': 3.8,
    'south': 1.0,
    'west': 32.8,
    'east': 34.9
}

print(f"\nOutput directory: {ERA5_DIR}")
print(f"Region: Uganda ({UGANDA_BOUNDS['west']}, {UGANDA_BOUNDS['south']}) to ({UGANDA_BOUNDS['east']}, {UGANDA_BOUNDS['north']})")
print(f"Period: 2021-01-01 to 2022-12-31")
print(f"Reference: https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/")

if not HAS_CDS:
    print("\n" + "="*70)
    print("SETUP REQUIRED")
    print("="*70)
    print("\nSteps to download ERA5 data:")
    print("1. pip install cdsapi")
    print("2. Register at: https://cds.climate.copernicus.eu/")
    print("3. Create ~/.cdsapirc with:")
    print("   url: https://cds.climate.copernicus.eu/api/v2")
    print("   key: YOUR_UID:YOUR_API_KEY")
    print("\nThen run this script again.")
    sys.exit(1)

# Initialize CDS API
try:
    c = cdsapi.Client()
    print("✓ CDS API client initialized")
except Exception as e:
    print(f"✗ CDS API client error: {e}")
    print("\nCheck your ~/.cdsapirc file:")
    print("  url: https://cds.climate.copernicus.eu/api/v2")
    print("  key: YOUR_UID:YOUR_API_KEY")
    sys.exit(1)

def download_era5_variable(variable, years, months, output_file):
    """Download ERA5 variable for specified period."""
    print(f"\nDownloading {variable}...")
    print(f"  Years: {years}")
    print(f"  Output: {output_file}")
    
    start_time = time.time()
    
    try:
        c.retrieve(
            'reanalysis-era5-single-levels',
            {
                'product_type': 'reanalysis',
                'variable': variable,
                'year': years,
                'month': months,
                'day': [f'{d:02d}' for d in range(1, 32)],
                'time': [
                    '00:00', '01:00', '02:00', '03:00', '04:00', '05:00',
                    '06:00', '07:00', '08:00', '09:00', '10:00', '11:00',
                    '12:00', '13:00', '14:00', '15:00', '16:00', '17:00',
                    '18:00', '19:00', '20:00', '21:00', '22:00', '23:00',
                ],
                'area': [
                    UGANDA_BOUNDS['north'], UGANDA_BOUNDS['west'],
                    UGANDA_BOUNDS['south'], UGANDA_BOUNDS['east'],
                ],
                'format': 'netcdf',
            },
            output_file
        )
        
        elapsed = time.time() - start_time
        print(f"  ✓ Downloaded in {elapsed/60:.1f} minutes")
        return True
        
    except Exception as e:
        print(f"  ✗ Download failed: {e}")
        return False

# Download variables year by year (to avoid CDS cost limits)
print("\n" + "="*70)
print("DOWNLOADING ERA5 VARIABLES")
print("="*70)
print("\nNOTE: Downloading year by year to avoid CDS cost limits...")
print("This will take 40-60 minutes total (20-30 minutes per year)...")

years_list = ['2021', '2022']
months = [f'{m:02d}' for m in range(1, 13)]

downloads = []

# Function to download and merge yearly files
def download_and_merge_yearly(variable, output_file, var_name):
    """Download variable year by year and merge."""
    yearly_files = []
    
    for year in years_list:
        year_file = ERA5_DIR / f'{variable}_{year}.nc'
        
        if year_file.exists():
            print(f"  Year {year} already exists, skipping...")
            yearly_files.append(year_file)
            continue
        
        print(f"\n  Downloading {variable} for {year}...")
        success = download_era5_variable(
            variable,
            [year],
            months,
            str(year_file)
        )
        
        if success and year_file.exists():
            yearly_files.append(year_file)
        else:
            print(f"  ✗ Failed to download {year}")
            return False
    
    # Merge yearly files
    if len(yearly_files) == len(years_list):
        print(f"\n  Merging {len(yearly_files)} yearly files...")
        try:
            datasets = [xr.open_dataset(f) for f in yearly_files]
            merged = xr.concat(datasets, dim='time')
            merged.to_netcdf(output_file)
            
            # Clean up yearly files
            for f in yearly_files:
                f.unlink()
            
            print(f"  ✓ Merged to {output_file.name}")
            return True
        except Exception as e:
            print(f"  ✗ Merge failed: {e}")
            return False
    
    return False

# 1. Temperature (2m temperature)
print("\n[1/3] 2-meter Temperature")
temp_file = ERA5_DIR / 'temperature_2m_2021_2022.nc'
success_temp = download_and_merge_yearly('2m_temperature', temp_file, 'temperature')
downloads.append(('temperature', temp_file, success_temp))

# 2. Potential Evapotranspiration
print("\n[2/3] Potential Evapotranspiration")
pet_file = ERA5_DIR / 'potential_evaporation_2021_2022.nc'
success_pet = download_and_merge_yearly('potential_evaporation', pet_file, 'potential_evaporation')
downloads.append(('potential_evaporation', pet_file, success_pet))

# 3. Additional: Surface pressure (useful for calculations)
print("\n[3/3] Surface Pressure")
pressure_file = ERA5_DIR / 'surface_pressure_2021_2022.nc'
success_pressure = download_and_merge_yearly('surface_pressure', pressure_file, 'surface_pressure')
downloads.append(('surface_pressure', pressure_file, success_pressure))

# Summary
print("\n" + "="*70)
print("DOWNLOAD COMPLETE!")
print("="*70)

successful = [d for d in downloads if d[2]]
failed = [d for d in downloads if not d[2]]

print(f"\n✓ Successful: {len(successful)}/{len(downloads)}")
for var, path, _ in successful:
    print(f"  - {var}: {path.name}")

if failed:
    print(f"\n✗ Failed: {len(failed)}/{len(downloads)}")
    for var, path, _ in failed:
        print(f"  - {var}")

# Save download info
download_info = {
    'source': 'ERA5 Reanalysis',
    'region': 'Uganda',
    'bounds': UGANDA_BOUNDS,
    'period': '2021-01-01 to 2022-12-31',
    'variables': [
        '2m_temperature (K)',
        'potential_evaporation (m)',
        'surface_pressure (Pa)'
    ],
    'temporal_resolution': 'hourly',
    'downloads': {
        d[0]: {'file': d[1].name, 'success': d[2]} 
        for d in downloads
    },
    'reference': 'https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/'
}

with open(ERA5_DIR / 'download_info.json', 'w') as f:
    json.dump(download_info, f, indent=2)

print(f"\n✓ Download info saved: {ERA5_DIR / 'download_info.json'}")

print("\n" + "="*70)
print("NEXT STEP: Prepare forcing.nc for Wflow")
print("="*70)
