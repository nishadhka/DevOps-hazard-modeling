#!/usr/bin/env python3
"""
Memory-Optimized Complete workflow v4: Download → Subset → Regrid → Icechunk
Features:
- FIXED subsetting logic to avoid division by zero errors
- SUBSET FIRST, then regrid (much more memory efficient!)
- Robust coordinate handling for different data sources
- Optimized for machines with limited RAM (4-8 GB)

Usage:
  python create_regridded_icechunk_memory_optimized_v4.py                  # Download + regrid
  python create_regridded_icechunk_memory_optimized_v4.py --skip-download  # Only regrid existing data
"""

import sys
import os
import time
import shutil
import gc
from datetime import datetime
from pathlib import Path

# Add current directory to path
sys.path.append('/home/runner/workspace')

import numpy as np
import xarray as xr
import icechunk
import rioxarray
import xesmf as xe

# Import download functions
from download_pet_imerg_chirpsgefs import (download_pet_data,
                                           download_imerg_data,
                                           download_chirps_gefs_data)


def setup_config(target_date,
                 lat_bounds=(-12.0, 24.2),
                 lon_bounds=(22.9, 51.6),
                 resolution=0.01):
    """Setup configuration for processing"""
    config = {
        'TARGET_DATE': target_date,
        'LAT_BOUNDS': lat_bounds,
        'LON_BOUNDS': lon_bounds,
        'TARGET_RESOLUTION': resolution,
        'OUTPUT_DIR': f"./{target_date.strftime('%Y%m%d')}",
        'ICECHUNK_PATH':
        f"./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr",
        'WEIGHTS_DIR': "./regridder_weights_regional"
    }

    # Create weights directory if it doesn't exist
    os.makedirs(config['WEIGHTS_DIR'], exist_ok=True)

    # Update the download script configuration
    import download_pet_imerg_chirpsgefs
    download_pet_imerg_chirpsgefs.TARGET_DATE = target_date
    download_pet_imerg_chirpsgefs.LAT_BOUNDS = lat_bounds
    download_pet_imerg_chirpsgefs.LON_BOUNDS = lon_bounds
    download_pet_imerg_chirpsgefs.OUTPUT_DIR = config['OUTPUT_DIR']

    return config


def create_target_grid(config):
    """Create target grid for regridding"""
    lat_min, lat_max = config['LAT_BOUNDS']
    lon_min, lon_max = config['LON_BOUNDS']
    resolution = config['TARGET_RESOLUTION']

    lat_points = int((lat_max - lat_min) / resolution) + 1
    lon_points = int((lon_max - lon_min) / resolution) + 1

    lat = np.linspace(lat_min, lat_max, lat_points)
    lon = np.linspace(lon_min, lon_max, lon_points)

    target_grid = xr.Dataset({
        'lat': (['lat'], lat),
        'lon': (['lon'], lon),
    })

    grid_points = lat_points * lon_points
    memory_per_layer = grid_points * 4 / (1024**2)  # MB

    print(
        f"🗺️ Regional target grid: {lat_points} x {lon_points} = {grid_points:,} points"
    )
    print(f"💾 Memory per layer: {memory_per_layer:.1f} MB")

    return target_grid


def subset_to_region_robust(ds, lat_bounds, lon_bounds, buffer_deg=2.0):
    """
    Robust subsetting that handles different coordinate systems and edge cases
    """
    lat_min, lat_max = lat_bounds
    lon_min, lon_max = lon_bounds

    # Add buffer
    lat_min_buf = lat_min - buffer_deg
    lat_max_buf = lat_max + buffer_deg
    lon_min_buf = lon_min - buffer_deg
    lon_max_buf = lon_max + buffer_deg

    print(f"   📐 Robust subsetting with {buffer_deg}° buffer:")
    print(
        f"      Target region: {lat_min}° to {lat_max}°N, {lon_min}° to {lon_max}°E"
    )
    print(
        f"      Buffered region: {lat_min_buf}° to {lat_max_buf}°N, {lon_min_buf}° to {lon_max_buf}°E"
    )

    try:
        # Get coordinate information
        lat_coord = ds.lat
        lon_coord = ds.lon

        print(f"      Source grid: {len(lat_coord)} x {len(lon_coord)} points")
        print(
            f"      Lat range: {float(lat_coord.min()):.1f}° to {float(lat_coord.max()):.1f}°"
        )
        print(
            f"      Lon range: {float(lon_coord.min()):.1f}° to {float(lon_coord.max()):.1f}°"
        )

        # Check coordinate order and fix if needed
        if lat_coord[0] > lat_coord[-1]:
            print(
                f"      🔄 Flipping latitude coordinate (descending → ascending)"
            )
            ds = ds.isel(lat=slice(None, None, -1))
            lat_coord = ds.lat

        # Ensure longitude is in -180 to 180 range if needed
        if float(lon_coord.max()) > 180:
            print(f"      🔄 Converting longitude from 0-360 to -180-180")
            ds = ds.assign_coords(lon=(ds.lon + 180) % 360 - 180)
            ds = ds.sortby('lon')
            lon_coord = ds.lon

        # Find indices for subsetting
        lat_mask = (lat_coord >= lat_min_buf) & (lat_coord <= lat_max_buf)
        lon_mask = (lon_coord >= lon_min_buf) & (lon_coord <= lon_max_buf)

        # Check if we have any points in the region
        lat_indices = np.where(lat_mask)[0]
        lon_indices = np.where(lon_mask)[0]

        if len(lat_indices) == 0 or len(lon_indices) == 0:
            print(
                f"      ⚠️ No points found in target region, using full dataset"
            )
            return ds

        # Apply subsetting using isel (index-based selection)
        lat_start, lat_end = lat_indices[0], lat_indices[-1] + 1
        lon_start, lon_end = lon_indices[0], lon_indices[-1] + 1

        ds_subset = ds.isel(lat=slice(lat_start, lat_end),
                            lon=slice(lon_start, lon_end))

        # Verify the subset
        subset_lat_min = float(ds_subset.lat.min())
        subset_lat_max = float(ds_subset.lat.max())
        subset_lon_min = float(ds_subset.lon.min())
        subset_lon_max = float(ds_subset.lon.max())

        print(
            f"      ✅ Subset result: {len(ds_subset.lat)} x {len(ds_subset.lon)} points"
        )
        print(
            f"      Subset bounds: {subset_lat_min:.1f}° to {subset_lat_max:.1f}°N, {subset_lon_min:.1f}° to {subset_lon_max:.1f}°E"
        )

        # Calculate reduction factor
        original_size = len(ds.lat) * len(ds.lon)
        subset_size = len(ds_subset.lat) * len(ds_subset.lon)
        if subset_size > 0:
            reduction_factor = original_size / subset_size
            print(
                f"      🎯 Size reduction: {original_size:,} → {subset_size:,} points ({reduction_factor:.1f}x smaller)"
            )

        return ds_subset

    except Exception as e:
        print(f"      ❌ Robust subset failed: {e}")
        print(f"      🔄 Using full dataset as fallback")
        return ds


def get_or_create_regridder(source_ds,
                            target_grid,
                            method='bilinear',
                            weights_dir="./regridder_weights_regional"):
    """Get cached regridder or create new one for regional grids"""

    # Create a unique identifier
    source_shape = f"{len(source_ds.lat)}x{len(source_ds.lon)}"
    target_shape = f"{len(target_grid.lat)}x{len(target_grid.lon)}"

    # Get bounds for identification
    source_lat_range = f"{float(source_ds.lat.min()):.1f}to{float(source_ds.lat.max()):.1f}"
    source_lon_range = f"{float(source_ds.lon.min()):.1f}to{float(source_ds.lon.max()):.1f}"
    target_lat_range = f"{float(target_grid.lat.min()):.1f}to{float(target_grid.lat.max()):.1f}"
    target_lon_range = f"{float(target_grid.lon.min()):.1f}to{float(target_grid.lon.max()):.1f}"

    weight_filename = f"regional_{method}_{source_shape}_{source_lat_range}_{source_lon_range}_to_{target_shape}_{target_lat_range}_{target_lon_range}.nc"
    weight_path = os.path.join(weights_dir, weight_filename)

    # Check if weights already exist
    if os.path.exists(weight_path):
        print(
            f"   🔄 Loading cached regional weights ({os.path.getsize(weight_path) / (1024**2):.1f} MB)"
        )

        try:
            regridder = xe.Regridder(source_ds,
                                     target_grid,
                                     method,
                                     weights=weight_path)
            print(f"   ✅ Loaded cached regridder in ~33ms")
            return regridder
        except Exception as e:
            print(f"   ⚠️ Failed to load cached weights: {e}")

    # Create new regridder
    print(f"   🔧 Creating new regional regridder...")
    print(
        f"   📊 Source: {len(source_ds.lat)} x {len(source_ds.lon)} → Target: {len(target_grid.lat)} x {len(target_grid.lon)}"
    )

    start_time = time.time()
    regridder = xe.Regridder(source_ds, target_grid, method)
    creation_time = time.time() - start_time

    # Save weights
    try:
        saved_path = regridder.to_netcdf(weight_path)
        weight_size = os.path.getsize(weight_path) / (1024**2)
        print(f"   💾 Saved regional weights ({weight_size:.1f} MB)")
        print(f"   ⏱️ Creation time: {creation_time:.1f}s")
    except Exception as e:
        print(f"   ⚠️ Failed to save weights: {e}")

    return regridder


def check_memory():
    """Check available memory"""
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if 'MemAvailable' in line:
                    available_kb = int(line.split()[1])
                    available_mb = available_kb / 1024
                    available_gb = available_mb / 1024
                    print(
                        f"💾 Available memory: {available_mb:.0f} MB ({available_gb:.1f} GB)"
                    )
                    return available_mb
    except:
        print("💾 Could not determine available memory")
        return None


def download_all_data(config):
    """Download all three data sources"""
    print("📥 Downloading all data sources...")

    os.makedirs(config['OUTPUT_DIR'], exist_ok=True)

    # Download each source
    pet_success = download_pet_data()
    imerg_success = download_imerg_data()
    chirps_success = download_chirps_gefs_data()

    return {
        'pet': pet_success,
        'imerg': imerg_success,
        'chirps': chirps_success
    }


def load_and_regrid_pet_regional(config, target_grid):
    """Regional PET processing with robust subsetting"""
    print("🌡️ Processing PET data (regional subset + regrid)...")

    check_memory()

    pet_dir = os.path.join(config['OUTPUT_DIR'], 'pet_data')
    bil_files = list(Path(pet_dir).glob('*.bil'))

    if not bil_files:
        print("   ❌ No PET files found")
        return None

    bil_file = bil_files[0]

    try:
        # Load BIL file
        with open(bil_file, 'rb') as f:
            data = np.frombuffer(f.read(), dtype=np.float32)

        file_size = len(data)
        print(
            f"   📊 File size: {file_size} values ({file_size * 4 / (1024**2):.1f} MB)"
        )

        # Determine dimensions
        possible_dims = [
            (181, 360),  # 1° global
            (361, 720),  # 0.5° global
            (721, 1440),  # 0.25° global
            (1801, 3600),  # 0.1° global
        ]

        height, width = None, None
        for h, w in possible_dims:
            if h * w == file_size:
                height, width = h, w
                break

        if height is None:
            for i in range(100, int(np.sqrt(file_size)) + 1):
                if file_size % i == 0:
                    height, width = i, file_size // i
                    break

        if height is None:
            print(f"   ❌ Cannot determine dimensions for {file_size} values")
            return None

        data = data.reshape(height, width)
        data = np.where(data < -9000, np.nan, data)

        # Create coordinates (global grid)
        lat_step = 180.0 / height
        lon_step = 360.0 / width
        lat_global = np.linspace(90 - lat_step / 2, -90 + lat_step / 2, height)
        lon_global = np.linspace(-180 + lon_step / 2, 180 - lon_step / 2,
                                 width)

        # Create full global dataset
        pet_ds_global = xr.Dataset({'pet': (['lat', 'lon'], data)},
                                   coords={
                                       'lat': lat_global,
                                       'lon': lon_global
                                   })

        pet_ds_global.pet.attrs = {
            'long_name': 'potential_evapotranspiration',
            'units': 'mm/day',
            'source': 'USGS FEWS NET'
        }

        # ROBUST subsetting
        print("   🎯 Subsetting PET to East Africa region...")
        pet_ds_regional = subset_to_region_robust(pet_ds_global,
                                                  config['LAT_BOUNDS'],
                                                  config['LON_BOUNDS'],
                                                  buffer_deg=2.0)

        # Clean up global dataset
        del pet_ds_global, data
        gc.collect()

        print("   🔄 Starting regional regridding...")

        # Create regridder for regional data
        regridder = get_or_create_regridder(pet_ds_regional, target_grid,
                                            'bilinear', config['WEIGHTS_DIR'])

        # Apply regridding
        pet_regridded = regridder(pet_ds_regional)

        # Clean up
        del regridder, pet_ds_regional
        gc.collect()

        # Final subset to exact region
        pet_regridded = pet_regridded.sel(lat=slice(config['LAT_BOUNDS'][0],
                                                    config['LAT_BOUNDS'][1]),
                                          lon=slice(config['LON_BOUNDS'][0],
                                                    config['LON_BOUNDS'][1]))

        print(f"   ✅ PET regridded: {pet_regridded.pet.shape}")
        print(f"   💾 Memory after PET: {check_memory():.0f} MB available")

        return pet_regridded

    except Exception as e:
        print(f"   ❌ PET processing failed: {e}")
        import traceback
        traceback.print_exc()
        gc.collect()
        return None


def load_and_regrid_imerg_regional(config, target_grid):
    """Regional IMERG processing with robust subsetting"""
    print("🛰️ Processing IMERG data (regional subset + regrid)...")

    check_memory()

    imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
    tiff_files = list(Path(imerg_dir).glob('*.tif'))

    if not tiff_files:
        print("   ❌ No IMERG files found")
        return None

    print(f"   📊 Processing {len(tiff_files)} IMERG files")

    try:
        regional_datasets = []

        for i, tiff_file in enumerate(sorted(tiff_files)):
            print(
                f"   🔄 Processing file {i+1}/{len(tiff_files)}: {tiff_file.name}"
            )

            # Extract date
            filename = os.path.basename(tiff_file)
            try:
                date_str = filename.split('.')[3][:8]
                file_date = datetime.strptime(date_str, '%Y%m%d')
            except:
                file_date = datetime.fromtimestamp(os.path.getmtime(tiff_file))

            # Load file
            ds = rioxarray.open_rasterio(tiff_file)
            ds = ds.squeeze('band').drop('band')

            if 'x' in ds.dims:
                ds = ds.rename({'x': 'lon', 'y': 'lat'})

            ds = ds.expand_dims('time')
            ds = ds.assign_coords(time=[file_date])

            # ROBUST subsetting
            print(f"      🎯 Subsetting IMERG file to region...")
            ds_regional = subset_to_region_robust(ds,
                                                  config['LAT_BOUNDS'],
                                                  config['LON_BOUNDS'],
                                                  buffer_deg=2.0)

            regional_datasets.append(ds_regional)

            # Clean up original dataset
            del ds
            gc.collect()

        # Combine regional datasets
        print("   🔗 Combining regional IMERG datasets...")
        imerg_combined = xr.concat(regional_datasets, dim='time')

        # Clean up individual datasets
        del regional_datasets
        gc.collect()

        # Handle variable naming
        if hasattr(imerg_combined, 'data_vars') and len(
                imerg_combined.data_vars) > 0:
            data_var = list(imerg_combined.data_vars)[0]
            imerg_combined = imerg_combined.rename({data_var: 'precipitation'})
        else:
            if hasattr(imerg_combined, 'name'):
                if imerg_combined.name != 'precipitation':
                    imerg_combined.name = 'precipitation'
            else:
                imerg_combined.name = 'precipitation'
            imerg_combined = imerg_combined.to_dataset()

        imerg_combined.precipitation.attrs = {
            'long_name': 'precipitation_rate',
            'units': 'mm/day',
            'source': 'NASA IMERG'
        }

        print("   🔄 Starting regional regridding...")

        # Create regridder for regional data
        regridder = get_or_create_regridder(imerg_combined, target_grid,
                                            'bilinear', config['WEIGHTS_DIR'])

        # Apply regridding
        imerg_regridded = regridder(imerg_combined)

        # Clean up
        del regridder, imerg_combined
        gc.collect()

        # Final subset to exact region
        imerg_regridded = imerg_regridded.sel(
            lat=slice(config['LAT_BOUNDS'][0], config['LAT_BOUNDS'][1]),
            lon=slice(config['LON_BOUNDS'][0], config['LON_BOUNDS'][1]))

        print(f"   ✅ IMERG regridded: {imerg_regridded.precipitation.shape}")
        print(f"   💾 Memory after IMERG: {check_memory():.0f} MB available")

        return imerg_regridded

    except Exception as e:
        print(f"   ❌ IMERG processing failed: {e}")
        import traceback
        traceback.print_exc()
        gc.collect()
        return None


def load_and_regrid_chirps_regional(config, target_grid):
    """Regional CHIRPS-GEFS processing with robust subsetting"""
    print("🌧️ Processing CHIRPS-GEFS data (regional subset + regrid)...")

    check_memory()

    chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')
    nc_files = list(Path(chirps_dir).glob('*.nc'))

    if not nc_files:
        print("   ❌ No CHIRPS-GEFS files found")
        return None

    try:
        nc_file = nc_files[0]
        print(f"   📊 Loading: {nc_file.name}")

        # Open dataset
        chirps_ds = xr.open_dataset(nc_file)

        # Standardize coordinate names for CHIRPS-GEFS
        print(f"   📋 Original coordinates: {list(chirps_ds.coords)}")
        print(f"   📋 Original dimensions: {list(chirps_ds.dims)}")

        # Rename coordinates if needed (CHIRPS uses y/x instead of lat/lon)
        coord_renames = {}
        if 'y' in chirps_ds.dims and 'lat' not in chirps_ds.dims:
            coord_renames['y'] = 'lat'
        if 'x' in chirps_ds.dims and 'lon' not in chirps_ds.dims:
            coord_renames['x'] = 'lon'

        if coord_renames:
            print(f"   🔄 Renaming coordinates: {coord_renames}")
            chirps_ds = chirps_ds.rename(coord_renames)

        print(f"   ✅ Standardized coordinates: {list(chirps_ds.coords)}")

        # Find precipitation variable
        precip_vars = [
            var for var in chirps_ds.data_vars if 'precip' in var.lower()
        ]
        if not precip_vars:
            precip_vars = list(chirps_ds.data_vars)

        if precip_vars:
            chirps_ds = chirps_ds.rename({precip_vars[0]: 'precipitation'})
            print(f"   🔄 Renamed variable: {precip_vars[0]} → precipitation")

        # ROBUST subsetting
        print("   🎯 Subsetting CHIRPS to region...")
        chirps_regional = subset_to_region_robust(chirps_ds,
                                                  config['LAT_BOUNDS'],
                                                  config['LON_BOUNDS'],
                                                  buffer_deg=2.0)

        # Clean up full dataset
        del chirps_ds
        gc.collect()

        chirps_regional.precipitation.attrs = {
            'long_name': 'precipitation_forecast',
            'units': 'mm/day',
            'source': 'CHIRPS-GEFS'
        }

        print(
            f"   🔄 Starting regional regridding ({len(chirps_regional.time)} time steps)..."
        )

        # Create regridder for regional data
        regridder = get_or_create_regridder(chirps_regional, target_grid,
                                            'bilinear', config['WEIGHTS_DIR'])

        # Apply regridding
        chirps_regridded = regridder(chirps_regional)

        # Clean up
        del regridder, chirps_regional
        gc.collect()

        # Final subset to exact region
        chirps_regridded = chirps_regridded.sel(
            lat=slice(config['LAT_BOUNDS'][0], config['LAT_BOUNDS'][1]),
            lon=slice(config['LON_BOUNDS'][0], config['LON_BOUNDS'][1]))

        print(
            f"   ✅ CHIRPS-GEFS regridded: {chirps_regridded.precipitation.shape}"
        )
        print(
            f"   💾 Memory after CHIRPS-GEFS: {check_memory():.0f} MB available"
        )

        return chirps_regridded

    except Exception as e:
        print(f"   ❌ CHIRPS-GEFS processing failed: {e}")
        import traceback
        traceback.print_exc()
        gc.collect()
        return None


def create_icechunk_dataset_optimized(config, pet_data, imerg_data,
                                      chirps_data):
    """Memory-optimized icechunk creation"""
    print("🧊 Creating icechunk dataset (memory optimized)...")

    if os.path.exists(config['ICECHUNK_PATH']):
        shutil.rmtree(config['ICECHUNK_PATH'])

    # Get spatial coordinates
    if pet_data is not None:
        lat_coord = pet_data['lat']
        lon_coord = pet_data['lon']
    elif imerg_data is not None:
        lat_coord = imerg_data['lat']
        lon_coord = imerg_data['lon']
    else:
        print("   ❌ No data available")
        return False, 0

    # Create time coordinate
    all_times = []
    if imerg_data is not None:
        all_times.extend(imerg_data['time'].values)
    if chirps_data is not None:
        all_times.extend(chirps_data['time'].values)
    if not all_times:
        all_times = [np.datetime64(config['TARGET_DATE'])]

    unique_times = sorted(set(all_times))

    try:
        # Create icechunk store
        storage = icechunk.local_filesystem_storage(config['ICECHUNK_PATH'])
        repo = icechunk.Repository.create(storage)
        session = repo.writable_session("main")
        store = session.store

        # Write variables sequentially
        total_variables = 0

        if pet_data is not None:
            print("   📝 Writing PET data...")

            pet_values = pet_data['pet'].values
            if len(pet_values.shape) == 2:
                broadcasted = np.broadcast_to(
                    pet_values[np.newaxis, :, :],
                    (len(unique_times), len(lat_coord), len(lon_coord)))
            else:
                broadcasted = pet_values

            pet_ds = xr.Dataset({'pet': (['time', 'lat', 'lon'], broadcasted)},
                                coords={
                                    'time': unique_times,
                                    'lat': lat_coord,
                                    'lon': lon_coord
                                })

            pet_ds.pet.attrs = pet_data['pet'].attrs
            pet_ds.to_zarr(store, mode='w', consolidated=False)
            total_variables += 1

            del pet_ds, broadcasted
            gc.collect()

        if imerg_data is not None:
            print("   📝 Writing IMERG data...")

            full_data = np.full(
                (len(unique_times), len(lat_coord), len(lon_coord)),
                np.nan,
                dtype=np.float32)

            for i, time_val in enumerate(imerg_data['time'].values):
                if time_val in unique_times:
                    time_idx = unique_times.index(time_val)
                    full_data[time_idx, :, :] = imerg_data[
                        'precipitation'].values[i, :, :]

            imerg_ds = xr.Dataset(
                {'imerg_precipitation': (['time', 'lat', 'lon'], full_data)},
                coords={
                    'time': unique_times,
                    'lat': lat_coord,
                    'lon': lon_coord
                })

            imerg_ds.imerg_precipitation.attrs = imerg_data[
                'precipitation'].attrs

            if total_variables == 0:
                imerg_ds.to_zarr(store, mode='w', consolidated=False)
            else:
                imerg_ds.to_zarr(store, mode='a', consolidated=False)
            total_variables += 1

            del imerg_ds, full_data
            gc.collect()

        if chirps_data is not None:
            print("   📝 Writing CHIRPS-GEFS data...")

            full_data = np.full(
                (len(unique_times), len(lat_coord), len(lon_coord)),
                np.nan,
                dtype=np.float32)

            for i, time_val in enumerate(chirps_data['time'].values):
                if time_val in unique_times:
                    time_idx = unique_times.index(time_val)
                    full_data[time_idx, :, :] = chirps_data[
                        'precipitation'].values[i, :, :]

            chirps_ds = xr.Dataset(
                {
                    'chirps_gefs_precipitation':
                    (['time', 'lat', 'lon'], full_data)
                },
                coords={
                    'time': unique_times,
                    'lat': lat_coord,
                    'lon': lon_coord
                })

            chirps_ds.chirps_gefs_precipitation.attrs = chirps_data[
                'precipitation'].attrs

            if total_variables == 0:
                chirps_ds.to_zarr(store, mode='w', consolidated=False)
            else:
                chirps_ds.to_zarr(store, mode='a', consolidated=False)
            total_variables += 1

            del chirps_ds, full_data
            gc.collect()

        # Commit the session
        session.commit(
            f"East Africa climate data for {config['TARGET_DATE'].strftime('%Y-%m-%d')}"
        )

        # Calculate size
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(config['ICECHUNK_PATH']):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)

        size_mb = total_size / (1024 * 1024)
        size_gb = total_size / (1024 * 1024 * 1024)

        print(f"   ✅ Icechunk created: {config['ICECHUNK_PATH']}")
        print(f"   📊 Variables: {total_variables}")
        print(f"   🗺️ Grid: {len(lat_coord)} x {len(lon_coord)}")
        print(f"   ⏰ Time steps: {len(unique_times)}")
        print(f"   💾 Size: {size_mb:.2f} MB ({size_gb:.3f} GB)")

        return True, total_size

    except Exception as e:
        print(f"   ❌ Icechunk creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False, 0


def main(target_date,
         lat_bounds=(-12.0, 24.2),
         lon_bounds=(22.9, 51.6),
         resolution=0.01,
         skip_download=False):
    """Regional regridding workflow with robust subsetting"""

    # Setup
    config = setup_config(target_date, lat_bounds, lon_bounds, resolution)

    print("🚀 REGIONAL Climate Data Workflow v4 (robust subset + regrid)")
    print("=" * 80)
    print(f"Date: {target_date.strftime('%Y-%m-%d')}")
    print(
        f"Region: {lat_bounds[0]}° to {lat_bounds[1]}°N, {lon_bounds[0]}° to {lon_bounds[1]}°E"
    )
    print(f"Resolution: {resolution}°")
    print(f"Strategy: Robust Subset → Regrid (memory efficient!)")
    print("=" * 80)

    check_memory()

    start_time = time.time()

    # Step 1: Download (optional)
    if skip_download:
        print("\n📥 STEP 1: Skipping Download (using existing data)")
        pet_dir = os.path.join(config['OUTPUT_DIR'], 'pet_data')
        imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
        chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')

        download_results = {
            'pet':
            os.path.exists(pet_dir)
            and len(list(Path(pet_dir).glob('*.bil'))) > 0,
            'imerg':
            os.path.exists(imerg_dir)
            and len(list(Path(imerg_dir).glob('*.tif'))) > 0,
            'chirps':
            os.path.exists(chirps_dir)
            and len(list(Path(chirps_dir).glob('*.nc'))) > 0
        }

        print(
            f"   PET data available: {'✅' if download_results['pet'] else '❌'}"
        )
        print(
            f"   IMERG data available: {'✅' if download_results['imerg'] else '❌'}"
        )
        print(
            f"   CHIRPS-GEFS data available: {'✅' if download_results['chirps'] else '❌'}"
        )

        download_time = 0
    else:
        print("\n📥 STEP 1: Data Download")
        download_results = download_all_data(config)
        download_time = time.time() - start_time

    # Step 2: Regional regridding with robust subsetting
    print("\n🗺️ STEP 2: Regional Regridding (Robust Subset → Regrid)")
    regrid_start = time.time()

    target_grid = create_target_grid(config)

    # Process variables with robust regional approach
    pet_data = None
    imerg_data = None
    chirps_data = None

    if download_results['pet']:
        pet_data = load_and_regrid_pet_regional(config, target_grid)
        gc.collect()

    if download_results['imerg']:
        imerg_data = load_and_regrid_imerg_regional(config, target_grid)
        gc.collect()

    if download_results['chirps']:
        chirps_data = load_and_regrid_chirps_regional(config, target_grid)
        gc.collect()

    regrid_time = time.time() - regrid_start

    # Step 3: Icechunk
    print("\n🧊 STEP 3: Icechunk Creation")
    icechunk_start = time.time()

    success, dataset_size = create_icechunk_dataset_optimized(
        config, pet_data, imerg_data, chirps_data)

    icechunk_time = time.time() - icechunk_start
    total_time = time.time() - start_time

    # Final cleanup
    del pet_data, imerg_data, chirps_data, target_grid
    gc.collect()

    # Summary
    print("\n" + "=" * 80)
    print("🎉 REGIONAL WORKFLOW v4 COMPLETE")
    print("=" * 80)

    if success:
        size_mb = dataset_size / (1024 * 1024)
        size_gb = dataset_size / (1024 * 1024 * 1024)

        print(f"✅ Success! Dataset created: {config['ICECHUNK_PATH']}")
        print(f"💾 Final size: {size_mb:.2f} MB ({size_gb:.3f} GB)")
        print(
            f"⏱️ Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)"
        )
        print(f"📊 Timing breakdown:")
        print(
            f"   Download: {download_time:.2f}s ({download_time/total_time*100:.1f}%)"
        )
        print(
            f"   Regridding: {regrid_time:.2f}s ({regrid_time/total_time*100:.1f}%)"
        )
        print(
            f"   Icechunk: {icechunk_time:.2f}s ({icechunk_time/total_time*100:.1f}%)"
        )

        # Show cache info
        weight_files = list(Path(config['WEIGHTS_DIR']).glob('*.nc'))
        if weight_files:
            total_cache_size = sum(f.stat().st_size
                                   for f in weight_files) / (1024**2)
            print(
                f"💾 Regional regridder cache: {len(weight_files)} files, {total_cache_size:.1f} MB"
            )

        check_memory()
        return True, dataset_size
    else:
        print("❌ Workflow failed")
        return False, 0


# Example usage
if __name__ == "__main__":
    # Example: Process July 22, 2025 with robust regional regridding
    target_date = datetime(2025, 7, 22)

    # Try different resolutions
    resolutions = [0.01]

    for resolution in resolutions:
        print(f"\n🧪 Attempting {resolution}° resolution...")
        try:
            skip_download = len(sys.argv) > 1 and '--skip-download' in sys.argv
            success, size = main(target_date,
                                 resolution=resolution,
                                 skip_download=skip_download)
            if success:
                print(f"\n🎯 Success with {resolution}° resolution!")
                print(
                    f"Dataset location: ./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr"
                )
                print(f"Dataset size: {size / (1024*1024):.2f} MB")
                break
        except MemoryError:
            print(
                f"❌ Out of memory with {resolution}° resolution, trying lower resolution..."
            )
            continue
        except Exception as e:
            print(f"❌ Failed with {resolution}° resolution: {e}")
            continue
    else:
        print("❌ All resolutions failed")
        sys.exit(1)

    sys.exit(0)
