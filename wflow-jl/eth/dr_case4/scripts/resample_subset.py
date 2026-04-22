#!/usr/bin/env python3
"""
Resample the subset forcing to match staticmaps grid.
Now much more manageable with the smaller subset file.
"""

import numpy as np
import xarray as xr
import os
import gc
from scipy.interpolate import RegularGridInterpolator

BASE_DIR = "/data/bdi_trail2/dr_case4"
FORCING_SUBSET = os.path.join(BASE_DIR, "data/input/forcing_subset.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_FILE = os.path.join(BASE_DIR, "data/input/forcing.nc")
BATCH_SIZE = 100

print("=" * 70)
print("Ethiopia Forcing Resampling (from subset)")
print("=" * 70)

# Get target grid from staticmaps
print("\n1. Loading target grid from staticmaps...")
ds_static = xr.open_dataset(STATICMAPS_FILE)
target_lat = ds_static['lat'].values.astype(np.float64)
target_lon = ds_static['lon'].values.astype(np.float64)
target_ny, target_nx = len(target_lat), len(target_lon)
print(f"   Target: {target_ny} x {target_nx}")
ds_static.close()

# Load forcing subset
print("\n2. Loading forcing subset...")
ds_force = xr.open_dataset(FORCING_SUBSET)
source_lat = ds_force['lat'].values.astype(np.float64)
source_lon = ds_force['lon'].values.astype(np.float64)
source_time = ds_force['time'].values
nt = len(source_time)
print(f"   Source: {len(source_lat)} x {len(source_lon)}, {nt} timesteps")

# Check lat order and sort if needed
if source_lat[0] > source_lat[-1]:
    source_lat_sorted = source_lat[::-1]
    lat_reversed = True
    print("   Latitude reversed for interpolation")
else:
    source_lat_sorted = source_lat
    lat_reversed = False

# Create target points mesh
target_lon_mesh, target_lat_mesh = np.meshgrid(target_lon, target_lat)
target_points = np.column_stack([target_lat_mesh.ravel(), target_lon_mesh.ravel()])
del target_lon_mesh, target_lat_mesh

# Process each variable
print("\n3. Resampling variables...")
resampled_data = {}

for var in ['precip', 'temp', 'pet']:
    if var not in ds_force:
        print(f"   {var}: NOT FOUND")
        continue

    print(f"\n   Processing {var}...")
    var_data = ds_force[var].values

    # Output array
    resampled = np.zeros((nt, target_ny, target_nx), dtype=np.float32)

    # Process in batches
    n_batches = (nt + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_idx in range(n_batches):
        t_start = batch_idx * BATCH_SIZE
        t_end = min((batch_idx + 1) * BATCH_SIZE, nt)

        if batch_idx % 5 == 0:
            print(f"      Batch {batch_idx+1}/{n_batches} (timesteps {t_start}-{t_end-1})")

        for t in range(t_start, t_end):
            data_t = var_data[t]
            if lat_reversed:
                data_t = data_t[::-1, :]

            # Fill NaN for interpolation
            data_filled = np.where(np.isnan(data_t), 0, data_t)

            try:
                interp = RegularGridInterpolator(
                    (source_lat_sorted, source_lon),
                    data_filled,
                    method='nearest',
                    bounds_error=False,
                    fill_value=None
                )
                resampled[t] = interp(target_points).reshape(target_ny, target_nx)
            except Exception as e:
                print(f"      Error at t={t}: {e}")
                resampled[t] = 0.0

    # Fill remaining NaN
    nan_count = np.sum(np.isnan(resampled))
    if nan_count > 0:
        print(f"      Filling {nan_count:,} NaN values")
        if var == 'precip':
            fill_val = 0.0
        else:
            fill_val = float(np.nanmean(resampled))
        resampled = np.where(np.isnan(resampled), fill_val, resampled)

    print(f"      Range: {np.min(resampled):.3f} to {np.max(resampled):.3f}")
    resampled_data[var] = resampled
    gc.collect()

ds_force.close()

# Create output dataset
print("\n4. Creating output dataset...")
ds_out = xr.Dataset(
    coords={
        'time': (['time'], source_time),
        'lat': (['lat'], target_lat, {'units': 'degrees_north'}),
        'lon': (['lon'], target_lon, {'units': 'degrees_east'}),
    }
)

for var, data in resampled_data.items():
    units = 'mm/day' if var in ['precip', 'pet'] else 'degrees_C'
    ds_out[var] = xr.DataArray(data, dims=['time', 'lat', 'lon'], attrs={'units': units})

# Save with compression
print("\n5. Saving...")
encoding = {var: {'zlib': True, 'complevel': 4} for var in resampled_data.keys()}
ds_out.to_netcdf(OUTPUT_FILE, format='NETCDF4', encoding=encoding)

size_gb = os.path.getsize(OUTPUT_FILE) / 1e9
print(f"   Saved: {OUTPUT_FILE}")
print(f"   Size: {size_gb:.2f} GB")

# Verify
print("\n6. Verification:")
ds_check = xr.open_dataset(OUTPUT_FILE)
print(f"   Grid: {len(ds_check.lat)} x {len(ds_check.lon)}")
print(f"   Time: {len(ds_check.time)} steps")
for var in ['precip', 'temp', 'pet']:
    v = ds_check[var].isel(time=0).values
    nan_pct = np.sum(np.isnan(v)) / v.size * 100
    print(f"   {var}: min={np.nanmin(v):.3f}, max={np.nanmax(v):.3f}, NaN={nan_pct:.1f}%")
ds_check.close()

print("\n" + "=" * 70)
print("DONE!")
print("=" * 70)
