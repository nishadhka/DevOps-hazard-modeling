#!/usr/bin/env python3
"""
01-get-regrid.py - GeoSFM Data Download and Regridding Script

Memory-Optimized Complete workflow: Direct TIFF Download + Raw Zarr Creation
Features:
- Direct TIFF download using plain requests for CHIRPS-GEFS
- Creates raw zarr files for each dataset subset to East Africa region
- Updated East Africa extent: -12 to 23°N latitude, 21 to 53°E longitude  
- Uses 0.02° equal grid for regridded zarr icechunk creation
- Separate lat/lon coordinates for different grid resolutions in raw files
- All datasets subset to larger East Africa extent before processing

Usage:
  python 01-get-regrid.py --date-str 20250722                  # Download + process for specific date
  python 01-get-regrid.py --date-str 20250722 --skip-download  # Only process existing data
"""

import sys
import os
import time
import shutil
import gc
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Add current directory to path
sys.path.append('/home/runner/workspace')

import numpy as np
import xarray as xr
import icechunk
import rioxarray
import xesmf as xe


def setup_config(target_date,
                 lat_bounds=(-12.0, 23.0),
                 lon_bounds=(21.0, 53.0),
                 resolution=0.02):
    """Setup configuration for processing with updated East Africa extent"""
    config = {
        'TARGET_DATE': target_date,
        'LAT_BOUNDS': lat_bounds,
        'LON_BOUNDS': lon_bounds,
        'TARGET_RESOLUTION': resolution,
        'OUTPUT_DIR': f"./{target_date.strftime('%Y%m%d')}",
        'RAW_ZARR_DIR': f"./east_africa_raw_{target_date.strftime('%Y%m%d')}.zarr",
        'ICECHUNK_PATH': f"./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr",
        'WEIGHTS_DIR': "./02regridder_weights_regional"
    }

    # Create directories
    os.makedirs(config['WEIGHTS_DIR'], exist_ok=True)
    os.makedirs(config['OUTPUT_DIR'], exist_ok=True)

    return config


def extract_date_from_filename(filename, target_date):
    """Extract date from filename, fallback to target date"""
    try:
        filename_str = str(filename)
        
        # Common patterns for date extraction
        patterns = [
            # et250722.bil -> 20250722
            lambda f: f"20{f.split('et')[1][:6]}" if 'et' in f and f.split('et')[1][:6].isdigit() else None,
            
            # IMERG format: 3B-HHR-E.MS.MRG.3IMERG.20250715-S233000-E235959.1410.V07B.1day.tif
            lambda f: f.split('3IMERG.')[1][:8] if '3IMERG.' in f and len(f.split('3IMERG.')) > 1 and f.split('3IMERG.')[1][:8].isdigit() else None,
            
            # CHIRPS-GEFS: data.2025.0628.tif -> 2025-06-28
            lambda f: f"{f.split('.')[1]}-{f.split('.')[2][:2]}-{f.split('.')[2][2:]}" if len(f.split('.')) >= 3 and f.split('.')[1].isdigit() and f.split('.')[2].isdigit() else None,
            
            # YYYYMMDD anywhere in filename
            lambda f: next((s for s in f.split('_') + f.split('.') + f.split('-') if len(s) == 8 and s.isdigit()), None)
        ]
        
        for pattern in patterns:
            try:
                date_str = pattern(filename_str)
                if date_str and len(date_str) >= 8:
                    if '-' in date_str:
                        return datetime.strptime(date_str, '%Y-%m-%d')
                    else:
                        return datetime.strptime(date_str, '%Y%m%d')
            except:
                continue
                
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


def subset_to_region_robust(ds, lat_bounds, lon_bounds, buffer_deg=1.0):
    """Robust subsetting to East Africa region with buffer"""
    lat_min, lat_max = lat_bounds
    lon_min, lon_max = lon_bounds

    # Add buffer
    lat_min_buf = lat_min - buffer_deg
    lat_max_buf = lat_max + buffer_deg
    lon_min_buf = lon_min - buffer_deg
    lon_max_buf = lon_max + buffer_deg

    print(f"   📐 Subsetting to East Africa with {buffer_deg}° buffer:")
    print(f"      Target region: {lat_min}° to {lat_max}°N, {lon_min}° to {lon_max}°E")
    print(f"      Buffered region: {lat_min_buf}° to {lat_max_buf}°N, {lon_min_buf}° to {lon_max_buf}°E")

    try:
        # Get coordinate information
        lat_coord = ds.lat
        lon_coord = ds.lon

        print(f"      Source grid: {len(lat_coord)} x {len(lon_coord)} points")
        print(f"      Lat range: {float(lat_coord.min()):.1f}° to {float(lat_coord.max()):.1f}°")
        print(f"      Lon range: {float(lon_coord.min()):.1f}° to {float(lon_coord.max()):.1f}°")

        # Check coordinate order and fix if needed
        if lat_coord[0] > lat_coord[-1]:
            print(f"      🔄 Flipping latitude coordinate (descending → ascending)")
            ds = ds.isel(lat=slice(None, None, -1))
            lat_coord = ds.lat

        # Ensure longitude is in correct range
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
            print(f"      ⚠️ No points found in target region, using full dataset")
            return ds

        # Apply subsetting using isel
        lat_start, lat_end = lat_indices[0], lat_indices[-1] + 1
        lon_start, lon_end = lon_indices[0], lon_indices[-1] + 1

        ds_subset = ds.isel(lat=slice(lat_start, lat_end),
                            lon=slice(lon_start, lon_end))

        # Verify the subset
        subset_lat_min = float(ds_subset.lat.min())
        subset_lat_max = float(ds_subset.lat.max())
        subset_lon_min = float(ds_subset.lon.min())
        subset_lon_max = float(ds_subset.lon.max())

        print(f"      ✅ Subset result: {len(ds_subset.lat)} x {len(ds_subset.lon)} points")
        print(f"      Subset bounds: {subset_lat_min:.1f}° to {subset_lat_max:.1f}°N, {subset_lon_min:.1f}° to {subset_lon_max:.1f}°E")

        # Calculate reduction factor
        original_size = len(ds.lat) * len(ds.lon)
        subset_size = len(ds_subset.lat) * len(ds_subset.lon)
        if subset_size > 0:
            reduction_factor = original_size / subset_size
            print(f"      🎯 Size reduction: {original_size:,} → {subset_size:,} points ({reduction_factor:.1f}x smaller)")

        return ds_subset

    except Exception as e:
        print(f"      ❌ Robust subset failed: {e}")
        print(f"      🔄 Using full dataset as fallback")
        return ds


def download_chirps_gefs_tiff_files(config):
    """Download CHIRPS-GEFS TIFF files directly using requests"""
    print("🌧️ Downloading CHIRPS-GEFS TIFF files directly...")
    
    chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')
    os.makedirs(chirps_dir, exist_ok=True)
    
    try:
        # Build URL for the target date
        target_date = config['TARGET_DATE']
        chirps_url = f"https://data.chc.ucsb.edu/products/EWX/data/forecasts/CHIRPS-GEFS_precip_v12/daily_16day/{target_date.strftime('%Y')}/{target_date.strftime('%m')}/{target_date.strftime('%d')}/"
        
        print(f"🌐 URL: {chirps_url}")
        print(f"🔍 Discovering TIFF files...")
        
        # Get directory listing
        response = requests.get(chirps_url, timeout=30)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        tiff_files = []
        
        for link in soup.find_all('a'):
            href = link.get('href')
            if href and isinstance(href, str) and href.endswith('.tif'):
                full_url = urljoin(chirps_url + '/', href)
                tiff_files.append({
                    'filename': href,
                    'url': full_url
                })
        
        if not tiff_files:
            print("❌ No TIFF files found")
            return False
        
        print(f"✅ Found {len(tiff_files)} TIFF files")
        
        # Download each TIFF file
        downloaded_files = []
        for i, file_info in enumerate(tiff_files):
            print(f"\n📥 Downloading {i+1}/{len(tiff_files)}: {file_info['filename']}")
            
            try:
                response = requests.get(file_info['url'], timeout=300, stream=True)
                response.raise_for_status()
                
                # Save file
                file_path = os.path.join(chirps_dir, file_info['filename'])
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                print(f"\r📊 Progress: {progress:.1f}% ({downloaded}/{total_size} bytes)", end='')
                
                print(f"\n✅ Downloaded: {file_path}")
                print(f"📦 File size: {os.path.getsize(file_path):,} bytes")
                downloaded_files.append(file_path)
                
            except Exception as e:
                print(f"❌ Failed to download {file_info['filename']}: {str(e)}")
                continue
        
        print(f"\n📊 Downloaded {len(downloaded_files)}/{len(tiff_files)} CHIRPS-GEFS files")
        return len(downloaded_files) > 0
        
    except Exception as e:
        print(f"❌ CHIRPS-GEFS download failed: {str(e)}")
        return False


def download_pet_data_with_fallback(target_date, output_dir):
    """Download PET data with fallback to last available date"""
    print("\n🌡️ Downloading PET Data (with fallback)")
    print("=" * 50)
    
    # Try downloading for target date first
    for days_back in range(7):
        try_date = target_date - timedelta(days=days_back)
        pet_filename = f"et{try_date.strftime('%y%m%d')}.tar.gz"
        pet_url = f"https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/fews/web/global/daily/pet/downloads/daily/{pet_filename}"
        
        print(f"🔍 Trying date: {try_date.strftime('%Y-%m-%d')} (age: {days_back} days)")
        
        try:
            response = requests.head(pet_url, timeout=30)
            if response.status_code == 200:
                print(f"✅ Found available PET data: {try_date.strftime('%Y-%m-%d')}")
                
                # Download the file
                pet_dir = os.path.join(output_dir, 'pet_data')
                os.makedirs(pet_dir, exist_ok=True)
                
                print(f"📥 Downloading: {pet_filename}")
                
                response = requests.get(pet_url, timeout=300, stream=True)
                response.raise_for_status()
                
                # Save tar.gz file
                tar_path = os.path.join(pet_dir, pet_filename)
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(tar_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                print(f"\r📊 Progress: {progress:.1f}% ({downloaded}/{total_size} bytes)", end='')
                
                print(f"\n✅ Downloaded: {tar_path}")
                
                # Extract the tar.gz file
                print(f"📂 Extracting files...")
                import tarfile
                with tarfile.open(tar_path, 'r:gz') as tar:
                    tar.extractall(pet_dir)
                    extracted_files = tar.getnames()
                
                print(f"✅ Extracted {len(extracted_files)} files")
                
                # Look for the main BIL file
                bil_files = [f for f in extracted_files if f.endswith('.bil')]
                if bil_files:
                    print(f"🗺️ Found BIL file: {bil_files[0]}")
                    return True, try_date
                else:
                    print("❌ No BIL file found in archive")
                    continue
                    
            else:
                print(f"❌ No data available for {try_date.strftime('%Y-%m-%d')} (HTTP {response.status_code})")
                continue
                
        except Exception as e:
            print(f"❌ Failed to download {try_date.strftime('%Y-%m-%d')}: {str(e)}")
            continue
    
    print("❌ No PET data found for any date in the past 7 days")
    return False, None


def download_imerg_data_enhanced(config):
    """Download IMERG data with adaptive strategy"""
    print("\n🛰️ Downloading IMERG Data")
    print("=" * 50)
    
    try:
        # Mock credentials for now - user should provide these
        try:
            from dotenv import load_dotenv
            load_dotenv()
            username = os.getenv('imerg_username')
            password = os.getenv('imerg_password')
            
            if not username or not password:
                print("⚠️ IMERG credentials not found in .env file")
                return False
        except:
            print("⚠️ IMERG credentials not available")
            return False
        
        print(f"✅ Using credentials: {username[:3]}***")
        
        # Find last available IMERG date
        print("🔍 Finding last available IMERG date...")
        current_date = config['TARGET_DATE'] - timedelta(days=1)
        last_available = None
        
        for days_back in range(10):
            test_date = current_date - timedelta(days=days_back)
            filename = f"3B-HHR-E.MS.MRG.3IMERG.{test_date.strftime('%Y%m%d')}-S233000-E235959.1410.V07B.1day.tif"
            url = f"https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/early/{test_date.strftime('%Y')}/{test_date.strftime('%m')}/{filename}"
            
            response = requests.head(url, auth=(username, password), timeout=30)
            if response.status_code == 200:
                last_available = test_date
                print(f"✅ Found available data: {test_date.strftime('%Y-%m-%d')} (age: {days_back} days)")
                break
        
        if not last_available:
            print("❌ No IMERG data found")
            return False
        
        # Calculate 7-day range
        end_date = last_available
        start_date = end_date - timedelta(days=6)
        
        print(f"📅 Downloading range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        
        # Create IMERG directory
        imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
        os.makedirs(imerg_dir, exist_ok=True)
        
        # Download files for the date range
        downloaded_files = []
        current = start_date
        
        while current <= end_date:
            filename = f"3B-HHR-E.MS.MRG.3IMERG.{current.strftime('%Y%m%d')}-S233000-E235959.1410.V07B.1day.tif"
            url = f"https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/early/{current.strftime('%Y')}/{current.strftime('%m')}/{filename}"
            
            print(f"\n📥 Downloading: {filename}")
            
            try:
                response = requests.get(url, auth=(username, password), timeout=300, stream=True)
                response.raise_for_status()
                
                # Save file
                file_path = os.path.join(imerg_dir, filename)
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                print(f"\r📊 Progress: {progress:.1f}% ({downloaded}/{total_size} bytes)", end='')
                
                print(f"\n✅ Saved: {file_path}")
                print(f"📦 File size: {os.path.getsize(file_path):,} bytes")
                downloaded_files.append(filename)
                
            except Exception as e:
                print(f"❌ Failed to download {current.strftime('%Y-%m-%d')}: {str(e)}")
            
            current += timedelta(days=1)
        
        print(f"\n📊 Downloaded {len(downloaded_files)}/7 IMERG files")
        return len(downloaded_files) > 0
            
    except Exception as e:
        print(f"❌ IMERG download failed: {str(e)}")
        return False


def download_all_data_enhanced(config):
    """Enhanced download with direct TIFF download for CHIRPS-GEFS"""
    print("📥 Downloading all data sources (v9 - direct downloads)...")

    os.makedirs(config['OUTPUT_DIR'], exist_ok=True)

    # Download PET with fallback
    pet_success, pet_actual_date = download_pet_data_with_fallback(config['TARGET_DATE'], config['OUTPUT_DIR'])
    
    # Download IMERG
    imerg_success = download_imerg_data_enhanced(config)
    
    # Download CHIRPS-GEFS TIFF files directly
    chirps_success = download_chirps_gefs_tiff_files(config)

    return {
        'pet': pet_success,
        'imerg': imerg_success,
        'chirps': chirps_success,
        'pet_actual_date': pet_actual_date
    }


def load_and_process_pet_to_raw_zarr(config):
    """Load PET data and create raw zarr file subset to East Africa"""
    print("🌡️ Processing PET data to raw zarr...")

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
            (181, 360),    # 1° global
            (361, 720),    # 0.5° global
            (721, 1440),   # 0.25° global
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
            return None, None

        data = data.reshape(height, width)
        data = np.where(data < -9000, np.nan, data)

        # Create coordinates (global grid)
        lat_step = 180.0 / height
        lon_step = 360.0 / width
        lat_global = np.linspace(90 - lat_step / 2, -90 + lat_step / 2, height)
        lon_global = np.linspace(-180 + lon_step / 2, 180 - lon_step / 2, width)

        # Create global dataset
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

        # Subset to East Africa region
        print("   🎯 Subsetting PET to East Africa region...")
        pet_ds_regional = subset_to_region_robust(pet_ds_global,
                                                  config['LAT_BOUNDS'],
                                                  config['LON_BOUNDS'],
                                                  buffer_deg=1.0)

        # Clean up global dataset
        del pet_ds_global, data
        gc.collect()

        print(f"   ✅ PET regional subset: {pet_ds_regional.pet.shape}")
        
        return pet_ds_regional, pet_date

    except Exception as e:
        print(f"   ❌ PET processing failed: {e}")
        import traceback
        traceback.print_exc()
        gc.collect()
        return None, None


def load_and_process_imerg_to_raw_zarr(config):
    """Load IMERG data and create raw zarr file subset to East Africa"""
    print("🛰️ Processing IMERG data to raw zarr...")

    imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
    tiff_files = list(Path(imerg_dir).glob('*.tif'))

    if not tiff_files:
        print("   ❌ No IMERG files found")
        return None, None

    print(f"   📊 Processing {len(tiff_files)} IMERG files")

    try:
        regional_datasets = []
        imerg_dates = []

        for i, tiff_file in enumerate(sorted(tiff_files)):
            print(f"   🔄 Processing file {i+1}/{len(tiff_files)}: {tiff_file.name}")

            # Extract date from filename
            file_date = extract_date_from_filename(tiff_file.name, config['TARGET_DATE'])
            imerg_dates.append(file_date)

            # Load file
            ds = rioxarray.open_rasterio(tiff_file)
            ds = ds.squeeze('band').drop('band')

            if 'x' in ds.dims:
                ds = ds.rename({'x': 'lon', 'y': 'lat'})

            ds = ds.expand_dims('time')
            ds = ds.assign_coords(time=[file_date])

            # Subset to East Africa region
            print(f"      🎯 Subsetting IMERG file to East Africa region...")
            ds_regional = subset_to_region_robust(ds,
                                                  config['LAT_BOUNDS'],
                                                  config['LON_BOUNDS'],
                                                  buffer_deg=1.0)

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
        if hasattr(imerg_combined, 'data_vars') and len(imerg_combined.data_vars) > 0:
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

        print(f"   ✅ IMERG regional processing: {imerg_combined.precipitation.shape}")
        
        return imerg_combined, imerg_dates

    except Exception as e:
        print(f"   ❌ IMERG processing failed: {e}")
        import traceback
        traceback.print_exc()
        gc.collect()
        return None, None


def load_and_process_chirps_to_raw_zarr(config):
    """Load CHIRPS-GEFS TIFF files and create raw zarr file subset to East Africa"""
    print("🌧️ Processing CHIRPS-GEFS TIFF files to raw zarr...")

    chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')
    tiff_files = list(Path(chirps_dir).glob('*.tif'))

    if not tiff_files:
        print("   ❌ No CHIRPS-GEFS TIFF files found")
        return None, None

    print(f"   📊 Processing {len(tiff_files)} CHIRPS-GEFS TIFF files")

    try:
        regional_datasets = []
        chirps_times = []

        for i, tiff_file in enumerate(sorted(tiff_files)):
            print(f"   🔄 Processing file {i+1}/{len(tiff_files)}: {tiff_file.name}")

            # Extract date from filename
            file_date = extract_date_from_filename(tiff_file.name, config['TARGET_DATE'])
            chirps_times.append(file_date)

            # Load TIFF file
            ds = rioxarray.open_rasterio(tiff_file)
            ds = ds.squeeze('band').drop('band')

            # Standardize coordinate names
            if 'x' in ds.dims:
                ds = ds.rename({'x': 'lon', 'y': 'lat'})

            ds = ds.expand_dims('time')
            ds = ds.assign_coords(time=[file_date])

            # Add variable name
            if hasattr(ds, 'name') and ds.name is None:
                ds.name = 'precipitation'
            ds = ds.to_dataset(name='precipitation')

            # Subset to East Africa region
            print(f"      🎯 Subsetting CHIRPS-GEFS to East Africa region...")
            ds_regional = subset_to_region_robust(ds,
                                                  config['LAT_BOUNDS'],
                                                  config['LON_BOUNDS'],
                                                  buffer_deg=1.0)

            regional_datasets.append(ds_regional)

            # Clean up original dataset
            del ds
            gc.collect()

        # Combine regional datasets
        print("   🔗 Combining regional CHIRPS-GEFS datasets...")
        chirps_combined = xr.concat(regional_datasets, dim='time')

        # Clean up individual datasets
        del regional_datasets
        gc.collect()

        chirps_combined.precipitation.attrs = {
            'long_name': 'precipitation_forecast', 
            'units': 'mm/day',
            'source': 'CHIRPS-GEFS'
        }

        print(f"   ✅ CHIRPS-GEFS regional processing: {chirps_combined.precipitation.shape}")
        
        return chirps_combined, chirps_times

    except Exception as e:
        print(f"   ❌ CHIRPS-GEFS processing failed: {e}")
        import traceback
        traceback.print_exc()
        gc.collect()
        return None, None


def create_raw_zarr_files(config, pet_data, pet_date, imerg_data, imerg_dates, chirps_data, chirps_dates):
    """Create raw zarr files for each dataset with separate lat/lon coordinates"""
    print("💾 Creating raw zarr files with separate lat/lon coordinates...")

    if os.path.exists(config['RAW_ZARR_DIR']):
        shutil.rmtree(config['RAW_ZARR_DIR'])

    os.makedirs(config['RAW_ZARR_DIR'], exist_ok=True)

    try:
        total_variables = 0

        # Save PET data with its native coordinates
        if pet_data is not None:
            print("   📝 Writing PET raw data...")
            pet_raw_dir = os.path.join(config['RAW_ZARR_DIR'], 'pet')
            
            pet_ds = pet_data.copy()
            pet_ds = pet_ds.expand_dims('time')
            pet_ds = pet_ds.assign_coords(time=[pet_date])
            
            pet_ds.to_zarr(pet_raw_dir, consolidated=True)
            print(f"      ✅ PET saved: {pet_ds.pet.shape} at {pet_ds.lat.shape} x {pet_ds.lon.shape}")
            total_variables += 1

        # Save IMERG data with its native coordinates
        if imerg_data is not None:
            print("   📝 Writing IMERG raw data...")
            imerg_raw_dir = os.path.join(config['RAW_ZARR_DIR'], 'imerg')
            
            imerg_data.to_zarr(imerg_raw_dir, consolidated=True)
            print(f"      ✅ IMERG saved: {imerg_data.precipitation.shape} at {imerg_data.lat.shape} x {imerg_data.lon.shape}")
            total_variables += 1

        # Save CHIRPS-GEFS data with its native coordinates
        if chirps_data is not None:
            print("   📝 Writing CHIRPS-GEFS raw data...")
            chirps_raw_dir = os.path.join(config['RAW_ZARR_DIR'], 'chirps_gefs')
            
            chirps_data.to_zarr(chirps_raw_dir, consolidated=True)
            print(f"      ✅ CHIRPS-GEFS saved: {chirps_data.precipitation.shape} at {chirps_data.lat.shape} x {chirps_data.lon.shape}")
            total_variables += 1

        # Calculate total size
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(config['RAW_ZARR_DIR']):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)

        size_mb = total_size / (1024 * 1024)
        size_gb = total_size / (1024 * 1024 * 1024)

        print(f"   ✅ Raw zarr files created: {config['RAW_ZARR_DIR']}")
        print(f"   📊 Variables: {total_variables}")
        print(f"   💾 Total size: {size_mb:.2f} MB ({size_gb:.3f} GB)")

        return True, total_size

    except Exception as e:
        print(f"   ❌ Raw zarr creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False, 0


def get_or_create_regridder(source_ds, target_grid, method='bilinear', weights_dir="./02regridder_weights_regional"):
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
        print(f"   🔄 Loading cached regional weights ({os.path.getsize(weight_path) / (1024**2):.1f} MB)")

        try:
            regridder = xe.Regridder(source_ds, target_grid, method, weights=weight_path)
            print(f"   ✅ Loaded cached regridder")
            return regridder
        except Exception as e:
            print(f"   ⚠️ Failed to load cached weights: {e}")

    # Create new regridder
    print(f"   🔧 Creating new regional regridder...")
    print(f"   📊 Source: {len(source_ds.lat)} x {len(source_ds.lon)} → Target: {len(target_grid.lat)} x {len(target_grid.lon)}")

    start_time = time.time()
    regridder = xe.Regridder(source_ds, target_grid, method)
    creation_time = time.time() - start_time

    # Save weights
    try:
        regridder.to_netcdf(weight_path)
        weight_size = os.path.getsize(weight_path) / (1024**2)
        print(f"   💾 Saved regional weights ({weight_size:.1f} MB)")
        print(f"   ⏱️ Creation time: {creation_time:.1f}s")
    except Exception as e:
        print(f"   ⚠️ Failed to save weights: {e}")

    return regridder


def create_regridded_icechunk_dataset(config, pet_data, pet_date, imerg_data, imerg_dates, chirps_data, chirps_dates):
    """Create regridded icechunk dataset with unified time coordinate and 0.02° grid"""
    print("🧊 Creating regridded icechunk dataset with 0.02° grid...")

    if os.path.exists(config['ICECHUNK_PATH']):
        shutil.rmtree(config['ICECHUNK_PATH'])

    # Create target grid
    target_grid = create_target_grid(config)

    # Create unified time coordinate
    unified_times = create_unified_time_coordinate(pet_date, imerg_dates, chirps_dates)

    try:
        # Create icechunk store
        storage = icechunk.local_filesystem_storage(config['ICECHUNK_PATH'])
        repo = icechunk.Repository.create(storage)
        session = repo.writable_session("main")
        store = session.store

        # Get spatial coordinates from target grid
        lat_coord = target_grid['lat']
        lon_coord = target_grid['lon']

        total_variables = 0

        # Process and regrid PET data
        if pet_data is not None:
            print("   🔧 Regridding and writing PET data...")
            
            # Create regridder
            regridder = get_or_create_regridder(pet_data, target_grid, 'bilinear', config['WEIGHTS_DIR'])
            
            # Apply regridding
            pet_regridded = regridder(pet_data)
            
            # Create full time array
            pet_full_time = np.full((len(unified_times), len(lat_coord), len(lon_coord)), np.nan, dtype=np.float32)
            
            if pet_date in unified_times:
                time_idx = unified_times.index(pet_date)
                pet_full_time[time_idx, :, :] = pet_regridded['pet'].values

            pet_ds = xr.Dataset({'pet': (['time', 'lat', 'lon'], pet_full_time)},
                                coords={
                                    'time': unified_times,
                                    'lat': lat_coord,
                                    'lon': lon_coord
                                })

            pet_ds.pet.attrs = pet_data['pet'].attrs
            pet_ds.to_zarr(store, mode='w', consolidated=False)
            total_variables += 1

            del regridder, pet_regridded, pet_ds, pet_full_time
            gc.collect()

        # Process and regrid IMERG data
        if imerg_data is not None:
            print("   🔧 Regridding and writing IMERG data...")
            
            # Create regridder
            regridder = get_or_create_regridder(imerg_data, target_grid, 'bilinear', config['WEIGHTS_DIR'])
            
            # Apply regridding
            imerg_regridded = regridder(imerg_data)
            
            # Create full time array
            imerg_full_time = np.full((len(unified_times), len(lat_coord), len(lon_coord)), np.nan, dtype=np.float32)

            # Fill in available IMERG dates
            for i, imerg_time in enumerate(imerg_dates):
                if imerg_time in unified_times:
                    time_idx = unified_times.index(imerg_time)
                    imerg_full_time[time_idx, :, :] = imerg_regridded['precipitation'].values[i, :, :]

            imerg_ds = xr.Dataset(
                {'imerg_precipitation': (['time', 'lat', 'lon'], imerg_full_time)},
                coords={
                    'time': unified_times,
                    'lat': lat_coord,
                    'lon': lon_coord
                })

            imerg_ds.imerg_precipitation.attrs = imerg_data['precipitation'].attrs

            if total_variables == 0:
                imerg_ds.to_zarr(store, mode='w', consolidated=False)
            else:
                imerg_ds.to_zarr(store, mode='a', consolidated=False)
            total_variables += 1

            del regridder, imerg_regridded, imerg_ds, imerg_full_time
            gc.collect()

        # Process and regrid CHIRPS-GEFS data
        if chirps_data is not None:
            print("   🔧 Regridding and writing CHIRPS-GEFS data...")
            
            # Create regridder
            regridder = get_or_create_regridder(chirps_data, target_grid, 'bilinear', config['WEIGHTS_DIR'])
            
            # Apply regridding
            chirps_regridded = regridder(chirps_data)
            
            # Create full time array
            chirps_full_time = np.full((len(unified_times), len(lat_coord), len(lon_coord)), np.nan, dtype=np.float32)

            # Fill in available CHIRPS dates
            for i, chirps_time in enumerate(chirps_dates):
                if chirps_time in unified_times:
                    time_idx = unified_times.index(chirps_time)
                    chirps_full_time[time_idx, :, :] = chirps_regridded['precipitation'].values[i, :, :]

            chirps_ds = xr.Dataset(
                {'chirps_gefs_precipitation': (['time', 'lat', 'lon'], chirps_full_time)},
                coords={
                    'time': unified_times,
                    'lat': lat_coord,
                    'lon': lon_coord
                })

            chirps_ds.chirps_gefs_precipitation.attrs = chirps_data['precipitation'].attrs

            if total_variables == 0:
                chirps_ds.to_zarr(store, mode='w', consolidated=False)
            else:
                chirps_ds.to_zarr(store, mode='a', consolidated=False)
            total_variables += 1

            del regridder, chirps_regridded, chirps_ds, chirps_full_time
            gc.collect()

        # Commit the session
        session.commit(f"East Africa climate data regridded to 0.02° for {config['TARGET_DATE'].strftime('%Y-%m-%d')}")

        # Calculate size
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(config['ICECHUNK_PATH']):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)

        size_mb = total_size / (1024 * 1024)
        size_gb = total_size / (1024 * 1024 * 1024)

        print(f"   ✅ Regridded icechunk created: {config['ICECHUNK_PATH']}")
        print(f"   📊 Variables: {total_variables}")
        print(f"   🗺️ Grid: {len(lat_coord)} x {len(lon_coord)} at 0.02°")
        print(f"   ⏰ Unified time steps: {len(unified_times)}")
        print(f"   💾 Size: {size_mb:.2f} MB ({size_gb:.3f} GB)")

        return True, total_size

    except Exception as e:
        print(f"   ❌ Regridded icechunk creation failed: {e}")
        import traceback
        traceback.print_exc()
        return False, 0


def main(target_date,
         lat_bounds=(-12.0, 23.0),
         lon_bounds=(21.0, 53.0),
         resolution=0.02,
         skip_download=False):
    """Main workflow v9: Direct TIFF downloads + Raw zarr + Regridded icechunk"""

    # Setup
    config = setup_config(target_date, lat_bounds, lon_bounds, resolution)

    print("🚀 CLIMATE DATA WORKFLOW v9 (Direct TIFF + Raw Zarr + Regridded)")
    print("=" * 80)
    print(f"Date: {target_date.strftime('%Y-%m-%d')}")
    print(f"East Africa Region: {lat_bounds[0]}° to {lat_bounds[1]}°N, {lon_bounds[0]}° to {lon_bounds[1]}°E")
    print(f"Target Resolution: {resolution}° (regridded)")
    print(f"Strategy: Direct Downloads → Raw Zarr → Regridded Icechunk")
    print("=" * 80)

    start_time = time.time()

    # Step 1: Download data (optional)
    if skip_download:
        print("\n📥 STEP 1: Skipping Download (using existing data)")
        pet_dir = os.path.join(config['OUTPUT_DIR'], 'pet_data')
        imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
        chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')

        download_results = {
            'pet': os.path.exists(pet_dir) and len(list(Path(pet_dir).glob('*.bil'))) > 0,
            'imerg': os.path.exists(imerg_dir) and len(list(Path(imerg_dir).glob('*.tif'))) > 0,
            'chirps': os.path.exists(chirps_dir) and len(list(Path(chirps_dir).glob('*.tif'))) > 0,
            'pet_actual_date': target_date
        }

        print(f"   PET data available: {'✅' if download_results['pet'] else '❌'}")
        print(f"   IMERG data available: {'✅' if download_results['imerg'] else '❌'}")
        print(f"   CHIRPS-GEFS data available: {'✅' if download_results['chirps'] else '❌'}")

        download_time = 0
    else:
        print("\n📥 STEP 1: Direct Data Download")
        download_results = download_all_data_enhanced(config)
        download_time = time.time() - start_time

    # Step 2: Process data to raw zarr files
    print("\n💾 STEP 2: Creating Raw Zarr Files (East Africa subset)")
    raw_zarr_start = time.time()

    # Process each dataset
    pet_data, pet_date = None, None
    imerg_data, imerg_dates = None, None
    chirps_data, chirps_dates = None, None

    if download_results['pet']:
        pet_data, pet_date = load_and_process_pet_to_raw_zarr(config)
        gc.collect()

    if download_results['imerg']:
        imerg_data, imerg_dates = load_and_process_imerg_to_raw_zarr(config)
        gc.collect()

    if download_results['chirps']:
        chirps_result = load_and_process_chirps_to_raw_zarr(config)
        if chirps_result:
            chirps_data, chirps_dates = chirps_result
        gc.collect()

    # Create raw zarr files
    raw_success, raw_size = create_raw_zarr_files(config, pet_data, pet_date, imerg_data, imerg_dates, chirps_data, chirps_dates)
    raw_zarr_time = time.time() - raw_zarr_start

    # Step 3: Create regridded icechunk dataset
    print("\n🧊 STEP 3: Creating Regridded Icechunk Dataset (0.02° grid)")
    icechunk_start = time.time()

    regrid_success, regrid_size = create_regridded_icechunk_dataset(
        config, pet_data, pet_date, imerg_data, imerg_dates, chirps_data, chirps_dates)

    icechunk_time = time.time() - icechunk_start
    total_time = time.time() - start_time

    # Final cleanup
    del pet_data, imerg_data, chirps_data
    gc.collect()

    # Summary
    print("\n" + "=" * 80)
    print("🎉 WORKFLOW v9 COMPLETE")
    print("=" * 80)

    if raw_success and regrid_success:
        raw_size_mb = raw_size / (1024 * 1024)
        raw_size_gb = raw_size / (1024 * 1024 * 1024)
        regrid_size_mb = regrid_size / (1024 * 1024)
        regrid_size_gb = regrid_size / (1024 * 1024 * 1024)

        print(f"✅ Success! Datasets created:")
        print(f"   📁 Raw zarr: {config['RAW_ZARR_DIR']} ({raw_size_mb:.2f} MB / {raw_size_gb:.3f} GB)")
        print(f"   🧊 Regridded icechunk: {config['ICECHUNK_PATH']} ({regrid_size_mb:.2f} MB / {regrid_size_gb:.3f} GB)")
        print(f"⏱️ Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
        print(f"📊 Timing breakdown:")
        print(f"   Download: {download_time:.2f}s ({download_time/total_time*100:.1f}%)")
        print(f"   Raw zarr: {raw_zarr_time:.2f}s ({raw_zarr_time/total_time*100:.1f}%)")
        print(f"   Regridded: {icechunk_time:.2f}s ({icechunk_time/total_time*100:.1f}%)")

        # Show cache info
        weight_files = list(Path(config['WEIGHTS_DIR']).glob('*.nc'))
        if weight_files:
            total_cache_size = sum(f.stat().st_size for f in weight_files) / (1024**2)
            print(f"💾 Regridder cache: {len(weight_files)} files, {total_cache_size:.1f} MB")

        return True, raw_size + regrid_size
    else:
        print("❌ Workflow failed")
        return False, 0


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Download and regrid hydrological input data for GeoSFM model"
    )
    
    parser.add_argument(
        "--date-str", 
        type=str, 
        required=True,
        help="Date string in YYYYMMDD format (e.g., 20250722)"
    )
    
    parser.add_argument(
        "--skip-download", 
        action="store_true",
        help="Skip download phase and only process existing data"
    )
    
    parser.add_argument(
        "--lat-bounds", 
        type=float,
        nargs=2,
        default=(-12.0, 23.0),
        help="Latitude bounds (min max) for East Africa region"
    )
    
    parser.add_argument(
        "--lon-bounds", 
        type=float,
        nargs=2,
        default=(21.0, 53.0),
        help="Longitude bounds (min max) for East Africa region"
    )
    
    parser.add_argument(
        "--resolution", 
        type=float,
        default=0.02,
        help="Target grid resolution in degrees"
    )
    
    return parser.parse_args()

# Main execution
if __name__ == "__main__":
    args = parse_args()
    
    # Parse date string to datetime object
    try:
        target_date = datetime.strptime(args.date_str, '%Y%m%d')
    except ValueError as e:
        print(f"❌ Invalid date format '{args.date_str}'. Use YYYYMMDD format (e.g., 20250722)")
        sys.exit(1)
    
    print(f"Processing date: {target_date.strftime('%Y-%m-%d')}")
    print(f"Skip download: {args.skip_download}")
    print(f"Latitude bounds: {args.lat_bounds}")
    print(f"Longitude bounds: {args.lon_bounds}")
    print(f"Resolution: {args.resolution}°")

    try:
        success, total_size = main(
            target_date, 
            lat_bounds=tuple(args.lat_bounds),
            lon_bounds=tuple(args.lon_bounds),
            resolution=args.resolution,
            skip_download=args.skip_download
        )
        if success:
            print(f"\n🎯 Success with 01-get-regrid.py!")
            print(f"Raw zarr location: ./east_africa_raw_{target_date.strftime('%Y%m%d')}.zarr")
            print(f"Regridded icechunk location: ./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr")
            print(f"Total dataset size: {total_size / (1024*1024):.2f} MB")
        else:
            print("❌ Workflow failed")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)