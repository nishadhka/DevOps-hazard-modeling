#!/usr/bin/env python3
"""
Memory-Optimized Forcing Preparation for Djibouti

Uses xarray with dask for lazy loading to avoid memory issues.
"""

import sys
from pathlib import Path
from datetime import datetime
import json
import time
import numpy as np
import xarray as xr
import warnings
warnings.filterwarnings('ignore')

print("="*70)
print("PREPARE WFLOW FORCING FILE - DJIBOUTI (OPTIMIZED)")
print("="*70)

# Paths
SCRIPT_DIR = Path(__file__).parent.absolute()
CASE_DIR = SCRIPT_DIR.parent  # dr_case2/
DATA_DIR = CASE_DIR / '02_Djibouti_2021_2023' / 'data'
CHIRPS_DIR = DATA_DIR / 'chirps' / 'daily'
ERA5_DIR = DATA_DIR / 'era5'

OUTPUT_DIR = CASE_DIR / 'data' / 'input'
OUTPUT_FILE = OUTPUT_DIR / 'forcing.nc'
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

print(f"\nInput directories:")
print(f"  CHIRPS: {CHIRPS_DIR}")
print(f"  ERA5: {ERA5_DIR}")
print(f"\nOutput file: {OUTPUT_FILE}")

# Check input files
print("\n" + "="*70)
print("LOADING DATA WITH DASK (LAZY LOADING)")
print("="*70)

start_time = time.time()

# 1. Load CHIRPS with open_mfdataset (lazy loading with dask)
print("\n[1/3] Loading CHIRPS precipitation (lazy)...")
chirps_pattern = str(CHIRPS_DIR / 'chirps-v2.0.*.tif')

try:
    import rioxarray as rxr
    # We need to use a custom approach since rioxarray doesn't support open_mfdataset directly
    # Let's load in smaller batches and concatenate

    from glob import glob
    chirps_files = sorted(glob(chirps_pattern))
    print(f"  Found {len(chirps_files)} CHIRPS files")

    # Process in very small chunks to conserve memory
    chunk_size = 50
    print(f"  Processing in chunks of {chunk_size} files...")

    chirps_data_list = []
    for i in range(0, len(chirps_files), chunk_size):
        chunk_files = chirps_files[i:i+chunk_size]
        print(f"  Chunk {i//chunk_size + 1}/{(len(chirps_files)-1)//chunk_size + 1}...", flush=True)

        chunk_arrays = []
        for f in chunk_files:
            da = rxr.open_rasterio(f, chunks={'x': 50, 'y': 50}).squeeze()
            # Extract date from filename
            parts = Path(f).stem.split('.')
            date_str = f"{parts[-3]}-{parts[-2]}-{parts[-1]}"
            da = da.expand_dims(time=[np.datetime64(date_str)])
            chunk_arrays.append(da)

        # Concatenate this chunk
        chunk_data = xr.concat(chunk_arrays, dim='time')
        chirps_data_list.append(chunk_data)

        # Clear memory
        del chunk_arrays

    # Final concatenation
    print("  Final concatenation...")
    chirps = xr.concat(chirps_data_list, dim='time')
    chirps.name = 'precip'
    chirps.attrs['units'] = 'mm/day'
    print(f"  ✓ CHIRPS loaded: {chirps.shape}")

except Exception as e:
    print(f"  ✗ Error loading CHIRPS: {e}")
    sys.exit(1)

# 2. Load ERA5 temperature
print("\n[2/3] Loading ERA5 temperature...")
temp_ds = xr.open_dataset(ERA5_DIR / 'temperature_2m_2021_2023.nc', chunks={'time': 100})
temp = temp_ds['t2m']

if 'time' in temp.dims and 'valid_time' in temp.dims:
    temp = temp.isel(time=0).drop_vars('time', errors='ignore')

if 'valid_time' in temp.dims:
    temp = temp.rename({'valid_time': 'time'})

# Convert K to C
temp = temp - 273.15
temp.attrs['units'] = '°C'

# Resample to daily
temp_daily = temp.resample(time='1D').mean()
print(f"  ✓ Temperature: {temp_daily.shape}")

# 3. Load ERA5 PET
print("\n[3/3] Loading ERA5 PET...")
pet_ds = xr.open_dataset(ERA5_DIR / 'potential_evaporation_2021_2023.nc', chunks={'time': 100})
pet = pet_ds['pev']

if 'time' in pet.dims and 'valid_time' in pet.dims:
    pet = pet.isel(time=0).drop_vars('time', errors='ignore')

if 'valid_time' in pet.dims:
    pet = pet.rename({'valid_time': 'time'})

# Convert m to mm and make positive
pet = -pet * 1000
pet.attrs['units'] = 'mm/day'

# Resample to daily
pet_daily = pet.resample(time='1D').sum()
print(f"  ✓ PET: {pet_daily.shape}")

# Interpolate ERA5 to CHIRPS grid
print("\n" + "="*70)
print("INTERPOLATING TO COMMON GRID")
print("="*70)

target_y = chirps.coords['y']
target_x = chirps.coords['x']

print("  Interpolating temperature...")
temp_interp = temp_daily.interp(
    latitude=target_y,
    longitude=target_x,
    method='linear'
)
# Rename only if needed
if 'latitude' in temp_interp.dims:
    temp_interp = temp_interp.rename({'latitude': 'y', 'longitude': 'x'})

print("  Interpolating PET...")
pet_interp = pet_daily.interp(
    latitude=target_y,
    longitude=target_x,
    method='linear'
)
# Rename only if needed
if 'latitude' in pet_interp.dims:
    pet_interp = pet_interp.rename({'latitude': 'y', 'longitude': 'x'})

# Align times
print("\nAligning time dimensions...")
import pandas as pd

chirps_times = pd.to_datetime(chirps.time.values)
temp_times = pd.to_datetime(temp_interp.time.values)
pet_times = pd.to_datetime(pet_interp.time.values)

common_start = max(chirps_times.min(), temp_times.min(), pet_times.min())
common_end = min(chirps_times.max(), temp_times.max(), pet_times.max())

chirps_aligned = chirps.sel(time=slice(common_start, common_end))
temp_aligned = temp_interp.sel(time=slice(common_start, common_end))
pet_aligned = pet_interp.sel(time=slice(common_start, common_end))

print(f"  ✓ Aligned to {len(chirps_aligned.time)} days")

# Create forcing dataset
print("\n" + "="*70)
print("CREATING FORCING DATASET")
print("="*70)

forcing = xr.Dataset({
    'precip': chirps_aligned,
    'temp': temp_aligned,
    'pet': pet_aligned
})

forcing.attrs['title'] = 'Wflow forcing data for Djibouti'
forcing.attrs['source'] = 'CHIRPS v2.0, ERA5'
forcing.attrs['period'] = '2021-2023'
forcing.attrs['created'] = datetime.now().isoformat()

print(f"\nDataset:")
print(f"  Time steps: {len(forcing.time)}")
print(f"  Spatial: {len(forcing.y)} x {len(forcing.x)}")
print(f"  Variables: {list(forcing.data_vars)}")

# Save with compression
print(f"\nSaving to: {OUTPUT_FILE}")
print("  (This may take several minutes...)")

forcing.to_netcdf(
    OUTPUT_FILE,
    encoding={
        'precip': {'zlib': True, 'complevel': 4, 'dtype': 'float32'},
        'temp': {'zlib': True, 'complevel': 4, 'dtype': 'float32'},
        'pet': {'zlib': True, 'complevel': 4, 'dtype': 'float32'}
    },
    compute=True  # Force computation
)

elapsed = time.time() - start_time

print("\n" + "="*70)
print("FORCING FILE CREATED!")
print("="*70)
print(f"\n✓ Output: {OUTPUT_FILE}")
print(f"✓ File size: {OUTPUT_FILE.stat().st_size / 1024**2:.1f} MB")
print(f"✓ Time: {elapsed/60:.1f} minutes")

# Save info
forcing_info = {
    'output_file': str(OUTPUT_FILE),
    'period': f'{common_start} to {common_end}',
    'time_steps': int(len(forcing.time)),
    'spatial': f"{len(forcing.y)} x {len(forcing.x)}",
    'processing_time_minutes': round(elapsed / 60, 2)
}

info_file = OUTPUT_DIR / 'forcing_info.json'
with open(info_file, 'w') as f:
    json.dump(forcing_info, f, indent=2)

print(f"✓ Info saved: {info_file}")
print("\nFORCING FILE READY FOR WFLOW!")
