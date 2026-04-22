#!/usr/bin/env python3
"""
Resample forcing using dask for memory-efficient processing.
"""

import numpy as np
import xarray as xr
import dask.array as da
import os

BASE_DIR = "/data/bdi_trail2/dr_case4"
FORCING_SUBSET = os.path.join(BASE_DIR, "data/input/forcing_subset.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_FILE = os.path.join(BASE_DIR, "data/input/forcing.nc")

print("=" * 70)
print("Ethiopia Forcing Resampling with Dask")
print("=" * 70)

# Load target grid
print("\n1. Loading target grid...")
ds_static = xr.open_dataset(STATICMAPS_FILE)
target_lat = ds_static['lat'].values
target_lon = ds_static['lon'].values
print(f"   Target: {len(target_lat)} x {len(target_lon)}")
ds_static.close()

# Load forcing with dask chunking
print("\n2. Loading forcing with dask...")
ds_force = xr.open_dataset(FORCING_SUBSET, chunks={'time': 10})
print(f"   Source: {len(ds_force.lat)} x {len(ds_force.lon)}, {len(ds_force.time)} timesteps")

# Interpolate using xarray (dask-aware)
print("\n3. Interpolating (streaming with dask)...")
ds_interp = ds_force.interp(lat=target_lat, lon=target_lon, method='nearest')

# Fill NaN before writing
print("\n4. Writing to disk (this may take a while)...")
for var in ['precip', 'temp', 'pet']:
    if var in ds_interp:
        fill_val = 0.0 if var == 'precip' else 20.0
        ds_interp[var] = ds_interp[var].fillna(fill_val)

# Write with chunked encoding
encoding = {
    var: {'zlib': True, 'complevel': 4, 'chunksizes': (10, 100, 100)}
    for var in ['precip', 'temp', 'pet']
    if var in ds_interp
}

ds_interp.to_netcdf(OUTPUT_FILE, encoding=encoding)

print(f"\nSaved: {OUTPUT_FILE}")
print(f"Size: {os.path.getsize(OUTPUT_FILE)/1e9:.2f} GB")

# Verify
print("\n5. Verification:")
ds_check = xr.open_dataset(OUTPUT_FILE)
print(f"   Grid: {len(ds_check.lat)} x {len(ds_check.lon)}")
print(f"   Time: {len(ds_check.time)} steps")
ds_check.close()

print("\nDONE!")
