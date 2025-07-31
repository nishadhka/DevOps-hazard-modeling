# Python Processing Workflow Documentation (01-07 Scripts)

## Overview

This document provides a detailed analysis of the Python processing workflows implemented in files 01-07, covering data download, regridding, spatial aggregation using flox, gap-filling mechanisms, and zarr upload processes for cloud-native data storage.

## Table of Contents

1. [Processing Pipeline Architecture](#processing-pipeline-architecture)
2. [Regridding Processes](#regridding-processes)
3. [Polygon-to-TIFF Conversion for Flox Integration](#polygon-to-tiff-conversion-for-flox-integration)
4. [Flox-Based Spatial Aggregation](#flox-based-spatial-aggregation)
5. [Gap-Filling Mechanisms](#gap-filling-mechanisms)
6. [Zarr Upload and Cloud Storage](#zarr-upload-and-cloud-storage)
7. [Detailed Workflow Analysis by File](#detailed-workflow-analysis-by-file)

## Processing Pipeline Architecture

### Overall Data Flow

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Data Source   │───►│  Download &     │───►│   Regridding    │
│ (Remote Servers)│    │   Processing    │    │ (0.01° → 1km)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                       │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Zone-based     │◄───│  Flox Groupby   │◄───│ Polygon-to-TIFF │
│ Aggregation     │    │  Operations     │    │  Conversion     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │
         ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ GEOSFM Input    │    │ Gap-filling &   │    │ Zarr Upload to  │
│ Files (CSV)     │    │ Forecast Ext.   │    │ Cloud Storage   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Regridding Processes

### Regridding Implementation

**Function:** `regrid_dataset()` in `utils.py:684-747`

```python
def regrid_dataset(input_ds, input_chunk_sizes, output_chunk_sizes, zone_extent, regrid_method="bilinear"):
    """
    Regrid dataset to 1km resolution using xESMF regridder
    """
    # 1. Extract spatial bounds from zone extent
    z1lat_min = zone_extent['lat_min']
    z1lat_max = zone_extent['lat_max']
    z1lon_min = zone_extent['lon_min']
    z1lon_max = zone_extent['lon_max']

    # 2. Create 0.01° output grid (approximately 1km resolution)
    ds_out = xr.Dataset({
        "lat": (["lat"], np.arange(z1lat_min, z1lat_max, 0.01), {"units": "degrees_north"}),
        "lon": (["lon"], np.arange(z1lon_min, z1lon_max, 0.01), {"units": "degrees_east"})
    }).chunk(output_chunk_sizes)

    # 3. Create xESMF regridder
    regridder = xe.Regridder(input_ds, ds_out, regrid_method)

    # 4. Apply regridding with chunking
    regridded = input_ds.groupby('time').map(regrid_chunk)
    
    # 5. Compute results with progress bar
    with ProgressBar():
        result = regridded.compute()
    
    return result
```

### Regridding Parameters by Data Source

| Data Source | Input Resolution | Output Resolution | Method | Chunk Sizes |
|-------------|------------------|-------------------|---------|-------------|
| **PET** | ~1km (variable) | 0.01° (~1km) | bilinear | `{'time': 10, 'lat': 30, 'lon': 30}` |
| **CHIRPS-GEFS** | 0.05° (~5.5km) | 0.01° (~1km) | bilinear | `{'time': 10, 'lat': 30, 'lon': 30}` |
| **IMERG** | 0.1° (~11km) | 0.01° (~1km) | bilinear | `{'time': 10, 'lat': 30, 'lon': 30}` |

### Why Regridding is Necessary

1. **Resolution Standardization**: Different data sources have different native resolutions
2. **Computational Efficiency**: 1km resolution balances detail with processing speed
3. **Zone Alignment**: Ensures proper alignment with polygon boundaries for accurate aggregation
4. **Memory Management**: Chunked processing prevents memory overflow

## Polygon-to-TIFF Conversion for Flox Integration

### TIFF Generation Process

**Function:** `make_zones_geotif()` in `utils.py:543-594`

```python
def make_zones_geotif(shapefl_name, km_str, zone_str):
    """
    Convert shapefile polygons to rasterized TIFF for flox operations
    """
    # 1. Read shapefile with geopandas
    gdf = gp.read_file(shapefl_name)
    
    # 2. Define raster properties
    pixel_size = km_str/100  # Convert km to degrees (approx 0.01°)
    minx, miny, maxx, maxy = gdf.total_bounds
    width = int((maxx - minx) / pixel_size)
    height = int((maxy - miny) / pixel_size)
    
    # 3. Create transformation matrix
    transform = from_bounds(minx, miny, maxx, maxy, width, height)
    
    # 4. Rasterize polygons using GRIDCODE values
    shapes = ((geom, value) for geom, value in zip(gdf.geometry, gdf['GRIDCODE']))
    raster = rasterize(shapes, out_shape=(height, width), transform=transform, 
                      fill=0, dtype=np.uint16)
    
    # 5. Save as GeoTIFF
    output_tiff_path = f'{output_dir}/ea_geofsm_prod_{zone_str}_{km_str}km.tif'
    with rasterio.open(output_tiff_path, 'w', driver='GTiff', ...) as dst:
        dst.write(raster, 1)
    
    return output_tiff_path
```

### TIFF Characteristics

- **Resolution**: 0.01° (approximately 1km)
- **Data Type**: `uint16` for GRIDCODE values
- **Projection**: Inherits from source shapefile (WGS84)
- **Fill Value**: 0 for areas outside polygons
- **Pixel Values**: GRIDCODE identifiers from shapefile

### Integration with Zone Processing

```python
def process_zone_from_combined(master_shapefile, zone_name, km_str, pds):
    """
    Process specific zone from combined shapefile
    """
    # 1. Filter shapefile to specific zone
    gdf = gp.read_file(master_shapefile)
    zone_gdf = gdf[gdf['zone'] == zone_name]
    
    # 2. Create temporary shapefile for this zone
    temp_shapefile = f"/tmp/{zone_name}_temp.shp"
    zone_gdf.to_file(temp_shapefile)
    
    # 3. Convert to TIFF for flox operations
    zone1_tif = make_zones_geotif(temp_shapefile, km_str, zone_name)
    
    # 4. Load TIFF as xarray dataset
    z1ds = rioxarray.open_rasterio(zone1_tif, chunks="auto").squeeze()
    z1crds = z1ds.rename(x='lon', y='lat')
    
    return z1ds, pdsz1, zone_extent
```

## Flox-Based Spatial Aggregation

### Flox Integration

**Library Import:** `import flox` and `import flox.xarray`

**Core Function:** `zone_mean_df()` in `utils.py:753-794`

```python
def zone_mean_df(input_ds, zone_ds):
    """
    Compute zonal means using flox groupby optimization
    
    Flox Method (Split-Apply-Combine):
    1. Split: Align datasets and split by zone boundaries
    2. Apply: Calculate mean for each zone group 
    3. Combine: Merge results into DataFrame
    """
    # 1. Align input data with zone boundaries
    z1d_, aligned_zone_ds = xr.align(input_ds, zone_ds, join="override")
    
    # 2. Group by zones and calculate means (uses flox optimization)
    z1 = input_ds.groupby(aligned_zone_ds).mean()
    
    # 3. Convert to DataFrame for output processing
    z1 = z1.to_dataframe()
    z1a = z1.reset_index()
    
    return z1a
```

### Flox Optimization Benefits

1. **Performance**: Optimized groupby operations for large datasets
2. **Memory Efficiency**: Chunked processing prevents memory overflow
3. **Dask Integration**: Seamless integration with dask for parallel processing
4. **Scalability**: Handles large spatial datasets efficiently

### Aggregation Process Flow

```python
# Example from 01-pet-process-1km.py
def calculate_zone_means(regridded_data, zone_ds):
    """Calculate mean PET values for each zone"""
    return zone_mean_df(regridded_data, zone_ds)  # Uses flox internally

# Usage in processing pipeline
z1ds, pdsz1, zone_extent = process_zone(data_path, pds, zone_str)
regridded_data = regrid_pet_data(pdsz1, zone_extent)
zone_means = calculate_zone_means(regridded_data, z1ds)  # Flox aggregation here
```

## Gap-Filling Mechanisms

### Gap Detection Strategy

All three processing scripts (01-03) implement sophisticated gap-filling:

```python
def get_last_date_from_[variable](zone_dir, is_init=False):
    """
    Read existing data files and determine the last available date
    """
    # 1. Check if data file exists
    data_file = os.path.join(zone_dir, '[variable].txt')
    if not os.path.exists(data_file):
        return None
    
    # 2. Read file and extract last date
    df = pd.read_csv(data_file, sep=",")
    if 'NA' not in df.columns:
        return None
    
    # 3. Convert YYYYDDD format to datetime
    last_date_str = df['NA'].iloc[-1]
    last_date = datetime.strptime(str(last_date_str), '%Y%j')
    
    return last_date
```

### Gap-Filling Workflow

```python
# Example from 01-pet-process-1km.py workflow
def pet_all_zones_workflow():
    for zone_str in unique_zones:
        # 1. Check for existing data in reliable init directory
        last_date = get_last_date_from_evap(init_zone_dir, is_init=True)
        if last_date is None:
            # Fallback to standard directory
            last_date = get_last_date_from_evap(zone_dir, is_init=False)
        
        # 2. Determine gap-filling needs
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if last_date:
            start_date = last_date + timedelta(days=1)
            if start_date >= today:
                # Up to date - only update forecast
                update_standard_directory_with_forecast(data_path, zone_str)
                continue
        else:
            # No existing data - use default lookback period
            start_date = today - timedelta(days=30)
        
        # 3. Process missing date range
        end_date = today - timedelta(days=1)  # Up to yesterday
        pet_files = get_pet_files_task(url, start_date, end_date)
        # Process files...
```

### Dual Directory Strategy

1. **Init Directory**: Contains only verified historical data
   - Path: `data_path/zone_wise_txt_files/init/{zone}/`
   - Purpose: Reliable baseline for gap detection
   - Content: Historical data only (no forecasts)

2. **Standard Directory**: Contains historical + forecast data
   - Path: `data_path/zone_wise_txt_files/{zone}/`
   - Purpose: Complete model input with forecasts
   - Content: Historical data + 16-day forecast extension

### Forecast Extension

```python
def pet_extend_forecast_improved(df, date_column, days_to_add=16):
    """
    Create 16-day forecast by repeating last 15 days pattern
    """
    # 1. Sort data by date
    df = df.sort_values('_temp_date')
    
    # 2. Get last 15 days of data as pattern
    days_to_copy = min(15, len(df))
    historical_pattern = df.iloc[-days_to_copy:].copy()
    
    # 3. Generate 16 forecast days cycling through pattern
    new_rows = []
    last_date = df['_temp_date'].iloc[-1]
    
    for i in range(days_to_add):
        new_date = last_date + timedelta(days=i+1)
        historical_idx = i % len(historical_pattern)
        new_row = historical_pattern.iloc[historical_idx].copy()
        new_row['_temp_date'] = new_date
        new_rows.append(new_row)
    
    # 4. Concatenate forecast to historical data
    result_df = pd.concat([df, new_rows_df], ignore_index=True)
    
    return result_df
```

## Zarr Upload and Cloud Storage

### Zarr Conversion Process

**Files 04-06** implement cloud-native data storage using Zarr format:

```python
def convert_to_zarr(data_array, zarr_path, date_string):
    """
    Convert xarray DataArray to Zarr format with optimization
    """
    # 1. Prepare dataset with metadata
    ds = xr.Dataset({
        'precipitation': data_array  # or 'pet', depending on data type
    })
    
    # 2. Add comprehensive metadata
    ds.attrs.update({
        'title': f'IMERG Precipitation Data for {date_string}',
        'source': 'NASA GPM IMERG',
        'date_processed': datetime.now().isoformat(),
        'spatial_resolution': '0.1 degrees',
        'temporal_resolution': 'daily',
        'units': 'mm/day',
        'processing_version': '1.0',
        'extent': f'East Africa ({EXTENT[0]}°E-{EXTENT[1]}°E, {EXTENT[2]}°N-{EXTENT[3]}°N)'
    })
    
    # 3. Define optimal chunking strategy
    chunk_sizes = {
        'lat': min(len(ds.lat), 100),
        'lon': min(len(ds.lon), 100)
    }
    ds = ds.chunk(chunk_sizes)
    
    # 4. Save to Zarr with compression
    ds.to_zarr(zarr_path, mode='w', consolidated=True)
    
    return zarr_path
```

### Cloud Upload Integration

```python
def upload_to_gcs(zarr_path, bucket_name, gcs_path):
    """
    Upload Zarr dataset to Google Cloud Storage
    """
    # 1. Initialize GCS client with credentials
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    # 2. Upload all Zarr files recursively
    for root, dirs, files in os.walk(zarr_path):
        for file in files:
            local_file_path = os.path.join(root, file)
            # Create relative path for GCS
            relative_path = os.path.relpath(local_file_path, zarr_path)
            gcs_file_path = f"{gcs_path}/{relative_path}"
            
            # Upload individual file
            blob = bucket.blob(gcs_file_path)
            blob.upload_from_filename(local_file_path)
    
    return f"gs://{bucket_name}/{gcs_path}"
```

### Zarr Directory Structure

```
DATASET_ZARR/
├── YYYY/MM/DD/
│   └── dataset_YYYYMMDD.zarr/
│       ├── .zgroup
│       ├── .zattrs
│       ├── precipitation/
│       │   ├── .zarray
│       │   ├── .zattrs
│       │   └── 0.0  # Chunk files
│       ├── lat/
│       │   ├── .zarray
│       │   └── 0
│       └── lon/
│           ├── .zarray
│           └── 0
```

### Zarr Benefits

1. **Cloud-Native**: Optimized for cloud storage and access
2. **Chunked Storage**: Efficient partial data access
3. **Compression**: Reduced storage costs
4. **Metadata Rich**: Self-describing datasets
5. **Parallel Access**: Supports concurrent read/write operations

## Detailed Workflow Analysis by File

### File 01: PET Processing (01-pet-process-1km.py)

**Key Features:**
- Downloads from USGS FEWS NET servers
- Converts BIL to NetCDF format
- **Adds shapefile aggregation** (missing in R version)
- Implements forecast extension
- Dual directory structure

**Processing Steps:**
1. **Download**: `pet_download_extract_bilfile()` → Extract tar.gz files
2. **Convert**: `pet_bil_netcdf()` → BIL to NetCDF conversion
3. **Zone Processing**: `process_zone_from_combined()` → Generate zone TIFF
4. **Regridding**: `regrid_dataset()` → Standardize to 1km resolution
5. **Aggregation**: `zone_mean_df()` → Flox-based zonal means
6. **Gap Detection**: `get_last_date_from_evap()` → Check for missing data
7. **Forecast**: `pet_extend_forecast_improved()` → 16-day extension
8. **Output**: Generate `evap.txt` and zone-specific files

### File 02: CHIRPS-GEFS Processing (02-gef-chirps-process-1km.py)

**Key Features:**
- Downloads from UC Santa Barbara servers
- Processes 16-day forecast data
- **Scales R approach to all zones**
- Availability checking before download

**Processing Steps:**
1. **Availability Check**: `check_data_availability()` → Verify data exists
2. **Download**: `gefs_chrips_download_files()` → Retrieve TIFF files
3. **Processing**: `gefs_chrips_process()` → Convert to xarray
4. **Zone Processing**: `process_zone_from_combined()` → Zone extraction
5. **Regridding**: `regrid_dataset()` → Standardize resolution
6. **Aggregation**: `zone_mean_df()` → Zonal means calculation
7. **Gap Detection**: `get_last_date_from_rain()` → Check existing data
8. **Output**: Generate `rain.txt` files with forecast

### File 03: IMERG Processing (03-imerg-process-1km.py)

**Key Features:**
- Downloads from NASA servers with authentication
- **Adds shapefile aggregation** (missing in R version)
- Date-by-date processing for memory efficiency
- Coordinate renaming (x,y → lon,lat)

**Processing Steps:**
1. **File Listing**: `imerg_list_files_by_date()` → Find available files
2. **Download**: `imerg_download_files()` → NASA Earthdata authentication
3. **Processing**: `imerg_read_tiffs_to_dataset()` → TIFF to xarray
4. **Coordinate Fix**: `rename_coordinates()` → Standardize coordinate names
5. **Zone Processing**: `process_zone_from_combined()` → Zone extraction
6. **Regridding**: `regrid_dataset()` → Resolution standardization
7. **Aggregation**: `zone_mean_df()` → Flox-based means
8. **Gap Detection**: `get_last_date_from_rain()` → Missing data check
9. **Output**: Generate rain.txt files

### Files 04-06: Zarr Upload Scripts

**Common Features:**
- Cloud-native data storage
- Metadata-rich datasets
- GCS upload integration
- Date-based organization

**File 04 (CHIRPS-GEFS Zarr):**
- Processes forecast data for multiple days
- Organizes by date hierarchy
- Includes forecast metadata

**File 05 (IMERG Zarr):**
- Single-date processing
- NASA authentication handling
- High-resolution preservation

**File 06 (PET Zarr):**
- BIL to NetCDF to Zarr pipeline
- Handles compressed archives
- USGS server integration

### File 07: General GCS Upload (07-upload_to_gcs.py)

**Purpose:** Upload any files to Google Cloud Storage
**Features:**
- Batch upload capability
- Date-prefixed filenames
- Comprehensive logging
- Error handling and retry logic

## Technical Advantages of Python Implementation

### 1. **Complete Spatial Coverage**
- All data sources properly aggregated by zones
- Consistent methodology across variables
- Scalable to any number of zones

### 2. **Memory-Efficient Processing**
- Chunked data operations
- Dask integration for parallel processing
- Streaming data processing for large datasets

### 3. **Cloud-Native Architecture**
- Zarr format for efficient cloud storage
- Direct GCS integration
- Metadata-rich datasets

### 4. **Robust Gap-Filling**
- Dual directory strategy for data integrity
- Intelligent forecast extension
- Comprehensive missing data detection

### 5. **Modern Geospatial Stack**
- xarray for n-dimensional data
- rioxarray for geospatial operations
- geopandas for vector data
- flox for optimized groupby operations

## Performance Considerations

### Memory Usage
- **Chunking Strategy**: All operations use optimal chunk sizes
- **Streaming Processing**: Large datasets processed in chunks
- **Memory Cleanup**: Explicit garbage collection between operations

### Processing Speed
- **Parallel Operations**: Dask-based parallelization
- **Vectorized Operations**: NumPy/xarray optimizations
- **Efficient Regridding**: xESMF conservative interpolation

### Storage Efficiency
- **Zarr Compression**: Reduces storage requirements by 50-80%
- **Chunked Storage**: Enables efficient partial data access
- **Cloud Optimization**: Direct cloud storage integration

This Python implementation represents a significant advancement over the R scripts, providing complete spatial aggregation, modern cloud-native architecture, and robust operational capabilities for the GEOSFM hydrological modeling system.