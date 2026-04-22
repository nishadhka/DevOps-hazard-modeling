#!/usr/bin/env python3
"""
Step 3: Prepare Wflow Forcing File (forcing.nc) for Uganda - Fine Resolution

Uses CHIRPS native resolution and interpolates ERA5 to match (like Burundi/Eritrea).
Period: 2021-2022
"""

import sys
from pathlib import Path
from datetime import datetime
import json
import time
import numpy as np
import xarray as xr
import rasterio
from glob import glob
import warnings
warnings.filterwarnings('ignore')

print("="*70)
print("PREPARE WFLOW FORCING FILE - UGANDA (2021-2022) - FINE RESOLUTION")
print("="*70)

# Paths
BASE_DIR = Path(__file__).parent.parent
CHIRPS_DIR = BASE_DIR / 'data' / 'chirps' / 'daily'
ERA5_DIR = BASE_DIR / 'data' / 'era5'
OUTPUT_DIR = BASE_DIR / 'forcing'
OUTPUT_FILE = OUTPUT_DIR / 'forcing.nc'
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

# Uganda bounds
UGANDA_BOUNDS = {
    'west': 32.8,
    'east': 34.9,
    'south': 1.0,
    'north': 3.8
}

print(f"\nOutput: {OUTPUT_FILE}")
start_time = time.time()

# 1. Load CHIRPS at native resolution
print("\n[1/3] Loading CHIRPS precipitation at native resolution...")
chirps_files = sorted(glob(str(CHIRPS_DIR / 'chirps-v2.0.*.tif')))
print(f"  Found {len(chirps_files)} CHIRPS files")

# Process in chunks to manage memory
chunk_size = 200
chirps_chunks = []

for chunk_start in range(0, len(chirps_files), chunk_size):
    chunk_end = min(chunk_start + chunk_size, len(chirps_files))
    chunk_files = chirps_files[chunk_start:chunk_end]
    
    print(f"  Processing chunk {chunk_start//chunk_size + 1}/{(len(chirps_files)-1)//chunk_size + 1} (files {chunk_start+1}-{chunk_end})...", flush=True)
    
    chunk_list = []
    for chirps_file in chunk_files:
        try:
            with rasterio.open(chirps_file) as src:
                data = src.read(1)
                transform = src.transform
                height, width = data.shape
                
                # Calculate coordinates (center of pixels)
                y = np.array([transform[5] + transform[4] * (i + 0.5) for i in range(height)])
                x = np.array([transform[2] + transform[0] * (j + 0.5) for j in range(width)])
                
                # Crop to Uganda bounds
                lat_mask = (y >= UGANDA_BOUNDS['south']) & (y <= UGANDA_BOUNDS['north'])
                lon_mask = (x >= UGANDA_BOUNDS['west']) & (x <= UGANDA_BOUNDS['east'])
                
                if not (lat_mask.any() and lon_mask.any()):
                    continue
                
                data_cropped = data[lat_mask, :][:, lon_mask]
                y_cropped = y[lat_mask]
                x_cropped = x[lon_mask]
                
                # Handle NoData (negative values)
                data_cropped = np.where(data_cropped < 0, 0, data_cropped)
                
                # Get date from filename
                filename = Path(chirps_file).stem
                date_str = filename.split('.')[-3:]
                date = datetime(int(date_str[0]), int(date_str[1]), int(date_str[2]))
                
                # Create DataArray
                da = xr.DataArray(
                    data_cropped[np.newaxis, :, :],
                    dims=['time', 'y', 'x'],
                    coords={'time': [date], 'y': y_cropped, 'x': x_cropped}
                )
                chunk_list.append(da)
                
        except Exception as e:
            if len(chunk_list) < 5:  # Only print first few errors
                print(f"    ✗ Error: {Path(chirps_file).name}: {e}")
    
    if chunk_list:
        chunk_data = xr.concat(chunk_list, dim='time')
        chirps_chunks.append(chunk_data)
        del chunk_list

# Concatenate all chunks
print("  Concatenating chunks...")
chirps = xr.concat(chirps_chunks, dim='time')
del chirps_chunks

chirps.name = 'precip'
chirps.attrs['units'] = 'mm/day'
chirps.attrs['long_name'] = 'Precipitation'
print(f"  ✓ CHIRPS shape: {chirps.shape}")
print(f"  ✓ Grid size: {len(chirps.y)} x {len(chirps.x)}")

# Get CHIRPS grid for ERA5 interpolation
target_y = chirps.coords['y']
target_x = chirps.coords['x']

# 2. Load ERA5 temperature
print("\n[2/3] Loading ERA5 temperature...")
# Check if merged file exists, otherwise use year-by-year files
temp_file = ERA5_DIR / 'temperature_2m_2021_2022.nc'
if not temp_file.exists():
    # Try to merge year-by-year files
    temp_2021 = ERA5_DIR / '2m_temperature_2021.nc'
    temp_2022 = ERA5_DIR / '2m_temperature_2022.nc'
    if temp_2021.exists() and temp_2022.exists():
        print("  Merging year-by-year temperature files...")
        ds_2021 = xr.open_dataset(temp_2021)
        ds_2022 = xr.open_dataset(temp_2022)
        temp_ds = xr.concat([ds_2021, ds_2022], dim='time')
        ds_2021.close()
        ds_2022.close()
    else:
        print(f"  ✗ Temperature file not found: {temp_file}")
        sys.exit(1)
else:
    temp_ds = xr.open_dataset(temp_file)

temp = temp_ds['t2m']

# Handle dimensions
if 'time' in temp.dims and 'valid_time' in temp.dims:
    temp = temp.isel(time=0).drop_vars('time', errors='ignore')
if 'valid_time' in temp.dims:
    temp = temp.rename({'valid_time': 'time'})

temp = temp - 273.15  # K to C
temp.attrs['units'] = '°C'
temp_daily = temp.resample(time='1D').mean()
print(f"  ✓ Temperature shape: {temp_daily.shape}")

# Interpolate ERA5 to CHIRPS grid
print("  Interpolating to CHIRPS grid...")
temp_interp = temp_daily.interp(
    latitude=target_y,
    longitude=target_x,
    method='linear'
)
# Drop any existing y/x coordinates, then rename dimensions
temp_interp = temp_interp.drop_vars(['y', 'x'], errors='ignore')
temp_interp = temp_interp.rename({'latitude': 'y', 'longitude': 'x'})
# Assign CHIRPS coordinates
temp_interp = temp_interp.assign_coords(y=target_y, x=target_x)
print(f"  ✓ Interpolated shape: {temp_interp.shape}")

# 3. Load ERA5 PET
print("\n[3/3] Loading ERA5 PET...")
pet_ds = xr.open_dataset(ERA5_DIR / 'potential_evaporation_2021_2022.nc')
pet = pet_ds['pev']

# Handle dimensions
if 'time' in pet.dims and 'valid_time' in pet.dims:
    pet = pet.isel(time=0).drop_vars('time', errors='ignore')
if 'valid_time' in pet.dims:
    pet = pet.rename({'valid_time': 'time'})

pet = -pet * 1000  # m to mm, make positive
pet.attrs['units'] = 'mm/day'
pet_daily = pet.resample(time='1D').sum()
print(f"  ✓ PET shape: {pet_daily.shape}")

# Interpolate ERA5 to CHIRPS grid
print("  Interpolating to CHIRPS grid...")
pet_interp = pet_daily.interp(
    latitude=target_y,
    longitude=target_x,
    method='linear'
)
# Drop any existing y/x coordinates, then rename dimensions
pet_interp = pet_interp.drop_vars(['y', 'x'], errors='ignore')
pet_interp = pet_interp.rename({'latitude': 'y', 'longitude': 'x'})
# Assign CHIRPS coordinates
pet_interp = pet_interp.assign_coords(y=target_y, x=target_x)
print(f"  ✓ Interpolated shape: {pet_interp.shape}")

# 4. Align time dimensions and combine
print("\n[4/4] Creating forcing dataset...")

# Align times
import pandas as pd
chirps_times = pd.to_datetime(chirps.time.values)
temp_times = pd.to_datetime(temp_interp.time.values)
pet_times = pd.to_datetime(pet_interp.time.values)

common_start = max(chirps_times.min(), temp_times.min(), pet_times.min())
common_end = min(chirps_times.max(), temp_times.max(), pet_times.max())

chirps_aligned = chirps.sel(time=slice(common_start, common_end))
temp_aligned = temp_interp.sel(time=slice(common_start, common_end))
pet_aligned = pet_interp.sel(time=slice(common_start, common_end))

print(f"  Common time steps: {len(chirps_aligned.time)}")

# Create forcing dataset
forcing = xr.Dataset({
    'precip': chirps_aligned,
    'temp': temp_aligned,
    'pet': pet_aligned
})

# Rename coordinates to lat/lon for consistency with Burundi
forcing = forcing.rename({'y': 'lat', 'x': 'lon'})

forcing.attrs['title'] = 'Wflow forcing - Uganda'
forcing.attrs['source'] = 'CHIRPS v2.0 + ERA5'
forcing.attrs['period'] = f"{forcing.time[0].values} to {forcing.time[-1].values}"

print(f"\n  ✓ Forcing dataset created")
print(f"    Time: {len(forcing.time)} days")
print(f"    Grid: {len(forcing.lat)} x {len(forcing.lon)}")
print(f"    Variables: {list(forcing.data_vars)}")

# Save
print(f"\nSaving to: {OUTPUT_FILE}")
forcing.to_netcdf(
    OUTPUT_FILE,
    encoding={
        'precip': {'zlib': True, 'complevel': 4, 'dtype': 'float32'},
        'temp': {'zlib': True, 'complevel': 4, 'dtype': 'float32'},
        'pet': {'zlib': True, 'complevel': 4, 'dtype': 'float32'}
    }
)

elapsed = time.time() - start_time

print("\n" + "="*70)
print("FORCING FILE COMPLETE!")
print("="*70)
print(f"✓ Output: {OUTPUT_FILE}")
print(f"✓ Size: {OUTPUT_FILE.stat().st_size / 1024**2:.1f} MB")
print(f"✓ Time: {elapsed/60:.1f} minutes")

# Save info
info = {
    'output_file': str(OUTPUT_FILE),
    'time_steps': int(len(forcing.time)),
    'spatial_grid': f"{len(forcing.lat)} x {len(forcing.lon)}",
    'period': f"{forcing.time[0].values} to {forcing.time[-1].values}",
    'variables': ['precip (mm/day)', 'temp (°C)', 'pet (mm/day)'],
    'processing_time_minutes': round(elapsed / 60, 2)
}

with open(OUTPUT_DIR / 'forcing_info.json', 'w') as f:
    json.dump(info, f, indent=2, default=str)

print(f"✓ Info: {OUTPUT_DIR / 'forcing_info.json'}")
print("\n" + "="*70)
