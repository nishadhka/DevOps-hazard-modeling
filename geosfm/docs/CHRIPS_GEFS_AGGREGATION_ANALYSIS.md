# CHRIPS-GEFS Rainfall Aggregation Analysis

## Overview
The `chrips_gefs.R` script processes CHIRPS-GEFS precipitation data and performs spatial aggregation using shapefiles to calculate areal average rainfall for different zones.

## Key Aggregation Method

### Shapefile-Based Aggregation
The script uses **mean aggregation** with area weighting for extracting rainfall values from raster pixels within polygon boundaries.

**Location in code:** Lines 163-173

```r
# Read sub cat shapefile
dsn <- "D:/geofsm/BASINS41/modelout/WGS/zone5.shp"
zone5 <- st_read(dsn)

streamorder <- read.csv(file="D:/geofsm/streamorder/order5.txt")[,1]
Areal.average.rainfall <- array(NA, dim=c(17, length(streamorder) + 1))

# KEY AGGREGATION LINE - Uses MEAN with area weighting
rain5 <- raster::extract(rc, as(zone5, "Spatial"), fun=mean, na.rm=TRUE, df=TRUE, weights=TRUE)
```

### Aggregation Details

**Method:** `fun=mean` with `weights=TRUE`
- **Function:** Area-weighted mean
- **Purpose:** Calculate average rainfall intensity (mm) across each polygon
- **Weighting:** Uses pixel area weights to account for partial pixel coverage
- **Missing Data:** `na.rm=TRUE` excludes missing values from calculation

### Data Processing Flow

1. **Raster Stack Creation:** Combines 23 days of rainfall data into a raster stack
2. **Spatial Extraction:** Extracts values from raster pixels that intersect with polygon boundaries
3. **Aggregation:** Computes area-weighted mean rainfall for each polygon
4. **Output:** Generates time series data for each hydrological zone

### Why Mean Instead of Sum?

For rainfall data, using **mean** rather than sum is appropriate because:
- The output represents rainfall **intensity** (mm/day) rather than total volume
- Each polygon gets a representative rainfall value that can be used for hydrological modeling
- Area weighting ensures larger pixels don't disproportionately influence the result

### Code Example of the Core Aggregation
```r
# This line performs the key aggregation
rain5 <- raster::extract(rc, as(zone5, "Spatial"), fun=mean, na.rm=TRUE, df=TRUE, weights=TRUE)

# Process results
df <- t(data.frame(rain5))
df <- df[-1,]  # Remove ID column
df <- round(df, 1)  # Round to 1 decimal place
```

### Output Format
The aggregated data is written to text files with the following structure:
- Column 1: Date (YYYYDDD format)
- Remaining columns: Average rainfall (mm) for each stream order zone

**File output location:** `D:/geofsm/BASINS41/modelout_imerg/Zone5/rain.txt`