# GEOSFM Hydrological Model: Comprehensive Documentation

## Table of Contents
1. [Overview](#overview)
2. [GEOSFM Model Architecture](#geosfm-model-architecture)
3. [Data Sources and Processing](#data-sources-and-processing)
4. [R Scripts Workflow Analysis](#r-scripts-workflow-analysis)
5. [Spatial Data Management](#spatial-data-management)
6. [Model Input File Generation](#model-input-file-generation)
7. [Quality Control and Validation](#quality-control-and-validation)
8. [Operational Workflow](#operational-workflow)

## Overview

The GEOSFM (Geospatial Stream Flow Model) is a distributed hydrological model designed for real-time and forecast streamflow prediction in data-sparse regions. The system integrates multiple satellite and forecast data sources to provide basin-specific precipitation and evapotranspiration inputs for hydrological modeling in East African river basins.

### Key Components
- **Data Acquisition**: Automated download from multiple satellite/forecast sources
- **Spatial Processing**: Basin-specific aggregation using hydrological zone shapefiles
- **Temporal Integration**: Combines historical observations with forecast data
- **Model Input Generation**: Creates standardized text files for GEOSFM model execution

## GEOSFM Model Architecture

### Model Characteristics
- **Type**: Distributed, physics-based hydrological model
- **Spatial Resolution**: Sub-basin level (basin polygons)
- **Temporal Resolution**: Daily time steps
- **Domain**: East African river basins
- **Framework**: USGS BASINS-based modeling system

### Model Structure
```
GEOSFM Model Framework
├── Meteorological Inputs
│   ├── rain.txt (precipitation time series)
│   └── evap.txt (evapotranspiration time series)
├── Basin Configuration
│   ├── Zone shapefiles (spatial boundaries)
│   ├── Stream order files (basin hierarchy)
│   └── Model parameters (calibrated values)
└── Output Generation
    ├── Streamflow forecasts
    ├── Water balance components
    └── Performance metrics
```

### Model Inputs Required
1. **Precipitation Data**: Daily rainfall (mm/day)
2. **Evapotranspiration Data**: Daily PET (mm/day)
3. **Basin Geometry**: Polygon shapefiles with unique identifiers
4. **Stream Network**: Hierarchical basin ordering
5. **Model Parameters**: Calibrated hydrological parameters

## Data Sources and Processing Summary

### Data Sources Overview Table

| Data Source | Script File | Download Period | Processing Method | Spatial Aggregation | Output Format |
|-------------|-------------|-----------------|-------------------|-------------------|---------------|
| **CHIRPS-GEFS** | `chrips_gefs.R`, `1_gefs_dl.R` | 16-day forecast + 7-day historical (23 days total) | Area-weighted mean | ✅ Shapefile-based zonal aggregation | Zone-based rain.txt |
| **IMERG** | `IMERG.R` | Gap-filling (missing days only) | Grid-point based | ❌ No aggregation (pixel-level processing) | Individual pixel CSV files |
| **PET** | `PET.R` | Gap-filling (missing days only) + 15-day forecast | Fixed 40×40 grid | ❌ No aggregation (grid-point processing) | Individual grid CSV files |

### 1. CHIRPS-GEFS Precipitation Forecasts

#### Source Details
- **Provider**: UC Santa Barbara Climate Hazards Group
- **Product**: CHIRPS-GEFS v12 daily precipitation
- **URL**: `https://data.chc.ucsb.edu/products/EWX/data/forecasts/CHIRPS-GEFS_precip_v12/`
- **Spatial Resolution**: 0.05° (~5.5 km)
- **Temporal Coverage**: 16-day forecasts, updated daily
- **Format**: GeoTIFF raster files

#### Processing Workflow
```r
# Download 16-day forecast
for (i in 1:16) {
  fname <- paste(folder, year, dm, "tif", sep=".")
  curl_download(fname, tmp)
  f2 <- raster(tmp)
  r <- crop(f2, extent(19, 54, -14, 25))  # East Africa extent
  writeRaster(r, filename=fin[i], overwrite=TRUE)
}
```

#### Data Integration
- **Historical Component**: Last 7 days of observations
- **Forecast Component**: 16-day forecast extension
- **Total Time Series**: 23 days (7 historical + 16 forecast)

#### Spatial Aggregation Method
**Location in code:** `chrips_gefs.R:169`
```r
# Read sub cat shapefile
dsn <- "D:/geofsm/BASINS41/modelout/WGS/zone5.shp"
zone5 <- st_read(dsn)

# KEY AGGREGATION: Area-weighted mean for rainfall intensity
rain5 <- raster::extract(rc, as(zone5, "Spatial"), fun=mean, na.rm=TRUE, df=TRUE, weights=TRUE)
```

**Aggregation Details:**
- **Method**: `fun=mean` with `weights=TRUE`
- **Purpose**: Calculate average rainfall intensity (mm/day) across each polygon
- **Weighting**: Uses pixel area weights for partial pixel coverage
- **Rationale**: Mean is appropriate for rainfall intensity; area weighting ensures accuracy

### 2. IMERG Precipitation Observations

#### Source Details
- **Provider**: NASA GPM Mission
- **Product**: IMERG Early Run (3IMERG)
- **URL**: `https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/early/`
- **Spatial Resolution**: 0.1° (~11 km)
- **Temporal Coverage**: Near real-time (4-hour latency)
- **Authentication**: NASA Earthdata login required

#### Processing Features
- **Gap Detection**: Automatically identifies missing days
- **Backfill Capability**: Downloads missing historical data
- **Quality Control**: Handles no-data values and spatial cropping
- **Format Conversion**: Units converted to mm/day

#### Spatial Processing Method
**Location in code:** `IMERG.R:55-66`
```r
# NO SHAPEFILE AGGREGATION - Grid-point based processing
x <- as.data.frame(rc, xy=TRUE)
y <- t(x)

# Process each grid point individually
for(i in 1:length(y[1,])){
    z <- data.frame("Date"=Date, "Guage_Grid_dailymm"=y[3, i]/10) 
    f <- paste("IMERG", round(y[2,i],2), "_", round(y[1,i],2), ".csv", sep="")
    write.table(z, file=f, append=TRUE, row.names=FALSE, col.names=FALSE, sep=",")
}
```

**Processing Details:**
- **Method**: No spatial aggregation - individual pixel processing
- **Shapefile Usage**: Only for cropping boundary (not aggregation)
- **Output**: Separate time series file for each grid point
- **Rationale**: Preserves high-resolution data for validation and flexible post-processing

### 3. Potential Evapotranspiration (PET)

#### Source Details
- **Provider**: USGS FEWS NET
- **Product**: Global daily PET estimates
- **URL**: `http://edcintl.cr.usgs.gov/downloads/sciweb1/shared/fews/web/global/daily/pet/downloads/daily/`
- **Spatial Resolution**: 1 km
- **Format**: Compressed tar.gz containing .bil files
- **Units**: Original units converted to mm/day

#### Processing Steps
1. **Download**: Automated retrieval of compressed files
2. **Extraction**: Untar and decompress .bil raster files
3. **Conversion**: Transform to GeoTIFF format
4. **Cropping**: Subset to Greater Horn of Africa extent
5. **Unit Conversion**: Scale to mm/day for model compatibility

#### Spatial Processing Method
**Location in code:** `PET.R:61-86`
```r
# NO SHAPEFILE AGGREGATION - Fixed 40×40 grid processing
k=1
for(j_lon in 1:40) {
    for(i_lat in 1:40) {
        pet=(round(r[k]/100,2))  # Convert from 0.01mm to mm
        
        if (pet <0){
           m[i_lat,j_lon]=0      # Quality control: set negative values to 0
           k=k+1
        } else{
         m[i_lat,j_lon]<-pet
         k=k+1
        }
    }
}

# Create time series for each grid point
for(j_lon in 1:40) {
    for(i_lat in 1:40) {
        lat = 25.0 - 1*(i_lat)    # Calculate latitude
        lon = 14 + 1*(j_lon)      # Calculate longitude
        x <- data.frame("Date"=cdate, "pet_daily_et_mm"=m[j_lon,i_lat])   
        f=paste("pet_",round(lat, 2),"_",round(lon, 2),".csv", sep="")
        write.table(x, file=f, append=TRUE, row.names=FALSE,col.names=FALSE, sep=",")
    }
}
```

**Processing Details:**
- **Method**: No spatial aggregation - fixed 1° grid processing
- **Grid Resolution**: 40×40 grid (1-degree spacing)
- **Coordinate System**: 14°E-54°E longitude, 25°N to -15°N latitude
- **Quality Control**: Removes negative PET values
- **Expected Aggregation**: If implemented, should use **mean** (PET is a rate/intensity variable)
- **Output**: Individual CSV files per grid point

### Spatial Aggregation Comparison Analysis

#### Summary of Aggregation Methods

| Data Source | Current Aggregation | Recommended Method | Rationale |
|-------------|--------------------|--------------------|-----------|
| **CHIRPS-GEFS** | ✅ Area-weighted mean | ✅ Correctly implemented | Rainfall intensity - mean provides representative value per zone |
| **IMERG** | ❌ No aggregation | Depends on use case | Could use **sum** for total accumulation or **mean** for intensity |
| **PET** | ❌ No aggregation | **Mean aggregation** | PET is rate/intensity - mean provides representative demand per zone |

#### Detailed Analysis by Data Type

**Rainfall Data (CHIRPS-GEFS, IMERG):**
- **For Model Input**: Use **mean** (as correctly implemented in CHIRPS-GEFS)
  - Provides representative rainfall intensity for hydrological modeling
  - Area weighting accounts for partial pixel coverage
- **For Accumulation Analysis**: Could use **sum** 
  - Total rainfall volume within polygon boundaries

**Evapotranspiration Data (PET):**
- **Recommended**: Use **mean aggregation**
  - PET represents potential evapotranspiration rate (mm/day)
  - Mean provides representative evapotranspiration demand for the zone
  - Summing would incorrectly inflate the demand

#### Implementation Recommendations

**For IMERG shapefile aggregation (if needed):**
```r
# Hypothetical aggregation implementation
zones <- st_read("path/to/zones.shp")
# Use mean for rainfall intensity
imerg_aggregated <- raster::extract(rc, as(zones, "Spatial"), fun=mean, na.rm=TRUE, df=TRUE, weights=TRUE)
```

**For PET shapefile aggregation (if needed):**
```r
# Hypothetical aggregation implementation  
zones <- st_read("path/to/zones.shp")
# Use mean for evapotranspiration rate
pet_aggregated <- raster::extract(rc, as(zones, "Spatial"), fun=mean, na.rm=TRUE, df=TRUE, weights=TRUE)
```

## R Scripts Workflow Analysis

### Script Hierarchy and Dependencies

```
Data Processing Pipeline
├── 1_gefs_dl.R (Primary CHIRPS-GEFS processor)
├── 2_last_7days_gefs_dl.R (Historical data supplement)
├── chrips_gefs.R (Legacy/alternative processor)
├── IMERG.R (NASA precipitation data)
└── PET.R (Evapotranspiration data)
```

### 1. Primary CHIRPS-GEFS Processor (1_gefs_dl.R)

#### Purpose
Main script for downloading and processing CHIRPS-GEFS forecast data, creating basin-specific precipitation time series for GEOSFM model input.

#### Key Operations
```r
# 1. Download 16-day forecast
base <- "https://data.chc.ucsb.edu/products/EWX/data/forecasts/CHIRPS-GEFS_precip_v12/daily_16day"
for (i in 1:16) {
  # Download and crop each daily forecast
}

# 2. Combine with historical data (last 7 days)
fname[8:23] <- files[(length(files) - 15):length(files)]

# 3. Create raster stack
rc <- stack(fname)

# 4. Extract values for Zone5 polygons
zone5 <- st_read("D:/geofsm/BASINS41/modelout/WGS/zone5.shp")
rain5 <- raster::extract(rc, as(zone5, "Spatial"), fun=mean, na.rm=TRUE, weights=TRUE)

# 5. Map to stream order and output
streamorder <- read.csv("D:/geofsm/streamorder/order5.txt")[,1]
for(i in 1:length(streamorder)) {
  j <- which(streamorder == i)
  Areal.average.rainfall[2:24, (j + 1)] <- df[,i]
}
```

#### Output Structure
- **File**: `rain.txt` in Zone5 directory
- **Format**: CSV with Julian dates and basin values
- **Columns**: Date + one column per basin (ordered by streamorder)

### 2. Historical Data Supplement (2_last_7days_gefs_dl.R)

#### Purpose
Downloads the most recent 7 days of CHIRPS-GEFS data to ensure temporal continuity between observations and forecasts.

#### Enhanced Features
- **Error Handling**: Improved download retry logic
- **Debug Output**: Enhanced logging for troubleshooting
- **File Validation**: Checks for successful downloads before processing

### 3. IMERG Processor (IMERG.R)

#### Purpose
Downloads and processes NASA IMERG precipitation data for model validation and gap-filling.

#### Key Features
```r
# Gap detection
imergfile <- read.csv("IMERG-1.85_28.05.csv", header=FALSE)[,1]
ldate <- dmy(imerg_file[length(imerg_file)])
lag <- as.numeric(difftime(tdate, ldate))

# Download missing days
if (lag > 1) {
  for (lday in 1:(lag-1)) {
    # Download and process each missing day
  }
}
```

#### Authentication
- **Method**: NASA Earthdata credentials
- **Implementation**: Uses curl handle with username/password

### 4. PET Processor (PET.R)

#### Purpose
Downloads and processes potential evapotranspiration data from USGS FEWS NET.

#### Processing Chain
```r
# Download compressed file
download.file(pet_file_link, pet_dest)

# Extract tar.gz file
gunzip(pet_dest)
untar(pet_dest2, exdir=pet_dir)

# Process raster data
r2 <- raster(file)
r <- crop(r2, extent(15, 55, -16, 25))  # GHA extent
rc <- r/100  # Unit conversion
```

## Spatial Data Management

### Zone Shapefile Structure

#### Current Configuration (geofsm-prod-all-zones-20240712.shp)
```
Total Features: 3,197 polygons
Zones Distribution:
├── Zone1: 86 features    (GRIDCODE 1-86)
├── Zone2: 254 features   (GRIDCODE 87-340)
├── Zone3: 471 features   (GRIDCODE 341-811)
├── Zone4: 390 features   (GRIDCODE 812-1201)
├── Zone5: 377 features   (GRIDCODE 1202-1578)
└── Zone6: 1619 features  (GRIDCODE 1579-3197)
```

#### Spatial Attributes
- **Coordinate System**: WGS84 (EPSG:4326)
- **Columns**: GRIDCODE, zone, id, geometry
- **Coverage**: East African river basins
- **Resolution**: Sub-basin level polygons

### Stream Order System

#### Purpose
The stream order files (`order5.txt`) define the hierarchical relationship between basin polygons and model computational units.

#### Implementation
```r
# Read stream order mapping
streamorder <- read.csv("order5.txt")[,1]

# Map polygon index to model basin
for(i in 1:length(streamorder)) {
  j <- which(streamorder == i)  # Find basin index
  model_input[, (j + 1)] <- extracted_data[,i]  # Assign to model column
}
```

#### Critical Function
- **Basin Ordering**: Ensures consistent column ordering in model input files
- **Index Mapping**: Links shapefile features to model computational nodes
- **Data Integrity**: Maintains spatial relationships in model inputs

### Zone5 Special Handling

#### Historical Issue
Original Zone5 shapefile used HydroBASINS format with HYBAS_ID instead of GRIDCODE, requiring special processing logic.

#### Current Status (Corrected Shapefile)
- **Issue Resolved**: Now uses standard GRIDCODE (1-377)
- **Data Gap**: Zone5 rain.txt references GRIDCODE 1-390, but shapefile only has 1-377
- **Missing Polygons**: 13 polygons (GRIDCODE 378-390) referenced in rain data but absent from shapefile

#### Recommendations
1. **Data Validation**: Verify if missing polygons should exist
2. **Rain Data Update**: Remove references to non-existent polygons (378-390)
3. **Consistency Check**: Ensure all zones have matching rain.txt coverage

## Model Input File Generation

### Output File Structure

#### rain.txt Format
```
Column 1: Julian Date (YYYYDDD format)
Column 2-N: Basin-specific precipitation values (mm/day)
Example:
2011001,0.5,1.2,0.0,2.3,...
2011002,1.1,0.8,0.5,1.7,...
```

#### Date Conversion Process
```r
# Convert to Julian day format
mydate <- ymd(ndate[i])
y <- year(mydate)
doy <- strftime(mydate, format="%j")
yd <- as.numeric(paste(y, doy, sep=""))
```

### Data Quality Requirements

#### Temporal Continuity
- **No Gaps**: Must have continuous daily time series
- **Format Consistency**: Julian date format required
- **Chronological Order**: Dates must be sorted chronologically

#### Spatial Completeness
- **All Basins**: Every basin must have values for each day
- **No Missing Data**: Use `na.rm=TRUE` in raster extraction
- **Unit Consistency**: All values in mm/day

#### File Validation
- **Column Count**: Must match number of basins + 1 (date column)
- **Row Count**: Must cover required time period
- **Numeric Values**: All data must be valid numbers

## Quality Control and Validation

### Data Source Validation

#### Download Verification
```r
# Check file existence after download
if (!file.exists(tmp)) {
  print(paste("Error: File not found:", tmp))
  next
}
```

#### Retry Logic
```r
# Multiple download attempts
attempt <- 1
while(is.null(rr) && attempt <= 3) {
  attempt <- attempt + 1
  try(curl_download(fname, tmp))
}
```

### Spatial Validation

#### Extent Checking
- **East Africa Bounds**: 19°E to 54°E, -14°S to 25°N
- **GHA Bounds**: 15°E to 55°E, -16°S to 25°N
- **Coordinate System**: Ensure WGS84 consistency

#### Polygon Integrity
- **Complete Coverage**: All rain.txt GRIDCODE values must have corresponding polygons
- **Unique Identifiers**: No duplicate GRIDCODE values
- **Spatial Topology**: Valid polygon geometries

### Temporal Validation

#### Gap Detection
```r
# IMERG gap checking
lag <- as.numeric(difftime(tdate, ldate))
if (lag > 1) {
  # Fill missing days
}
```

#### Date Continuity
- **Sequential Dates**: No missing days in time series
- **Format Validation**: Proper Julian day format
- **Time Zone Consistency**: UTC time reference

## Operational Workflow

### Daily Processing Sequence

#### 1. Data Acquisition Phase
```bash
# Morning execution (automated)
Rscript 1_gefs_dl.R           # Download latest CHIRPS-GEFS forecast
Rscript IMERG.R               # Update IMERG observations
Rscript PET.R                 # Update PET data
```

#### 2. Data Processing Phase
- **Spatial Cropping**: Subset to regional extents
- **Temporal Stacking**: Combine multiple days into raster stacks
- **Unit Conversion**: Standardize to mm/day
- **Quality Control**: Validate downloads and formats

#### 3. Model Input Generation
- **Zone Extraction**: Extract values for each basin polygon
- **Stream Order Mapping**: Map to model basin numbering
- **File Output**: Generate rain.txt and evap.txt files
- **Validation**: Check file completeness and format

#### 4. Model Execution (External)
- **GEOSFM Run**: Execute hydrological model with new inputs
- **Forecast Generation**: Produce streamflow forecasts
- **Output Processing**: Generate forecast products and visualizations

### Error Handling and Recovery

#### Common Issues
1. **Download Failures**: Network connectivity or server issues
2. **File Corruption**: Incomplete downloads or processing errors
3. **Spatial Misalignment**: Coordinate system inconsistencies
4. **Missing Data**: No-data values in raster extractions

#### Recovery Procedures
1. **Retry Downloads**: Multiple attempts with exponential backoff
2. **Fallback Data**: Use alternative data sources if primary fails
3. **Quality Flags**: Mark questionable data for manual review
4. **Notification System**: Alert operators of critical failures

### Performance Optimization

#### Processing Efficiency
- **Parallel Downloads**: Multiple simultaneous data retrievals
- **Raster Caching**: Store intermediate products for reuse
- **Incremental Updates**: Process only new/changed data
- **Memory Management**: Efficient handling of large raster stacks

#### Storage Management
- **Archive Policy**: Retain historical data for specified periods
- **Compression**: Use efficient storage formats for large datasets
- **Cleanup Procedures**: Remove temporary files and old data

## System Requirements and Dependencies

### R Environment
```r
# Required R packages
library(lubridate)      # Date/time handling
library(stringr)        # String manipulation
library(raster)         # Raster data processing
library(sf)             # Spatial features
library(curl)           # Web downloads
library(sp)             # Spatial data classes
library(rgdal)          # Geospatial data abstraction
```

### System Dependencies
- **R Version**: 3.6+ recommended
- **GDAL**: Geospatial Data Abstraction Library
- **PROJ**: Cartographic projections library
- **NetCDF**: Network Common Data Form support
- **CURL**: Command line tool for transferring data

### Infrastructure Requirements
- **Internet Connectivity**: High-speed connection for data downloads
- **Storage Space**: Sufficient disk space for raster archives
- **Processing Power**: Multi-core CPU for parallel processing
- **Memory**: Adequate RAM for large raster operations (8GB+ recommended)

### External Dependencies
- **NASA Earthdata Account**: Required for IMERG data access
- **Network Access**: Outbound HTTP/HTTPS connections
- **File System**: Read/write access to data directories
- **Scheduled Execution**: Cron or Task Scheduler for automation

## Conclusion

The GEOSFM data processing system represents a sophisticated integration of multiple satellite and forecast data sources to support operational hydrological forecasting in East Africa. The R-based workflow successfully transforms diverse geospatial datasets into standardized model inputs, enabling reliable streamflow predictions for water resource management and flood early warning applications.

Key strengths of the system include:
- **Multi-source Integration**: Combines complementary precipitation and evapotranspiration datasets
- **Automated Processing**: Minimal manual intervention required for daily operations
- **Quality Control**: Built-in validation and error handling procedures
- **Scalable Architecture**: Can be extended to additional regions or data sources

Areas for continued development:
- **Real-time Validation**: Automated comparison with ground-based observations
- **Ensemble Processing**: Integration of multiple forecast scenarios
- **Cloud Migration**: Transition to cloud-based processing infrastructure
- **Enhanced Monitoring**: Improved system health monitoring and alerting