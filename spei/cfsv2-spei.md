perational SPEI Calculation from NOAA CFS Forecasts for East Africa

## 1. Introduction

This document outlines a methodology for calculating the Standardized Precipitation Evapotranspiration Index (SPEI) from NOAA Climate Forecast System (CFS) forecasts for East Africa. The approach leverages cloud-based data access and parallel computing to create an operational, cost-effective drought monitoring system.

SPEI is a multi-scalar drought index that accounts for both precipitation and potential evapotranspiration, making it more comprehensive than precipitation-only indices. It is particularly valuable for regions like East Africa that are vulnerable to drought events with significant socioeconomic and agricultural impacts.

### Xclim for SPEI calculation

The Standardized Precipitation Evapotranspiration Index (SPEI) is calculated through a two-step process in the xclim library. First, a water budget is computed using the water_budget function, which calculates the difference between precipitation and potential evapotranspiration (P-PET). This function accepts daily precipitation data along with various meteorological variables (temperature, radiation, humidity, and wind) to estimate evapotranspiration using the Baier-Robertson (BR65) method when direct PET measurements aren't available. Once the water budget is determined, the standardized_precipitation_evapotranspiration_index function aggregates these values over specified time periods (typically 1, 3, 6, or 12 months), fits the data to a statistical distribution (commonly gamma), and transforms the cumulative probability to a standard normal distribution with mean zero and variance one. This transformation allows meaningful comparison of drought conditions across different climate regions and time periods, making SPEI an invaluable tool for monitoring agricultural drought, as negative values indicate water deficit conditions of varying severity.

https://xclim.readthedocs.io/en/stable/indices.html#xclim.indices.water_budget

## 2. Data Sources

### 2.1 NOAA CFS Forecast Data

The NOAA Climate Forecast System (CFS) is a global coupled atmosphere-ocean-land model that provides forecasts up to 9 months in advance. The data is available at 0.5° spatial resolution (approximately 56 km) and is updated four times daily (00, 06, 12, and 18 UTC cycles).

**Key characteristics:**
- CFS generates 16 ensemble runs daily: 4 runs at the 00 UTC cycle (9-month forecasts) and 4 runs at each of the other cycles (seasonal forecasts)
- Data is available in GRIB2 format
- Files are organized by initialization time, forecast period, and ensemble member
- Data is hosted on multiple cloud platforms, including AWS S3 (available at SAWS S3 link for historical data starting from cfs.20181031/)

### 2.2 Required Variables for SPEI Calculation

Based on our investigation, we need the following variables from the CFS dataset to calculate water budget and subsequently SPEI using the xclim.indices.water_budget function:

1. **pr** - Precipitation rate (`prate.01.*.daily.grb2`) - 44.3 MB
2. **tasmin** - Minimum daily temperature (`tmin.01.*.daily.grb2`) - 37.4 MB
3. **tasmax** - Maximum daily temperature (`tmax.01.*.daily.grb2`) - 36.2 MB
4. **tas** - Mean daily temperature (`tmp2m.01.*.daily.grb2`) - 91.7 MB
5. **rsds** - Surface downwelling shortwave radiation (`dswsfc.01.*.daily.grb2`) - 36.1 MB
6. **rsus** - Surface upwelling shortwave radiation (`uswsfc.01.*.daily.grb2`) - 24.4 MB
7. **rlds** - Surface downwelling longwave radiation (`dlwsfc.01.*.daily.grb2`) - 42.2 MB
8. **rlus** - Surface upwelling longwave radiation (`ulwsfc.01.*.daily.grb2`) - 31.7 MB
9. **sfcWind** - Surface wind velocity (10m) (`wnd10m.01.*.daily.grb2`) - 138.2 MB

**Total file size per ensemble member, per forecast day: ~482.2 MB (0.48 GB)**

## 3. Methodology

### 3.1 Data Access Strategy using Kerchunk

Kerchunk provides a method to create lightweight reference files that map the internal structure of GRIB2 files, allowing for virtual aggregation and efficient access without downloading entire datasets.

**Approach:**
1. Create reference files for each required CFS variable using Kerchunk
2. Aggregate references across ensemble members and time steps
3. Create a single Zarr-compatible reference that maps all necessary data

**Benefits:**
- Eliminates need to download full GRIB files
- Enables cloud-optimized data access patterns
- Allows targeted extraction of East Africa region only
- Reduces data transfer costs and computational overhead

### 3.2 Processing Pipeline

```
┌────────────────┐     ┌───────────────┐     ┌────────────────┐
│                │     │               │     │                │
│  CFS Forecast  │────►│  Kerchunk     │────►│  Dask-based    │
│  GRIB2 Files   │     │  References   │     │  Processing    │
│                │     │               │     │                │
└────────────────┘     └───────────────┘     └────────────────┘
                                                     │
                                                     ▼
┌────────────────┐     ┌───────────────┐     ┌────────────────┐
│                │     │               │     │                │
│  SPEI          │◄────│  Water Budget │◄────│  Data          │
│  Calculation   │     │  Calculation  │     │  Extraction    │
│                │     │               │     │                │
└────────────────┘     └───────────────┘     └────────────────┘
        │
        ▼
┌────────────────┐
│                │
│  Visualization │
│  & Products    │
│                │
└────────────────┘
```

### 3.3 Implementation Steps

1. **Kerchunk Reference Creation**
   - Generate references for each required variable across ensemble members
   - Create a consolidated reference for all variables needed for SPEI

2. **Dask-based Parallel Processing**
   - Set up a Dask cluster (local or cloud-based)
   - Create delayed computation graph for water budget calculation
   - Implement region-specific extraction for East Africa

3. **Water Budget Calculation**
   - Use xclim.indices.water_budget with method='BR65' (Baier-Robertson)
   - Calculate potential evapotranspiration from temperature, radiation, and wind data
   - Compute water budget (P-PET) for each grid cell

4. **SPEI Calculation**
   - Fit statistical distribution to water budget series
   - Transform to standardized index
   - Calculate SPEI at multiple time scales (1, 3, 6, 9 months)

5. **Operational Implementation**
   - Schedule automated runs following CFS updates
   - Implement quality control and validation
   - Create visualization products and alerts

## 4. CFS Data Structure and Scale Analysis

### 4.1 CFS Forecast Structure

The CFS forecast dataset has the following structure as observed from the ECMWF CDS:

**Dimensions:**
- number: 124 (31 days × 4 cycles per day)
- forecastMonth: 6 (forecast months)
- time: 604 (forecast time steps)
- latitude: 36 (grid cells in latitude)
- longitude: 33 (grid cells in longitude)

**Variables:**
- tprate (precipitation rate), plus other required meteorological variables

### CFSv2 From CDS 

```
xarray.Dataset

    Dimensions:
        number: 124forecastMonth: 6time: 604latitude: 36longitude: 33
    Coordinates:
        number
        (number)
        int64
        0 1 2 3 4 5 ... 119 120 121 122 123
        forecastMonth
        (forecastMonth)
        int64
        1 2 3 4 5 6
        time
        (time)
        datetime64[ns]
        2024-12-02 ... 2025-05-01T00:18:00
        surface
        ()
        float64
        ...
        latitude
        (latitude)
        float64
        23.0 22.0 21.0 ... -11.0 -12.0
        longitude
        (longitude)
        float64
        21.0 22.0 23.0 ... 51.0 52.0 53.0
    Data variables:
        tprate
        (number, forecastMonth, time, latitude, longitude)
        float32
        dask.array<chunksize=(124, 6, 604, 12, 12), meta=np.ndarray>
    Indexes: (5)
    Attributes:

    GRIB_edition :
        1
    GRIB_centre :
        kwbc
    GRIB_centreDescription :
        US National Weather Service - NCEP
    GRIB_subCentre :
        98
    Conventions :
        CF-1.7
    institution :
        US National Weather Service - NCEP
    history :
        2025-05-19T13:26 GRIB to CDM+CF via cfgrib-0.9.14.1/ecCodes-2.38.3 with {"source": "../../../../Downloads/e837c2d5e01d6c700e9967e94db24458.grib", "filter_by_keys": {}, "encode_cf": ["parameter", "time", "geography", "vertical"]}
```



### 4.2 Scale and Storage Requirements

For the East Africa domain, we can estimate the total data volume required for a complete forecast cycle:

- 9 required variables × 124 ensemble members
- Each daily file (482.2 MB) already contains the complete 9-month forecast in 6-hour time steps
- Total theoretical data volume: ~482.2 MB × 124 = **59.8 GB**

**Using Kerchunk reference approach:**
- Reference files are typically <1% of original data size
- Expected reference file size: ~0.6 GB
- Actual data transferred during computation: ~5-10 GB (depending on region of interest)

This represents a significant reduction in data transfer and storage requirements compared to downloading the complete dataset.

## 5. Implementation for East Africa

### 5.1 Region Definition

The East Africa region for this implementation covers:
- Latitude: 12°N to 12°S
- Longitude: 21°E to 53°E
- Countries: Ethiopia, Kenya, Somalia, South Sudan, Sudan, Tanzania, Uganda, Rwanda, Burundi, and portions of surrounding nations




