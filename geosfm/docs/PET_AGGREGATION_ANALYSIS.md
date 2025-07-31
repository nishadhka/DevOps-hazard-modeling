# PET (Potential Evapotranspiration) Aggregation Analysis

## Overview
The `PET.R` script processes USGS FEWS NET potential evapotranspiration data. Like IMERG, this script does **NOT** perform shapefile-based spatial aggregation, instead processing data at individual grid points.

## Data Processing Approach

### Grid-Point Based Processing (No Shapefile Aggregation)
The script processes PET data at fixed grid coordinates without using shapefiles for spatial aggregation.

**Location in code:** Lines 60-86

```r
# Manual grid processing with fixed coordinates
k=1
for(j_lon in 1:40)
{
for(i_lat in 1:40)
{
pet=(round(r[k]/100,2))  # Convert from 0.01mm to mm

if (pet <0){
   m[i_lat,j_lon]=0      # Set negative values to 0
   k=k+1
} else{
 m[i_lat,j_lon]<-pet
 k=k+1
}
}
}

# Create time series for each grid point
for(j_lon in 1:40)
{
for(i_lat in 1:40)
{
lat = 25.0 - 1*(i_lat)    # Calculate latitude
lon = 14 + 1*(j_lon)      # Calculate longitude
x <- data.frame("Date"=cdate, "pet_daily_et_mm"=m[j_lon,i_lat])   
f=paste("pet_",round(lat, 2),"_",round(lon, 2),".csv", sep="")
write.table(x, file=f, append=TRUE, row.names=FALSE,col.names=FALSE, sep=",")
}
}
```

### Key Characteristics

**No Spatial Aggregation:**
- Processes data on a fixed 40x40 grid
- No shapefile interaction for polygon-based extraction
- Creates individual time series files for each grid point

**Data Processing Details:**
- **Unit Conversion:** Divides by 100 to convert from 0.01mm to mm units (`r[k]/100`)
- **Quality Control:** Sets negative PET values to 0
- **Coordinate System:** Fixed grid from 14°E to 54°E longitude, 25°N to -15°N latitude
- **Resolution:** 1-degree grid spacing

### Coordinate Calculation
```r
lat = 25.0 - 1*(i_lat)    # Latitude: 25°N to -15°N (decreasing)
lon = 14 + 1*(j_lon)      # Longitude: 15°E to 54°E (increasing)
```

### Why Mean Would Be Appropriate for PET

Unlike rainfall (which can be summed for total accumulation), **PET represents an intensity/rate** and should be aggregated using **mean** when working with shapefiles:

**Reasoning:**
- PET is potential evapotranspiration rate (mm/day)
- Averaging gives representative evapotranspiration demand for a region
- Summing would incorrectly inflate the evapotranspiration demand

### Cropping Operation
The script does crop the global data to a regional extent:

```r
# Crop to Greater Horn of Africa region
r <- crop(r2, extent(15,55,-16,25))
```

**Purpose:** Limits processing to East Africa region (15°E-55°E, -16°N-25°N)

### Comparison Summary

| Aspect | PET.R | IMERG.R | CHRIPS-GEFS |
|--------|-------|---------|-------------|
| **Aggregation Method** | None (fixed grid) | None (pixel-based) | Area-weighted mean |
| **Coordinate System** | Fixed 1° grid | Native pixel coords | Polygon-based zones |
| **Expected Aggregation** | **Mean** (for rates) | **Sum** (for totals) | **Mean** (used correctly) |
| **Quality Control** | Removes negative values | Unit conversion only | None specified |

### Missing Aggregation Implementation

If shapefile-based aggregation were implemented for PET, it should use **mean aggregation**:

```r
# Hypothetical aggregation code (not present in current script)
zones <- st_read("path/to/zones.shp")
# Use MEAN for PET (rate/intensity variable)
aggregated_pet <- raster::extract(rc, as(zones, "Spatial"), fun=mean, na.rm=TRUE, df=TRUE, weights=TRUE)
```

### Data Quality Features

**Negative Value Handling:**
```r
if (pet <0){
   m[i_lat,j_lon]=0  # Set negative PET to zero
}
```

**Unit Standardization:**
- Input: 0.01mm units
- Output: mm/day units (appropriate for hydrological modeling)

### Output Structure
- **File naming:** `pet_lat_lon.csv` (e.g., `pet_24.00_15.00.csv`)
- **Data format:** Date, PET_daily_et_mm
- **Spatial coverage:** 40x40 grid over East Africa
- **Temporal resolution:** Daily values