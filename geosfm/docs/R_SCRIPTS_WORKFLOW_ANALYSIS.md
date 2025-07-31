# R Scripts Workflow Analysis

## Overview
This document analyzes the 5 R scripts found in the workspace that handle climate data processing, focusing on their workflows and the Zone5 shapefile handling.

## Script Analysis

### 1. chrips_gefs.R
**Purpose**: Downloads and processes CHIRPS-GEFS precipitation forecast data

**Key Workflow**:
- Downloads 16-day CHIRPS-GEFS precipitation forecasts from UCSB
- Processes historical data (last 7 days) and forecast data
- Crops raster data to East African extent (19°-54°E, -14°-25°N)
- **Zone5 Processing**: 
  - Reads zone5.shp from `D:/geofsm/BASINS41/modelout/WGS/zone5.shp`
  - Extracts areal average rainfall using `raster::extract()`
  - Uses streamorder data from `order5.txt` to map subcatchments
  - **Important**: Uses zone5 shapefile for spatial extraction but doesn't rely on GRIDCODE

**Zone5 Handling Strategy**:
- Uses HYBAS_ID or polygon geometry for spatial operations
- Relies on streamorder file for subcatchment indexing
- Outputs to Zone5 directory with rain.txt file

### 2. IMERG.R
**Purpose**: Downloads and processes IMERG precipitation data

**Key Workflow**:
- Downloads IMERG Early Run precipitation data from NASA
- Processes daily data with gap-filling capability
- Crops to Greater Horn of Africa (GHA) extent
- Converts raster to time series data
- **No direct zone processing** - focuses on grid-based data extraction

### 3. 2_last_7days_gefs_dl.R
**Purpose**: Enhanced version of CHIRPS-GEFS downloader with better error handling

**Key Workflow**:
- Downloads last 7 days of CHIRPS-GEFS data
- Includes improved error handling and debug statements
- Similar to chrips_gefs.R but focused on recent data
- **Zone5 Processing**: Same approach as chrips_gefs.R

### 4. 1_gefs_dl.R
**Purpose**: Primary CHIRPS-GEFS data downloader and processor

**Key Workflow**:
- Downloads 16-day forecast + 7-day historical data (23 days total)
- Processes and stacks raster data
- **Zone5 Processing**: Identical to chrips_gefs.R
  - Reads zone5.shp
  - Extracts areal averages
  - Uses streamorder indexing system

### 5. PET.R
**Purpose**: Downloads and processes Potential Evapotranspiration data

**Key Workflow**:
- Downloads PET data from USGS FEWS NET
- Processes daily PET data with gap-filling
- Crops to Greater Horn of Africa
- Converts units (from original to mm)
- **No zone processing** - creates grid-based time series

## Zone5 GRIDCODE Issue Analysis

### Problem Identification
Zone5 shapefile lacks GRIDCODE column, containing instead:
- HYBAS_ID (HydroBASINS identifier)
- Hydrological attributes (NEXT_DOWN, DIST_SINK, etc.)
- Sub-basin area and flow direction data

### Solution Implemented in R Scripts

**Strategy Used**:
1. **Streamorder File**: Uses external `order5.txt` file containing subcatchment IDs
2. **Sequential Indexing**: Maps subcatchments using array indices rather than GRIDCODE
3. **Spatial Extraction**: Uses polygon geometry directly for raster extraction
4. **Alternative ID System**: Relies on HYBAS_ID for unique identification

**Code Pattern**:
```r
# Read shapefile (no GRIDCODE dependency)
zone5 <- st_read("zone5.shp")

# Read streamorder file for indexing
streamorder <- read.csv("order5.txt")[,1]

# Extract data using polygon geometry
rain5 <- raster::extract(rc, as(zone5, "Spatial"), fun=mean, na.rm=TRUE)

# Map to streamorder indices
for(i in 1:length(streamorder)) {
  j <- which(streamorder == i)
  # Use index j instead of GRIDCODE
}
```

### Alternative Solutions Available

1. **HYBAS_ID as Substitute**: Use HYBAS_ID as unique identifier
2. **Geometry-based**: Direct polygon-to-raster extraction
3. **External Mapping**: Maintain separate lookup table (streamorder.txt)
4. **Sequential ID**: Create sequential numbering system

## Recommendations

1. **For Shapefile Merging**: Use HYBAS_ID as GRIDCODE substitute for Zone5
2. **Maintain Compatibility**: Keep streamorder mapping system
3. **Documentation**: Document the ID mapping strategy
4. **Quality Control**: Verify spatial alignment across all zones