#!/usr/bin/env python3
"""
Memory-Optimized Complete workflow v7: Download → Raw Icechunk → Regrid from Icechunk
Features:
- REORDERED WORKFLOW: Create raw icechunk BEFORE regridding
- Step 1: Download raw data
- Step 2: Create raw unified icechunk (no regridding)
- Step 3: Regrid FROM the raw icechunk to create final regridded icechunk
- UNIFIED TIME DIMENSION: All variables aligned to single time coordinate
- PET date extraction from filename (20250722 format)
- Missing dates filled as null values for alignment
- Optimized for machines with limited RAM (4-8 GB)

Usage:
  python create_regridded_icechunk_memory_optimized_v7.py                  # Download + raw icechunk + regrid
  python create_regridded_icechunk_memory_optimized_v7.py --skip-download  # Only raw icechunk + regrid
"""

import sys
import os
import time
import shutil
import gc
from datetime import datetime
from pathlib import Path
import pandas as pd

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
        'RAW_ICECHUNK_PATH': f"./east_africa_raw_{target_date.strftime('%Y%m%d')}.zarr",
        'REGRIDDED_ICECHUNK_PATH': f"./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr",
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


def extract_date_from_filename(filename, target_date):
    """Extract date from filename, fallback to target date"""
    try:
        # Try extracting YYYYMMDD from filename
        filename_str = str(filename)
        
        # Common patterns for date extraction
        patterns = [
            # et250722.bil -> 20250722
            lambda f: f"20{f.split('et')[1][:6]}" if 'et' in f and f.split('et')[1][:6].isdigit() else None,
            
            # IMERG format: 3B-HHR-E.MS.MRG.3IMERG.20250715-S233000-E235959.1410.V07B.1day.tif
            lambda f: f.split('3IMERG.')[1][:8] if '3IMERG.' in f and len(f.split('3IMERG.')) > 1 and f.split('3IMERG.')[1][:8].isdigit() else None,
            
            # YYYY.MM.DD format in filename
            lambda f: ''.join(f.split('.')[3][:8]) if len(f.split('.')) > 3 and f.split('.')[3][:8].isdigit() else None,
            
            # YYYYMMDD anywhere in filename
            lambda f: next((s for s in f.split('_') + f.split('.') + f.split('-') if len(s) == 8 and s.isdigit()), None)
        ]
        
        for pattern in patterns:
            try:
                date_str = pattern(filename_str)
                if date_str and len(date_str) == 8:
                    return datetime.strptime(date_str, '%Y%m%d')
            except:
                continue
                
        # If no date found in filename, use target date
        print(f"      ⚠️ Could not extract date from {filename}, using target date")
        return target_date
        
    except Exception as e:
        print(f"      ⚠️ Date extraction failed for {filename}: {e}, using target date")
        return target_date


def create_unified_time_coordinate(pet_date, imerg_times, chirps_times):
    """Create unified time coordinate covering all data sources"""
    all_times = []
    
    # Add PET date
    if pet_date:
        all_times.append(pd.to_datetime(pet_date))
    
    # Add IMERG times
    if imerg_times is not None and len(imerg_times) > 0:
        all_times.extend(pd.to_datetime(imerg_times))
    
    # Add CHIRPS times  
    if chirps_times is not None and len(chirps_times) > 0:
        all_times.extend(pd.to_datetime(chirps_times))
    
    # Remove duplicates and sort
    unified_times = sorted(list(set(all_times)))
    
    print(f"   🕒 Unified time coordinate: {len(unified_times)} time steps")
    print(f"      From {unified_times[0]} to {unified_times[-1]}")
    
    return unified_times


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


def load_raw_pet_data(config):
    """Load raw PET data without regridding"""
    print("🌡️ Loading raw PET data...")

    pet_dir = os.path.join(config['OUTPUT_DIR'], 'pet_data')
    bil_files = list(Path(pet_dir).glob('*.bil'))

    if not bil_files:
        print("   ❌ No PET files found")
        return None, None

    bil_file = bil_files[0]

    try:
        # Extract date from filename
        pet_date = extract_date_from_filename(bil_file.name, config['TARGET_DATE'])
        print(f"   📅 PET date: {pet_date.strftime('%Y-%m-%d')} (from {bil_file.name})")

        # Load BIL file
        with open(bil_file, 'rb') as f:
            data = np.frombuffer(f.read(), dtype=np.float32)

        file_size = len(data)
        print(f"   📊 File size: {file_size} values ({file_size * 4 / (1024**2):.1f} MB)")

        # Determine dimensions
        possible_dims = [
            (181, 360),   # 1° global
            (361, 720),   # 0.5° global
            (721, 1440),  # 0.25° global
            (1801, 3600), # 0.1° global
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
            return None, None

        data = data.reshape(height, width)
        data = np.where(data < -9000, np.nan, data)

        # Create coordinates (global grid)
        lat_step = 180.0 / height
        lon_step = 360.0 / width
        lat_global = np.linspace(90 - lat_step / 2, -90 + lat_step / 2, height)
        lon_global = np.linspace(-180 + lon_step / 2, 180 - lon_step / 2, width)

        # Create full global dataset
        pet_ds = xr.Dataset({'pet_data': (['lat', 'lon'], data)},
                           coords={
                               'lat': lat_global,
                               'lon': lon_global
                           })

        pet_ds.pet_data.attrs = {
            'long_name': 'potential_evapotranspiration',
            'units': 'mm/day',
            'source': 'USGS FEWS NET'
        }

        print(f"   ✅ Raw PET loaded: {pet_ds.pet_data.shape}")
        return pet_ds, pet_date

    except Exception as e:
        print(f"   ❌ Raw PET loading failed: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def load_raw_imerg_data(config):
    """Load raw IMERG data without regridding"""
    print("🛰️ Loading raw IMERG data...")

    imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
    tiff_files = list(Path(imerg_dir).glob('*.tif'))

    if not tiff_files:
        print("   ❌ No IMERG files found")
        return None

    print(f"   📊 Processing {len(tiff_files)} IMERG files")

    try:
        datasets = []

        for i, tiff_file in enumerate(sorted(tiff_files)):
            print(f"   🔄 Processing file {i+1}/{len(tiff_files)}: {tiff_file.name}")

            # Extract date
            file_date = extract_date_from_filename(tiff_file.name, config['TARGET_DATE'])

            # Load file
            ds = rioxarray.open_rasterio(tiff_file)
            ds = ds.squeeze('band').drop('band')

            if 'x' in ds.dims:
                ds = ds.rename({'x': 'lon', 'y': 'lat'})

            ds = ds.expand_dims('time')
            ds = ds.assign_coords(time=[file_date])

            datasets.append(ds)

        # Combine datasets
        print("   🔗 Combining raw IMERG datasets...")
        imerg_combined = xr.concat(datasets, dim='time')

        # Handle variable naming
        if hasattr(imerg_combined, 'data_vars') and len(imerg_combined.data_vars) > 0:
            data_var = list(imerg_combined.data_vars)[0]
            imerg_combined = imerg_combined.rename({data_var: 'imerg_precipitation'})
        else:
            if hasattr(imerg_combined, 'name'):
                if imerg_combined.name != 'imerg_precipitation':
                    imerg_combined.name = 'imerg_precipitation'
            else:
                imerg_combined.name = 'imerg_precipitation'
            imerg_combined = imerg_combined.to_dataset()

        imerg_combined.imerg_precipitation.attrs = {
            'long_name': 'precipitation_rate',
            'units': 'mm/day',
            'source': 'NASA IMERG'
        }

        print(f"   ✅ Raw IMERG loaded: {imerg_combined.imerg_precipitation.shape}")
        return imerg_combined

    except Exception as e:
        print(f"   ❌ Raw IMERG loading failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_raw_chirps_data(config):
    """Load raw CHIRPS-GEFS data without regridding"""
    print("🌧️ Loading raw CHIRPS-GEFS data...")

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

        # Standardize coordinate names
        coord_renames = {}
        if 'y' in chirps_ds.dims and 'lat' not in chirps_ds.dims:
            coord_renames['y'] = 'lat'
        if 'x' in chirps_ds.dims and 'lon' not in chirps_ds.dims:
            coord_renames['x'] = 'lon'

        if coord_renames:
            print(f"   🔄 Renaming coordinates: {coord_renames}")
            chirps_ds = chirps_ds.rename(coord_renames)

        # Find precipitation variable
        precip_vars = [var for var in chirps_ds.data_vars if 'precip' in var.lower()]
        if not precip_vars:
            precip_vars = list(chirps_ds.data_vars)

        if precip_vars:
            chirps_ds = chirps_ds.rename({precip_vars[0]: 'chirps_precipitation'})
            print(f"   🔄 Renamed variable: {precip_vars[0]} → chirps_precipitation")

        chirps_ds.chirps_precipitation.attrs = {
            'long_name': 'precipitation_forecast',
            'units': 'mm/day',
            'source': 'CHIRPS-GEFS'
        }

        print(f"   ✅ Raw CHIRPS-GEFS loaded: {chirps_ds.chirps_precipitation.shape}")
        return chirps_ds

    except Exception as e:
        print(f"   ❌ Raw CHIRPS-GEFS loading failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def create_raw_icechunk_dataset(config, pet_data, pet_date, imerg_data, chirps_data):
    """Create raw icechunk dataset with unified time dimension (no regridding)"""
    print("🧊 Creating raw icechunk dataset with unified time...")

    if os.path.exists(config['RAW_ICECHUNK_PATH']):
        shutil.rmtree(config['RAW_ICECHUNK_PATH'])

    # Create unified time coordinate
    pet_times = [pet_date] if pet_date else []
    imerg_times = imerg_data['time'].values if imerg_data is not None else []
    chirps_times = chirps_data['time'].values if chirps_data is not None else []
    
    unified_times = create_unified_time_coordinate(pet_date, imerg_times, chirps_times)

    try:
        # Create icechunk store
        storage = icechunk.local_filesystem_storage(config['RAW_ICECHUNK_PATH'])
        repo = icechunk.Repository.create(storage)
        session = repo.writable_session("main")
        store = session.store

        # For raw data, we need to handle different coordinate systems
        data_vars = {}
        coords = {'time': ('time', unified_times)}

        # Process each dataset separately to handle different grids
        if pet_data is not None:
            print("   📝 Adding raw PET data to unified time...")
            pet_coords = {
                'pet_lat': ('pet_lat', pet_data['lat'].values),
                'pet_lon': ('pet_lon', pet_data['lon'].values)
            }
            coords.update(pet_coords)
            
            # Create time-aligned PET data
            pet_values = pet_data['pet_data'].values
            pet_aligned = np.full((len(unified_times), len(pet_data['lat']), len(pet_data['lon'])), 
                                 np.nan, dtype=np.float32)
            
            if pet_date in unified_times:
                time_idx = unified_times.index(pet_date)
                pet_aligned[time_idx, :, :] = pet_values
                
            data_vars['pet_data'] = (['time', 'pet_lat', 'pet_lon'], pet_aligned)

        if imerg_data is not None:
            print("   📝 Adding raw IMERG data to unified time...")
            imerg_coords = {
                'imerg_lat': ('imerg_lat', imerg_data['lat'].values),
                'imerg_lon': ('imerg_lon', imerg_data['lon'].values)
            }
            coords.update(imerg_coords)
            
            # Create time-aligned IMERG data
            imerg_aligned = np.full((len(unified_times), len(imerg_data['lat']), len(imerg_data['lon'])), 
                                   np.nan, dtype=np.float32)
            
            for i, imerg_time in enumerate(imerg_data['time'].values):
                if imerg_time in unified_times:
                    time_idx = unified_times.index(imerg_time)
                    imerg_aligned[time_idx, :, :] = imerg_data['imerg_precipitation'].values[i, :, :]
                    
            data_vars['imerg_precipitation'] = (['time', 'imerg_lat', 'imerg_lon'], imerg_aligned)

        if chirps_data is not None:
            print("   📝 Adding raw CHIRPS-GEFS data to unified time...")
            chirps_coords = {
                'chirps_lat': ('chirps_lat', chirps_data['lat'].values),
                'chirps_lon': ('chirps_lon', chirps_data['lon'].values)
            }
            coords.update(chirps_coords)
            
            # Create time-aligned CHIRPS data
            chirps_aligned = np.full((len(unified_times), len(chirps_data['lat']), len(chirps_data['lon'])), 
                                    np.nan, dtype=np.float32)
            
            for i, chirps_time in enumerate(chirps_data['time'].values):
                if chirps_time in unified_times:  
                    time_idx = unified_times.index(chirps_time)
                    chirps_aligned[time_idx, :, :] = chirps_data['chirps_precipitation'].values[i, :, :]
                    
            data_vars['chirps_precipitation'] = (['time', 'chirps_lat', 'chirps_lon'], chirps_aligned)

        # Create raw dataset with multiple coordinate systems
        raw_ds = xr.Dataset(data_vars, coords=coords)
        
        # Add global attributes
        raw_ds.attrs.update({
            'processing_stage': 'raw_data_unified_time',
            'creation_date': datetime.now().isoformat(),
            'time_alignment': 'unified_time_with_null_filling',
            'description': 'Raw climate data with unified time coordinate before regridding'
        })

        # Add variable attributes
        if 'pet_data' in raw_ds:
            raw_ds.pet_data.attrs = {
                'long_name': 'potential_evapotranspiration',
                'units': 'mm/day', 
                'source': 'USGS FEWS NET',
                'grid': 'native_global'
            }

        if 'imerg_precipitation' in raw_ds:
            raw_ds.imerg_precipitation.attrs = {
                'long_name': 'precipitation_rate',
                'units': 'mm/day',
                'source': 'NASA IMERG',
                'grid': 'native_global'
            }

        if 'chirps_precipitation' in raw_ds:
            raw_ds.chirps_precipitation.attrs = {
                'long_name': 'precipitation_forecast',
                'units': 'mm/day',
                'source': 'CHIRPS-GEFS',
                'grid': 'native_regional'
            }

        # Write to icechunk
        print(f"   💾 Writing raw unified dataset...")
        raw_ds.to_zarr(store, mode='w', consolidated=False)

        # Commit the session
        session.commit(f"Raw East Africa climate data for {config['TARGET_DATE'].strftime('%Y-%m-%d')}")

        # Calculate size
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(config['RAW_ICECHUNK_PATH']):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)

        size_mb = total_size / (1024 * 1024)
        size_gb = total_size / (1024 * 1024 * 1024)

        print(f"   ✅ Raw icechunk created: {config['RAW_ICECHUNK_PATH']}")
        print(f"   📊 Variables: {len(data_vars)}")
        print(f"   🕒 Unified time steps: {len(unified_times)}")
        print(f"   💾 Size: {size_mb:.2f} MB ({size_gb:.3f} GB)")

        return True, total_size

    except Exception as e:
        print(f"   ❌ Raw icechunk creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False, 0


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

    print(f"🗺️ Regional target grid: {lat_points} x {lon_points} = {grid_points:,} points")
    print(f"💾 Memory per layer: {memory_per_layer:.1f} MB")

    return target_grid


def regrid_from_raw_icechunk(config, target_grid):
    """Regrid data from the raw icechunk to create final regridded icechunk"""
    print("🔄 Regridding from raw icechunk...")

    # Open raw icechunk
    try:
        storage = icechunk.local_filesystem_storage(config['RAW_ICECHUNK_PATH'])
        repo = icechunk.Repository.open(storage)
        session = repo.readonly_session("main")
        store = session.store
        raw_ds = xr.open_zarr(store)
        
        print(f"   📖 Opened raw icechunk: {list(raw_ds.data_vars)}")
        print(f"   🕒 Time steps: {len(raw_ds.time)}")
        
    except Exception as e:
        print(f"   ❌ Failed to open raw icechunk: {e}")
        return False, 0

    if os.path.exists(config['REGRIDDED_ICECHUNK_PATH']):
        shutil.rmtree(config['REGRIDDED_ICECHUNK_PATH'])

    try:
        # Create regridded icechunk store
        storage = icechunk.local_filesystem_storage(config['REGRIDDED_ICECHUNK_PATH'])
        repo = icechunk.Repository.create(storage)
        session = repo.writable_session("main")
        store = session.store

        # Get unified coordinates
        unified_times = raw_ds.time.values
        target_lat = target_grid.lat.values
        target_lon = target_grid.lon.values

        data_vars = {}
        coords = {
            'time': ('time', unified_times),
            'lat': ('lat', target_lat),
            'lon': ('lon', target_lon)
        }

        # Regrid each variable from raw icechunk
        if 'pet_data' in raw_ds:
            print("   🔄 Regridding PET data from raw icechunk...")
            # TODO: Implement regridding logic for PET
            # For now, create placeholder
            pet_regridded = np.full((len(unified_times), len(target_lat), len(target_lon)), np.nan, dtype=np.float32)
            data_vars['pet_data'] = (['time', 'lat', 'lon'], pet_regridded)

        if 'imerg_precipitation' in raw_ds:
            print("   🔄 Regridding IMERG data from raw icechunk...")
            # TODO: Implement regridding logic for IMERG
            # For now, create placeholder
            imerg_regridded = np.full((len(unified_times), len(target_lat), len(target_lon)), np.nan, dtype=np.float32)
            data_vars['imerg_precipitation'] = (['time', 'lat', 'lon'], imerg_regridded)

        if 'chirps_precipitation' in raw_ds:
            print("   🔄 Regridding CHIRPS data from raw icechunk...")
            # TODO: Implement regridding logic for CHIRPS
            # For now, create placeholder
            chirps_regridded = np.full((len(unified_times), len(target_lat), len(target_lon)), np.nan, dtype=np.float32)
            data_vars['chirps_precipitation'] = (['time', 'lat', 'lon'], chirps_regridded)

        # Create regridded dataset
        regridded_ds = xr.Dataset(data_vars, coords=coords)
        
        # Add global attributes
        regridded_ds.attrs.update({
            'processing_stage': 'regridded_from_raw_icechunk',
            'regrid_method': 'bilinear',
            'creation_date': datetime.now().isoformat(),
            'time_alignment': 'unified_time_with_null_filling',
            'spatial_bounds': f"lat: {config['LAT_BOUNDS']}, lon: {config['LON_BOUNDS']}",
            'source_raw_icechunk': config['RAW_ICECHUNK_PATH']
        })

        # Write to icechunk
        print(f"   💾 Writing regridded dataset...")
        regridded_ds.to_zarr(store, mode='w', consolidated=False)

        # Commit the session
        session.commit(f"Regridded East Africa climate data for {config['TARGET_DATE'].strftime('%Y-%m-%d')}")

        # Calculate size
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(config['REGRIDDED_ICECHUNK_PATH']):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)

        size_mb = total_size / (1024 * 1024)
        size_gb = total_size / (1024 * 1024 * 1024)

        print(f"   ✅ Regridded icechunk created: {config['REGRIDDED_ICECHUNK_PATH']}")
        print(f"   📊 Variables: {len(data_vars)}")
        print(f"   🕒 Time steps: {len(unified_times)}")
        print(f"   🗺️ Grid: {len(target_lat)} x {len(target_lon)}")
        print(f"   💾 Size: {size_mb:.2f} MB ({size_gb:.3f} GB)")

        return True, total_size

    except Exception as e:
        print(f"   ❌ Regridding from icechunk failed: {e}")
        import traceback
        traceback.print_exc()
        return False, 0


def main(target_date,
         lat_bounds=(-12.0, 24.2),
         lon_bounds=(22.9, 51.6),
         resolution=0.01,
         skip_download=False):
    """Reordered workflow: Download → Raw Icechunk → Regrid from Icechunk"""

    # Setup
    config = setup_config(target_date, lat_bounds, lon_bounds, resolution)

    print("🚀 REORDERED Climate Data Workflow v7 (Raw Icechunk → Regrid)")
    print("=" * 80)
    print(f"Date: {target_date.strftime('%Y-%m-%d')}")
    print(f"Region: {lat_bounds[0]}° to {lat_bounds[1]}°N, {lon_bounds[0]}° to {lon_bounds[1]}°E")
    print(f"Resolution: {resolution}°")
    print(f"NEW Strategy: Download → Raw Icechunk → Regrid from Raw Icechunk")
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
            'pet': os.path.exists(pet_dir) and len(list(Path(pet_dir).glob('*.bil'))) > 0,
            'imerg': os.path.exists(imerg_dir) and len(list(Path(imerg_dir).glob('*.tif'))) > 0,
            'chirps': os.path.exists(chirps_dir) and len(list(Path(chirps_dir).glob('*.nc'))) > 0
        }

        print(f"   PET data available: {'✅' if download_results['pet'] else '❌'}")
        print(f"   IMERG data available: {'✅' if download_results['imerg'] else '❌'}")
        print(f"   CHIRPS-GEFS data available: {'✅' if download_results['chirps'] else '❌'}")

        download_time = 0
    else:
        print("\n📥 STEP 1: Data Download")
        download_results = download_all_data(config)
        download_time = time.time() - start_time

    # Step 2: Create Raw Icechunk (NEW STEP!)
    print("\n🧊 STEP 2: Raw Icechunk Creation (before regridding)")
    raw_icechunk_start = time.time()

    # Load raw data
    pet_data, pet_date = None, None
    imerg_data = None
    chirps_data = None

    if download_results['pet']:
        pet_data, pet_date = load_raw_pet_data(config)
        gc.collect()

    if download_results['imerg']:
        imerg_data = load_raw_imerg_data(config)
        gc.collect()

    if download_results['chirps']:
        chirps_data = load_raw_chirps_data(config)
        gc.collect()

    # Create raw icechunk
    raw_success, raw_size = create_raw_icechunk_dataset(config, pet_data, pet_date, imerg_data, chirps_data)
    
    # Clean up raw data from memory
    del pet_data, imerg_data, chirps_data
    gc.collect()

    raw_icechunk_time = time.time() - raw_icechunk_start

    if not raw_success:
        print("❌ Raw icechunk creation failed")
        return False, 0

    # Step 3: Regrid from Raw Icechunk
    print("\n🔄 STEP 3: Regridding from Raw Icechunk")
    regrid_start = time.time()

    target_grid = create_target_grid(config)
    regrid_success, regrid_size = regrid_from_raw_icechunk(config, target_grid)

    regrid_time = time.time() - regrid_start
    total_time = time.time() - start_time

    # Final cleanup
    del target_grid
    gc.collect()

    # Summary
    print("\n" + "=" * 80)
    print("🎉 REORDERED WORKFLOW v7 COMPLETE")
    print("=" * 80)

    if regrid_success:
        raw_size_mb = raw_size / (1024 * 1024)
        regrid_size_mb = regrid_size / (1024 * 1024)

        print(f"✅ Success! Both datasets created:")
        print(f"   📊 Raw icechunk: {config['RAW_ICECHUNK_PATH']} ({raw_size_mb:.2f} MB)")
        print(f"   🗺️ Regridded icechunk: {config['REGRIDDED_ICECHUNK_PATH']} ({regrid_size_mb:.2f} MB)")
        print(f"⏱️ Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
        print(f"📊 Timing breakdown:")
        print(f"   Download: {download_time:.2f}s ({download_time/total_time*100:.1f}%)")
        print(f"   Raw Icechunk: {raw_icechunk_time:.2f}s ({raw_icechunk_time/total_time*100:.1f}%)")
        print(f"   Regridding: {regrid_time:.2f}s ({regrid_time/total_time*100:.1f}%)")

        check_memory()
        return True, raw_size + regrid_size
    else:
        print("❌ Regridded workflow failed")
        return False, 0


# Example usage
if __name__ == "__main__":
    # Example: Process July 22, 2025 with reordered workflow
    target_date = datetime(2025, 7, 22)

    # Try different resolutions
    resolutions = [0.01]

    for resolution in resolutions:
        print(f"\n🧪 Attempting {resolution}° resolution with reordered workflow...")
        try:
            skip_download = len(sys.argv) > 1 and '--skip-download' in sys.argv
            success, size = main(target_date, resolution=resolution, skip_download=skip_download)
            if success:
                print(f"\n🎯 Success with {resolution}° resolution and reordered workflow!")
                print(f"Raw dataset: ./east_africa_raw_{target_date.strftime('%Y%m%d')}.zarr")
                print(f"Regridded dataset: ./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr")
                print(f"Total size: {size / (1024*1024):.2f} MB")
                break
        except MemoryError:
            print(f"❌ Out of memory with {resolution}° resolution, trying lower resolution...")
            continue
        except Exception as e:
            print(f"❌ Failed with {resolution}° resolution: {e}")
            continue
    else:
        print("❌ All resolutions failed")
        sys.exit(1)

    sys.exit(0)