#!/usr/bin/env python3
"""
Resample forcing data to match staticmaps grid resolution for Uganda.

The forcing data is at coarse resolution (56 x 42 grid)
The staticmaps are at 1km resolution (313 x 235 grid)
This script resamples forcing to match staticmaps using interpolation.

Uses nearest neighbor interpolation with NaN filling for robustness.

Region: Uganda (dr_case11)
"""

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
import warnings
import os
import time
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================

FORCING_FILE = "forcing/forcing.nc"
STATICMAPS_FILE = "data/input/staticmaps.nc"
OUTPUT_FILE = "data/input/forcing.nc"
N_THREADS = 4

start_time = time.time()

# =============================================================================
# LOAD DATA
# =============================================================================
print("=" * 80)
print("STEP 1: Loading forcing and staticmaps data...")
print("=" * 80)

# Load forcing
ds_forcing = xr.open_dataset(FORCING_FILE)
print(f"Forcing file: {FORCING_FILE}")
print(f"Forcing dimensions: {dict(ds_forcing.dims)}")
print(f"Forcing variables: {list(ds_forcing.data_vars)}")

# Load staticmaps for target grid
ds_static = xr.open_dataset(STATICMAPS_FILE)
target_lat = ds_static['lat'].values
target_lon = ds_static['lon'].values
ds_static.close()

print(f"\nTarget grid from staticmaps: {len(target_lat)} x {len(target_lon)}")
print(f"Target lat range: {target_lat.min():.4f} to {target_lat.max():.4f}")
print(f"Target lon range: {target_lon.min():.4f} to {target_lon.max():.4f}")

# Source grid
source_lat = ds_forcing['lat'].values
source_lon = ds_forcing['lon'].values
time_vals = ds_forcing['time'].values

print(f"\nSource grid: {len(source_lat)} x {len(source_lon)}")
print(f"Source lat range: {source_lat.min():.4f} to {source_lat.max():.4f}")
print(f"Source lon range: {source_lon.min():.4f} to {source_lon.max():.4f}")

# Check if lat is ascending or descending
source_lat_ascending = source_lat[0] < source_lat[-1]
target_lat_ascending = target_lat[0] < target_lat[-1]
print(f"\nSource lat ascending: {source_lat_ascending}")
print(f"Target lat ascending: {target_lat_ascending}")

# =============================================================================
# PREPARE INTERPOLATION
# =============================================================================
print("\n" + "=" * 80)
print("STEP 2: Setting up interpolation...")
print("=" * 80)

# Ensure source latitude is ascending for interpolator
if not source_lat_ascending:
    source_lat_sorted = source_lat[::-1]
    lat_reversed = True
else:
    source_lat_sorted = source_lat
    lat_reversed = False

# Ensure source longitude is ascending
source_lon_sorted = source_lon
lon_reversed = False
if source_lon[0] > source_lon[-1]:
    source_lon_sorted = source_lon[::-1]
    lon_reversed = True

print(f"Lat reversed: {lat_reversed}")
print(f"Lon reversed: {lon_reversed}")

# Create target grid points
target_points = np.array(np.meshgrid(target_lat, target_lon, indexing='ij')).T.reshape(-1, 2)
print(f"Total target points: {len(target_points):,}")

# =============================================================================
# RESAMPLE EACH VARIABLE
# =============================================================================
print("\n" + "=" * 80)
print(f"STEP 3: Resampling forcing variables ({N_THREADS} threads)...")
print("=" * 80)

variables = ['precip', 'temp', 'pet']
resampled_data = {}

def resample_timestep(args):
    """Resample a single timestep using nearest neighbor."""
    var_name, t, data_2d = args

    # Reverse axes if needed to match sorted coordinates
    if lat_reversed:
        data_2d = data_2d[::-1, :]
    if lon_reversed:
        data_2d = data_2d[:, ::-1]

    # Handle NaN values - fill with mean for interpolation
    data_filled = data_2d.copy()
    nan_mask = np.isnan(data_filled)
    if nan_mask.any():
        valid_mean = np.nanmean(data_filled)
        if np.isnan(valid_mean):
            valid_mean = 0.0  # Fallback
        data_filled[nan_mask] = valid_mean

    # Create interpolator with nearest neighbor for robustness
    interp = RegularGridInterpolator(
        (source_lat_sorted, source_lon_sorted),
        data_filled,
        method='nearest',
        bounds_error=False,
        fill_value=None  # Extrapolate
    )

    # Interpolate to target grid
    resampled = interp(target_points).reshape(len(target_lat), len(target_lon))

    # Fill any remaining NaN with mean
    nan_mask_out = np.isnan(resampled)
    if nan_mask_out.any():
        valid_mean = np.nanmean(resampled)
        if np.isnan(valid_mean):
            valid_mean = 0.0
        resampled[nan_mask_out] = valid_mean

    return t, resampled

for var in variables:
    print(f"\nProcessing {var}...")

    var_data = ds_forcing[var].values
    nt = var_data.shape[0]
    print(f"  Shape: {var_data.shape}")
    print(f"  Input range: {np.nanmin(var_data):.3f} to {np.nanmax(var_data):.3f}")
    print(f"  Input NaN %: {100*np.isnan(var_data).sum()/var_data.size:.1f}%")

    # Prepare arguments for parallel processing
    args_list = [(var, t, var_data[t]) for t in range(nt)]

    # Process in parallel
    resampled_var = np.zeros((nt, len(target_lat), len(target_lon)), dtype=np.float32)

    with ThreadPoolExecutor(max_workers=N_THREADS) as executor:
        results = list(executor.map(resample_timestep, args_list))
        for t, data in results:
            resampled_var[t] = data

    print(f"  Output shape: {resampled_var.shape}")
    print(f"  Output range: {np.nanmin(resampled_var):.3f} to {np.nanmax(resampled_var):.3f}")
    print(f"  Output NaN %: {100*np.isnan(resampled_var).sum()/resampled_var.size:.1f}%")

    resampled_data[var] = resampled_var

# =============================================================================
# CREATE OUTPUT DATASET
# =============================================================================
print("\n" + "=" * 80)
print("STEP 4: Creating output NetCDF file...")
print("=" * 80)

ds_out = xr.Dataset(
    coords={
        'time': (['time'], time_vals),
        'lat': (['lat'], target_lat, {'units': 'degrees_north', 'axis': 'Y'}),
        'lon': (['lon'], target_lon, {'units': 'degrees_east', 'axis': 'X'}),
    }
)

# Add variables with appropriate attributes
ds_out['precip'] = xr.DataArray(
    resampled_data['precip'],
    dims=['time', 'lat', 'lon'],
    attrs={'units': 'mm/day', 'long_name': 'precipitation'}
)

ds_out['temp'] = xr.DataArray(
    resampled_data['temp'],
    dims=['time', 'lat', 'lon'],
    attrs={'units': 'degC', 'long_name': 'temperature'}
)

ds_out['pet'] = xr.DataArray(
    resampled_data['pet'],
    dims=['time', 'lat', 'lon'],
    attrs={'units': 'mm/day', 'long_name': 'potential evapotranspiration'}
)

# Add spatial reference
ds_out['spatial_ref'] = xr.DataArray(0, attrs={
    'crs_wkt': 'GEOGCS["WGS 84"]',
    'spatial_ref': 'EPSG:4326',
})

# Global attributes
ds_out.attrs['title'] = 'Resampled forcing data for Uganda Wflow simulation'
ds_out.attrs['source'] = f'Resampled from {FORCING_FILE}'
ds_out.attrs['history'] = f'Created by resample_forcing.py on {time.strftime("%Y-%m-%d %H:%M:%S")}'

# =============================================================================
# SAVE OUTPUT
# =============================================================================
print("\n" + "=" * 80)
print("STEP 5: Saving resampled forcing...")
print("=" * 80)

# Create backup of original if it exists
if os.path.exists(OUTPUT_FILE):
    backup_file = OUTPUT_FILE.replace('.nc', '_original.nc')
    if not os.path.exists(backup_file):
        os.rename(OUTPUT_FILE, backup_file)
        print(f"Original forcing backed up to: {backup_file}")

ds_out.to_netcdf(OUTPUT_FILE, format='NETCDF4')

ds_forcing.close()
ds_out.close()

elapsed_time = time.time() - start_time
file_size_mb = os.path.getsize(OUTPUT_FILE) / 1e6

print(f"\nSaved to: {OUTPUT_FILE}")
print(f"File size: {file_size_mb:.1f} MB")
print(f"Processing time: {elapsed_time:.1f} seconds")

# =============================================================================
# VERIFICATION
# =============================================================================
print("\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80)

ds_check = xr.open_dataset(OUTPUT_FILE)
print(f"\nOutput dimensions: {dict(ds_check.dims)}")
print(f"Time range: {ds_check.time.values[0]} to {ds_check.time.values[-1]}")

for var in ['precip', 'temp', 'pet']:
    data = ds_check[var].values
    print(f"\n{var}:")
    print(f"  Shape: {data.shape}")
    print(f"  Range: {np.nanmin(data):.3f} to {np.nanmax(data):.3f}")
    print(f"  Mean: {np.nanmean(data):.3f}")
    print(f"  NaN count: {np.isnan(data).sum()}")

ds_check.close()

print("\n" + "=" * 80)
print("DONE! Forcing resampled to match staticmaps grid")
print("=" * 80)
