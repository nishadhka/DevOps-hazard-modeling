#!/usr/bin/env python3
"""
Resample Tanzania forcing data to match staticmaps grid.

The forcing data covers a larger extent and different resolution than the
staticmaps grid. This script:
1. Subsets forcing to Tanzania extent
2. Resamples to match staticmaps grid (1198 x 1248)
3. Fills any NaN values
4. Saves to output file with proper time coordinates

Uses streaming approach to manage memory for large datasets.
"""

from netCDF4 import Dataset
import numpy as np
from scipy.interpolate import RegularGridInterpolator
import xarray as xr
import os
import gc
import pandas as pd

# =============================================================================
# CONFIGURATION
# =============================================================================
BASE_DIR = "/data/bdi_trail2/dr_case10"
FORCING_RAW = os.path.join(BASE_DIR, "forcing/forcing.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_FILE = os.path.join(BASE_DIR, "data/input/forcing.nc")

print("=" * 70)
print("Tanzania Forcing Resampling")
print("=" * 70)

# =============================================================================
# LOAD TARGET GRID FROM STATICMAPS
# =============================================================================
print("\n1. Loading target grid from staticmaps...")
with xr.open_dataset(STATICMAPS_FILE) as ds:
    target_lat = ds['lat'].values.astype(np.float64)
    target_lon = ds['lon'].values.astype(np.float64)

target_ny, target_nx = len(target_lat), len(target_lon)
print(f"   Target grid: {target_ny} x {target_nx}")
print(f"   Target lat: {target_lat.min():.4f} to {target_lat.max():.4f}")
print(f"   Target lon: {target_lon.min():.4f} to {target_lon.max():.4f}")

# =============================================================================
# LOAD SOURCE FORCING
# =============================================================================
print("\n2. Loading source forcing data...")
ds_source = xr.open_dataset(FORCING_RAW)
source_lat = ds_source['lat'].values.astype(np.float64)
source_lon = ds_source['lon'].values.astype(np.float64)
source_time = ds_source['time'].values
nt = len(source_time)

print(f"   Source grid: {len(source_lat)} x {len(source_lon)}")
print(f"   Source lat: {source_lat.min():.4f} to {source_lat.max():.4f}")
print(f"   Source lon: {source_lon.min():.4f} to {source_lon.max():.4f}")
print(f"   Time steps: {nt}")
print(f"   Variables: {list(ds_source.data_vars)}")

# =============================================================================
# PREPARE FOR INTERPOLATION
# =============================================================================
print("\n3. Preparing for interpolation...")

# Check lat order - scipy needs ascending order
if source_lat[0] > source_lat[-1]:
    source_lat_sorted = source_lat[::-1]
    lat_reversed = True
    print("   Source latitude reversed (descending -> ascending)")
else:
    source_lat_sorted = source_lat
    lat_reversed = False

# Create target points grid
target_lon_mesh, target_lat_mesh = np.meshgrid(target_lon, target_lat)
target_points = np.column_stack([target_lat_mesh.ravel(), target_lon_mesh.ravel()])
del target_lon_mesh, target_lat_mesh
gc.collect()

print(f"   Target points: {len(target_points):,}")

# =============================================================================
# CREATE OUTPUT FILE
# =============================================================================
print("\n4. Creating output NetCDF file...")
if os.path.exists(OUTPUT_FILE):
    os.remove(OUTPUT_FILE)

nc_out = Dataset(OUTPUT_FILE, 'w', format='NETCDF4')
nc_out.createDimension('time', None)  # Unlimited for appending
nc_out.createDimension('lat', target_ny)
nc_out.createDimension('lon', target_nx)

# Time coordinate - use days since start
start_date = pd.Timestamp(source_time[0])
time_var = nc_out.createVariable('time', 'f8', ('time',))
time_var.units = f'days since {start_date.strftime("%Y-%m-%d")}'
time_var.calendar = 'standard'
time_var[:] = np.arange(nt)

# Lat/lon coordinates
lat_var = nc_out.createVariable('lat', 'f8', ('lat',))
lat_var.units = 'degrees_north'
lat_var.axis = 'Y'
lat_var[:] = target_lat

lon_var = nc_out.createVariable('lon', 'f8', ('lon',))
lon_var.units = 'degrees_east'
lon_var.axis = 'X'
lon_var[:] = target_lon

# Data variables with compression
precip_var = nc_out.createVariable('precip', 'f4', ('time', 'lat', 'lon'),
                                    zlib=True, complevel=4)
precip_var.units = 'mm/day'
precip_var.long_name = 'precipitation'

temp_var = nc_out.createVariable('temp', 'f4', ('time', 'lat', 'lon'),
                                  zlib=True, complevel=4)
temp_var.units = 'degrees_C'
temp_var.long_name = 'temperature'

pet_var = nc_out.createVariable('pet', 'f4', ('time', 'lat', 'lon'),
                                 zlib=True, complevel=4)
pet_var.units = 'mm/day'
pet_var.long_name = 'potential evapotranspiration'

# =============================================================================
# RESAMPLE EACH TIMESTEP
# =============================================================================
print("\n5. Resampling timesteps (this may take a while)...")
vars_map = {'precip': precip_var, 'temp': temp_var, 'pet': pet_var}

# Default fill values for each variable
fill_defaults = {
    'precip': 0.0,
    'temp': 25.0,  # Reasonable default for Tanzania
    'pet': 3.0     # Typical PET for tropical region
}

for t in range(nt):
    if t % 50 == 0:
        print(f"   Processing timestep {t+1}/{nt}...")

    for var_name in ['precip', 'temp', 'pet']:
        # Get data for this timestep
        data_t = ds_source[var_name].isel(time=t).values

        # Reverse latitude if needed
        if lat_reversed:
            data_t = data_t[::-1, :]

        # Determine fill value
        valid_data = data_t[~np.isnan(data_t) & (data_t > -9000)]
        if len(valid_data) > 0:
            fill_val = float(np.mean(valid_data))
        else:
            fill_val = fill_defaults[var_name]

        # Fill NaN and bad values
        data_filled = np.where(np.isnan(data_t), fill_val, data_t)
        data_filled = np.where(data_filled < -9000, fill_val, data_filled)

        # Ensure non-negative for precip and PET
        if var_name in ['precip', 'pet']:
            data_filled = np.where(data_filled < 0, 0, data_filled)

        # Interpolate using nearest neighbor (more robust for edge handling)
        try:
            interp = RegularGridInterpolator(
                (source_lat_sorted, source_lon),
                data_filled,
                method='nearest',
                bounds_error=False,
                fill_value=fill_val
            )
            resampled = interp(target_points).reshape(target_ny, target_nx).astype(np.float32)
        except Exception as e:
            print(f"   Warning: Interpolation failed for {var_name} at t={t}: {e}")
            resampled = np.full((target_ny, target_nx), fill_val, dtype=np.float32)

        # Final NaN check
        nan_count = np.isnan(resampled).sum()
        if nan_count > 0:
            resampled = np.where(np.isnan(resampled), fill_val, resampled)

        vars_map[var_name][t, :, :] = resampled

    # Sync and free memory periodically
    if t % 100 == 0:
        nc_out.sync()
        gc.collect()

# Close files
nc_out.close()
ds_source.close()

# =============================================================================
# REPORT RESULTS
# =============================================================================
size_mb = os.path.getsize(OUTPUT_FILE) / 1e6
print(f"\n6. Saved: {OUTPUT_FILE}")
print(f"   Size: {size_mb:.1f} MB")

# =============================================================================
# VERIFICATION
# =============================================================================
print("\n7. Verification:")
with xr.open_dataset(OUTPUT_FILE) as ds:
    print(f"   Grid: {len(ds.lat)} x {len(ds.lon)}")
    print(f"   Time: {len(ds.time)} steps")
    print(f"   Time range: {str(ds.time.values[0])[:10]} to {str(ds.time.values[-1])[:10]}")

    for var in ['precip', 'temp', 'pet']:
        v = ds[var].values
        nan_pct = 100 * np.isnan(v).sum() / v.size
        print(f"   {var}:")
        print(f"      Range: {np.nanmin(v):.3f} to {np.nanmax(v):.3f}")
        print(f"      Mean: {np.nanmean(v):.3f}")
        print(f"      NaN: {nan_pct:.2f}%")

print("\n" + "=" * 70)
print("DONE! Forcing resampled successfully")
print("=" * 70)
