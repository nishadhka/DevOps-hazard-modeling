#!/usr/bin/env python3
"""
Resample forcing data to match staticmaps grid for Ethiopia.
Memory-efficient version that processes in batches.
"""

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
import warnings
import os
import gc
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================
BASE_DIR = "/data/bdi_trail2/dr_case4"
FORCING_INPUT = os.path.join(BASE_DIR, "forcing/forcing.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_FILE = os.path.join(BASE_DIR, "data/input/forcing.nc")
BATCH_SIZE = 50  # Process 50 timesteps at a time

# =============================================================================
# LOAD TARGET GRID FROM STATICMAPS
# =============================================================================
print("=" * 80)
print("STEP 1: Loading target grid from staticmaps...")
print("=" * 80)

ds_static = xr.open_dataset(STATICMAPS_FILE)
target_lat = ds_static['lat'].values.astype(np.float64)
target_lon = ds_static['lon'].values.astype(np.float64)
target_ny, target_nx = len(target_lat), len(target_lon)

print(f"Target grid: {target_ny} x {target_nx}")
print(f"Target lat: {target_lat.min():.4f} to {target_lat.max():.4f}")
print(f"Target lon: {target_lon.min():.4f} to {target_lon.max():.4f}")
ds_static.close()

# =============================================================================
# LOAD SOURCE FORCING METADATA
# =============================================================================
print("\n" + "=" * 80)
print("STEP 2: Loading source forcing metadata...")
print("=" * 80)

ds_force = xr.open_dataset(FORCING_INPUT)
print(f"Variables: {list(ds_force.data_vars)}")

source_lat = ds_force['lat'].values.astype(np.float64)
source_lon = ds_force['lon'].values.astype(np.float64)
source_time = ds_force['time'].values
nt = len(source_time)

print(f"Source grid: {len(source_lat)} x {len(source_lon)}")
print(f"Time steps: {nt}")
print(f"Time range: {source_time[0]} to {source_time[-1]}")

# Check if latitude needs to be reversed
if source_lat[0] > source_lat[-1]:
    source_lat_sorted = source_lat[::-1]
    lat_reversed = True
else:
    source_lat_sorted = source_lat
    lat_reversed = False

print(f"Latitude reversed: {lat_reversed}")

# Create meshgrid for target points (do this once)
target_lon_grid, target_lat_grid = np.meshgrid(target_lon, target_lat)
target_points = np.column_stack([target_lat_grid.ravel(), target_lon_grid.ravel()])
del target_lon_grid, target_lat_grid
gc.collect()

# =============================================================================
# PROCESS IN BATCHES
# =============================================================================
print("\n" + "=" * 80)
print("STEP 3: Processing forcing in batches...")
print("=" * 80)

force_vars = ['precip', 'temp', 'pet']
n_batches = (nt + BATCH_SIZE - 1) // BATCH_SIZE
print(f"Processing {nt} timesteps in {n_batches} batches of {BATCH_SIZE}")

# Create output file with empty arrays
print("\nInitializing output file...")
ds_out = xr.Dataset(
    coords={
        'time': (['time'], source_time),
        'lat': (['lat'], target_lat),
        'lon': (['lon'], target_lon),
    }
)

for var in force_vars:
    ds_out[var] = xr.DataArray(
        np.zeros((nt, target_ny, target_nx), dtype=np.float32),
        dims=['time', 'lat', 'lon']
    )

ds_out.close()
del ds_out
gc.collect()

# Process each variable
for var in force_vars:
    if var not in ds_force:
        print(f"WARNING: {var} not found in forcing data")
        continue

    print(f"\n=== Processing {var} ===")

    # Load variable data lazily and process in batches
    var_data = ds_force[var]

    all_resampled = []

    for batch_idx in range(n_batches):
        t_start = batch_idx * BATCH_SIZE
        t_end = min((batch_idx + 1) * BATCH_SIZE, nt)
        print(f"  Batch {batch_idx+1}/{n_batches}: timesteps {t_start} to {t_end-1}")

        # Load batch data into memory
        batch_data = var_data[t_start:t_end].values
        batch_size_actual = t_end - t_start

        # Resample batch
        resampled_batch = np.zeros((batch_size_actual, target_ny, target_nx), dtype=np.float32)

        for i in range(batch_size_actual):
            data_t = batch_data[i]
            if lat_reversed:
                data_t = data_t[::-1, :]

            # Fill NaN for interpolation
            data_t_filled = np.where(np.isnan(data_t), 0, data_t)

            try:
                interp = RegularGridInterpolator(
                    (source_lat_sorted, source_lon),
                    data_t_filled,
                    method='nearest',
                    bounds_error=False,
                    fill_value=None
                )
                resampled_flat = interp(target_points)
                resampled_batch[i] = resampled_flat.reshape(target_ny, target_nx)
            except Exception as e:
                print(f"    Error at timestep {t_start + i}: {e}")
                resampled_batch[i] = np.nan

        all_resampled.append(resampled_batch)
        del batch_data, resampled_batch
        gc.collect()

    # Concatenate all batches
    print(f"  Concatenating {len(all_resampled)} batches...")
    full_resampled = np.concatenate(all_resampled, axis=0)
    del all_resampled
    gc.collect()

    # Fill NaN with appropriate defaults
    nan_count = np.sum(np.isnan(full_resampled))
    if nan_count > 0:
        print(f"  Filling {nan_count:,} NaN values...")
        if var == 'precip':
            fill_value = 0.0
        else:
            fill_value = float(np.nanmean(full_resampled))
        full_resampled = np.where(np.isnan(full_resampled), fill_value, full_resampled)

    print(f"  Range: {np.min(full_resampled):.3f} to {np.max(full_resampled):.3f}")

    # Store for output
    if var == 'precip':
        precip_data = full_resampled
    elif var == 'temp':
        temp_data = full_resampled
    elif var == 'pet':
        pet_data = full_resampled

    del full_resampled
    gc.collect()

ds_force.close()

# =============================================================================
# SAVE OUTPUT
# =============================================================================
print("\n" + "=" * 80)
print("STEP 4: Saving resampled forcing...")
print("=" * 80)

ds_out = xr.Dataset(
    coords={
        'time': (['time'], source_time, {'units': 'days since 2020-01-01'}),
        'lat': (['lat'], target_lat, {'units': 'degrees_north'}),
        'lon': (['lon'], target_lon, {'units': 'degrees_east'}),
    }
)

ds_out['precip'] = xr.DataArray(
    precip_data, dims=['time', 'lat', 'lon'],
    attrs={'units': 'mm/day', 'long_name': 'precipitation'}
)
ds_out['temp'] = xr.DataArray(
    temp_data, dims=['time', 'lat', 'lon'],
    attrs={'units': 'degrees_C', 'long_name': 'temperature'}
)
ds_out['pet'] = xr.DataArray(
    pet_data, dims=['time', 'lat', 'lon'],
    attrs={'units': 'mm/day', 'long_name': 'potential_evapotranspiration'}
)

encoding = {var: {'zlib': True, 'complevel': 4} for var in ['precip', 'temp', 'pet']}

print("Writing to disk...")
ds_out.to_netcdf(OUTPUT_FILE, format='NETCDF4', encoding=encoding)

file_size = os.path.getsize(OUTPUT_FILE) / 1e9
print(f"Saved: {OUTPUT_FILE}")
print(f"Size: {file_size:.2f} GB")

# =============================================================================
# VERIFICATION
# =============================================================================
print("\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80)

ds_check = xr.open_dataset(OUTPUT_FILE)
print(f"Grid: {len(ds_check.lat)} x {len(ds_check.lon)}")
print(f"Timesteps: {len(ds_check.time)}")

for var in ['precip', 'temp', 'pet']:
    data = ds_check[var].isel(time=0).values
    nan_pct = np.sum(np.isnan(data)) / data.size * 100
    print(f"{var}: min={np.nanmin(data):.3f}, max={np.nanmax(data):.3f}, NaN={nan_pct:.1f}%")

ds_check.close()

print("\nDONE!")
