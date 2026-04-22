#!/usr/bin/env python3
"""
Subset forcing to Kenya region only.
"""

import numpy as np
import xarray as xr
import os

BASE_DIR = "/data/bdi_trail2/dr_case5"
FORCING_INPUT = os.path.join(BASE_DIR, "forcing/forcing.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_FILE = os.path.join(BASE_DIR, "data/input/forcing_subset.nc")

print("=" * 70)
print("Kenya Forcing Subset")
print("=" * 70)

# Get target bounds from staticmaps
print("\n1. Loading target bounds from staticmaps...")
ds_static = xr.open_dataset(STATICMAPS_FILE)
target_lat = ds_static['lat'].values
target_lon = ds_static['lon'].values
lat_min, lat_max = target_lat.min(), target_lat.max()
lon_min, lon_max = target_lon.min(), target_lon.max()
print(f"   Target lat: {lat_min:.4f} to {lat_max:.4f}")
print(f"   Target lon: {lon_min:.4f} to {lon_max:.4f}")
ds_static.close()

# Add buffer
buffer = 0.1
lat_min_buf = lat_min - buffer
lat_max_buf = lat_max + buffer
lon_min_buf = lon_min - buffer
lon_max_buf = lon_max + buffer

# Load and subset forcing
print("\n2. Loading forcing and subsetting...")
ds_force = xr.open_dataset(FORCING_INPUT)
print(f"   Original: {len(ds_force.lat)} x {len(ds_force.lon)}, {len(ds_force.time)} timesteps")

# Check lat order (descending = need to reverse slice)
if ds_force.lat.values[0] > ds_force.lat.values[-1]:
    # Lat is descending, reverse the slice
    ds_subset = ds_force.sel(
        lat=slice(lat_max_buf, lat_min_buf),
        lon=slice(lon_min_buf, lon_max_buf)
    )
else:
    ds_subset = ds_force.sel(
        lat=slice(lat_min_buf, lat_max_buf),
        lon=slice(lon_min_buf, lon_max_buf)
    )

print(f"   Subset: {len(ds_subset.lat)} x {len(ds_subset.lon)}, {len(ds_subset.time)} timesteps")

# Save subset
print("\n3. Saving subset...")
ds_subset.to_netcdf(OUTPUT_FILE)

size_mb = os.path.getsize(OUTPUT_FILE) / 1e6
print(f"   Saved: {OUTPUT_FILE}")
print(f"   Size: {size_mb:.1f} MB")

ds_force.close()
ds_subset.close()

print("\nDONE!")
