# Flox-Based Polygon Operations Guide

## Overview
This guide documents the polygon-based groupby operations used in the climate data processing pipeline, specifically how shapefiles are converted to rasters and used with flox for efficient zone-based aggregations.

## Core Concept: Split-Apply-Combine Strategy

The pipeline implements the **"split-apply-combine"** strategy optimized by flox for xarray operations:

1. **Split**: Input datasets are aligned and split according to zones defined in polygon shapefiles
2. **Apply**: Statistical reductions (mean, sum, etc.) are applied to each zone group
3. **Combine**: Results are combined into a single DataFrame for analysis

## Key Functions and Workflow

### 1. Shapefile to Raster Conversion

**Function**: `make_zones_geotif()` in `utils.py:543`

```python
def make_zones_geotif(shapefl_name, km_str, zone_str):
    """
    Convert polygon shapefile to rasterized GeoTIFF for efficient spatial operations
    
    Parameters:
    - shapefl_name: Path to shapefile
    - km_str: Pixel size in kilometers  
    - zone_str: Zone identifier for output naming
    """
```

**Process**:
- Reads shapefile using GeoPandas
- Creates raster grid with specified resolution (typically 1km)
- Rasterizes polygon geometries using `rasterio.features.rasterize()`
- Assigns unique GRIDCODE values to each polygon zone
- Outputs GeoTIFF compatible with xarray operations

### 2. Zone Processing from Combined Shapefile

**Function**: `process_zone_from_combined()` in `utils.py:597`

```python
def process_zone_from_combined(master_shapefile, zone_name, km_str, pds):
    """
    Extract specific zone from master shapefile and subset climate data
    
    Returns:
    - z1crds: Rasterized zone dataset
    - pz1ds: Climate data subset to zone extent  
    - zone_extent: Bounding box coordinates
    """
```

**Key Operations**:
- Filters master shapefile for specific zone (e.g., 'zone1')
- Creates temporary zone-specific shapefile
- Generates rasterized GeoTIFF using `make_zones_geotif()`
- Subsets climate data to zone bounding box using `xr.Dataset.sel()`

### 3. Flox-Based Zone Aggregation

**Function**: `zone_mean_df()` in `utils.py:753`

```python
def zone_mean_df(input_ds, zone_ds):
    """
    Compute zone-wise means using flox optimized groupby operations
    
    This implements the 'flox groupby method' for efficient spatial aggregations:
    1. Split: Align datasets and split by zone polygons
    2. Apply: Calculate mean reduction for each zone
    3. Combine: Return results as pandas DataFrame
    """
```

**Critical Implementation Details**:
```python
# Align datasets to ensure spatial correspondence
z1d_, aligned_zone_ds = xr.align(input_ds, zone_ds, join="override")

# Groupby operation using flox optimization
z1 = input_ds.groupby(aligned_zone_ds).mean()

# Convert to DataFrame for downstream processing
z1 = z1.to_dataframe()
z1a = z1.reset_index()
```

## Shapefile Structure and Requirements

### Master Shapefile Format
- **Location**: `zones_shapefiles_20250320/` (extracted from zip)
- **Key Fields**:
  - `zone`: Zone identifier (e.g., 'zone1', 'zone2', etc.)
  - `GRIDCODE`: Unique numeric identifier for rasterization
  - Geometry polygons defining zone boundaries

### Individual Zone Files
Each zone has complete GIS metadata:
- `.shp`: Geometry data
- `.dbf`: Attribute table  
- `.prj`: Projection information
- `.shx`: Shape index
- `.sbn/.sbx`: Spatial index (optional)

## Flox Optimization Benefits

### Performance Advantages
1. **Memory Efficiency**: Lazy evaluation prevents loading entire datasets
2. **Parallel Processing**: Automatic chunking enables distributed computation
3. **Optimized Algorithms**: Purpose-built for xarray groupby operations
4. **Dask Integration**: Seamless scaling to cluster environments

### vs Traditional Approaches
```python
# Traditional (slow, memory intensive)
results = []
for zone_id in zones:
    mask = zone_ds == zone_id
    zone_mean = input_ds.where(mask).mean()
    results.append(zone_mean)

# Flox-optimized (fast, memory efficient)  
results = input_ds.groupby(zone_ds).mean()
```

## Data Flow in 01-pet-process-1km.py

### Workflow Steps
1. **Zone Processing**: `process_zone()` task at line 435
   - Loads master shapefile: `geofsm-prod-all-zones-20240712.shp`
   - Calls `process_zone_from_combined()` to extract specific zone
   - Returns rasterized zone dataset and climate data subset

2. **Data Regridding**: `regrid_pet_data()` task at line 464
   - Uses `regrid_dataset()` to align climate data to zone grid
   - Applies bilinear interpolation for spatial consistency

3. **Zone Aggregation**: `calculate_zone_means()` task at line 487  
   - Calls `zone_mean_df()` for flox-based aggregation
   - Computes mean values for each polygon zone

4. **Results Processing**: Outputs zone-wise time series data

## Integration with Unified Dataset

### Adapting for Multiple Variables
```python
# For unified dataset with PET, CHIRPS, IMERG
unified_ds = xr.Dataset({
    'pet': (['time', 'lat', 'lon'], pet_data),
    'chirps': (['time', 'lat', 'lon'], chirps_data), 
    'imerg': (['time', 'lat', 'lon'], imerg_data)
})

# Zone aggregation for all variables
zone_results = {}
for var in ['pet', 'chirps', 'imerg']:
    var_ds = unified_ds[var]
    zone_results[var] = zone_mean_df(var_ds, zone_ds)
```

## Local vs Cluster Compute Strategy

### Local Testing Approach
```python
# Start with single zone, small time range
test_zone = 'zone1'
test_dates = pd.date_range('2024-01-01', periods=5, freq='D')

# Use smaller chunks for local testing
local_chunks = (2, 100, 100)  # Reduced from (5, 500, 500)

# Process single zone locally
with Client('threads://'):  # Local threaded client
    zone_results = process_single_zone_climate(test_zone, test_dates)
```

### Cluster Scaling Preparation
```python
# Verify operations work with production chunks
production_chunks = (5, 500, 500)

# Test with multiple zones
test_zones = ['zone1', 'zone2', 'zone3']

# Benchmark local performance before cluster deployment
import time
start_time = time.time()
results = process_multiple_zones(test_zones, test_dates)
local_runtime = time.time() - start_time
```

### Coiled Cluster Configuration
```python
# After local testing, scale to Coiled cluster
from coiled import Cluster

cluster = Cluster(
    name="climate-processing",
    software="environment.yml",  # Include flox, xarray, geopandas
    n_workers=10,
    worker_memory="8GB",
    scheduler_memory="4GB"
)

with cluster.client() as client:
    # Process all zones with optimized chunks
    all_results = process_all_zones_climate(all_zones, full_date_range)
```

## Best Practices

### Chunking Strategy
- **Temporal**: 5-10 time steps per chunk
- **Spatial**: 500x500 pixels for 1km resolution data
- **Memory**: Keep chunks under 128MB for optimal performance

### Error Handling
```python
try:
    zone_results = zone_mean_df(climate_ds, zone_ds)
except Exception as e:
    print(f"Zone aggregation failed: {e}")
    # Fallback to manual polygon masking
    zone_results = manual_zone_aggregation(climate_ds, zone_polygons)
```

### Quality Assurance
- Verify zone coverage: Check for missing/overlapping polygons
- Validate aggregation results: Compare against manual calculations
- Monitor memory usage: Ensure chunks fit in worker memory

## Performance Optimization Tips

1. **Preprocessing**: Pre-compute zone rasters once, reuse for all variables
2. **Alignment**: Ensure consistent coordinate grids to avoid regridding overhead  
3. **Chunking**: Align chunk boundaries with zone boundaries when possible
4. **Caching**: Store intermediate results to avoid recomputation
5. **Monitoring**: Use Dask dashboard to identify bottlenecks

## Output Format

### Zone-wise Time Series
```csv
time,group,pet,chirps,imerg
2024-01-01,1,2.5,0.0,0.1
2024-01-01,2,2.3,0.2,0.0
2024-01-02,1,2.6,1.2,0.5
2024-01-02,2,2.4,0.8,0.3
```

### Metadata Preservation
- Original shapefile attributes maintained in group identifiers
- Spatial reference information preserved in dataset attributes
- Processing parameters documented in output metadata

This polygon-based approach enables efficient analysis of climate extremes across administrative or watershed boundaries, making it ideal for hydrological modeling and regional climate assessments.