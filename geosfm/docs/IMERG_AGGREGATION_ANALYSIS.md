# IMERG Rainfall Aggregation Analysis

## Overview
The `IMERG.R` script processes NASA's Integrated Multi-satellitE Retrievals for GPM (IMERG) precipitation data. However, this script does **NOT** perform shapefile-based spatial aggregation.

## Data Processing Approach

### Grid-Point Based Processing (No Shapefile Aggregation)
Unlike CHRIPS-GEFS, this script processes data at individual grid points rather than aggregating within polygon boundaries.

**Location in code:** Lines 55-66

```r
# Convert raster to dataframe with coordinates
x <- as.data.frame(rc, xy=TRUE)
y <- t(x)

# Process each grid point individually
for(i in 1:length(y[1,])){
    z <- data.frame("Date"=Date, "Guage_Grid_dailymm"=y[3, i]/10) 
    f <- paste("IMERG", round(y[2,i],2), "_", round(y[1,i],2), ".csv", sep="")
    write.table(z, file=f, append=TRUE, row.names=FALSE, col.names=FALSE, sep=",")
}
```

### Key Characteristics

**No Spatial Aggregation:** 
- Each raster pixel is processed individually
- No shapefile interaction or polygon-based extraction
- Creates separate time series files for each grid point

**Data Processing:**
- **Unit Conversion:** Divides by 10 to convert from 0.1mm to mm units (`y[3, i]/10`)
- **Coordinate Extraction:** Uses `xy=TRUE` to get lat/lon coordinates
- **File Naming:** Creates files named by coordinates (e.g., `IMERG_lat_lon.csv`)

### Shapefile Usage
The script does read a shapefile, but only for **cropping purposes**:

```r
# Cropping raster to GHA (Greater Horn of Africa)
dsn <- "C:/Data/GIS/WGS/GHA_Admin1.shp"
ppoly = readOGR(dsn)
e <- extent(ppoly)  # Get spatial extent
r <- raster(tmp)
rc <- crop(r,e)     # Crop raster to shapefile extent
```

**Purpose:** The shapefile is used to define the spatial boundary for cropping the global IMERG data to the Greater Horn of Africa region, not for aggregation.

### Comparison with CHRIPS-GEFS

| Aspect | IMERG.R | CHRIPS-GEFS |
|--------|---------|-------------|
| **Aggregation Method** | None (grid-point based) | Area-weighted mean |
| **Shapefile Usage** | Cropping boundary only | Spatial aggregation zones |
| **Output** | Individual pixel time series | Aggregated zonal averages |
| **File Structure** | One file per grid point | One file per zone |

### Why No Aggregation in IMERG?

The IMERG script appears to be designed for:
1. **High-resolution analysis** - Preserving original pixel resolution
2. **Point-based validation** - Comparing with ground station data
3. **Flexible post-processing** - Allowing users to aggregate later as needed

### Data Flow Summary

1. **Download:** Retrieve IMERG data from NASA servers
2. **Crop:** Limit to Greater Horn of Africa using shapefile extent
3. **Convert:** Transform raster to coordinate-value pairs
4. **Export:** Create individual CSV files for each grid point

### Missing Aggregation Capability

If shapefile-based aggregation were needed for IMERG data, it would require adding code similar to:

```r
# Hypothetical aggregation code (not present in current script)
zones <- st_read("path/to/zones.shp")
aggregated_rain <- raster::extract(rc, as(zones, "Spatial"), fun=mean, na.rm=TRUE, df=TRUE, weights=TRUE)
```