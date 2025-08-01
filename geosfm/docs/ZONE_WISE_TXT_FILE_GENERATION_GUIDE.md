# Zone-Wise Txt File Generation Guide

## Overview
This guide describes the comprehensive workflow for generating zone-wise txt files from the optimized lean table format created by `flox_shapefile_groupby_processor_v3.py`. The system converts climate model output data into zone-specific text files suitable for hydrological modeling and operational forecasting workflows.

## Data Flow Architecture

### Input Sources
1. **Lean Long Table Format** (from flox_shapefile_groupby_processor_v3.py)
   - Format: `gtime,zones_id,variable,mean_value,processed_at`
   - Variables: 1=imerg, 2=pet, 3=chirps_gefs
   - Time format: `YYYYMMDDTHH` (e.g., `2025073108`)

2. **Shapefile Reference** (`geofsm-prod-all-zones-20240712.shp`)
   - Columns: `GRIDCODE`, `zone`, `id`, `geometry`
   - 3,197 polygons across 6 zones (zone1-zone6)
   - Zone mapping: `zone` column contains zone identifiers

3. **Existing Zone Structure** (`zone_output/lt_stable_input_YYYYMMDD/`)
   - 6 zone directories: `zone1/` through `zone6/`
   - Each zone contains: `rain.txt`, `evap.txt`

## Target Output Structure

### Zone Directory Organization
```
zone_output/
├── lt_stable_input_20250501/  # Example date
│   ├── zone1/
│   │   ├── rain.txt    # Variables 1 (IMERG) + 3 (CHIRPS-GEFS)
│   │   └── evap.txt    # Variable 2 (PET)
│   ├── zone2/
│   │   ├── rain.txt    
│   │   └── evap.txt    
│   └── ... (zone3-zone6)
└── lt_stable_input_YYYYMMDD/  # New processing date
    ├── zone1/
    │   ├── rain.txt    
    │   └── evap.txt    
    └── ... (zone2-zone6)
```

### File Format Specifications

#### Header Row Format
```
NA,44,46,50,14,53,58,15,18,62,25,69,26,70,28,73,52,76,30,55,61,8,54,79,5,33,64,82,4,23,27,81,65,48,60,42,9,63,32,37,36,24,16,3,86,39,85,17,47,71,84,29,45,31,77,72,74,35,12,49,43,67,22,34,56,57,19,59,20,41,78,83,1,80,68,75,66,11,51,2,21,7,6,13,40,38,10
```
- **Purpose**: Represents spatial unit identifiers within each zone
- **Source**: Derived from shapefile `GRIDCODE` values for polygons in each zone
- **Count**: 87 values per zone (fixed structure for modeling consistency)

#### Data Row Format
```
YYYYDDD,value1,value2,value3,...,value87
```
- **Date Format**: Julian day format (YYYYDDD) where DDD is day of year (001-366)
- **Values**: Climate variable measurements for each spatial unit
- **Variables**:
  - `rain.txt`: Precipitation data (IMERG + CHIRPS-GEFS)
  - `evap.txt`: Evapotranspiration data (PET)

## Data Processing Strategy

### Historical Data Requirement (2011-Current)
- **Stability Period**: Hydrological models require data from 2011 onwards for proper initialization
- **Data Types**: Historical observations (2011-2024) + current observations + forecasts

### Variable Assignment Logic

#### IMERG Precipitation (Variable 1)
- **Source**: Satellite-based precipitation estimates
- **Temporal Coverage**: Last 7 days (observations) + current day
- **File Destination**: `rain.txt`
- **Processing**: Extract `mean_value` where `variable=1`

#### PET (Variable 2) 
- **Source**: Potential Evapotranspiration estimates
- **Temporal Coverage**: Single day data (typically sparse)
- **File Destination**: `evap.txt`
- **Processing**: Extract `mean_value` where `variable=2`
- **Replication Strategy**: Duplicate single-day PET values for forecast period alignment

#### CHIRPS-GEFS Precipitation (Variable 3)
- **Source**: Combined satellite/forecast precipitation
- **Temporal Coverage**: Current day + future forecast
- **File Destination**: `rain.txt` (combined with IMERG)
- **Processing**: Extract `mean_value` where `variable=3`

### Time Series Assembly Strategy

#### Rainfall Data Assembly (`rain.txt`)
1. **Historical Observations** (2011 - (Current-7days))
   - Source: Existing zone files (preserve historical data)
   - Approach: Copy from previous zone files, removing old forecasts

2. **Recent Observations** (Last 7 days)
   - Source: IMERG data (Variable 1)
   - Format conversion: `YYYYMMDDTHH` → `YYYYDDD`

3. **Current Day + Forecasts**
   - Source: CHIRPS-GEFS data (Variable 3)
   - Format conversion: `YYYYMMDDTHH` → `YYYYDDD`
   - Temporal alignment: Ensure forecast starts from current day

#### Evapotranspiration Data Assembly (`evap.txt`)
1. **Historical Data** (2011 - (Current-1day))
   - Source: Existing zone files (preserve historical data)

2. **Current Day**
   - Source: PET data (Variable 2)
   - Single-day measurement

3. **Forecast Period**
   - Strategy: Replicate current day PET value for forecast period
   - Duration: Match CHIRPS-GEFS forecast length

## Implementation Requirements

### Data Validation Checks
1. **Zone Completeness**: Ensure all 6 zones have data
2. **Spatial Unit Count**: Verify 87 values per data row
3. **Temporal Continuity**: Check for date gaps in time series
4. **Variable Consistency**: Validate variable encoding (1,2,3)

### Forecast Alignment Strategy
1. **Remove Old Forecasts**: Strip forecast portion from existing files
2. **Preserve Observations**: Keep all observational data
3. **Add New Data**: Append new observations + new forecasts
4. **Temporal Consistency**: Ensure no date overlap or gaps

### File Update Logic
```python
# Pseudo-code for file update strategy
def update_zone_file(existing_file, new_data, forecast_start_date):
    # 1. Load existing data
    historical_data = load_existing_file(existing_file)
    
    # 2. Remove old forecasts (keep only observations)
    observations_only = filter_observations(historical_data, forecast_start_date)
    
    # 3. Add new observations + forecasts
    updated_data = append_new_data(observations_only, new_data)
    
    # 4. Validate and save
    validate_temporal_continuity(updated_data)
    save_file(existing_file, updated_data)
```

## Processing Workflow Steps

### Step 1: Data Extraction
- Load lean long table CSV from flox processor
- Filter data by variable type (1, 2, 3)
- Convert time format: `YYYYMMDDTHH` → `YYYYDDD`

### Step 2: Zone Mapping
- Use shapefile to determine zone assignment for each `zones_id`
- Create mapping: `zones_id` → `zone` (zone1-zone6)
- Group data by zone and variable

### Step 3: Spatial Unit Assignment
- Map `zones_id` values to spatial unit positions (1-87)
- Create value arrays for each time step
- Ensure consistent spatial ordering across all time steps

### Step 4: File Generation/Update
- Create or update zone directories
- Generate rain.txt (Variables 1+3) and evap.txt (Variable 2)
- Apply forecast alignment and historical preservation logic

### Step 5: Quality Assurance
- Validate file formats and completeness
- Check temporal continuity
- Verify spatial unit consistency

## Technical Specifications

### Date Format Conversion
```python
# Convert from lean table format to Julian day
def convert_date_format(gtime_str):
    """Convert YYYYMMDDTHH to YYYYDDD format"""
    from datetime import datetime
    dt = datetime.strptime(gtime_str, '%Y%m%dT%H')
    julian_day = dt.timetuple().tm_yday
    return f"{dt.year}{julian_day:03d}"
```

### Spatial Unit Mapping
```python
# Map zones_id to spatial position within zone
def create_spatial_mapping(shapefile_path):
    """Create mapping from zones_id to spatial unit index"""
    import geopandas as gpd
    gdf = gpd.read_file(shapefile_path)
    
    # Group by zone and create index mapping
    zone_mappings = {}
    for zone in ['zone1', 'zone2', 'zone3', 'zone4', 'zone5', 'zone6']:
        zone_data = gdf[gdf['zone'] == zone].sort_values('GRIDCODE')
        zone_mappings[zone] = {
            row['id']: idx for idx, row in enumerate(zone_data.itertuples())
        }
    return zone_mappings
```

### File I/O Operations
```python
def write_zone_file(file_path, header, time_series_data):
    """Write zone file with header and time series data"""
    with open(file_path, 'w') as f:
        # Write header
        f.write(','.join(map(str, header)) + '\n')
        
        # Write time series data
        for date, values in time_series_data:
            row = [date] + list(values)
            f.write(','.join(map(str, row)) + '\n')
```

## Error Handling and Edge Cases

### Missing Data Handling
- **Missing Zones**: Create empty entries with zero values
- **Missing Time Steps**: Fill gaps with interpolated values or zeros
- **Missing Spatial Units**: Pad with zeros to maintain 87-value structure

### Forecast Period Handling
- **Variable Forecast Lengths**: Adapt evap.txt replication to match rain.txt forecast period
- **Forecast Start Detection**: Automatically detect observation vs. forecast boundary
- **Temporal Alignment**: Ensure all variables align temporally

### Historical Data Preservation
- **Backup Strategy**: Create backups before modifying existing files
- **Version Control**: Track changes to zone files
- **Rollback Capability**: Maintain ability to restore previous versions

## Quality Control Metrics

### Data Validation Checks
1. **Completeness**: All 6 zones, 87 spatial units each
2. **Temporal Continuity**: No gaps in date sequence
3. **Value Ranges**: Realistic climate variable ranges
4. **Format Consistency**: Proper CSV structure and date formats

### Processing Metrics
1. **Processing Time**: Track generation/update duration
2. **Data Volume**: Monitor file sizes and record counts
3. **Success Rate**: Percentage of successful zone file updates
4. **Error Logging**: Comprehensive error tracking and reporting

## Integration Points

### Upstream Dependencies
- `flox_shapefile_groupby_processor_v3.py`: Lean table generation
- Shapefile: Zone and spatial unit definitions
- Historical zone files: Existing time series data

### Downstream Applications
- Hydrological models requiring zone-wise input files
- Operational forecasting systems
- Climate analysis workflows

### Monitoring and Alerting
- File generation success/failure notifications
- Data quality alerts for anomalous values
- Processing time performance monitoring

## Usage Examples

### Basic Zone File Generation
```bash
python zone_wise_txt_generator.py \
    --lean-table flox_output/flox_results_lean_long_table_v3_20250731.csv \
    --shapefile geofsm-prod-all-zones-20240712.shp \
    --output-dir zone_output \
    --date-str 20250731
```

### Update Existing Zone Files
```bash
python zone_wise_txt_generator.py \
    --lean-table flox_output/flox_results_lean_long_table_v3_20250731.csv \
    --shapefile geofsm-prod-all-zones-20240712.shp \
    --output-dir zone_output \
    --date-str 20250731 \
    --update-existing \
    --preserve-history-from 20110101
```

### Generate Specific Zones Only
```bash
python zone_wise_txt_generator.py \
    --lean-table flox_output/flox_results_lean_long_table_v3_20250731.csv \
    --shapefile geofsm-prod-all-zones-20240712.shp \
    --output-dir zone_output \
    --date-str 20250731 \
    --zones zone1,zone3,zone5
```

## Performance Considerations

### Memory Management
- Process zones sequentially to manage memory usage
- Use streaming I/O for large historical files
- Implement data chunking for large time series

### Processing Optimization
- Parallel zone processing where possible
- Efficient data structure for spatial mappings
- Minimize file I/O operations

### Scalability Factors
- Historical data volume growth
- Increased spatial resolution (more zones/units)
- Extended forecast periods

## Conclusion

This comprehensive workflow enables the conversion of optimized lean table climate data into zone-specific text files suitable for operational hydrological modeling. The system maintains historical data integrity while incorporating new observations and forecasts, ensuring seamless integration with existing modeling workflows.

The implementation prioritizes data quality, temporal consistency, and processing efficiency while providing comprehensive error handling and quality control mechanisms.