# Ethiopia Wflow SBM Simulation

## Overview

- **Region:** Ethiopia (Blue Nile headwaters region)
- **Period:** 2020-01-02 to 2023-11-30 (1,429 days)
- **Drought Event:** 2020-2023 East African drought
- **Grid:** 1,671 × 1,351 cells (~1km resolution)
- **Outlet:** 33.1523°E, 15.1231°N (Blue Nile headwaters)

## Simulation Results

### Output Files

| File | Description | Size |
|------|-------------|------|
| `output_ethiopia_combined.csv` | Final combined output | 135 KB |
| `output_ethiopia_partial_backup.csv` | Part 1: 2020-01-02 to 2021-10-03 | 642 rows |
| `output_ethiopia.csv` | Part 2: 2021-10-05 to 2022-07-11 | 280 rows |
| `output_ethiopia_part2.csv` | Part 3: 2022-07-13 to 2023-11-30 | 506 rows |

### Summary Statistics

| Parameter | Min | Max | Mean |
|-----------|-----|-----|------|
| Discharge Q (m³/s) | 0.00 | 53,612.47 | 8,272.99 |
| Recharge (mm/day) | 0.0001 | 4.6511 | 0.2473 |
| Soil Moisture L1 (vol fraction) | 0.1165 | 0.5438 | 0.4135 |
| Soil Moisture L2 (vol fraction) | 0.5434 | 0.5477 | 0.5473 |

### Output Variables

- `Q` - River discharge at outlet (m³/s)
- `recharge` - Basin-average groundwater recharge (mm/day)
- `soil_moisture_L1` - Top soil layer (0-100mm) volumetric water content
- `soil_moisture_L2` - Root zone (100-400mm) volumetric water content
- `soil_moisture_L3` - Deep soil (400-1200mm) volumetric water content (NaN - not outputted)

## Input Data

### Staticmaps

- **File:** `data/input/staticmaps.nc`
- **Size:** 4.4 GB
- **Grid:** 1,671 × 1,351 cells
- **Lat range:** 2.996°N to 15.12°N
- **Lon range:** 33.0°E to 48.0°E
- **Soil layers:** 4 (workaround for Wflow v1.0.1 Brooks-Corey bug)

### Forcing Data

- **File:** `data/input/forcing.nc`
- **Size:** 536 MB
- **Variables:** Precipitation, PET, Temperature
- **Time steps:** Daily

## Simulation Execution

The simulation was run in three parts due to interruptions:

### Part 1 (Partial Backup)
- **Period:** 2020-01-02 to 2021-10-04
- **Status:** Completed but last day (2021-10-04) truncated
- **Rows:** 641 complete + 1 incomplete

### Part 2 (Main)
- **Period:** 2021-10-05 to 2022-07-11
- **Duration:** ~6 hours
- **Rows:** 280

### Part 3
- **Period:** 2022-07-13 to 2023-11-30
- **Duration:** ~6 hours
- **Rows:** 506

### Combined Output
- **Period:** 2020-01-02 to 2023-11-30
- **Total days:** 1,429
- **Interpolated dates:** 2021-10-04, 2022-07-12 (linear interpolation)

## Issues Encountered and Fixes

### Issue 1: Simulation Interruption
**Problem:** Long-running simulation was interrupted multiple times
**Solution:** Ran simulation in segments with different start/end dates, then combined outputs

### Issue 2: Incomplete Date (2021-10-04)
**Problem:** Last row of first segment was truncated mid-write
**Solution:** Excluded incomplete row and interpolated the missing date

### Issue 3: Missing Date (2022-07-12)
**Problem:** Gap between simulation segments
**Solution:** Linear interpolation of all variables for the missing date

### Issue 4: Brooks-Corey Bug Workaround
**Problem:** Wflow v1.0.1 bug with `soil_layer_water__brooks_corey_exponent`
**Solution:** Created `c`, `kv`, `sl` variables with 4 layers instead of 3 in staticmaps.nc

## Technical Configuration

### TOML Settings
```toml
[model]
soil_layer__thickness = [100, 300, 800]
type = "sbm"
reservoir__flag = false
snow__flag = true

[time]
starttime = 2020-01-01T00:00:00
endtime = 2023-12-31T00:00:00
```

### Kinematic Wave Settings
- Land flow: Adaptive timestepping, 3600s internal timestep
- River flow: Adaptive timestepping, 900s internal timestep

## Files

### Configuration
- `ethiopia_sbm.toml` - Main Wflow configuration

### Input Data
- `data/input/staticmaps.nc` - Static parameters (4.4 GB)
- `data/input/forcing.nc` - Meteorological forcing (536 MB)

### Output Data
- `data/output/output_ethiopia_combined.csv` - Combined simulation results
- `data/output/log.txt` - Simulation log (Part 2)
- `data/output/log_part2.txt` - Simulation log (Part 3)
- `data/output/log_partial_backup.txt` - Simulation log (Part 1)

## Post-Processing

The combined output was created using `combine_ethiopia_output.py` which:
1. Reads all three partial output files
2. Removes the incomplete 2021-10-04 row
3. Concatenates and sorts by date
4. Interpolates missing dates (2021-10-04, 2022-07-12) using linear interpolation
5. Saves the final combined CSV

## Status

✅ **COMPLETED**

- Staticmaps: 4.4 GB, 4-layer soil configuration
- Forcing: 536 MB, resampled to 1km grid
- LDD: Cycle-free
- Simulation: Completed in 3 parts
- Output: `output_ethiopia_combined.csv` (1,429 days, 135 KB)
