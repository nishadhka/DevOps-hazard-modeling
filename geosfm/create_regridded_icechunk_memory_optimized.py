#!/usr/bin/env python3
"""
Memory-Optimized Complete workflow v2: Download → Regrid → Icechunk
Features:
- Optimized for machines with limited RAM (4-8 GB)
- Sequential processing to minimize peak memory usage  
- xesmf regridder weight caching for massive memory savings
- Reuses saved regridding weights to avoid recreating 2-3GB weight matrices

Usage:
  python create_regridded_icechunk_memory_optimized_v2.py                  # Download + regrid
  python create_regridded_icechunk_memory_optimized_v2.py --skip-download  # Only regrid existing data
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
from download_pet_imerg_chirpsgefs import (
    download_pet_data, download_imerg_data, download_chirps_gefs_data
)

def setup_config(target_date, lat_bounds=(-12.0, 24.2), lon_bounds=(22.9, 51.6), resolution=0.01):
    """Setup configuration for processing"""
    config = {
        'TARGET_DATE': target_date,
        'LAT_BOUNDS': lat_bounds,
        'LON_BOUNDS': lon_bounds, 
        'TARGET_RESOLUTION': resolution,
        'OUTPUT_DIR': f"./{target_date.strftime('%Y%m%d')}",
        'ICECHUNK_PATH': f"./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr",
        'WEIGHTS_DIR': "./regridder_weights"  # New: directory for cached weights
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
    
    print(f"🗺️ Target grid: {lat_points} x {lon_points} = {grid_points:,} points")
    print(f"💾 Memory per layer: {memory_per_layer:.1f} MB")
    
    return target_grid

def get_or_create_regridder(source_ds, target_grid, method='bilinear', weights_dir="./regridder_weights"):
    """
    Get cached regridder or create new one and save weights
    
    This dramatically reduces memory usage by reusing pre-computed regridding weights.
    Weight files are typically small (few MB) but save 2-3GB of RAM during regridding.
    """
    
    # Create a unique identifier for this source->target grid combination
    source_shape = f"{len(source_ds.lat)}x{len(source_ds.lon)}"
    target_shape = f"{len(target_grid.lat)}x{len(target_grid.lon)}"
    
    # Get lat/lon bounds for more specific identification
    source_lat_range = f"{float(source_ds.lat.min()):.1f}to{float(source_ds.lat.max()):.1f}"
    source_lon_range = f"{float(source_ds.lon.min()):.1f}to{float(source_ds.lon.max()):.1f}"
    target_lat_range = f"{float(target_grid.lat.min()):.1f}to{float(target_grid.lat.max()):.1f}"
    target_lon_range = f"{float(target_grid.lon.min()):.1f}to{float(target_grid.lon.max()):.1f}"
    
    weight_filename = f"{method}_{source_shape}_{source_lat_range}_{source_lon_range}_to_{target_shape}_{target_lat_range}_{target_lon_range}.nc"
    weight_path = os.path.join(weights_dir, weight_filename)
    
    # Check if weights already exist
    if os.path.exists(weight_path):
        print(f"   🔄 Loading cached regridder weights: {weight_filename}")
        print(f"   📁 Weight file size: {os.path.getsize(weight_path) / (1024**2):.1f} MB")
        
        try:
            # Load regridder with pre-computed weights
            regridder = xe.Regridder(source_ds, target_grid, method, weights=weight_path)
            print(f"   ✅ Loaded cached regridder (~33ms vs several minutes)")
            return regridder
        except Exception as e:
            print(f"   ⚠️ Failed to load cached weights ({e}), creating new regridder...")
    
    # Create new regridder and save weights
    print(f"   🔧 Creating new regridder and saving weights...")
    print(f"   ⚠️ This may take several minutes and use 2-3GB RAM...")
    
    start_time = time.time()
    regridder = xe.Regridder(source_ds, target_grid, method)
    creation_time = time.time() - start_time
    
    # Save weights for future use
    try:
        saved_path = regridder.to_netcdf(weight_path)
        weight_size = os.path.getsize(weight_path) / (1024**2)
        print(f"   💾 Saved regridder weights: {weight_filename} ({weight_size:.1f} MB)")
        print(f"   ⏱️ Regridder creation time: {creation_time:.1f}s")
        print(f"   🔮 Next time this will load in ~33ms!")
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
                    print(f"💾 Available memory: {available_mb:.0f} MB ({available_gb:.1f} GB)")
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

def load_and_regrid_pet_optimized_v2(config, target_grid):
    """Memory-optimized PET processing with weight caching"""
    print("🌡️ Processing PET data (memory optimized v2)...")
    
    available_mem = check_memory()
    
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
        print(f"   📊 File size: {file_size} values ({file_size * 4 / (1024**2):.1f} MB)")
        
        # Determine dimensions with memory-efficient approach
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
            # Try factorization
            for i in range(100, int(np.sqrt(file_size)) + 1):
                if file_size % i == 0:
                    height, width = i, file_size // i
                    break
        
        if height is None:
            print(f"   ❌ Cannot determine dimensions for {file_size} values")
            return None
        
        data = data.reshape(height, width)
        data = np.where(data < -9000, np.nan, data)
        
        # Create coordinates
        lat_step = 180.0 / height
        lon_step = 360.0 / width
        lat_global = np.linspace(90 - lat_step/2, -90 + lat_step/2, height)
        lon_global = np.linspace(-180 + lon_step/2, 180 - lon_step/2, width)
        
        # Create dataset
        pet_ds = xr.Dataset({
            'pet': (['lat', 'lon'], data)
        }, coords={
            'lat': lat_global,
            'lon': lon_global
        })
        
        pet_ds.pet.attrs = {
            'long_name': 'potential_evapotranspiration',
            'units': 'mm/day',
            'source': 'USGS FEWS NET'
        }
        
        print("   🔄 Starting regridding with weight caching...")
        
        # Get cached regridder or create new one
        regridder = get_or_create_regridder(pet_ds, target_grid, 'bilinear', config['WEIGHTS_DIR'])
        
        # Apply regridding
        pet_regridded = regridder(pet_ds)
        
        # Aggressive cleanup to free memory immediately
        del regridder
        del pet_ds
        del data
        gc.collect()
        
        # Force more aggressive memory cleanup
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)  # Return freed memory to OS
        
        # Subset to region
        pet_regridded = pet_regridded.sel(
            lat=slice(config['LAT_BOUNDS'][0], config['LAT_BOUNDS'][1]),
            lon=slice(config['LON_BOUNDS'][0], config['LON_BOUNDS'][1])
        )
        
        print(f"   ✅ PET regridded: {pet_regridded.pet.shape}")
        print(f"   💾 Memory after PET: {check_memory():.0f} MB available")
        
        return pet_regridded
        
    except Exception as e:
        print(f"   ❌ PET processing failed: {e}")
        gc.collect()  # Clean up on failure
        return None

def load_and_regrid_imerg_optimized_v2(config, target_grid):
    """Memory-optimized IMERG processing with weight caching"""
    print("🛰️ Processing IMERG data (memory optimized v2)...")
    
    available_mem = check_memory()
    
    imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
    tiff_files = list(Path(imerg_dir).glob('*.tif'))
    
    if not tiff_files:
        print("   ❌ No IMERG files found")
        return None
    
    print(f"   📊 Processing {len(tiff_files)} IMERG files")
    
    try:
        # Process files in smaller batches to manage memory
        batch_size = min(3, len(tiff_files))  # Process 3 files at a time
        all_datasets = []
        
        for i in range(0, len(tiff_files), batch_size):
            batch_files = tiff_files[i:i+batch_size]
            print(f"   🔄 Processing batch {i//batch_size + 1}/{(len(tiff_files)-1)//batch_size + 1}")
            
            batch_datasets = []
            
            for tiff_file in batch_files:
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
                batch_datasets.append(ds)
            
            # Combine batch
            if batch_datasets:
                batch_combined = xr.concat(batch_datasets, dim='time')
                all_datasets.append(batch_combined)
                
                # Clean up batch datasets
                del batch_datasets
                gc.collect()
        
        # Combine all batches
        if not all_datasets:
            print("   ❌ No IMERG data loaded")
            return None
            
        imerg_combined = xr.concat(all_datasets, dim='time')
        
        # Clean up intermediate datasets
        del all_datasets
        gc.collect()
        
        # Rename precipitation variable
        if hasattr(imerg_combined, 'data_vars') and len(imerg_combined.data_vars) > 0:
            data_var = list(imerg_combined.data_vars)[0]
            imerg_combined = imerg_combined.rename({data_var: 'precipitation'})
        else:
            # Handle case where imerg_combined is a DataArray
            if hasattr(imerg_combined, 'name'):
                if imerg_combined.name != 'precipitation':
                    imerg_combined.name = 'precipitation'
            else:
                imerg_combined.name = 'precipitation'
            # Convert DataArray to Dataset
            imerg_combined = imerg_combined.to_dataset()
        
        imerg_combined.precipitation.attrs = {
            'long_name': 'precipitation_rate',
            'units': 'mm/day',
            'source': 'NASA IMERG'
        }
        
        print("   🔄 Starting regridding with weight caching...")
        
        # Get cached regridder or create new one
        regridder = get_or_create_regridder(imerg_combined, target_grid, 'bilinear', config['WEIGHTS_DIR'])
        
        # Apply regridding
        imerg_regridded = regridder(imerg_combined)
        
        # Clean up
        del regridder
        del imerg_combined
        gc.collect()
        
        # Subset to region
        imerg_regridded = imerg_regridded.sel(
            lat=slice(config['LAT_BOUNDS'][0], config['LAT_BOUNDS'][1]),
            lon=slice(config['LON_BOUNDS'][0], config['LON_BOUNDS'][1])
        )
        
        print(f"   ✅ IMERG regridded: {imerg_regridded.precipitation.shape}")
        print(f"   💾 Memory after IMERG: {check_memory():.0f} MB available")
        
        return imerg_regridded
        
    except Exception as e:
        print(f"   ❌ IMERG processing failed: {e}")
        gc.collect()
        return None

def load_and_regrid_chirps_optimized_v2(config, target_grid):
    """Memory-optimized CHIRPS-GEFS processing with weight caching"""
    print("🌧️ Processing CHIRPS-GEFS data (memory optimized v2)...")
    
    available_mem = check_memory()
    
    chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')
    nc_files = list(Path(chirps_dir).glob('*.nc'))
    
    if not nc_files:
        print("   ❌ No CHIRPS-GEFS files found")
        return None
    
    try:
        # Load NetCDF
        nc_file = nc_files[0]
        print(f"   📊 Loading: {nc_file.name}")
        
        # Open with chunks to manage memory
        chirps_ds = xr.open_dataset(nc_file, chunks={'time': 4})  # Process 4 time steps at once
        
        # Find precipitation variable
        precip_vars = [var for var in chirps_ds.data_vars if 'precip' in var.lower()]
        if not precip_vars:
            precip_vars = list(chirps_ds.data_vars)
        
        if precip_vars:
            chirps_ds = chirps_ds.rename({precip_vars[0]: 'precipitation'})
        
        chirps_ds.precipitation.attrs = {
            'long_name': 'precipitation_forecast',
            'units': 'mm/day',
            'source': 'CHIRPS-GEFS'
        }
        
        print(f"   🔄 Starting regridding ({len(chirps_ds.time)} time steps) with weight caching...")
        
        # Check if we need to process in chunks
        time_steps = len(chirps_ds.time)
        estimated_memory = time_steps * 44.8  # MB per time step
        
        if available_mem and estimated_memory > available_mem * 0.7:
            print(f"   ⚠️ Large dataset ({estimated_memory:.0f} MB) - processing in chunks")
            
            # Process in time chunks
            chunk_size = max(1, int(available_mem * 0.5 / 44.8))  # Conservative chunk size
            regridded_chunks = []
            
            # Get regridder once for all chunks (weights will be cached after first use)
            sample_chunk = chirps_ds.isel(time=slice(0, 1))
            regridder = get_or_create_regridder(sample_chunk, target_grid, 'bilinear', config['WEIGHTS_DIR'])
            
            for i in range(0, time_steps, chunk_size):
                end_idx = min(i + chunk_size, time_steps)
                chunk = chirps_ds.isel(time=slice(i, end_idx))
                
                print(f"     Processing time chunk {i+1}-{end_idx}/{time_steps}")
                
                # Apply regridding with cached regridder
                chunk_regridded = regridder(chunk)
                regridded_chunks.append(chunk_regridded)
                del chunk
                gc.collect()
            
            # Combine chunks
            chirps_regridded = xr.concat(regridded_chunks, dim='time')
            del regridded_chunks
            del regridder
            
        else:
            # Process all at once with cached regridder
            regridder = get_or_create_regridder(chirps_ds, target_grid, 'bilinear', config['WEIGHTS_DIR'])
            chirps_regridded = regridder(chirps_ds)
            del regridder
        
        # Clean up
        del chirps_ds
        gc.collect()
        
        # Subset to region
        chirps_regridded = chirps_regridded.sel(
            lat=slice(config['LAT_BOUNDS'][0], config['LAT_BOUNDS'][1]),
            lon=slice(config['LON_BOUNDS'][0], config['LON_BOUNDS'][1])
        )
        
        print(f"   ✅ CHIRPS-GEFS regridded: {chirps_regridded.precipitation.shape}")
        print(f"   💾 Memory after CHIRPS-GEFS: {check_memory():.0f} MB available")
        
        return chirps_regridded
        
    except Exception as e:
        print(f"   ❌ CHIRPS-GEFS processing failed: {e}")
        gc.collect()
        return None

def create_icechunk_dataset_optimized(config, pet_data, imerg_data, chirps_data):
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
        # Create icechunk store first
        storage = icechunk.local_filesystem_storage(config['ICECHUNK_PATH'])
        repo = icechunk.Repository.create(storage)
        session = repo.writable_session("main")
        store = session.store
        
        # Write variables one by one to minimize memory usage
        total_variables = 0
        
        if pet_data is not None:
            print("   📝 Writing PET data...")
            
            # Create dataset with just PET
            pet_values = pet_data['pet'].values
            if len(pet_values.shape) == 2:
                broadcasted = np.broadcast_to(
                    pet_values[np.newaxis, :, :],
                    (len(unique_times), len(lat_coord), len(lon_coord))
                )
            else:
                broadcasted = pet_values
                
            pet_ds = xr.Dataset({
                'pet': (['time', 'lat', 'lon'], broadcasted)
            }, coords={
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
            
            # Create aligned dataset for IMERG
            full_data = np.full(
                (len(unique_times), len(lat_coord), len(lon_coord)), 
                np.nan, dtype=np.float32
            )
            
            for i, time_val in enumerate(imerg_data['time'].values):
                if time_val in unique_times:
                    time_idx = unique_times.index(time_val)
                    full_data[time_idx, :, :] = imerg_data['precipitation'].values[i, :, :]
            
            imerg_ds = xr.Dataset({
                'imerg_precipitation': (['time', 'lat', 'lon'], full_data)
            }, coords={
                'time': unique_times,
                'lat': lat_coord,
                'lon': lon_coord
            })
            
            imerg_ds.imerg_precipitation.attrs = imerg_data['precipitation'].attrs
            
            if total_variables == 0:
                imerg_ds.to_zarr(store, mode='w', consolidated=False)
            else:
                imerg_ds.to_zarr(store, mode='a', consolidated=False)
            total_variables += 1
            
            del imerg_ds, full_data
            gc.collect()
        
        if chirps_data is not None:
            print("   📝 Writing CHIRPS-GEFS data...")
            
            # Create aligned dataset for CHIRPS-GEFS
            full_data = np.full(
                (len(unique_times), len(lat_coord), len(lon_coord)), 
                np.nan, dtype=np.float32
            )
            
            for i, time_val in enumerate(chirps_data['time'].values):
                if time_val in unique_times:
                    time_idx = unique_times.index(time_val)
                    full_data[time_idx, :, :] = chirps_data['precipitation'].values[i, :, :]
            
            chirps_ds = xr.Dataset({
                'chirps_gefs_precipitation': (['time', 'lat', 'lon'], full_data)
            }, coords={
                'time': unique_times,
                'lat': lat_coord,
                'lon': lon_coord
            })
            
            chirps_ds.chirps_gefs_precipitation.attrs = chirps_data['precipitation'].attrs
            
            if total_variables == 0:
                chirps_ds.to_zarr(store, mode='w', consolidated=False)
            else:
                chirps_ds.to_zarr(store, mode='a', consolidated=False)
            total_variables += 1
            
            del chirps_ds, full_data
            gc.collect()
        
        # Commit the session
        session.commit(f"East Africa climate data for {config['TARGET_DATE'].strftime('%Y-%m-%d')}")
        
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

def main(target_date, lat_bounds=(-12.0, 24.2), lon_bounds=(22.9, 51.6), resolution=0.01, skip_download=False):
    """Memory-optimized main workflow function with regridder caching"""
    
    # Setup
    config = setup_config(target_date, lat_bounds, lon_bounds, resolution)
    
    print("🚀 Memory-Optimized Climate Data Workflow v2 (with regridder caching)")
    print("=" * 80)
    print(f"Date: {target_date.strftime('%Y-%m-%d')}")
    print(f"Region: {lat_bounds[0]}° to {lat_bounds[1]}°N, {lon_bounds[0]}° to {lon_bounds[1]}°E")
    print(f"Resolution: {resolution}°")
    print(f"Weights cache: {config['WEIGHTS_DIR']}")
    print("=" * 80)
    
    # Check initial memory
    check_memory()
    
    start_time = time.time()
    
    # Step 1: Download (optional)
    if skip_download:
        print("\n📥 STEP 1: Skipping Download (using existing data)")
        # Check if data directories exist
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
    
    # Step 2: Sequential Regridding (memory optimized with caching)
    print("\n🗺️ STEP 2: Sequential Regridding (Memory Optimized v2 with Caching)")
    regrid_start = time.time()
    
    target_grid = create_target_grid(config)
    
    # Process variables sequentially to minimize peak memory
    pet_data = None
    imerg_data = None  
    chirps_data = None
    
    # Check memory before each processing step
    available_mem = check_memory()
    
    if download_results['pet']:
        print(f"   🔄 Starting PET processing (need ~3GB for new weights)")
        pet_data = load_and_regrid_pet_optimized_v2(config, target_grid)
        
        # Force memory cleanup after PET
        gc.collect()
        import ctypes
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except:
            pass
        
        available_mem = check_memory()
        print(f"   🧹 Cleaned up after PET processing")
    
    if download_results['imerg']:
        available_mem = check_memory()
        if available_mem and available_mem < 3500:  # Need at least 3.5GB for IMERG weights
            print(f"   ⚠️ Warning: Only {available_mem:.0f}MB available, IMERG may fail")
            print(f"   💡 Consider running PET-only or using lower resolution")
        
        print(f"   🔄 Starting IMERG processing (need ~3GB for new weights)")
        imerg_data = load_and_regrid_imerg_optimized_v2(config, target_grid)
        
        # Force memory cleanup after IMERG
        gc.collect()
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except:
            pass
        
        available_mem = check_memory()
        print(f"   🧹 Cleaned up after IMERG processing")
    
    if download_results['chirps']:
        available_mem = check_memory()
        if available_mem and available_mem < 3500:  # Need at least 3.5GB for CHIRPS weights
            print(f"   ⚠️ Warning: Only {available_mem:.0f}MB available, CHIRPS may fail")
            print(f"   💡 Consider skipping CHIRPS or using lower resolution")
        
        print(f"   🔄 Starting CHIRPS processing (need ~3GB for new weights)")
        chirps_data = load_and_regrid_chirps_optimized_v2(config, target_grid)
    
    regrid_time = time.time() - regrid_start
    
    # Step 3: Icechunk
    print("\n🧊 STEP 3: Memory-Optimized Icechunk Creation")
    icechunk_start = time.time()
    
    success, dataset_size = create_icechunk_dataset_optimized(config, pet_data, imerg_data, chirps_data)
    
    icechunk_time = time.time() - icechunk_start
    total_time = time.time() - start_time
    
    # Final cleanup
    del pet_data, imerg_data, chirps_data, target_grid
    gc.collect()
    
    # Summary
    print("\n" + "=" * 80)
    print("🎉 MEMORY-OPTIMIZED WORKFLOW v2 COMPLETE")
    print("=" * 80)
    
    if success:
        size_mb = dataset_size / (1024 * 1024)
        size_gb = dataset_size / (1024 * 1024 * 1024)
        
        print(f"✅ Success! Dataset created: {config['ICECHUNK_PATH']}")
        print(f"💾 Final size: {size_mb:.2f} MB ({size_gb:.3f} GB)")
        print(f"⏱️ Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
        print(f"📊 Timing breakdown:")
        print(f"   Download: {download_time:.2f}s ({download_time/total_time*100:.1f}%)")
        print(f"   Regridding: {regrid_time:.2f}s ({regrid_time/total_time*100:.1f}%)")
        print(f"   Icechunk: {icechunk_time:.2f}s ({icechunk_time/total_time*100:.1f}%)")
        
        # Show cache info
        weight_files = list(Path(config['WEIGHTS_DIR']).glob('*.nc'))
        if weight_files:
            total_cache_size = sum(f.stat().st_size for f in weight_files) / (1024**2)
            print(f"💾 Regridder cache: {len(weight_files)} files, {total_cache_size:.1f} MB")
        
        # Final memory check
        check_memory()
        
        return True, dataset_size
    else:
        print("❌ Workflow failed")
        return False, 0

# Example usage
if __name__ == "__main__":
    # Example: Process July 22, 2025 with memory optimization
    target_date = datetime(2025, 7, 22)
    
    # Try different resolutions if memory is limited
    resolutions = [0.02, 0.01]  # Start with 0.02° if 0.01° fails
    
    for resolution in resolutions:
        print(f"\n🧪 Attempting {resolution}° resolution...")
        try:
            # Check if this is being run as a script with skip_download option
            skip_download = len(sys.argv) > 1 and '--skip-download' in sys.argv
            success, size = main(target_date, resolution=resolution, skip_download=skip_download)
            if success:
                print(f"\n🎯 Success with {resolution}° resolution!")
                print(f"Dataset location: ./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr")
                print(f"Dataset size: {size / (1024*1024):.2f} MB")
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