#!/usr/bin/env python3
"""
Step 3: Prepare Wflow Forcing File (forcing.nc) for Djibouti

Combines CHIRPS precipitation and ERA5 climate data into
a single NetCDF file formatted for Wflow input.

Required variables:
- precip: Precipitation (mm/day)
- temp: Temperature (°C)
- pet: Potential evapotranspiration (mm/day)
Period: 2021-2023

Adapted for VM structure: dr_case2/02_Djibouti_2021_2023/
"""

import sys
from pathlib import Path
from datetime import datetime
import json
import time
import numpy as np
import xarray as xr
import rioxarray as rxr
from glob import glob

print("="*70)
print("PREPARE WFLOW FORCING FILE - DJIBOUTI (2021-2023)")
print("="*70)

# Paths - adapted for VM structure
# Script location: dr_case2/02_Djibouti_2021_2023/scripts/
SCRIPT_DIR = Path(__file__).parent.absolute()
DATA_DIR = SCRIPT_DIR.parent / 'data'  # dr_case2/02_Djibouti_2021_2023/data/
CHIRPS_DIR = DATA_DIR / 'chirps' / 'daily'
ERA5_DIR = DATA_DIR / 'era5'

# Output to dr_case2/data/input/forcing.nc
CASE_DIR = SCRIPT_DIR.parent.parent  # dr_case2/
OUTPUT_DIR = CASE_DIR / 'data' / 'input'
OUTPUT_FILE = OUTPUT_DIR / 'forcing.nc'
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

print(f"\nInput directories:")
print(f"  CHIRPS: {CHIRPS_DIR}")
print(f"  ERA5: {ERA5_DIR}")
print(f"\nOutput file: {OUTPUT_FILE}")

# Check input files exist
print("\n" + "="*70)
print("CHECKING INPUT FILES")
print("="*70)

chirps_files = sorted(glob(str(CHIRPS_DIR / 'chirps-v2.0.*.tif')))
era5_temp = ERA5_DIR / 'temperature_2m_2021_2023.nc'
era5_pet = ERA5_DIR / 'potential_evaporation_2021_2023.nc'

print(f"\nCHIRPS files: {len(chirps_files)}")
if len(chirps_files) > 0:
    print(f"  First: {Path(chirps_files[0]).name}")
    print(f"  Last: {Path(chirps_files[-1]).name}")
else:
    print("  ✗ No CHIRPS files found!")
    print(f"  Expected location: {CHIRPS_DIR}")
    print(f"  Run: python 01_download_chirps_djibouti.py")
    sys.exit(1)

print(f"\nERA5 Temperature: {era5_temp.exists() and '✓' or '✗'} {era5_temp.name}")
print(f"ERA5 PET: {era5_pet.exists() and '✓' or '✗'} {era5_pet.name}")

if not era5_temp.exists() or not era5_pet.exists():
    print("\n✗ ERA5 files missing!")
    print(f"  Expected location: {ERA5_DIR}")
    print(f"  Run: python 02_download_era5_djibouti.py")
    sys.exit(1)

# Load data
print("\n" + "="*70)
print("LOADING AND PROCESSING DATA")
print("="*70)

start_time = time.time()

# 1. Load CHIRPS precipitation (memory-efficient: process in chunks)
print("\n[1/3] Loading CHIRPS precipitation...")
print("  Processing in chunks to manage memory...")

# Process in chunks of 200 files
chunk_size = 200
chirps_chunks = []

for chunk_start in range(0, len(chirps_files), chunk_size):
    chunk_end = min(chunk_start + chunk_size, len(chirps_files))
    chunk_files = chirps_files[chunk_start:chunk_end]
    
    print(f"  Processing chunk {chunk_start//chunk_size + 1}/{(len(chirps_files)-1)//chunk_size + 1} (files {chunk_start+1}-{chunk_end})...", flush=True)
    
    chunk_list = []
    for chirps_file in chunk_files:
        try:
            da = rxr.open_rasterio(chirps_file)
            # Get date from filename
            filename = Path(chirps_file).stem  # chirps-v2.0.2021.01.01
            date_str = filename.split('.')[-3:]  # ['2021', '01', '01']
            date = datetime(int(date_str[0]), int(date_str[1]), int(date_str[2]))
            
            # Add time dimension
            da_time = da.squeeze().expand_dims(time=[date])
            chunk_list.append(da_time)
        except Exception as e:
            print(f"    ✗ Error reading {Path(chirps_file).name}: {e}")
    
    if chunk_list:
        chunk_data = xr.concat(chunk_list, dim='time')
        chirps_chunks.append(chunk_data)
        del chunk_list  # Free memory

print(f"  ✓ Loaded {len(chirps_files)} files in {len(chirps_chunks)} chunks")

# Concatenate chunks
print("  Concatenating chunks...")
chirps = xr.concat(chirps_chunks, dim='time')
del chirps_chunks  # Free memory

chirps.name = 'precip'
chirps.attrs['units'] = 'mm/day'
chirps.attrs['long_name'] = 'Precipitation'
print(f"  ✓ CHIRPS shape: {chirps.shape}")

# 2. Load ERA5 temperature
print("\n[2/3] Loading ERA5 temperature...")
temp_ds = xr.open_dataset(era5_temp)
temp = temp_ds['t2m']  # 2m temperature

# Handle dimensions - drop 'time' if both 'time' and 'valid_time' exist
if 'time' in temp.dims and 'valid_time' in temp.dims:
    temp = temp.isel(time=0)  # Take first slice of time dimension
    temp = temp.drop_vars('time', errors='ignore')

# Rename valid_time to time for consistency
if 'valid_time' in temp.dims:
    temp = temp.rename({'valid_time': 'time'})

# Convert from Kelvin to Celsius
temp = temp - 273.15
temp.attrs['units'] = '°C'
temp.attrs['long_name'] = 'Temperature'

# Resample to daily (mean temperature)
temp_daily = temp.resample(time='1D').mean()
print(f"  ✓ Temperature shape: {temp_daily.shape}")

# 3. Load ERA5 potential evapotranspiration
print("\n[3/3] Loading ERA5 potential evapotranspiration...")
pet_ds = xr.open_dataset(era5_pet)
pet = pet_ds['pev']  # Potential evaporation

# Handle dimensions - drop 'time' if both 'time' and 'valid_time' exist
if 'time' in pet.dims and 'valid_time' in pet.dims:
    pet = pet.isel(time=0)  # Take first slice of time dimension
    pet = pet.drop_vars('time', errors='ignore')

# Rename valid_time to time for consistency
if 'valid_time' in pet.dims:
    pet = pet.rename({'valid_time': 'time'})

# Convert from m to mm and make positive (ERA5 PET is negative)
pet = -pet * 1000
pet.attrs['units'] = 'mm/day'
pet.attrs['long_name'] = 'Potential Evapotranspiration'

# Resample to daily (sum)
pet_daily = pet.resample(time='1D').sum()
print(f"  ✓ PET shape: {pet_daily.shape}")

# Combine into single dataset
print("\n" + "="*70)
print("COMBINING DATASETS")
print("="*70)

# Match spatial grids (interpolate ERA5 to CHIRPS grid)
print("\nInterpolating ERA5 data to CHIRPS grid...")

# Get CHIRPS coordinates (CHIRPS uses y and x)
target_y = chirps.coords['y']
target_x = chirps.coords['x']

# Interpolate temperature (ERA5 uses latitude and longitude)
temp_interp = temp_daily.interp(
    latitude=target_y,
    longitude=target_x,
    method='linear'
)
temp_interp = temp_interp.rename({'latitude': 'y', 'longitude': 'x'})

# Interpolate PET
pet_interp = pet_daily.interp(
    latitude=target_y,
    longitude=target_x,
    method='linear'
)
pet_interp = pet_interp.rename({'latitude': 'y', 'longitude': 'x'})

print("  ✓ Interpolation complete")

# Align time dimensions
print("\nAligning time dimensions...")
# Find common time range - use pandas datetime for alignment
import pandas as pd

chirps_times = pd.to_datetime(chirps.time.values)
temp_times = pd.to_datetime(temp_interp.time.values)
pet_times = pd.to_datetime(pet_interp.time.values)

# Find intersection
common_start = max(chirps_times.min(), temp_times.min(), pet_times.min())
common_end = min(chirps_times.max(), temp_times.max(), pet_times.max())

chirps_aligned = chirps.sel(time=slice(common_start, common_end))
temp_aligned = temp_interp.sel(time=slice(common_start, common_end))
pet_aligned = pet_interp.sel(time=slice(common_start, common_end))

print(f"  ✓ Aligned to {len(chirps_aligned.time)} days")

# Create forcing dataset
print("\nCreating forcing dataset...")
forcing = xr.Dataset({
    'precip': chirps_aligned,
    'temp': temp_aligned,
    'pet': pet_aligned
})

# Add metadata
forcing.attrs['title'] = 'Wflow forcing data for Djibouti'
forcing.attrs['source'] = 'CHIRPS v2.0 (precipitation), ERA5 (temperature, PET)'
forcing.attrs['region'] = 'Djibouti'
forcing.attrs['period'] = '2021-01-01 to 2023-12-31'
forcing.attrs['created'] = datetime.now().isoformat()

print(f"  ✓ Forcing dataset created")
print(f"\nDataset summary:")
print(f"  Time steps: {len(forcing.time)}")
print(f"  Spatial: {len(forcing.y)} x {len(forcing.x)}")
print(f"  Variables: {list(forcing.data_vars)}")

# Save to NetCDF
print(f"\nSaving to: {OUTPUT_FILE}")
forcing.to_netcdf(
    OUTPUT_FILE,
    encoding={
        'precip': {'zlib': True, 'complevel': 4},
        'temp': {'zlib': True, 'complevel': 4},
        'pet': {'zlib': True, 'complevel': 4}
    }
)

elapsed = time.time() - start_time

print("\n" + "="*70)
print("FORCING FILE CREATED!")
print("="*70)
print(f"\n✓ Output: {OUTPUT_FILE}")
print(f"✓ File size: {OUTPUT_FILE.stat().st_size / 1024**2:.1f} MB")
print(f"✓ Time: {elapsed/60:.1f} minutes")

# Save processing info
forcing_info = {
    'output_file': str(OUTPUT_FILE),
    'period': '2021-01-01 to 2023-12-31',
    'time_steps': int(len(forcing.time)),
    'spatial_resolution': f"{len(forcing.y)} x {len(forcing.x)}",
    'variables': {
        'precip': {
            'source': 'CHIRPS v2.0',
            'units': 'mm/day',
            'mean': float(forcing.precip.mean().values),
            'max': float(forcing.precip.max().values)
        },
        'temp': {
            'source': 'ERA5',
            'units': '°C',
            'mean': float(forcing.temp.mean().values),
            'min': float(forcing.temp.min().values),
            'max': float(forcing.temp.max().values)
        },
        'pet': {
            'source': 'ERA5',
            'units': 'mm/day',
            'mean': float(forcing.pet.mean().values),
            'max': float(forcing.pet.max().values)
        }
    },
    'processing_time_minutes': round(elapsed / 60, 2)
}

info_file = OUTPUT_DIR / 'forcing_info.json'
with open(info_file, 'w') as f:
    json.dump(forcing_info, f, indent=2)

print(f"✓ Info saved: {info_file}")

print("\n" + "="*70)
print("FORCING FILE READY FOR WFLOW SIMULATION")
print("="*70)
