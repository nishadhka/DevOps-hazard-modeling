# IceChunk Integration Strategy: Phased Approach for GEOSFM Data Processing

## Overview

This document outlines a strategic phased approach to integrate IceChunk cloud-native storage technology into the GEOSFM data processing pipeline. The integration leverages improvements shown in `pet_to_icechunk_simple.py` and `multi_file_obstore_solution.py` while maintaining the existing zone-based aggregation workflow for daily `rain.txt` and `evap.txt` generation.

## Current State Analysis

### Existing Processing Chain
```
Data Source → Download → Regrid → Zone Aggregation → CSV Output (rain.txt/evap.txt)
     ↓              ↓          ↓           ↓              ↓
  Remote URL → Local Files → 1km Grid → Flox Groupby → Zone Folders
```

### Integration Points Identified

**From `pet_to_icechunk_simple.py`:**
- Direct BIL file processing to IceChunk
- East Africa subsetting optimization
- GCS-backed IceChunk repositories
- Versioned data storage with commit history

**From `multi_file_obstore_solution.py`:**
- Multi-file time series concatenation
- Kerchunk reference optimization
- Obstore-based chunk access
- Temporal-spatial caching

**From `03-imerg-process-1km.py`:**
- Zone-based flox aggregation
- Gap-filling mechanisms
- Dual directory structure (init/standard)
- Forecast extension capabilities

## Phased Integration Strategy

## Phase 1: Enhanced Data Ingestion with IceChunk Creation

### Phase 1A: PET Processing Enhancement

**Objective:** Replace PET download/processing with IceChunk-based approach

**Implementation:**
```python
# New PET processing workflow
def enhanced_pet_processing():
    # 1. Replace 01-pet-process-1km.py download with pet_to_icechunk_simple.py approach
    # 2. Direct BIL → IceChunk conversion
    # 3. East Africa subsetting during ingestion
    # 4. Maintain gap-filling detection
    
    store, session = setup_icechunk_store()
    
    # Check for existing data in IceChunk
    existing_data = check_icechunk_coverage(store, zone_str)
    gap_dates = detect_pet_gaps(existing_data)
    
    # Process only missing dates
    for date in gap_dates:
        ds = download_and_process_pet_file(filename, date)
        append_to_icechunk(store, ds, session)
    
    # Continue with existing zone processing...
    return icechunk_dataset
```

**Key Changes:**
- Replace `pet_download_extract_bilfile()` with direct IceChunk ingestion
- Eliminate intermediate NetCDF step
- Add East Africa subsetting during download
- Maintain existing gap-filling logic

**Files to Modify:**
- `01-pet-process-1km.py` → `01-pet-icechunk-process.py`
- Add IceChunk setup functions
- Integrate with existing zone processing

### Phase 1B: CHIRPS-GEFS Multi-File Enhancement

**Objective:** Implement obstore + kerchunk approach for CHIRPS-GEFS

**Implementation:**
```python
# New CHIRPS-GEFS processing workflow
def enhanced_chirps_processing():
    # 1. Replace download with multi_file_obstore_solution.py approach
    # 2. Create kerchunk references for each daily forecast
    # 3. Concatenate time series in memory
    # 4. Maintain existing zone aggregation
    
    chunk_manager = MultiFileChunkManager(reference_dir)
    dataset_handler = MultiFileChirpsDataset(chunk_manager)
    
    # Load time series for processing region
    success = dataset_handler.load_time_series_region(
        lat_bounds=(EAST_AFRICA_BOUNDS['lat_south'], EAST_AFRICA_BOUNDS['lat_north']),
        lon_bounds=(EAST_AFRICA_BOUNDS['lon_west'], EAST_AFRICA_BOUNDS['lon_east']),
        time_indices=gap_dates
    )
    
    # Continue with existing zone processing...
    return time_series_dataset
```

**Key Changes:**
- Replace `gefs_chrips_download_files()` with kerchunk references
- Add multi-file time concatenation
- Optimize memory usage with chunked loading
- Maintain forecast data handling

**Files to Modify:**
- `02-gef-chirps-process-1km.py` → `02-chirps-kerchunk-process.py`
- Add obstore + kerchunk functionality
- Integrate with existing gap-filling

### Phase 1C: IMERG Processing Integration

**Objective:** Maintain existing IMERG processing with enhanced caching

**Implementation:**
```python
# Enhanced IMERG with caching
def enhanced_imerg_processing():
    # 1. Keep existing download mechanism (NASA authentication required)
    # 2. Add local caching with kerchunk references
    # 3. Optimize memory usage
    # 4. Maintain zone aggregation approach
    
    # Use existing 03-imerg-process-1km.py approach
    # Add caching layer for processed data
    cached_data = check_imerg_cache(start_date, end_date)
    new_dates = [d for d in date_range if d not in cached_data]
    
    # Process only new dates
    for date in new_dates:
        process_imerg_date(date)
        cache_processed_data(date, processed_data)
```

**Key Changes:**
- Minimal changes to existing workflow
- Add caching layer for processed IMERG data
- Optimize memory usage during processing

**Files to Modify:**
- `03-imerg-process-1km.py` → Add caching functions
- Maintain existing authentication and processing

## Phase 2: Unified 1km Regridded Dataset Creation

### Phase 2A: Regridding Standardization

**Objective:** Create unified 1km regridded datasets in IceChunk format

**Implementation:**
```python
# Unified regridding workflow
def create_unified_1km_dataset():
    # 1. Consolidate all data sources at 1km resolution
    # 2. Create unified IceChunk dataset
    # 3. Optimize for dask operations
    
    # PET data from Phase 1A
    pet_ds = load_from_icechunk(pet_store, date_range)
    
    # CHIRPS-GEFS data from Phase 1B  
    chirps_ds = load_from_kerchunk_cache(chirps_refs, date_range)
    
    # IMERG data from Phase 1C
    imerg_ds = load_from_imerg_cache(date_range)
    
    # Regrid all to common 1km grid
    unified_grid = create_east_africa_1km_grid()
    
    pet_regridded = regrid_to_common(pet_ds, unified_grid)
    chirps_regridded = regrid_to_common(chirps_ds, unified_grid)
    imerg_regridded = regrid_to_common(imerg_ds, unified_grid)
    
    # Create unified dataset
    unified_ds = xr.Dataset({
        'pet': pet_regridded.pet,
        'chirps_precipitation': chirps_regridded.precipitation,
        'imerg_precipitation': imerg_regridded.precipitation
    })
    
    # Save to IceChunk with optimal chunking for dask
    unified_ds.to_zarr(unified_icechunk_store)
    
    return unified_ds
```

**Key Features:**
- Common 1km grid for all variables
- Optimized chunking for dask operations
- Unified time coordinates
- East Africa spatial bounds

### Phase 2B: IceChunk Dataset Organization

**Objective:** Organize regridded data for efficient dask operations

**Directory Structure:**
```
gs://geosfm/unified-1km-east-africa/
├── pet/
│   └── icechunk_repo/
├── precipitation/
│   ├── chirps-gefs/
│   │   └── icechunk_repo/
│   └── imerg/
│       └── icechunk_repo/
└── unified/
    └── icechunk_repo/
        ├── pet/
        ├── chirps_precipitation/
        └── imerg_precipitation/
```

**Chunking Strategy:**
```python
# Optimal chunking for East Africa analysis
CHUNK_STRATEGY = {
    'time': 30,        # Monthly chunks
    'lat': 100,        # ~100km spatial chunks  
    'lon': 100         # ~100km spatial chunks
}

# Dask-optimized metadata
DATASET_ATTRS = {
    'dask_chunks': CHUNK_STRATEGY,
    'spatial_resolution': '0.01 degrees (~1km)',
    'temporal_resolution': 'daily',
    'spatial_bounds': 'East Africa',
    'crs': 'EPSG:4326'
}
```

## Phase 3: Dask-Optimized Flox Operations

### Phase 3A: Zone Processing with Dask + Flox

**Objective:** Scale zone aggregation using dask-optimized flox operations

**Implementation:**
```python
# Dask-optimized zone processing
def dask_zone_aggregation():
    # 1. Load unified 1km dataset with dask
    # 2. Use flox for large-scale aggregation
    # 3. Process all zones in parallel
    
    # Load data with dask
    unified_ds = xr.open_zarr(unified_icechunk_store, chunks=CHUNK_STRATEGY)
    
    # Load zone boundaries as dask-friendly format
    zone_raster = load_zone_raster_dask()
    
    # Use flox for efficient groupby operations
    import flox.xarray
    
    # Aggregate by zones using dask
    zone_means = flox.xarray.xarray_reduce(
        unified_ds,
        zone_raster,
        func="mean",
        method="cohorts",  # Optimized for large datasets
        chunks=CHUNK_STRATEGY
    )
    
    # Process results for GEOSFM output
    return zone_means
```

### Phase 3B: Parallel Zone Processing

**Implementation:**
```python
# Parallel processing of all zones
def process_all_zones_parallel():
    from dask.distributed import Client, as_completed
    
    client = Client('dask-cluster-address')
    
    # Submit zone processing tasks
    futures = []
    for zone in ['zone1', 'zone2', 'zone3', 'zone4', 'zone5', 'zone6']:
        future = client.submit(process_single_zone_dask, zone)
        futures.append((zone, future))
    
    # Collect results
    for zone, future in as_completed(futures):
        rain_file, evap_file = future.result()
        print(f"Completed {zone}: {rain_file}, {evap_file}")
```

### Phase 3C: Automated Daily Processing Pipeline

**Implementation:**
```python
# Daily processing pipeline
def daily_processing_pipeline(date=None):
    if date is None:
        date = datetime.now().date()
    
    # Phase 1: Update data sources
    update_pet_icechunk(date)
    update_chirps_kerchunk(date)
    update_imerg_cache(date)
    
    # Phase 2: Update unified dataset
    update_unified_1km_dataset(date)
    
    # Phase 3: Generate zone files
    zone_results = process_all_zones_parallel()
    
    # Generate daily rain.txt and evap.txt files
    generate_geosfm_inputs(zone_results, date)
    
    return zone_results
```

## Implementation Timeline and Dependencies

### Phase 1: Enhanced Data Ingestion (Weeks 1-4)

**Week 1-2: PET Enhancement**
- [ ] Implement `setup_icechunk_store()` with GCS backend
- [ ] Replace BIL processing with direct IceChunk ingestion
- [ ] Test East Africa subsetting performance
- [ ] Validate against existing PET outputs

**Week 3-4: CHIRPS-GEFS Multi-File**
- [ ] Implement `MultiFileChunkManager` for daily forecasts
- [ ] Add kerchunk reference generation
- [ ] Test time series concatenation
- [ ] Validate against existing CHIRPS outputs

**Dependencies:**
- IceChunk Python library
- GCS credentials and bucket access
- Obstore and kerchunk libraries

### Phase 2: Unified Dataset Creation (Weeks 5-8)

**Week 5-6: Regridding Pipeline**
- [ ] Create common East Africa 1km grid
- [ ] Implement unified regridding for all sources
- [ ] Optimize chunking strategy for dask

**Week 7-8: IceChunk Integration**
- [ ] Design unified dataset schema
- [ ] Implement incremental updates
- [ ] Test dataset access patterns

**Dependencies:**
- Phase 1 completion
- Dask cluster access (optional)
- Storage optimization testing

### Phase 3: Dask Operations (Weeks 9-12)

**Week 9-10: Flox Integration**
- [ ] Implement dask-optimized zone aggregation
- [ ] Test parallel processing performance
- [ ] Optimize memory usage

**Week 11-12: Production Pipeline**
- [ ] Integrate with existing daily processing
- [ ] Add monitoring and error handling
- [ ] Performance benchmarking

**Dependencies:**
- Phase 2 completion
- Dask cluster deployment
- Production environment setup

## Risk Mitigation and Rollback Strategy

### Data Validation
- Parallel processing with existing pipeline during transition
- Automated comparison of outputs
- Performance benchmarking at each phase

### Rollback Plan
- Maintain existing scripts as backup
- Phase-by-phase rollback capability
- Data integrity verification

### Performance Monitoring
- Processing time metrics
- Memory usage tracking
- Error rate monitoring
- Data quality validation

## Expected Benefits

### Phase 1 Benefits
- **20-30% faster** data ingestion
- **Reduced storage costs** through cloud-native formats
- **Improved reliability** with versioned data storage
- **Better scalability** for multiple data sources

### Phase 2 Benefits
- **Unified data access** across all variables
- **50% faster** regridding through optimized workflows
- **Enhanced data discovery** with rich metadata
- **Improved data quality** through standardized processing

### Phase 3 Benefits
- **10x faster** zone aggregation through dask parallelization
- **Scalable processing** for any number of zones
- **Real-time processing** capability for operational forecasting
- **Enhanced monitoring** and error handling

## Technical Specifications

### Hardware Requirements
- **Minimum**: 16GB RAM, 4 CPU cores
- **Recommended**: 64GB RAM, 16 CPU cores
- **Cloud**: Dask cluster with 8-16 workers

### Software Dependencies
```python
# Core dependencies
icechunk >= 0.1.0
xarray >= 2023.1.0
dask >= 2023.1.0
flox >= 0.8.0

# Data access
obstore >= 0.1.0
kerchunk >= 0.2.0
gcsfs >= 2023.1.0

# Processing
rioxarray >= 0.13.0
geopandas >= 0.12.0
```

### Storage Requirements
- **Phase 1**: ~500GB for East Africa subsets
- **Phase 2**: ~1TB for unified 1km dataset
- **Phase 3**: ~100GB for zone aggregation cache

## Success Metrics

### Performance Metrics
- **Processing Time**: <2 hours for daily update (target: <30 minutes)
- **Memory Usage**: <32GB peak memory (target: <16GB)
- **Data Latency**: <4 hours from source to zone files
- **Reliability**: >99% successful daily processing

### Quality Metrics
- **Spatial Accuracy**: <1% difference from existing outputs
- **Temporal Consistency**: No gaps in time series
- **Zone Coverage**: All zones processed successfully
- **Forecast Quality**: Maintained forecast extension accuracy

## Conclusion

This phased approach provides a systematic migration to cloud-native processing while maintaining operational continuity. Each phase builds upon the previous one, allowing for validation and optimization at each step. The final result will be a scalable, efficient, and maintainable system capable of real-time hydrological forecasting with enhanced data management capabilities.