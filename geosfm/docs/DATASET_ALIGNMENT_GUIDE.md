# East Africa Climate Dataset Alignment Guide

## Overview
This guide documents the strategy for aligning three different climate datasets (PET, CHIRPS, IMERG) with varying temporal resolutions and coverage into a single unified xarray dataset optimized for Dask cluster processing.

## Problem Statement

### Original Dataset Characteristics
- **PET (Potential Evapotranspiration)**: 3 daily time steps (2024-01-01 to 2024-01-03)
- **CHIRPS (Precipitation)**: 15 daily time steps (2024-01-01 to 2024-01-15)  
- **IMERG (Precipitation)**: 3 sub-daily time steps at 6-hour intervals (2024-01-01 00:00 to 2024-01-01 12:00)

### Alignment Challenges
1. **Temporal Resolution Mismatch**: Daily vs 6-hourly frequencies
2. **Coverage Periods**: Different time ranges (3 days vs 15 days vs 12 hours)
3. **Missing Data Gaps**: Incomplete coverage in PET and IMERG compared to CHIRPS
4. **Processing Requirements**: Need single dataset for Dask cluster analysis

## Alignment Strategy

### 1. Common Temporal Grid
- **Base Resolution**: Daily frequency (most common denominator)
- **Time Range**: 15 days (2024-01-01 to 2024-01-15) to cover maximum available period
- **Aggregation**: Convert sub-daily IMERG to daily sums

### 2. Gap Handling Approaches

#### Default Strategy: Explicit NaN Values
```python
# Missing periods are marked with NaN values
# Allows robust analysis with proper missing data handling
aligned_data = da.full(shape, np.nan, chunks=chunks, dtype='float32')
```

#### Alternative Gap Filling Strategies
1. **Forward Fill**: Propagate last valid observation
   ```python
   ds_filled = ds.ffill(dim='time')
   ```

2. **Interpolation**: Linear interpolation between valid points
   ```python
   ds_filled = ds.interpolate_na(dim='time', method='linear')
   ```

3. **Backward Fill**: Propagate next valid observation
   ```python
   ds_filled = ds.bfill(dim='time')
   ```

### 3. Spatial Consistency
- **Grid**: Identical lat/lon coordinates for all variables
- **Resolution**: 1km (~0.009° spatial resolution)
- **Extent**: East Africa (21-53°E, -12-23°N)

### 4. Dask Optimization
- **Chunking Strategy**: (5, 500, 500) - 5 days, 500x500 spatial chunks
- **Memory Efficiency**: Lazy evaluation with Dask arrays
- **Cluster Ready**: Optimized chunk sizes for distributed processing

## Implementation Details

### Data Availability Matrix
| Dataset | Days 1-3 | Days 4-15 | Notes |
|---------|----------|-----------|-------|
| PET     | ✓        | NaN       | Original coverage |
| CHIRPS  | ✓        | ✓         | Complete coverage |
| IMERG   | ✓ (Day 1)| NaN       | Aggregated from 6-hourly |

### Temporal Aggregation
- **IMERG**: 4 × 6-hourly observations → 1 daily sum
- **PET**: Already daily resolution
- **CHIRPS**: Already daily resolution

### Unified Dataset Structure
```python
unified_ds = xr.Dataset(
    {
        'pet': (['time', 'lat', 'lon'], pet_aligned_data),
        'chirps': (['time', 'lat', 'lon'], chirps_aligned_data), 
        'imerg': (['time', 'lat', 'lon'], imerg_aligned_data)
    },
    coords={
        'time': common_time_range,  # 15-day daily grid
        'lat': lats,               # Consistent spatial grid
        'lon': lons                # Consistent spatial grid
    }
)
```

## Export Options for Dask Processing

### Option 1: Single NetCDF File
```python
unified_ds.to_netcdf('east_africa_unified_climate.nc',
                    engine='netcdf4',
                    encoding={
                        'pet': {'zlib': True, 'complevel': 4, 'chunksizes': (5, 500, 500)},
                        'chirps': {'zlib': True, 'complevel': 4, 'chunksizes': (5, 500, 500)},
                        'imerg': {'zlib': True, 'complevel': 4, 'chunksizes': (5, 500, 500)}
                    })
```

### Option 2: Zarr Format (Recommended for Dask)
```python
unified_ds.to_zarr('east_africa_unified_climate.zarr',
                  mode='w',
                  consolidated=True)
```

### Option 3: Time-Chunked Files for Distributed Processing
```python
for year in unified_ds.time.dt.year.unique():
    yearly_data = unified_ds.sel(time=unified_ds.time.dt.year == year)  
    yearly_data.to_netcdf(f'east_africa_climate_{year}.nc')
```

## Best Practices for Missing Data

### For Statistical Analysis
1. **Keep NaN values** for robust statistical methods
2. **Document data availability** in dataset attributes
3. **Use pairwise deletion** in correlation analysis

### For Machine Learning
1. **Forward fill** for time series continuity
2. **Interpolation** for smooth temporal transitions
3. **Feature engineering** to encode missingness patterns

### For Physical Modeling
1. **Climatological means** for process-based gap filling
2. **Spatial interpolation** from neighboring grid points
3. **Ensemble methods** for uncertainty quantification

## Validation Checklist

- [x] Temporal alignment: All variables on 15-day daily grid
- [x] Spatial consistency: Identical lat/lon grids for all variables  
- [x] Chunking optimized: (5, 500, 500) for Dask cluster processing
- [x] Memory efficient: Lazy evaluation with Dask arrays
- [x] Gap handling: Explicit NaN values with optional filling strategies
- [x] Metadata complete: Dataset attributes document alignment process

## Performance Considerations

### Memory Usage
- **Lazy Loading**: Data only loaded when computed
- **Chunking**: Optimal chunk sizes for cluster memory limits
- **Compression**: NetCDF compression reduces storage by ~50%

### Computation Efficiency  
- **Parallel Processing**: Chunk-aligned operations scale across workers
- **I/O Optimization**: Zarr format provides faster random access
- **Temporal Subsetting**: Select specific time periods to reduce memory footprint

## Future Extensions

1. **Dynamic Time Ranges**: Support for varying temporal coverage
2. **Multi-Resolution Support**: Handle different spatial resolutions
3. **Quality Flags**: Incorporate data quality indicators
4. **Automated Gap Detection**: Identify and flag missing data patterns
5. **Climatological Normals**: Add long-term averages for gap filling