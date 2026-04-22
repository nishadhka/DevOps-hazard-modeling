#!/usr/bin/env python3
"""
Resample Kenya forcing using streaming approach.
"""

from netCDF4 import Dataset
import numpy as np
from scipy.interpolate import RegularGridInterpolator
import xarray as xr
import os
import gc

BASE_DIR = "/data/bdi_trail2/dr_case5"
FORCING_SUBSET = os.path.join(BASE_DIR, "data/input/forcing_subset.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_FILE = os.path.join(BASE_DIR, "data/input/forcing.nc")

print("=" * 70)
print("Kenya Forcing Resampling")
print("=" * 70)

# Load target grid
print("\n1. Loading target grid...")
with xr.open_dataset(STATICMAPS_FILE) as ds:
    target_lat = ds['lat'].values.astype(np.float64)
    target_lon = ds['lon'].values.astype(np.float64)
target_ny, target_nx = len(target_lat), len(target_lon)
print(f"   Target: {target_ny} x {target_nx}")

# Load source metadata
print("\n2. Loading source forcing...")
ds_source = xr.open_dataset(FORCING_SUBSET)
source_lat = ds_source['lat'].values.astype(np.float64)
source_lon = ds_source['lon'].values.astype(np.float64)
source_time = ds_source['time'].values
nt = len(source_time)
print(f"   Source: {len(source_lat)} x {len(source_lon)}, {nt} timesteps")

# Check lat order
if source_lat[0] > source_lat[-1]:
    source_lat_sorted = source_lat[::-1]
    lat_reversed = True
else:
    source_lat_sorted = source_lat
    lat_reversed = False

# Create target points
target_lon_mesh, target_lat_mesh = np.meshgrid(target_lon, target_lat)
target_points = np.column_stack([target_lat_mesh.ravel(), target_lon_mesh.ravel()])
del target_lon_mesh, target_lat_mesh
gc.collect()

# Create output file
print("\n3. Creating output file...")
if os.path.exists(OUTPUT_FILE):
    os.remove(OUTPUT_FILE)

nc_out = Dataset(OUTPUT_FILE, 'w', format='NETCDF4')
nc_out.createDimension('time', None)
nc_out.createDimension('lat', target_ny)
nc_out.createDimension('lon', target_nx)

time_var = nc_out.createVariable('time', 'f8', ('time',))
time_var.units = 'days since 2020-01-01'
time_var[:] = np.arange(nt)

lat_var = nc_out.createVariable('lat', 'f8', ('lat',))
lat_var.units = 'degrees_north'
lat_var[:] = target_lat

lon_var = nc_out.createVariable('lon', 'f8', ('lon',))
lon_var.units = 'degrees_east'
lon_var[:] = target_lon

precip_var = nc_out.createVariable('precip', 'f4', ('time', 'lat', 'lon'),
                                    zlib=True, complevel=4)
precip_var.units = 'mm/day'

temp_var = nc_out.createVariable('temp', 'f4', ('time', 'lat', 'lon'),
                                  zlib=True, complevel=4)
temp_var.units = 'degrees_C'

pet_var = nc_out.createVariable('pet', 'f4', ('time', 'lat', 'lon'),
                                 zlib=True, complevel=4)
pet_var.units = 'mm/day'

# Process timesteps
print("\n4. Resampling...")
vars_map = {'precip': precip_var, 'temp': temp_var, 'pet': pet_var}

for t in range(nt):
    if t % 100 == 0:
        print(f"   Timestep {t+1}/{nt}...")

    for var_name in ['precip', 'temp', 'pet']:
        data_t = ds_source[var_name].isel(time=t).values
        if lat_reversed:
            data_t = data_t[::-1, :]

        fill_val = 0.0 if var_name == 'precip' else float(np.nanmean(data_t)) if not np.all(np.isnan(data_t)) else 20.0
        data_filled = np.where(np.isnan(data_t), fill_val, data_t)

        # Fix any -9999 values
        data_filled = np.where(data_filled < -9000, fill_val, data_filled)
        if var_name in ['precip', 'pet']:
            data_filled = np.where(data_filled < 0, 0, data_filled)

        try:
            interp = RegularGridInterpolator(
                (source_lat_sorted, source_lon),
                data_filled,
                method='nearest',
                bounds_error=False,
                fill_value=fill_val
            )
            resampled = interp(target_points).reshape(target_ny, target_nx).astype(np.float32)
        except:
            resampled = np.full((target_ny, target_nx), fill_val, dtype=np.float32)

        vars_map[var_name][t, :, :] = resampled

    if t % 200 == 0:
        nc_out.sync()
        gc.collect()

nc_out.close()
ds_source.close()

size_mb = os.path.getsize(OUTPUT_FILE) / 1e6
print(f"\n5. Saved: {OUTPUT_FILE}")
print(f"   Size: {size_mb:.1f} MB")

# Verify
print("\n6. Verification:")
with xr.open_dataset(OUTPUT_FILE) as ds:
    print(f"   Grid: {len(ds.lat)} x {len(ds.lon)}")
    print(f"   Time: {len(ds.time)} steps")
    for var in ['precip', 'temp', 'pet']:
        v = ds[var].isel(time=0).values
        print(f"   {var}: min={np.nanmin(v):.3f}, max={np.nanmax(v):.3f}")

print("\nDONE!")
