#!/usr/bin/env python3
"""
Complete workflow: Download → Regrid → Icechunk
Downloads PET, IMERG, CHIRPS-GEFS → Regrids to 0.01° → Creates icechunk dataset
"""

import sys
import os
import time
import shutil
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

# Configuration
def setup_config(target_date, lat_bounds=(-12.0, 23.0), lon_bounds=(21.0, 53.0), resolution=0.01):
    """Setup configuration for processing"""
    config = {
        'TARGET_DATE': target_date,
        'LAT_BOUNDS': lat_bounds,
        'LON_BOUNDS': lon_bounds, 
        'TARGET_RESOLUTION': resolution,
        'OUTPUT_DIR': f"/home/runner/workspace/{target_date.strftime('%Y%m%d')}",
        'ICECHUNK_PATH': f"/home/runner/workspace/east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr"
    }
    
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
    
    print(f"🗺️ Target grid: {lat_points} x {lon_points} = {lat_points * lon_points:,} points")
    return target_grid

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

def load_and_regrid_pet(config, target_grid):
    """Load and regrid PET data"""
    print("🌡️ Processing PET data...")
    
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
        
        # Determine dimensions
        file_size = len(data)
        
        # Common PET grid dimensions
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
        data = np.where(data < -9000, np.nan, data)  # Remove invalid values
        
        # Create coordinates (assume global grid)
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
        
        # Regrid
        regridder = xe.Regridder(pet_ds, target_grid, 'bilinear')
        pet_regridded = regridder(pet_ds)
        
        # Subset to region
        pet_regridded = pet_regridded.sel(
            lat=slice(config['LAT_BOUNDS'][0], config['LAT_BOUNDS'][1]),
            lon=slice(config['LON_BOUNDS'][0], config['LON_BOUNDS'][1])
        )
        
        print(f"   ✅ PET regridded: {pet_regridded.pet.shape}")
        return pet_regridded
        
    except Exception as e:
        print(f"   ❌ PET processing failed: {e}")
        return None

def load_and_regrid_imerg(config, target_grid):
    """Load and regrid IMERG data"""
    print("🛰️ Processing IMERG data...")
    
    imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
    tiff_files = list(Path(imerg_dir).glob('*.tif'))
    
    if not tiff_files:
        print("   ❌ No IMERG files found")
        return None
    
    try:
        datasets = []
        
        for tiff_file in sorted(tiff_files):
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
            datasets.append(ds)
        
        # Combine
        imerg_combined = xr.concat(datasets, dim='time')
        data_var = list(imerg_combined.data_vars)[0]
        imerg_combined = imerg_combined.rename({data_var: 'precipitation'})
        
        imerg_combined.precipitation.attrs = {
            'long_name': 'precipitation_rate',
            'units': 'mm/day',
            'source': 'NASA IMERG'
        }
        
        # Regrid
        regridder = xe.Regridder(imerg_combined, target_grid, 'bilinear')
        imerg_regridded = regridder(imerg_combined)
        
        # Subset
        imerg_regridded = imerg_regridded.sel(
            lat=slice(config['LAT_BOUNDS'][0], config['LAT_BOUNDS'][1]),
            lon=slice(config['LON_BOUNDS'][0], config['LON_BOUNDS'][1])
        )
        
        print(f"   ✅ IMERG regridded: {imerg_regridded.precipitation.shape}")
        return imerg_regridded
        
    except Exception as e:
        print(f"   ❌ IMERG processing failed: {e}")
        return None

def load_and_regrid_chirps(config, target_grid):
    """Load and regrid CHIRPS-GEFS data"""
    print("🌧️ Processing CHIRPS-GEFS data...")
    
    chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')
    nc_files = list(Path(chirps_dir).glob('*.nc'))
    
    if not nc_files:
        print("   ❌ No CHIRPS-GEFS files found")
        return None
    
    try:
        # Load NetCDF
        nc_file = nc_files[0]
        chirps_ds = xr.open_dataset(nc_file)
        
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
        
        # Regrid
        regridder = xe.Regridder(chirps_ds, target_grid, 'bilinear')
        chirps_regridded = regridder(chirps_ds)
        
        # Subset
        chirps_regridded = chirps_regridded.sel(
            lat=slice(config['LAT_BOUNDS'][0], config['LAT_BOUNDS'][1]),
            lon=slice(config['LON_BOUNDS'][0], config['LON_BOUNDS'][1])
        )
        
        print(f"   ✅ CHIRPS-GEFS regridded: {chirps_regridded.precipitation.shape}")
        return chirps_regridded
        
    except Exception as e:
        print(f"   ❌ CHIRPS-GEFS processing failed: {e}")
        return None

def create_icechunk_dataset(config, pet_data, imerg_data, chirps_data):
    """Create final icechunk dataset"""
    print("🧊 Creating icechunk dataset...")
    
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
    
    # Create combined dataset
    combined_ds = xr.Dataset(coords={
        'time': unique_times,
        'lat': lat_coord,
        'lon': lon_coord
    })
    
    # Add variables
    if pet_data is not None:
        # Broadcast PET to all times
        pet_values = pet_data['pet'].values
        if len(pet_values.shape) == 2:
            broadcasted = np.broadcast_to(
                pet_values[np.newaxis, :, :],
                (len(unique_times), len(lat_coord), len(lon_coord))
            )
        else:
            broadcasted = pet_values
        combined_ds['pet'] = (['time', 'lat', 'lon'], broadcasted)
        combined_ds['pet'].attrs = pet_data['pet'].attrs
    
    if imerg_data is not None:
        combined_ds['imerg_precipitation'] = imerg_data['precipitation']
        combined_ds['imerg_precipitation'].attrs = imerg_data['precipitation'].attrs
    
    if chirps_data is not None:
        combined_ds['chirps_gefs_precipitation'] = chirps_data['precipitation'] 
        combined_ds['chirps_gefs_precipitation'].attrs = chirps_data['precipitation'].attrs
    
    # Add global attributes
    combined_ds.attrs = {
        'title': f'East Africa Climate Data - 0.01° - {config["TARGET_DATE"].strftime("%Y-%m-%d")}',
        'institution': 'Claude Code Processing',
        'source': 'PET (USGS), IMERG (NASA), CHIRPS-GEFS (UCSB)',
        'resolution': f'{config["TARGET_RESOLUTION"]}°',
        'region': f'East Africa ({config["LAT_BOUNDS"][0]}° to {config["LAT_BOUNDS"][1]}°N, {config["LON_BOUNDS"][0]}° to {config["LON_BOUNDS"][1]}°E)',
        'processing_date': datetime.now().isoformat(),
        'target_date': config['TARGET_DATE'].strftime('%Y-%m-%d'),
        'regridding_method': 'xesmf bilinear interpolation',
        'storage_format': 'icechunk'
    }
    
    try:
        # Create icechunk
        storage = icechunk.local_filesystem_storage(config['ICECHUNK_PATH'])
        repo = icechunk.Repository.create(storage)
        session = repo.writable_session("main")
        store = session.store
        
        combined_ds.to_zarr(store, mode='w')
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
        print(f"   📊 Variables: {list(combined_ds.data_vars)}")
        print(f"   🗺️ Grid: {len(combined_ds.lat)} x {len(combined_ds.lon)}")
        print(f"   ⏰ Time steps: {len(combined_ds.time)}")
        print(f"   💾 Size: {size_mb:.2f} MB ({size_gb:.3f} GB)")
        
        return True, total_size
        
    except Exception as e:
        print(f"   ❌ Icechunk creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False, 0

def main(target_date, lat_bounds=(-12.0, 23.0), lon_bounds=(21.0, 53.0), resolution=0.01):
    """Main workflow function"""
    
    # Setup
    config = setup_config(target_date, lat_bounds, lon_bounds, resolution)
    
    print("🚀 Complete Climate Data Workflow")
    print("=" * 80)
    print(f"Date: {target_date.strftime('%Y-%m-%d')}")
    print(f"Region: {lat_bounds[0]}° to {lat_bounds[1]}°N, {lon_bounds[0]}° to {lon_bounds[1]}°E")
    print(f"Resolution: {resolution}°")
    print("=" * 80)
    
    start_time = time.time()
    
    # Step 1: Download
    print("\n📥 STEP 1: Data Download")
    download_results = download_all_data(config)
    download_time = time.time() - start_time
    
    # Step 2: Regrid
    print("\n🗺️ STEP 2: Regridding")
    regrid_start = time.time()
    
    target_grid = create_target_grid(config)
    
    pet_data = load_and_regrid_pet(config, target_grid) if download_results['pet'] else None
    imerg_data = load_and_regrid_imerg(config, target_grid) if download_results['imerg'] else None  
    chirps_data = load_and_regrid_chirps(config, target_grid) if download_results['chirps'] else None
    
    regrid_time = time.time() - regrid_start
    
    # Step 3: Icechunk
    print("\n🧊 STEP 3: Icechunk Creation")
    icechunk_start = time.time()
    
    success, dataset_size = create_icechunk_dataset(config, pet_data, imerg_data, chirps_data)
    
    icechunk_time = time.time() - icechunk_start
    total_time = time.time() - start_time
    
    # Summary
    print("\n" + "=" * 80)
    print("🎉 WORKFLOW COMPLETE")
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
        
        return True, dataset_size
    else:
        print("❌ Workflow failed")
        return False, 0

# Example usage
if __name__ == "__main__":
    # Example: Process July 21, 2025
    target_date = datetime(2025, 7, 21)
    success, size = main(target_date)
    
    if success:
        print(f"\n🎯 Ready for Dask processing!")
        print(f"Dataset location: /home/runner/workspace/east_africa_regridded_20250721.zarr")
        print(f"Dataset size: {size / (1024*1024):.2f} MB")
    
    sys.exit(0 if success else 1)