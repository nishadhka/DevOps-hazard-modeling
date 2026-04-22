#!/usr/bin/env python3
"""
Resample forcing year by year to manage memory.
"""

import numpy as np
import xarray as xr
import os
import gc
from scipy.interpolate import RegularGridInterpolator

BASE_DIR = "/data/bdi_trail2/dr_case4"
FORCING_SUBSET = os.path.join(BASE_DIR, "data/input/forcing_subset.nc")
STATICMAPS_FILE = os.path.join(BASE_DIR, "data/input/staticmaps.nc")
OUTPUT_DIR = os.path.join(BASE_DIR, "data/input")

print("=" * 70)
print("Ethiopia Forcing Resampling - Year by Year")
print("=" * 70)

# Get target grid from staticmaps
print("\n1. Loading target grid...")
ds_static = xr.open_dataset(STATICMAPS_FILE)
target_lat = ds_static['lat'].values.astype(np.float64)
target_lon = ds_static['lon'].values.astype(np.float64)
target_ny, target_nx = len(target_lat), len(target_lon)
print(f"   Target: {target_ny} x {target_nx}")
ds_static.close()

# Load source metadata
print("\n2. Loading source forcing metadata...")
ds_force = xr.open_dataset(FORCING_SUBSET)
source_lat = ds_force['lat'].values.astype(np.float64)
source_lon = ds_force['lon'].values.astype(np.float64)
source_time = ds_force['time'].values

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

# Get years
time_pd = xr.DataArray(source_time).to_pandas()
years = sorted(set(time_pd.dt.year.values))
print(f"   Years: {years}")

# Process year by year
yearly_files = []
for year in years:
    print(f"\n{'='*70}")
    print(f"Processing Year {year}")
    print('='*70)

    # Select year
    ds_year = ds_force.sel(time=str(year))
    year_time = ds_year['time'].values
    nt = len(year_time)
    print(f"   Timesteps: {nt}")

    # Resample each variable
    resampled_data = {}
    for var in ['precip', 'temp', 'pet']:
        if var not in ds_year:
            continue

        print(f"   Resampling {var}...")
        var_data = ds_year[var].values
        resampled = np.zeros((nt, target_ny, target_nx), dtype=np.float32)

        for t in range(nt):
            if t % 50 == 0:
                print(f"      t={t}/{nt}")
            data_t = var_data[t]
            if lat_reversed:
                data_t = data_t[::-1, :]
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
            except:
                resampled[t] = 0.0

        # Fill NaN
        if var == 'precip':
            fill_val = 0.0
        else:
            fill_val = float(np.nanmean(resampled)) if not np.all(np.isnan(resampled)) else 20.0
        resampled = np.where(np.isnan(resampled), fill_val, resampled)
        print(f"      Range: {np.min(resampled):.2f} to {np.max(resampled):.2f}")
        resampled_data[var] = resampled
        gc.collect()

    # Save year file
    ds_out = xr.Dataset(
        coords={
            'time': (['time'], year_time),
            'lat': (['lat'], target_lat),
            'lon': (['lon'], target_lon),
        }
    )
    for var, data in resampled_data.items():
        ds_out[var] = xr.DataArray(data, dims=['time', 'lat', 'lon'])

    year_file = os.path.join(OUTPUT_DIR, f"forcing_{year}.nc")
    encoding = {var: {'zlib': True, 'complevel': 5} for var in resampled_data.keys()}
    ds_out.to_netcdf(year_file, encoding=encoding)
    yearly_files.append(year_file)
    print(f"   Saved: {year_file} ({os.path.getsize(year_file)/1e6:.1f} MB)")

    del ds_year, resampled_data, ds_out
    gc.collect()

ds_force.close()

# Combine years
print("\n" + "="*70)
print("Combining yearly files...")
print("="*70)
ds_combined = xr.open_mfdataset(yearly_files, combine='by_coords')
output_file = os.path.join(OUTPUT_DIR, "forcing.nc")
encoding = {var: {'zlib': True, 'complevel': 4} for var in ['precip', 'temp', 'pet']}
ds_combined.to_netcdf(output_file, encoding=encoding)
print(f"Saved: {output_file} ({os.path.getsize(output_file)/1e9:.2f} GB)")

print("\nDONE!")
