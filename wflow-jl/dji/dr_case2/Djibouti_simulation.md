# Djibouti Drought Simulation (dr_case2)

## Overview

**Region:** Djibouti
**Drought Period:** 2021-01-01 to 2023-12-31 (1,095 days)
**Impact:** Severe drought affecting pastoral and agropastoral communities
**Data Source:** ICPAC Combined Drought Indicator (CDI)

### Geographic Extent
| Parameter | Value |
|-----------|-------|
| Longitude | 41.50°E to 43.50°E |
| Latitude | 10.90°N to 12.70°N |
| Grid Size | 201 x 224 cells |
| Resolution | ~1 km (0.009°) |
| Active Cells | 39,708 |

### Main Outlet
| Parameter | Value |
|-----------|-------|
| Coordinates | 41.5965°E, 11.1975°N |
| Upstream Area | 6,315.6 km² |

---

## Simulation Status

**Status:** ✅ COMPLETED
**Started:** 2026-02-01 03:34 UTC
**Completed:** 2026-02-01 03:40 UTC
**Duration:** 6 minutes
**Wflow Version:** v1.0.1
**Model Type:** SBM (Soil-Bucket-Model)
**Threads:** 4 (JULIA_NUM_THREADS=4)

### Output Summary
| Variable | Min | Max | Mean |
|----------|-----|-----|------|
| Q (m³/s) | 0.46 | 15.30 | 1.68 |
| Recharge (mm/day) | 0.0 | 3.46 | 0.37 |
| Soil Moisture L1 | 0.023 | 0.101 | 0.027 |
| Soil Moisture L2 | 68.64 | 69.76 | 69.09 |

---

## Input Data

### Core 10 GeoTIFF Datasets
| # | File | Description |
|---|------|-------------|
| 1 | `1_elevation_merit_1km.tif` | DEM from MERIT-Hydro |
| 2 | `2_landcover_esa_1km.tif` | ESA WorldCover land use |
| 3 | `3_soil_sand_1km.tif` | Sand fraction (%) |
| 4 | `3_soil_silt_1km.tif` | Silt fraction (%) |
| 5 | `3_soil_clay_1km.tif` | Clay fraction (%) |
| 6 | `4_soil_rootzone_depth_1km.tif` | Root zone depth |
| 7 | `5_soil_ksat_1km.tif` | Saturated hydraulic conductivity |
| 8 | `5_soil_porosity_1km.tif` | Soil porosity |
| 9 | `6_river_flow_direction_1km.tif` | D8 flow direction |
| 10 | `6_river_flow_accumulation_1km.tif` | Flow accumulation |

### Forcing Data
- **File:** `data/input/forcing.nc` (83 MB)
- **Period:** 2021-01-01 to 2023-12-31 (1,095 days)
- **Variables:** precip, temp, pet
- **Source:** CHIRPS + ERA5

---

## Errors Encountered and Fixes

### Issue 1: Brooks-Corey Bug (RESOLVED)

**Error:** `type InputEntries has no field soil_layer_water__brooks_corey_exponent`

**Previous Status:** BLOCKED - This was documented as unsolvable.

**Solution Found:** Apply the 4-layer workaround discovered in Rwanda/Ethiopia/Kenya:
- Create `c`, `kv`, `sl` with **4 layers** in staticmaps.nc
- Set TOML to use **3 layers**: `[100, 300, 800]` mm
- Wflow reads first 3 layers without triggering the bug

**Status:** ✅ FIXED

---

### Issue 2: LDD Cycles (Previously Fixed)

**Error:** `One or more cycles detected in flow graph`

**Solution:** pyflwdir regeneration from DEM (already applied)

**Status:** ✅ Already fixed

---

### Issue 3: Missing Values in Forcing

**Error:** `Forcing data has missing values on active model cells for precip`

**Cause:** Forcing data had NaN values at active cells (6-9% of grid)

**Solution:** Spatial interpolation using scipy.griddata with nearest neighbor:
```python
filled = griddata(valid_points, valid_values, nan_points, method='nearest')
```

**Status:** ✅ FIXED

---

### Issue 4: Invalid Soil Parameters (thetaS = 0)

**Error:** `DomainError with negative value: log was called with negative argument`

**Cause:** 518 cells had `thetaS = 0`, causing `thetaS - thetaR <= 0`

**Solution:** Set minimum valid thetaS:
```python
thetaS[invalid_mask] = thetaR[invalid_mask] + 0.15
```

**Status:** ✅ FIXED

---

### Issue 5: Zero Slope Values

**Problem:** 156 cells had Slope = 0, which can cause numerical issues

**Solution:** Set minimum slope:
```python
slope[zero_slope] = 0.001
```

**Status:** ✅ FIXED

---

## Configuration

### djibouti_sbm.toml Key Settings
```toml
[model]
soil_layer__thickness = [100, 300, 800]  # 3 layers (4 in NetCDF)
type = "sbm"
reservoir__flag = false
snow__flag = true

[time]
starttime = 2021-01-01T00:00:00
endtime = 2023-12-31T00:00:00

[output.csv]
path = "output_djibouti.csv"
```

### Output Variables
| Header | Parameter | Description |
|--------|-----------|-------------|
| Q | river_water__volume_flow_rate | Discharge at outlet (m³/s) |
| recharge | soil_water_saturated_zone_top__recharge_volume_flux | Mean recharge |
| soil_moisture_L1 | soil_layer_water__volume_fraction (layer=1) | Top 100mm |
| soil_moisture_L2 | soil_layer_water__volume_fraction (layer=2) | 100-400mm |

---

## File Structure

```
dr_case2/
├── djibouti_sbm.toml           # Main Wflow configuration
├── Djibouti_simulation.md      # This documentation
├── README.md                   # Project overview
├── data/
│   ├── input/
│   │   ├── staticmaps.nc       # 15.6 MB, 4-layer soil
│   │   ├── forcing.nc          # 83 MB, 1,095 timesteps
│   │   ├── staticmaps_original.nc  # Backup
│   │   └── forcing_backup.nc   # Backup
│   └── output/
│       ├── output_djibouti.csv # Results (1,094 days)
│       └── log.txt             # Simulation log
├── scripts/
│   └── fix_ldd_pyflwdir.py     # LDD fix script
└── 02_Djibouti_2021_2023/      # Raw data directory
```

---

## Key Lessons Learned

1. **4-Layer Workaround Works:** The Brooks-Corey bug that previously blocked Djibouti (and Eritrea) is now solved using the same 4-layer workaround from Rwanda/Ethiopia/Kenya.

2. **Forcing NaN Handling:** Spatial interpolation with nearest neighbor is effective for filling missing forcing values.

3. **Soil Parameter Validation:** Check for `thetaS <= thetaR` and zero slope values before running - these cause runtime errors.

4. **Small Domain Advantage:** Djibouti's small size (39K cells vs Kenya's 954K) allows very fast simulation (~6 min vs ~4.5 hours).

---

## References

- Rwanda simulation: `../dr_case6/Rwanda_simulation.md`
- Kenya simulation: `../dr_case5/Kenya_simulation.md`
- Ethiopia simulation: `../dr_case4/Ethiopia_simulation.md`
- Parent CLAUDE.md: `../CLAUDE.md`

---

*Document updated: 2026-02-01*
*Previous status: BLOCKED → Now: ✅ COMPLETED*
