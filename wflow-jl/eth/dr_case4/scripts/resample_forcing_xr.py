#!/usr/bin/env python3
"""
Resample forcing data using xarray's built-in interpolation.
More memory efficient approach.
"""

import numpy as np
import xarray as xr
import warnings
import os
warnings.filterwarnings('ignore')

BASE_DIR = "/data/bdi_trail2/dr_case4"
FORCING_INPUT = os.path.join(BASE_DIR, "forcing/forcing.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_FILE = os.path.join(BASE_DIR, "data/input/forcing.nc")

print("=" * 70)
print("Ethiopia Forcing Resampling")
print("=" * 70)

# Load target coordinates from staticmaps
print("\n1. Loading target grid from staticmaps...")
ds_static = xr.open_dataset(STATICMAPS_FILE)
target_lat = ds_static['lat'].values
target_lon = ds_static['lon'].values
print(f"   Target: {len(target_lat)} x {len(target_lon)} ({len(target_lat)*len(target_lon):,} cells)")
print(f"   Lat: {target_lat.min():.4f} to {target_lat.max():.4f}")
print(f"   Lon: {target_lon.min():.4f} to {target_lon.max():.4f}")
ds_static.close()

# Load forcing with chunking for memory efficiency
print("\n2. Loading forcing data...")
ds_force = xr.open_dataset(FORCING_INPUT, chunks={'time': 100})
print(f"   Source: {len(ds_force.lat)} x {len(ds_force.lon)}")
print(f"   Time: {len(ds_force.time)} steps")
print(f"   Variables: {list(ds_force.data_vars)}")

# Subset to region of interest first (more efficient)
print("\n3. Subsetting to Ethiopia region...")
lat_buffer = 0.5
lon_buffer = 0.5
lat_mask = (ds_force.lat >= target_lat.min() - lat_buffer) & (ds_force.lat <= target_lat.max() + lat_buffer)
lon_mask = (ds_force.lon >= target_lon.min() - lon_buffer) & (ds_force.lon <= target_lon.max() + lon_buffer)

ds_subset = ds_force.sel(lat=ds_force.lat[lat_mask], lon=ds_force.lon[lon_mask])
print(f"   Subset: {len(ds_subset.lat)} x {len(ds_subset.lon)}")

# Interpolate to target grid
print("\n4. Interpolating to target grid...")
ds_interp = ds_subset.interp(lat=target_lat, lon=target_lon, method='nearest')

# Load into memory and handle NaN
print("\n5. Loading and processing data...")
ds_loaded = ds_interp.compute()

# Fill NaN values
for var in ['precip', 'temp', 'pet']:
    if var in ds_loaded:
        data = ds_loaded[var].values
        nan_count = np.sum(np.isnan(data))
        if nan_count > 0:
            print(f"   {var}: filling {nan_count:,} NaN values")
            if var == 'precip':
                fill_val = 0.0
            else:
                fill_val = float(np.nanmean(data))
            ds_loaded[var].values = np.where(np.isnan(data), fill_val, data)

# Save
print("\n6. Saving resampled forcing...")
encoding = {var: {'zlib': True, 'complevel': 4} for var in ['precip', 'temp', 'pet'] if var in ds_loaded}
ds_loaded.to_netcdf(OUTPUT_FILE, format='NETCDF4', encoding=encoding)

size_gb = os.path.getsize(OUTPUT_FILE) / 1e9
print(f"   Saved: {OUTPUT_FILE}")
print(f"   Size: {size_gb:.2f} GB")

# Verification
print("\n7. Verification:")
ds_check = xr.open_dataset(OUTPUT_FILE)
print(f"   Grid: {len(ds_check.lat)} x {len(ds_check.lon)}")
print(f"   Time: {len(ds_check.time)} steps")
for var in ['precip', 'temp', 'pet']:
    if var in ds_check:
        v = ds_check[var]
        print(f"   {var}: min={float(v.min()):.3f}, max={float(v.max()):.3f}")
ds_check.close()

print("\n" + "=" * 70)
print("DONE!")
print("=" * 70)
