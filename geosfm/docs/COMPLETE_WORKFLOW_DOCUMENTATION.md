# Complete Workflow Documentation: Download → Regrid → Icechunk

This document provides the complete file list and step-by-step instructions to duplicate the workflow for downloading three climate variables (PET, IMERG, CHIRPS-GEFS), regridding to 0.01° resolution, and creating icechunk datasets.

## 📁 Required Files

### 1. Core Download Script
**File**: `download_pet_imerg_chirpsgefs.py`
- **Purpose**: Downloads PET, IMERG, and CHIRPS-GEFS data for specified date/region
- **Location**: `/home/runner/workspace/download_pet_imerg_chirpsgefs.py`
- **Dependencies**: requests, beautifulsoup4, python-dotenv, xarray, numpy, pandas
- **Key Features**:
  - PET: Downloads USGS FEWS NET BIL files
  - IMERG: Downloads NASA IMERG TIFF files (7-day history)
  - CHIRPS-GEFS: Creates kerchunk references for 16-day forecast TIFF files

### 2. Environment Configuration
**File**: `.env` (you need to create this)
- **Purpose**: Stores IMERG credentials
- **Location**: `/home/runner/workspace/.env`
- **Required content**:
```
imerg_username=your_username
imerg_password=your_password
```

### 3. Micromamba Environment Setup
**Directory**: `micromamba_dir/`
- **Purpose**: Contains Python 3.13 environment with all required packages
- **Location**: `/home/runner/workspace/micromamba_dir/`
- **Key packages**: xesmf, icechunk, zarr, rioxarray, obstore, kerchunk

### 4. Working Test Scripts

#### A. Size Estimation Script
**File**: `test_size_estimate_20250721.py`
- **Purpose**: Estimates final dataset size at different resolutions
- **Location**: `/home/runner/workspace/test_size_estimate_20250721.py`
- **Output**: Size projections and test dataset creation

#### B. Simple Icechunk Test
**File**: `simple_icechunk_test.py`
- **Purpose**: Basic icechunk creation test with dummy data
- **Location**: `/home/runner/workspace/simple_icechunk_test.py`
- **Output**: Working icechunk dataset for testing

#### C. Full Regridding Script (Template)
**File**: `create_regridded_icechunk_complete.py` (see below)
- **Purpose**: Complete workflow implementation
- **Location**: Create as `/home/runner/workspace/create_regridded_icechunk_complete.py`

### 5. Documentation Files
- `ICECHUNK_SUCCESS_DOCUMENTATION.md`: Setup guide
- `ICECHUNK_SIZE_ANALYSIS_20250721.md`: Size analysis results
- `COMPLETE_WORKFLOW_DOCUMENTATION.md`: This file

## 🔧 Complete Implementation Script

Create this file as the main workflow script:

**File**: `create_regridded_icechunk_complete.py`

```python
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
        return False
    
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
```

## 🚀 Setup Instructions

### 1. Environment Setup

```bash
# Create micromamba environment
mkdir micromamba_dir
export MAMBA_ROOT_PREFIX='/home/runner/workspace/micromamba_dir'

# Create base environment
micromamba create -n base -c conda-forge -y python

# Install all required packages
micromamba install -n base -c conda-forge -y \
    xesmf \
    icechunk \
    zarr \
    numcodecs \
    rioxarray \
    scipy \
    obstore \
    kerchunk \
    requests \
    beautifulsoup4 \
    python-dotenv
```

### 2. Credentials Setup

Create `.env` file:
```bash
# Create credentials file
cat > /home/runner/workspace/.env << EOF
imerg_username=your_nasa_earthdata_username
imerg_password=your_nasa_earthdata_password
EOF
```

### 3. Run Complete Workflow

```bash
# Set environment
PYTHONPATH=/home/runner/workspace/micromamba_dir/lib/python3.13/site-packages

# Run workflow
/home/runner/workspace/micromamba_dir/bin/python \
/home/runner/workspace/create_regridded_icechunk_complete.py
```

## 📊 Expected Outputs

### File Structure After Execution:
```
/home/runner/workspace/
├── 20250721/                          # Downloaded data
│   ├── pet_data/
│   │   └── et250721.bil               # PET binary file
│   ├── imerg_data/
│   │   └── *.tif                      # 7 IMERG TIFF files
│   └── chirps_gefs_data/
│       └── *.nc                       # CHIRPS-GEFS NetCDF
├── east_africa_regridded_20250721.zarr/  # Final icechunk dataset
│   ├── chunks/                        # Data chunks
│   ├── manifests/                     # Chunk manifests
│   ├── refs/                          # References
│   └── snapshots/                     # Version snapshots
└── micromamba_dir/                    # Python environment
```

### Expected Performance:
- **Total time**: 15-30 seconds
- **Final dataset size**: ~300 MB
- **Grid resolution**: 0.01° (11.2 million points)
- **Variables**: PET + IMERG + CHIRPS-GEFS (if available)

## 🎯 Usage for Different Dates/Regions

### Change Date:
```python
# In create_regridded_icechunk_complete.py
target_date = datetime(2025, 7, 25)  # Change date
```

### Change Region:
```python
# Different region bounds
lat_bounds = (-20.0, 30.0)  # Larger area
lon_bounds = (15.0, 60.0)   # Extended longitude
```

### Change Resolution:
```python
# Different resolution
resolution = 0.05  # 0.05° instead of 0.01°
```

## ⚠️ Important Notes

### Dependencies:
1. **NASA Earthdata account** required for IMERG downloads
2. **Internet connection** for data downloads
3. **~500 MB disk space** for temporary files
4. **4-6 GB RAM minimum** for 0.01° regridding (see RAM analysis below)
5. **Recommended: 8+ GB RAM** for safe processing

## 💾 RAM Requirements Analysis

### STEP 2: Regridding Memory Requirements

**Critical Information**: The regridding step is the most memory-intensive part of the workflow.

#### Target Grid Specifications:
- **Grid Size**: 3,501 × 3,201 = 11,206,701 points
- **Resolution**: 0.01° (≈1.1 km)
- **Total Variables**: 24 layers per day
  - 1 PET layer (single time)
  - 7 IMERG layers (7-day history)
  - 16 CHIRPS-GEFS layers (16-day forecast)

#### Memory Calculations:

**Per Variable Memory Usage**:
- **Float32 data**: 11,206,701 points × 4 bytes = **44.8 MB per layer**
- **Float64 coordinates**: Lat/lon grids = **~0.5 MB**

**Peak Memory Requirements**:

1. **Source Data Loading**:
   - Original resolution data: **~50-100 MB**
   - Multiple source formats simultaneously

2. **Regridding Process (xesmf)**:
   - **Source grid**: Original resolution data
   - **Target grid**: 44.8 MB per variable
   - **Regridding weights**: Can be **500MB - 2GB** depending on source/target resolution difference
   - **Temporary arrays**: 2-3x the target size during interpolation

3. **Per Variable Peak Usage**:
   ```
   PET:         ~150 MB (1 layer + weights + temp arrays)
   IMERG:       ~500 MB (7 layers + weights + temp arrays)  
   CHIRPS-GEFS: ~1.2 GB (16 layers + weights + temp arrays)
   ```

4. **Total Peak Memory**: **~2-4 GB**
   - **Conservative estimate**: 2.5 GB
   - **Safe requirement**: 4-6 GB RAM
   - **Recommended**: 8+ GB RAM

#### Memory Optimization Strategies:

**Option 1: Sequential Processing (Recommended)**
```python
# Process one variable at a time to reduce memory
def process_sequentially():
    pet_data = process_pet()      # ~150 MB peak
    del unnecessary_arrays        # Free memory
    
    imerg_data = process_imerg()  # ~500 MB peak  
    del unnecessary_arrays
    
    chirps_data = process_chirps() # ~1.2 GB peak
    del unnecessary_arrays
```

**Option 2: Chunked Processing**
```python
# Process in smaller spatial chunks
def process_in_chunks():
    for lat_chunk in lat_chunks:
        for lon_chunk in lon_chunks:
            chunk_data = process_chunk(lat_chunk, lon_chunk)
            write_chunk_to_store(chunk_data)
```

**Option 3: Lower Resolution First**
```python
# Test with lower resolution first
resolutions = [0.05, 0.02, 0.01]  # Start larger, go smaller
for res in resolutions:
    try:
        result = process_at_resolution(res)
        break  # Success - use this resolution
    except MemoryError:
        continue  # Try next lower resolution
```

#### GCP Machine Recommendations:

**Current Issue: n2-standard-2 (2 vCPU, 8 GB RAM)**
- **Status**: ❌ **Insufficient for 0.01° processing**
- **Bottleneck**: ~8 GB RAM < 2-4 GB requirement + OS overhead
- **Failure Point**: During CHIRPS-GEFS regridding (16 layers)

**Recommended GCP Machine Types**:

1. **n2-standard-4** (4 vCPU, 16 GB RAM)
   - **Status**: ✅ **Should work for 0.01°**
   - **Cost**: ~2x n2-standard-2
   - **Memory buffer**: 16 GB >> 4 GB requirement

2. **n2-highmem-2** (2 vCPU, 16 GB RAM)
   - **Status**: ✅ **Memory-optimized option**
   - **Cost**: Similar to n2-standard-4
   - **Use case**: Memory-bound workloads

3. **n2-standard-8** (8 vCPU, 32 GB RAM)
   - **Status**: ✅ **Overkill but very safe**
   - **Benefit**: Can process multiple days in parallel
   - **Cost**: ~4x n2-standard-2

**Alternative Approach: Use Smaller Resolution**
```python
# Instead of 0.01°, use 0.02° or 0.05°
target_date = datetime(2025, 7, 21)
success, size = main(target_date, resolution=0.02)  # 0.02° = 4x fewer points
```

#### Memory Monitoring Commands:
```bash
# Monitor memory usage during processing
watch -n 1 'free -h && ps aux --sort=-%mem | head -10'

# Check available memory before starting
free -h
cat /proc/meminfo | grep MemAvailable
```

### Troubleshooting:
1. **IMERG credentials**: Ensure `.env` file has correct NASA Earthdata credentials
2. **CHIRPS-GEFS**: May fail due to server availability - workflow continues with PET+IMERG
3. **Memory issues (CRITICAL)**: 
   - **Immediate fix**: Use 0.02° or 0.05° resolution instead of 0.01°
   - **Machine upgrade**: Use n2-standard-4 or n2-highmem-2
   - **Code fix**: Implement sequential processing (see memory optimization above)
4. **Network timeouts**: Retry download step if network is slow
5. **Process killed**: Usually indicates OOM (Out of Memory) - upgrade machine or reduce resolution

### Validation:

#### ❌ Common Error: GroupNotFoundError
When trying to open icechunk zarr files with standard xarray:
```python
import xarray as xr
ds = xr.open_zarr('east_africa_regridded_20250722.zarr')
# ❌ ERROR: GroupNotFoundError: No group found in store 'east_africa_regridded_20250722.zarr' at path ''
```

#### ✅ Correct Approach: Use Icechunk Store
Icechunk zarr files require special handling because they use icechunk's versioned storage format:

```python
import xarray as xr
import icechunk

# Method 1: Open with icechunk store (Recommended)
storage = icechunk.local_filesystem_storage('east_africa_regridded_20250722.zarr')
repo = icechunk.Repository.open(storage)
session = repo.readonly_session("main")  # Open main branch
store = session.store

ds = xr.open_zarr(store)
print(ds)
print(f"Variables: {list(ds.data_vars)}")
print(f"Grid size: {len(ds.lat)} x {len(ds.lon)}")
```

#### Alternative: List Groups First
If you need to explore the structure:
```python
import icechunk

# List available groups/snapshots
storage = icechunk.local_filesystem_storage('east_africa_regridded_20250722.zarr')
repo = icechunk.Repository.open(storage)

# List all snapshots/commits
print("Available snapshots:")
for snapshot in repo.snapshots():
    print(f"  - {snapshot}")

# Open specific snapshot
session = repo.readonly_session("main")
store = session.store
ds = xr.open_zarr(store)
```

#### Quick Validation Function
```python
def validate_icechunk_dataset(zarr_path):
    """Validate and inspect icechunk dataset"""
    import xarray as xr
    import icechunk
    
    try:
        # Open icechunk store
        storage = icechunk.local_filesystem_storage(zarr_path)
        repo = icechunk.Repository.open(storage)
        session = repo.readonly_session("main")
        store = session.store
        
        # Open dataset
        ds = xr.open_zarr(store)
        
        print(f"✅ Successfully opened: {zarr_path}")
        print(f"📊 Variables: {list(ds.data_vars)}")
        print(f"🗺️ Grid size: {len(ds.lat)} x {len(ds.lon)}")
        print(f"⏰ Time steps: {len(ds.time)}")
        print(f"📍 Spatial extent: {float(ds.lat.min()):.2f}° to {float(ds.lat.max()):.2f}°N, {float(ds.lon.min()):.2f}° to {float(ds.lon.max()):.2f}°E")
        
        return ds
        
    except Exception as e:
        print(f"❌ Error opening {zarr_path}: {e}")
        return None

# Usage
ds = validate_icechunk_dataset('east_africa_regridded_20250722.zarr')
```

This complete documentation provides everything needed to replicate the workflow for any date/region combination.