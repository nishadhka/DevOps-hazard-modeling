#!/usr/bin/env python3
"""
Resample forcing data (precipitation, temperature, PET) to match staticmaps grid.

This script takes coarse-resolution forcing data and resamples it to the
finer resolution staticmaps grid using bilinear interpolation.

Input: Raw forcing NetCDF (coarse resolution, e.g., 8x9 grid)
Output: Resampled forcing NetCDF matching staticmaps resolution (245x212 grid)
"""

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================

# Input files
STATICMAPS_FILE = "data/input/staticmaps.nc"  # Target grid
RAW_FORCING_FILE = "forcing_raw.nc"  # Original coarse forcing (adjust path as needed)

# Output file
OUTPUT_FILE = "data/input/forcing.nc"

# Forcing variables to resample
FORCING_VARS = {
    'precip': 'atmosphere_water__precipitation_volume_flux',
    'temp': 'atmosphere_air__temperature',
    'pet': 'land_surface_water__potential_evaporation_volume_flux'
}

# =============================================================================
# LOAD TARGET GRID FROM STATICMAPS
# =============================================================================
print("=" * 80)
print("STEP 1: Loading target grid from staticmaps...")
print("=" * 80)

staticmaps = xr.open_dataset(STATICMAPS_FILE)

# Get target coordinates
target_lat = staticmaps['lat'].values
target_lon = staticmaps['lon'].values

print(f"Target grid size: {len(target_lat)} x {len(target_lon)}")
print(f"Target lat range: {target_lat.min():.4f} to {target_lat.max():.4f}")
print(f"Target lon range: {target_lon.min():.4f} to {target_lon.max():.4f}")

# Get mask from DEM
dem = staticmaps['wflow_dem'].values
mask = ~np.isnan(dem)
print(f"Valid cells: {mask.sum()}")

staticmaps.close()

# =============================================================================
# LOAD RAW FORCING DATA
# =============================================================================
print("\n" + "=" * 80)
print("STEP 2: Loading raw forcing data...")
print("=" * 80)

try:
    forcing_raw = xr.open_dataset(RAW_FORCING_FILE)
except FileNotFoundError:
    print(f"ERROR: Raw forcing file not found: {RAW_FORCING_FILE}")
    print("\nPlease provide the path to your raw forcing data.")
    print("Expected variables: precip, temp, pet (or similar)")
    print("Expected dimensions: time, lat/latitude, lon/longitude")
    exit(1)

# Detect coordinate names
lat_name = 'lat' if 'lat' in forcing_raw.coords else 'latitude'
lon_name = 'lon' if 'lon' in forcing_raw.coords else 'longitude'
time_name = 'time'

source_lat = forcing_raw[lat_name].values
source_lon = forcing_raw[lon_name].values
source_time = forcing_raw[time_name].values

print(f"Source grid size: {len(source_lat)} x {len(source_lon)}")
print(f"Source lat range: {source_lat.min():.4f} to {source_lat.max():.4f}")
print(f"Source lon range: {source_lon.min():.4f} to {source_lon.max():.4f}")
print(f"Time steps: {len(source_time)}")

# Check if source grid covers target grid
if source_lat.min() > target_lat.min() or source_lat.max() < target_lat.max():
    print("WARNING: Source latitude does not fully cover target grid - extrapolation will occur")
if source_lon.min() > target_lon.min() or source_lon.max() < target_lon.max():
    print("WARNING: Source longitude does not fully cover target grid - extrapolation will occur")

# =============================================================================
# DETECT VARIABLE NAMES
# =============================================================================
print("\n" + "=" * 80)
print("STEP 3: Detecting forcing variables...")
print("=" * 80)

# Common variable name patterns
precip_names = ['precip', 'precipitation', 'pr', 'rain', 'rainfall', 'P']
temp_names = ['temp', 'temperature', 'tas', 'tair', 'T', 't2m']
pet_names = ['pet', 'evap', 'evaporation', 'evspsbl', 'ET', 'eto', 'potential_evaporation']

def find_var(ds, possible_names):
    """Find variable matching possible names (case-insensitive)"""
    for var in ds.data_vars:
        for name in possible_names:
            if name.lower() in var.lower():
                return var
    return None

precip_var = find_var(forcing_raw, precip_names)
temp_var = find_var(forcing_raw, temp_names)
pet_var = find_var(forcing_raw, pet_names)

print(f"Precipitation variable: {precip_var}")
print(f"Temperature variable: {temp_var}")
print(f"PET variable: {pet_var}")

if not all([precip_var, temp_var, pet_var]):
    print("\nWARNING: Could not auto-detect all variables.")
    print(f"Available variables: {list(forcing_raw.data_vars)}")

# =============================================================================
# RESAMPLE EACH VARIABLE
# =============================================================================
print("\n" + "=" * 80)
print("STEP 4: Resampling forcing data to target grid...")
print("=" * 80)

def resample_variable(data_3d, source_lat, source_lon, target_lat, target_lon):
    """
    Resample 3D data (time, lat, lon) from source to target grid.
    Uses bilinear interpolation with bounds_error=False for extrapolation.
    """
    nt = data_3d.shape[0]
    ny_target = len(target_lat)
    nx_target = len(target_lon)

    resampled = np.zeros((nt, ny_target, nx_target), dtype=np.float32)

    # Ensure latitude is in ascending order for interpolator
    if source_lat[0] > source_lat[-1]:
        source_lat_sorted = source_lat[::-1]
        data_sorted = data_3d[:, ::-1, :]
    else:
        source_lat_sorted = source_lat
        data_sorted = data_3d

    # Create target grid
    target_lon_grid, target_lat_grid = np.meshgrid(target_lon, target_lat)
    target_points = np.column_stack([target_lat_grid.ravel(), target_lon_grid.ravel()])

    # Resample each timestep
    for t in range(nt):
        if t % 100 == 0:
            print(f"  Processing timestep {t+1}/{nt}...")

        # Create interpolator for this timestep
        interpolator = RegularGridInterpolator(
            (source_lat_sorted, source_lon),
            data_sorted[t],
            method='linear',
            bounds_error=False,
            fill_value=None  # Extrapolate
        )

        # Interpolate to target grid
        resampled[t] = interpolator(target_points).reshape(ny_target, nx_target)

    return resampled

# Dictionary to store resampled data
resampled_data = {}

# Resample precipitation
if precip_var:
    print(f"\nResampling {precip_var}...")
    precip_data = forcing_raw[precip_var].values
    if precip_data.ndim == 3:
        resampled_data['precip'] = resample_variable(
            precip_data, source_lat, source_lon, target_lat, target_lon
        )
    print(f"  Done. Shape: {resampled_data['precip'].shape}")
    print(f"  Range: {np.nanmin(resampled_data['precip']):.3f} to {np.nanmax(resampled_data['precip']):.3f}")

# Resample temperature
if temp_var:
    print(f"\nResampling {temp_var}...")
    temp_data = forcing_raw[temp_var].values
    if temp_data.ndim == 3:
        resampled_data['temp'] = resample_variable(
            temp_data, source_lat, source_lon, target_lat, target_lon
        )
    print(f"  Done. Shape: {resampled_data['temp'].shape}")
    print(f"  Range: {np.nanmin(resampled_data['temp']):.3f} to {np.nanmax(resampled_data['temp']):.3f}")

# Resample PET
if pet_var:
    print(f"\nResampling {pet_var}...")
    pet_data = forcing_raw[pet_var].values
    if pet_data.ndim == 3:
        resampled_data['pet'] = resample_variable(
            pet_data, source_lat, source_lon, target_lat, target_lon
        )
    print(f"  Done. Shape: {resampled_data['pet'].shape}")
    print(f"  Range: {np.nanmin(resampled_data['pet']):.3f} to {np.nanmax(resampled_data['pet']):.3f}")

# =============================================================================
# APPLY MASK
# =============================================================================
print("\n" + "=" * 80)
print("STEP 5: Applying domain mask...")
print("=" * 80)

for var_name, data in resampled_data.items():
    for t in range(data.shape[0]):
        data[t][~mask] = np.nan
    print(f"  {var_name}: masked {(~mask).sum()} cells per timestep")

# =============================================================================
# CREATE OUTPUT DATASET
# =============================================================================
print("\n" + "=" * 80)
print("STEP 6: Creating output NetCDF...")
print("=" * 80)

# Create output dataset
ds_out = xr.Dataset(
    coords={
        'time': (['time'], source_time),
        'lat': (['lat'], target_lat, {'units': 'degrees_north', 'axis': 'Y'}),
        'lon': (['lon'], target_lon, {'units': 'degrees_east', 'axis': 'X'}),
    }
)

# Add variables with Wflow-compatible names
if 'precip' in resampled_data:
    ds_out['precip'] = xr.DataArray(
        resampled_data['precip'],
        dims=['time', 'lat', 'lon'],
        attrs={
            'units': 'mm/day',
            'long_name': 'precipitation',
            'standard_name': 'precipitation_flux'
        }
    )

if 'temp' in resampled_data:
    ds_out['temp'] = xr.DataArray(
        resampled_data['temp'],
        dims=['time', 'lat', 'lon'],
        attrs={
            'units': 'degC',
            'long_name': 'air temperature',
            'standard_name': 'air_temperature'
        }
    )

if 'pet' in resampled_data:
    ds_out['pet'] = xr.DataArray(
        resampled_data['pet'],
        dims=['time', 'lat', 'lon'],
        attrs={
            'units': 'mm/day',
            'long_name': 'potential evapotranspiration',
            'standard_name': 'water_potential_evaporation_flux'
        }
    )

# Add spatial reference
ds_out['spatial_ref'] = xr.DataArray(0, attrs={
    'crs_wkt': 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
    'spatial_ref': 'EPSG:4326',
})

# Add global attributes
ds_out.attrs['title'] = 'Wflow forcing data for Burundi'
ds_out.attrs['institution'] = 'Resampled from coarse resolution data'
ds_out.attrs['source'] = f'Resampled from {RAW_FORCING_FILE}'
ds_out.attrs['history'] = 'Created by resample_forcing.py'

# =============================================================================
# SAVE OUTPUT
# =============================================================================
print("\n" + "=" * 80)
print("STEP 7: Saving to NetCDF...")
print("=" * 80)

# Use compression for smaller file size
encoding = {}
for var in ds_out.data_vars:
    if var != 'spatial_ref':
        encoding[var] = {'zlib': True, 'complevel': 4}

ds_out.to_netcdf(OUTPUT_FILE, format='NETCDF4', encoding=encoding)

import os
file_size = os.path.getsize(OUTPUT_FILE) / 1e6

print(f"\nSaved to: {OUTPUT_FILE}")
print(f"File size: {file_size:.1f} MB")
print(f"Variables: {list(ds_out.data_vars)}")
print(f"Dimensions: time={len(source_time)}, lat={len(target_lat)}, lon={len(target_lon)}")

# =============================================================================
# VERIFICATION
# =============================================================================
print("\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80)

# Reload and verify
ds_check = xr.open_dataset(OUTPUT_FILE)
print(f"\nOutput file contents:")
print(f"  Variables: {list(ds_check.data_vars)}")
print(f"  Time range: {ds_check.time.values[0]} to {ds_check.time.values[-1]}")
print(f"  Grid size: {len(ds_check.lat)} x {len(ds_check.lon)}")

for var in ['precip', 'temp', 'pet']:
    if var in ds_check:
        data = ds_check[var].values
        print(f"  {var}: min={np.nanmin(data):.3f}, max={np.nanmax(data):.3f}, mean={np.nanmean(data):.3f}")

ds_check.close()
forcing_raw.close()

print("\n" + "=" * 80)
print("DONE! Forcing data resampled successfully")
print("=" * 80)
