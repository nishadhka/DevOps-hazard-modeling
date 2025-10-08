# CHIRPS-GEFS Bias Correction Implementation with Python and xclim.sdba

## Overview

This document describes the Python implementation of CHIRPS-GEFS bias correction using `xarray` and `xclim.sdba` as an alternative to the operational IDL-based system. The implementation replicates the rank-based quantile mapping methodology described in the original CHIRPS-GEFS system.

## Background

The Climate Hazards InfraRed Precipitation with Stations - Global Ensemble Forecast System (CHIRPS-GEFS) provides bias-corrected precipitation forecasts by applying quantile mapping to raw GEFS forecasts using CHIRPS as the reference dataset.

### Original IDL Implementation

The operational system consists of four main IDL scripts:
1. `get_gefs_op_v12_p25.pro` - Downloads GEFS forecasts
2. `mk_gefs_op_v12_dailies.pro` - Creates daily accumulations  
3. `mk_chirps_gefs_v12.pro` - **Core bias correction using rank-based quantile mapping**
4. `disagg_to_dailies_v12.pro` - Disaggregates to daily forecasts

## Python Implementation

### Script: `bias_correction_xsdba.py`

The Python script implements the core bias correction functionality using modern scientific Python libraries.

### Key Features

1. **Data Loading**: Handles NetCDF GEFS forecast files with ensemble dimensions
2. **Regridding**: Interpolates GEFS data to CHIRPS 0.05° resolution
3. **Bias Correction**: Implements empirical quantile mapping using `xclim.sdba`
4. **Output Generation**: Saves bias-corrected forecasts in CF-compliant NetCDF format

### Dependencies

```bash
pip install xarray xclim numpy pandas
```

### Usage

#### Basic Usage
```bash
python bias_correction_xsdba.py 20250826_00.nc.nc
```

#### Advanced Usage with Historical Data
```bash
python bias_correction_xsdba.py 20250826_00.nc.nc \
  --chirps-historical /path/to/chirps_historical.nc \
  --gefs-historical /path/to/gefs_historical.nc \
  --regrid \
  --output bias_corrected_forecast.nc
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `input_file` | Path to GEFS forecast NetCDF file |
| `--output, -o` | Output file path (default: adds `_bias_corrected` suffix) |
| `--chirps-historical` | Path to historical CHIRPS data for training |
| `--gefs-historical` | Path to historical GEFS data for training |
| `--regrid` | Regrid to CHIRPS resolution (0.05°) |
| `--no-compress` | Disable output compression |

## Data Requirements

### Input GEFS Forecast File

Expected structure for the GEFS forecast file (e.g., `20250826_00.nc.nc`):

```
Dimensions:
- ensemble: 30 (GEFS ensemble members)
- time: 81 (3-hourly forecast steps)
- latitude: 141 (spatial dimension)  
- longitude: 129 (spatial dimension)

Variables:
- tp(ensemble, time, latitude, longitude): Total precipitation [kg m-2]
- ensemble(ensemble): Ensemble member indices
- time(time): Forecast time [hours since initialization]
- latitude(latitude): Latitude coordinates [degrees_north]
- longitude(longitude): Longitude coordinates [degrees_east]
```

### Historical Training Data (Optional)

For full bias correction functionality, provide:

1. **CHIRPS Historical Data**: 
   - Daily precipitation at 0.05° resolution
   - Covering the same spatial domain as GEFS
   - Minimum 10-20 years of data for robust statistics

2. **GEFS Historical Data**:
   - Historical reforecasts/hindcasts for same period as CHIRPS
   - Same forecast lead times and spatial resolution as operational forecasts

## Methodology

### Bias Correction Algorithm

The script implements empirical quantile mapping following the CHIRPS-GEFS approach:

1. **Historical Analysis**: 
   - Calculate cumulative distribution functions (CDFs) for both historical GEFS and CHIRPS
   - Sort historical data to create quantile lookup tables

2. **Percentile Ranking**:
   - For each forecast pixel, find the percentile rank in historical GEFS distribution
   - `percentile_rank = position_in_sorted_gefs / n_historical_years`

3. **Quantile Mapping**:
   - Map GEFS percentile to corresponding CHIRPS quantile
   - `bias_corrected_value = chirps_quantile_at_same_percentile`

4. **Edge Case Handling**:
   - Values above historical maximum: use maximum CHIRPS value
   - Zero precipitation: preserve zero values
   - Values below historical minimum: use minimum CHIRPS value

### Implementation Details

```python
# Core bias correction using xclim.sdba
QM = sdba.EmpiricalQuantileMapping.train(
    ref=chirps_historical.tp,    # Reference dataset (CHIRPS)
    hist=gefs_historical.tp,     # Historical model data (GEFS)
    nquantiles=50,               # Number of quantiles for mapping
    kind="*",                    # Multiplicative scaling for precipitation
    group="time"                 # Temporal grouping
)

# Apply correction to forecast
forecast_corrected = QM.adjust(
    forecast_data.tp,
    extrapolation="constant",    # Handle out-of-range values
    interp="linear"             # Interpolation method
)
```

## Data Processing Steps

### 1. Data Loading and Preprocessing
```python
# Load GEFS ensemble forecast
gefs_daily, gefs_mean = load_gefs_forecast("20250826_00.nc.nc")

# Convert 3-hourly to daily accumulations
gefs_daily = gefs_data.resample(time='1D').sum()
```

### 2. Spatial Regridding
```python
# Regrid from GEFS native resolution to CHIRPS 0.05°
gefs_regridded = regrid_to_chirps_resolution(gefs_mean, target_resolution=0.05)
```

### 3. Bias Correction Training and Application
```python
# Train quantile mapping model with historical data
QM = sdba.EmpiricalQuantileMapping.train(chirps_hist.tp, gefs_hist.tp, ...)

# Apply to current forecast
corrected_forecast = QM.adjust(gefs_regridded.tp, ...)
```

### 4. Output Generation
```python
# Save with metadata and compression
corrected_forecast.to_netcdf("output.nc", encoding={'tp': {'zlib': True}})
```

## Example Workflow

### Step 1: Prepare Historical Data
```bash
# Organize historical CHIRPS data (example structure)
/data/chirps/historical/
├── chirps_daily_2000_2020.nc
└── ...

# Organize historical GEFS reforecasts
/data/gefs/historical/
├── gefs_reforecast_2000_2020.nc
└── ...
```

### Step 2: Run Bias Correction
```bash
# Process current forecast with full bias correction
python bias_correction_xsdba.py 20250826_00.nc.nc \
  --chirps-historical /data/chirps/historical/chirps_daily_2000_2020.nc \
  --gefs-historical /data/gefs/historical/gefs_reforecast_2000_2020.nc \
  --regrid \
  --output /output/chirps_gefs_20250826.nc
```

### Step 3: Verify Output
```python
import xarray as xr

# Load and examine output
ds = xr.open_dataset("/output/chirps_gefs_20250826.nc")
print(ds.tp.mean())  # Mean daily precipitation
print(ds.tp.attrs)   # Processing metadata
```

## Operational Considerations

### Performance Optimization

1. **Chunking**: Use Dask for large datasets
```python
import dask
gefs_data = xr.open_dataset("forecast.nc", chunks={'time': 10, 'latitude': 50})
```

2. **Parallel Processing**: Process multiple forecasts simultaneously
```python
from dask.distributed import Client
client = Client()  # Start Dask cluster
```

3. **Memory Management**: Process data in spatial chunks for large domains
```python
# Process in longitude chunks
for lon_chunk in longitude_chunks:
    process_spatial_subset(gefs_data.sel(longitude=lon_chunk))
```

### Quality Control

1. **Data Validation**: Check for missing values and valid ranges
2. **Metadata Preservation**: Maintain CF conventions and processing history
3. **Statistical Verification**: Compare with reference climatology

### Cloud Deployment

```python
# Access cloud-based datasets
gefs_zarr = xr.open_zarr("s3://noaa-gefs-pds/gefs.20250826/00/")
chirps_zarr = xr.open_zarr("s3://chirps-data/daily/")
```

## Comparison with IDL Implementation

| Aspect | IDL Implementation | Python Implementation |
|--------|-------------------|----------------------|
| **File Format** | TIFF/Binary | NetCDF/Zarr |
| **Memory Usage** | Full arrays in memory | Lazy loading with xarray/Dask |
| **Parallelization** | Manual loops | Automatic with Dask |
| **Regridding** | Simple rebin | Interpolation methods |
| **Metadata** | Limited | CF-compliant with history |
| **Cloud Ready** | No | Yes (Zarr/S3 compatible) |

## Limitations and Future Improvements

### Current Limitations

1. **Historical Data Requirement**: Full bias correction requires extensive historical datasets
2. **Computational Intensity**: Processing large ensembles can be memory-intensive
3. **Spatial Coverage**: Limited to areas with historical CHIRPS coverage

### Proposed Improvements

1. **Trend-Preserving Correction**: Implement `DetrendedQuantileMapping` for climate change scenarios
2. **Frequency Adaptation**: Use `adapt_freq` for better dry day handling
3. **Multi-Model Ensembles**: Extend to combine multiple forecast systems
4. **Real-Time Pipeline**: Automated processing of operational forecasts

## Conclusion

The Python implementation provides a modern, scalable alternative to the IDL-based CHIRPS-GEFS system while preserving the core rank-based quantile mapping methodology. The use of xarray and xclim.sdba offers improved performance, cloud compatibility, and extensibility for operational precipitation forecasting systems.

## References

1. Funk, C., et al. (2019). "The climate hazards infrared precipitation with stations—a new environmental record for monitoring extremes." Scientific Data, 6, 150.
2. xclim Documentation: https://xclim.readthedocs.io/
3. xarray Documentation: https://docs.xarray.dev/
4. GEFS Documentation: https://www.ncep.noaa.gov/products/forecasts/ensemble/