#!/usr/bin/env python3
"""
Resample forcing data to match staticmaps grid for Ethiopia.

The raw forcing data has a global extent and coarse resolution.
This script subsets and resamples to match the staticmaps grid exactly.
"""

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
import warnings
import os
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================
FORCING_INPUT = "forcing/forcing.nc"
STATICMAPS_FILE = "data/input/staticmaps.nc"
OUTPUT_FILE = "data/input/forcing.nc"

# =============================================================================
# LOAD TARGET GRID FROM STATICMAPS
# =============================================================================
print("=" * 80)
print("STEP 1: Loading target grid from staticmaps...")
print("=" * 80)

ds_static = xr.open_dataset(STATICMAPS_FILE)
target_lat = ds_static['lat'].values
target_lon = ds_static['lon'].values
target_ny, target_nx = len(target_lat), len(target_lon)

print(f"Target grid: {target_ny} x {target_nx}")
print(f"Target lat: {target_lat.min():.4f} to {target_lat.max():.4f}")
print(f"Target lon: {target_lon.min():.4f} to {target_lon.max():.4f}")

# Get mask for valid cells
dem = ds_static['wflow_dem'].values
mask = ~np.isnan(dem)
ds_static.close()

# =============================================================================
# LOAD SOURCE FORCING DATA
# =============================================================================
print("\n" + "=" * 80)
print("STEP 2: Loading source forcing data...")
print("=" * 80)

ds_force = xr.open_dataset(FORCING_INPUT)
print(f"Variables: {list(ds_force.data_vars)}")
print(f"Dimensions: {dict(ds_force.dims)}")

source_lat = ds_force['lat'].values
source_lon = ds_force['lon'].values
source_time = ds_force['time'].values

print(f"Source grid: {len(source_lat)} x {len(source_lon)}")
print(f"Source lat: {source_lat.min():.4f} to {source_lat.max():.4f}")
print(f"Source lon: {source_lon.min():.4f} to {source_lon.max():.4f}")
print(f"Time steps: {len(source_time)}")
print(f"Time range: {source_time[0]} to {source_time[-1]}")

# Check if source grid covers target
lat_covered = (source_lat.min() <= target_lat.min()) and (source_lat.max() >= target_lat.max())
lon_covered = (source_lon.min() <= target_lon.min()) and (source_lon.max() >= target_lon.max())
print(f"\nTarget area covered by source: lat={lat_covered}, lon={lon_covered}")

# =============================================================================
# RESAMPLE FORCING VARIABLES
# =============================================================================
print("\n" + "=" * 80)
print("STEP 3: Resampling forcing variables...")
print("=" * 80)

# Variables to resample
force_vars = ['precip', 'temp', 'pet']

# Create output arrays
resampled_data = {}
nt = len(source_time)

# Ensure latitude is in ascending order for interpolation
if source_lat[0] > source_lat[-1]:
    source_lat_sorted = source_lat[::-1]
    lat_reversed = True
else:
    source_lat_sorted = source_lat
    lat_reversed = False

# Create meshgrid for target points
target_lon_grid, target_lat_grid = np.meshgrid(target_lon, target_lat)
target_points = np.column_stack([target_lat_grid.ravel(), target_lon_grid.ravel()])

for var in force_vars:
    if var not in ds_force:
        print(f"  WARNING: Variable '{var}' not found in forcing data")
        continue

    print(f"\n  Processing {var}...")
    var_data = ds_force[var].values
    print(f"    Source shape: {var_data.shape}")
    print(f"    Source range: {np.nanmin(var_data):.3f} to {np.nanmax(var_data):.3f}")

    # Output array
    resampled = np.zeros((nt, target_ny, target_nx), dtype=np.float32)

    # Process each timestep
    for t in range(nt):
        if t % 100 == 0:
            print(f"    Timestep {t+1}/{nt}...")

        # Get source data for this timestep
        data_t = var_data[t]

        # Reverse latitude if needed
        if lat_reversed:
            data_t = data_t[::-1, :]

        # Handle NaN in source data
        data_t_filled = np.where(np.isnan(data_t), 0, data_t)

        # Create interpolator
        try:
            interp = RegularGridInterpolator(
                (source_lat_sorted, source_lon),
                data_t_filled,
                method='nearest',  # Use nearest neighbor for robustness
                bounds_error=False,
                fill_value=None
            )

            # Interpolate
            resampled_flat = interp(target_points)
            resampled[t] = resampled_flat.reshape(target_ny, target_nx)
        except Exception as e:
            print(f"    Error at timestep {t}: {e}")
            resampled[t] = np.nan

    # Fill any remaining NaN with variable-specific defaults
    nan_count = np.sum(np.isnan(resampled))
    if nan_count > 0:
        print(f"    Filling {nan_count:,} NaN values...")
        if var == 'precip':
            fill_value = 0.0
        elif var == 'temp':
            fill_value = np.nanmean(resampled)
        elif var == 'pet':
            fill_value = np.nanmean(resampled)
        else:
            fill_value = 0.0

        resampled = np.where(np.isnan(resampled), fill_value, resampled)

    print(f"    Output range: {np.nanmin(resampled):.3f} to {np.nanmax(resampled):.3f}")
    resampled_data[var] = resampled

ds_force.close()

# =============================================================================
# CREATE OUTPUT DATASET
# =============================================================================
print("\n" + "=" * 80)
print("STEP 4: Creating output NetCDF...")
print("=" * 80)

ds_out = xr.Dataset(
    coords={
        'time': (['time'], source_time, {'units': 'days since 2020-01-01', 'calendar': 'standard'}),
        'lat': (['lat'], target_lat, {'units': 'degrees_north', 'axis': 'Y'}),
        'lon': (['lon'], target_lon, {'units': 'degrees_east', 'axis': 'X'}),
    }
)

# Add resampled variables
if 'precip' in resampled_data:
    ds_out['precip'] = xr.DataArray(
        resampled_data['precip'],
        dims=['time', 'lat', 'lon'],
        attrs={'units': 'mm/day', 'long_name': 'precipitation'}
    )

if 'temp' in resampled_data:
    ds_out['temp'] = xr.DataArray(
        resampled_data['temp'],
        dims=['time', 'lat', 'lon'],
        attrs={'units': 'degrees_C', 'long_name': 'temperature'}
    )

if 'pet' in resampled_data:
    ds_out['pet'] = xr.DataArray(
        resampled_data['pet'],
        dims=['time', 'lat', 'lon'],
        attrs={'units': 'mm/day', 'long_name': 'potential evapotranspiration'}
    )

# =============================================================================
# SAVE OUTPUT
# =============================================================================
print("\n" + "=" * 80)
print("STEP 5: Saving resampled forcing...")
print("=" * 80)

# Ensure output directory exists
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

# Save with compression
encoding = {}
for var in ds_out.data_vars:
    encoding[var] = {'zlib': True, 'complevel': 4}

ds_out.to_netcdf(OUTPUT_FILE, format='NETCDF4', encoding=encoding)
ds_out.close()

print(f"Saved to: {OUTPUT_FILE}")
print(f"File size: {os.path.getsize(OUTPUT_FILE) / 1e6:.1f} MB")

# =============================================================================
# VERIFICATION
# =============================================================================
print("\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80)

ds_check = xr.open_dataset(OUTPUT_FILE)
print(f"Variables: {list(ds_check.data_vars)}")
print(f"Dimensions: {dict(ds_check.dims)}")
print(f"Lat: {ds_check['lat'].values.min():.4f} to {ds_check['lat'].values.max():.4f}")
print(f"Lon: {ds_check['lon'].values.min():.4f} to {ds_check['lon'].values.max():.4f}")

for var in ['precip', 'temp', 'pet']:
    if var in ds_check:
        data = ds_check[var].values
        nan_count = np.sum(np.isnan(data))
        print(f"{var}: min={np.nanmin(data):.3f}, max={np.nanmax(data):.3f}, NaN={nan_count}")

ds_check.close()

print("\n" + "=" * 80)
print("DONE! Forcing resampled to match staticmaps grid")
print("=" * 80)
