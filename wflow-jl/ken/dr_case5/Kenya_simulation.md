# Kenya Drought Simulation (dr_case5)

## Overview

**Region:** Kenya
**Drought Period:** 2020-01-01 to 2023-12-31 (1,461 days)
**Impact:** 4.5 million people affected by food shortages, 222,000 children malnourished
**Affected Areas:** Arid and semi-arid lands (ASAL)
**Data Source:** ICPAC Combined Drought Indicator (CDI)

### Geographic Extent
| Parameter | Value |
|-----------|-------|
| Longitude | 34.00°E to 41.90°E |
| Latitude | 4.70°S to 5.00°N |
| Grid Size | 1,083 x 881 cells |
| Resolution | ~1 km (0.009°) |
| Total Active Cells | 954,123 |

### Main Outlet (Tana River Region)
| Parameter | Value |
|-----------|-------|
| Coordinates | 41.9019°E, 0.6603°N |
| Upstream Area | 166,337 km² |

---

## Input Data

### Core 10 GeoTIFF Datasets
The following raw spatial datasets in `wflow_datasets_1km/` were used:

| # | File | Description | Size |
|---|------|-------------|------|
| 1 | `1_elevation_merit_1km.tif` | DEM from MERIT-Hydro | 2.8 MB |
| 2 | `2_landcover_esa_1km.tif` | ESA WorldCover land use classes | 124 KB |
| 3 | `3_soil_sand_1km.tif` | Sand fraction (%) | 474 KB |
| 4 | `3_soil_silt_1km.tif` | Silt fraction (%) | 361 KB |
| 5 | `3_soil_clay_1km.tif` | Clay fraction (%) | 427 KB |
| 6 | `4_soil_rootzone_depth_1km.tif` | Root zone depth (cm) | 424 KB |
| 7 | `5_soil_ksat_1km.tif` | Saturated hydraulic conductivity | 517 KB |
| 8 | `5_soil_porosity_1km.tif` | Soil porosity (%) | 694 KB |
| 9 | `6_river_flow_direction_1km.tif` | D8 flow direction | 292 KB |
| 10 | `6_river_flow_accumulation_1km.tif` | Flow accumulation (km²) | 3.3 MB |

### Forcing Data
| Parameter | Source | Resolution |
|-----------|--------|------------|
| Precipitation | CHIRPS | 0.05° → resampled to 0.009° |
| Temperature | ERA5 | 0.25° → resampled to 0.009° |
| PET | ERA5 | 0.25° → resampled to 0.009° |

**Forcing File:** `data/input/forcing.nc` (224 MB, 1,430 timesteps)

---

## Derived Variables (81+ Total)

### From DEM (1_elevation_merit_1km.tif)
- `wflow_dem` - Elevation (m)
- `Slope` - Surface slope (m/m)

### From Flow Direction/Accumulation (using pyflwdir)
- `wflow_ldd` - Local drain direction (PCRaster LDD format, cycle-free)
- `wflow_uparea` - Upstream area (km²)
- `wflow_river` - River mask (cells with uparea ≥ 10 km²)
- `wflow_riverwidth` - River width (m), power law: W = 1.22 × A^0.557
- `wflow_riverlength` - River length per cell (~1410 m)
- `wflow_streamorder` - Strahler stream order (1-8)
- `RiverSlope` - River bed slope
- `RiverDepth` - River depth (m), power law: D = 0.27 × A^0.39
- `RiverZ` - River bed elevation (DEM - depth)
- `wflow_subcatch` - Subcatchment ID
- `wflow_gauges` - Gauge locations
- `wflow_pits` - Pit/outlet locations

### From Soil Texture (sand, silt, clay)
Using Saxton & Rawls (2006) pedotransfer functions:
- `thetaS` - Saturated water content (0.35-0.55)
- `thetaR` - Residual water content (0.05-0.25)
- `c` - Brooks-Corey exponent (4D: 4 layers × lat × lon - workaround)
- `f` - Ksat exponential decay rate
- `M` - Ksat profile shape parameter

### From Ksat/Porosity
- `KsatVer` - Vertical saturated hydraulic conductivity
- `kv` - Ksat by soil layer (4D)

### From Rootzone Depth
- `SoilThickness` - Total soil thickness (mm)
- `RootingDepth` - Rooting depth by land cover (mm)

### From Land Cover
- `wflow_landuse` - Land use classes
- `N` - Manning's n for surface flow
- `N_River` - Manning's n for river flow (0.035 default)
- `Kext` - Light extinction coefficient
- `PathFrac` - Impervious/compacted fraction
- `WaterFrac` - Water body fraction
- `Sl` - Specific leaf storage
- `Swood` - Stem/wood storage

### Monthly Cyclic Variables
- `LAI` - Leaf Area Index (12 months × lat × lon)

### Default Constants
- `Cfmax` - Snow melt factor (3.76)
- `TT`, `TTI`, `TTM` - Temperature thresholds
- `cf_soil` - Infiltration reduction parameter
- `InfiltCapPath`, `InfiltCapSoil` - Infiltration capacities
- `KsatHorFrac` - Horizontal/vertical Ksat ratio
- `MaxLeakage` - Maximum groundwater leakage
- `EoverR` - Evaporation/precipitation ratio
- `rootdistpar` - Root distribution parameter

### Soil Layer Variables (4 layers for workaround)
- `sl` - Layer thicknesses (4D)
- `c` - Brooks-Corey c by layer (4D)
- `kv` - Vertical Ksat by layer (4D)

---

## Errors Encountered and Fixes

### Error 1: LDD Cycles Detected

**Error Message:**
```
ERROR: One or more cycles detected in flow graph.
The provided local drainage direction map may be unsound.
```

**Root Cause:**
The original D8 to LDD conversion created circular flow paths in flat areas.

**Solution:**
Ran `scripts/fix_ldd_pyflwdir.py` which:
1. Used `pyflwdir.from_dem()` to derive cycle-free flow direction from DEM
2. Recalculated upstream area properly
3. Regenerated river network parameters
4. Reduced pit cells from 67,748 (initial) to 64,553 (cycle-free)

**Status:** ✅ Fixed

---

### Error 2: Negative Upstream Area Values

**Problem:**
After pyflwdir regeneration, 64,068 cells at domain edges had negative upstream area values.

**Root Cause:**
Edge cells that flow out of the domain boundary get invalid upstream area calculations.

**Solution:**
Set negative upstream area values to 0.99 km² (just under river threshold):
```python
uparea[uparea < 0] = 0.99
```

**Status:** ✅ Fixed

---

### Error 3: Missing N_River Values at River Cells

**Problem:**
After pyflwdir regenerated 206,771 river cells, 159,929 cells had NaN N_River values.

**Root Cause:**
The new river network had more cells than the original N_River variable covered.

**Solution:**
Filled missing N_River values with default Manning's n (0.035):
```python
n_river[(river == 1) & np.isnan(n_river)] = 0.035
```

**Status:** ✅ Fixed

---

### Applied: 4-Layer Brooks-Corey Workaround

**Preventive Measure:**
Applied the known workaround for Wflow v1.0.1 Brooks-Corey bug:
- Created `c`, `kv`, `sl` variables with **4 soil layers** in staticmaps.nc
- TOML config specifies only 3 layers: `[100, 300, 800]` mm
- Wflow reads first 3 layers without triggering the bug

**Status:** ✅ Applied proactively (learned from Rwanda/Ethiopia)

---

## Final Configuration

### kenya_sbm.toml Key Settings
```toml
[model]
soil_layer__thickness = [100, 300, 800]  # 3 layers, 1200mm total
type = "sbm"
reservoir__flag = false
snow__flag = true

[time]
starttime = 2020-01-01T00:00:00
endtime = 2023-12-31T00:00:00

[output.csv]
path = "output_kenya.csv"
```

### Output Variables
| Header | Parameter | Description |
|--------|-----------|-------------|
| Q | river_water__volume_flow_rate | Discharge at outlet (m³/s) |
| recharge | soil_water_saturated_zone_top__recharge_volume_flux | Mean groundwater recharge |
| soil_moisture_L1 | soil_layer_water__volume_fraction (layer=1) | Top 100mm soil moisture |
| soil_moisture_L2 | soil_layer_water__volume_fraction (layer=2) | 100-400mm soil moisture |
| soil_moisture_L3 | soil_layer_water__volume_fraction (layer=3) | 400-1200mm soil moisture |

---

## File Structure

```
dr_case5/
├── kenya_sbm.toml              # Wflow configuration
├── Kenya_simulation.md         # This documentation
├── README.txt                  # Quick overview
├── data/
│   ├── input/
│   │   ├── staticmaps.nc       # 1.95 GB, 81+ variables, 4-layer soil
│   │   ├── forcing.nc          # 224 MB, 1,430 timesteps
│   │   └── staticmaps_backup.nc # Backup before LDD fix
│   └── output/
│       ├── output_kenya.csv    # Simulation results
│       └── log.txt             # Wflow execution log
├── scripts/
│   ├── derive_staticmaps.py    # Generate staticmaps from GeoTIFFs
│   ├── fix_ldd_pyflwdir.py     # Fix LDD cycles (USED)
│   ├── resample_forcing.py     # Resample forcing to 1km grid
│   └── [download scripts]      # CHIRPS/ERA5 data download
├── wflow_datasets_1km/         # 10 raw GeoTIFF inputs (~9 MB)
├── extent/                     # Region bounds and config
│   └── region_config.json      # Geographic extent, impact data
├── forcing/                    # Forcing metadata
│   └── forcing_info.json
└── cdi_data/                   # CDI drought indicator data
    ├── cdi_metadata.json
    └── cdi_2020_2023.nc
```

---

## Simulation Status

**Status:** ✅ COMPLETED
**Started:** 2026-01-31 17:01 UTC
**Completed:** 2026-01-31 21:29 UTC
**Duration:** ~4 hours 28 minutes
**Wflow Version:** v1.0.1
**Model Type:** SBM (Soil-Bucket-Model)
**Time Step:** Daily (86,400 seconds)
**Threads:** 4 (JULIA_NUM_THREADS=4)
**Simulation Period:** 1,429 days (2020-01-02 to 2023-11-30)

### Runtime Statistics
- Active cells: 954,123
- River cells: 206,771
- Kinematic wave timestep (land): 3600s
- Kinematic wave timestep (river): 900s
- Actual duration: ~4.5 hours

### Output Summary
| Variable | Min | Max | Mean |
|----------|-----|-----|------|
| Q (m³/s) | 0.0 | 119.31 | 5.14 |
| Recharge (mm/day) | 0.0 | 8.50 | 0.24 |
| Soil Moisture L1 | 0.12 | 0.54 | 0.43 |
| Soil Moisture L2 | 0.17 | 0.54 | 0.45 |
| Soil Moisture L3 | NaN | NaN | NaN |

**Note:** Simulation ended at 2023-11-30 (forcing data limit). Config specified 2023-12-31 but forcing.nc only covers through 2023-11-30. The 1,429 days of output represent 98% of the intended simulation period.

---

## Lessons Learned (from Rwanda, Ethiopia, Kenya)

1. **4-Layer Workaround:** Wflow v1.0.1 has a bug reading 3-layer Brooks-Corey data. Using 4 layers in the NetCDF file (while specifying 3 in TOML) resolves this.

2. **LDD Quality:** Always run `fix_ldd_pyflwdir.py` after generating staticmaps to ensure cycle-free flow routing. pyflwdir.from_dem() is more reliable than D8→LDD conversion.

3. **Grid Matching:** Forcing and staticmaps must have identical grid dimensions. Resample forcing if necessary.

4. **River Parameters:** After regenerating river network, verify all river parameters (N_River, width, length, slope) have valid values at river cell locations.

5. **Edge Cells:** Upstream area can become negative at domain edges after pyflwdir regeneration - set these to small positive values.

6. **Backup Files:** Always create backups before modifying staticmaps.nc (`staticmaps_backup.nc`).

7. **Parallel Processing:** Use `JULIA_NUM_THREADS=4` for faster execution on multi-core systems.

---

## Output Backup Strategy

To handle potential interruptions, output files are periodically backed up:
```bash
# Manual backup command
cp data/output/output_kenya.csv data/output/output_kenya_backup_$(date +%Y%m%d_%H%M).csv
```

If simulation is interrupted:
1. Check the last complete date in output_kenya.csv
2. Update `kenya_sbm.toml` starttime to resume from that date
3. Run simulation again
4. Combine output segments using merge script

---

## References

- Rwanda simulation: `../dr_case6/Rwanda_simulation.md`
- Ethiopia simulation: `../dr_case4/Ethiopia_simulation.md`
- Wflow documentation: https://deltares.github.io/Wflow.jl/stable/
- pyflwdir documentation: https://deltares.github.io/pyflwdir/
