#!/usr/bin/env python3
"""
Resample forcing incrementally - one day at a time.
This approach uses minimal memory by writing each timestep immediately.
"""

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator
from netCDF4 import Dataset
import os
import gc

BASE_DIR = "/data/bdi_trail2/dr_case4"
FORCING_SUBSET = os.path.join(BASE_DIR, "data/input/forcing_subset.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_FILE = os.path.join(BASE_DIR, "data/input/forcing.nc")

print("=" * 70)
print("Ethiopia Forcing - Incremental Resampling")
print("=" * 70)

# Load target grid
print("\n1. Loading target grid...")
with xr.open_dataset(STATICMAPS_FILE) as ds_static:
    target_lat = ds_static['lat'].values.astype(np.float64)
    target_lon = ds_static['lon'].values.astype(np.float64)
target_ny, target_nx = len(target_lat), len(target_lon)
print(f"   Target: {target_ny} x {target_nx}")

# Load source metadata
print("\n2. Loading source metadata...")
ds_source = xr.open_dataset(FORCING_SUBSET)
source_lat = ds_source['lat'].values.astype(np.float64)
source_lon = ds_source['lon'].values.astype(np.float64)
source_time = ds_source['time'].values
nt = len(source_time)
print(f"   Source: {len(source_lat)} x {len(source_lon)}, {nt} timesteps")

# Check if lat needs reversing
if source_lat[0] > source_lat[-1]:
    source_lat_sorted = source_lat[::-1]
    lat_reversed = True
else:
    source_lat_sorted = source_lat
    lat_reversed = False
print(f"   Lat reversed: {lat_reversed}")

# Create target points mesh (do once)
target_lon_mesh, target_lat_mesh = np.meshgrid(target_lon, target_lat)
target_points = np.column_stack([target_lat_mesh.ravel(), target_lon_mesh.ravel()])
del target_lon_mesh, target_lat_mesh
gc.collect()

# Create output NetCDF with netCDF4 directly for unlimited time dimension
print("\n3. Creating output file...")
if os.path.exists(OUTPUT_FILE):
    os.remove(OUTPUT_FILE)

nc_out = Dataset(OUTPUT_FILE, 'w', format='NETCDF4')

# Create dimensions
nc_out.createDimension('time', None)  # Unlimited
nc_out.createDimension('lat', target_ny)
nc_out.createDimension('lon', target_nx)

# Create coordinate variables
time_var = nc_out.createVariable('time', 'f8', ('time',))
time_var.units = 'days since 2020-01-01'
time_var.calendar = 'standard'

lat_var = nc_out.createVariable('lat', 'f8', ('lat',))
lat_var.units = 'degrees_north'
lat_var[:] = target_lat

lon_var = nc_out.createVariable('lon', 'f8', ('lon',))
lon_var.units = 'degrees_east'
lon_var[:] = target_lon

# Create data variables with compression
precip_var = nc_out.createVariable('precip', 'f4', ('time', 'lat', 'lon'),
                                    zlib=True, complevel=4, chunksizes=(1, target_ny, target_nx))
precip_var.units = 'mm/day'

temp_var = nc_out.createVariable('temp', 'f4', ('time', 'lat', 'lon'),
                                  zlib=True, complevel=4, chunksizes=(1, target_ny, target_nx))
temp_var.units = 'degrees_C'

pet_var = nc_out.createVariable('pet', 'f4', ('time', 'lat', 'lon'),
                                 zlib=True, complevel=4, chunksizes=(1, target_ny, target_nx))
pet_var.units = 'mm/day'

# Process one timestep at a time
print("\n4. Resampling timesteps...")
vars_map = {'precip': precip_var, 'temp': temp_var, 'pet': pet_var}

for t in range(nt):
    if t % 50 == 0:
        print(f"   Processing timestep {t+1}/{nt}...")

    # Store time
    time_var[t] = t  # Days since 2020-01-01

    for var_name in ['precip', 'temp', 'pet']:
        # Load single timestep
        data_t = ds_source[var_name].isel(time=t).values

        if lat_reversed:
            data_t = data_t[::-1, :]

        # Fill NaN for interpolation
        if var_name == 'precip':
            fill_val = 0.0
        else:
            fill_val = float(np.nanmean(data_t)) if not np.all(np.isnan(data_t)) else 20.0
        data_filled = np.where(np.isnan(data_t), fill_val, data_t)

        # Interpolate
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
            print(f"      Error at t={t}, var={var_name}: {e}")
            resampled = np.full((target_ny, target_nx), fill_val, dtype=np.float32)

        # Write to file
        vars_map[var_name][t, :, :] = resampled

    # Flush periodically and clean up
    if t % 100 == 0:
        nc_out.sync()
        gc.collect()

# Close files
nc_out.close()
ds_source.close()

# Report
size_gb = os.path.getsize(OUTPUT_FILE) / 1e9
print(f"\n5. Saved: {OUTPUT_FILE}")
print(f"   Size: {size_gb:.2f} GB")

# Verify
print("\n6. Verification:")
with xr.open_dataset(OUTPUT_FILE) as ds_check:
    print(f"   Grid: {len(ds_check.lat)} x {len(ds_check.lon)}")
    print(f"   Time: {len(ds_check.time)} steps")
    for var in ['precip', 'temp', 'pet']:
        v = ds_check[var].isel(time=0).values
        nan_pct = np.sum(np.isnan(v)) / v.size * 100
        print(f"   {var}: min={np.nanmin(v):.3f}, max={np.nanmax(v):.3f}, NaN={nan_pct:.1f}%")

print("\n" + "=" * 70)
print("DONE!")
print("=" * 70)
