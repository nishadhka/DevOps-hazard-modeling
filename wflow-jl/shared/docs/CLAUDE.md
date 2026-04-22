# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Wflow SBM hydrological modeling for drought simulations in East Africa. Currently supports:
- **Burundi**: 2021-2022 drought (✅ fully operational)
- **Djibouti** (dr_case2): 2021-2023 drought (✅ fully operational)
- **Eritrea**: 2021-2023 drought (⚠️ 95% complete, Wflow v1.0.1 compatibility issue)
- **Rwanda** (dr_case6): 2016-2017 drought (✅ fully operational)
- **Ethiopia** (dr_case4): 2020-2023 drought (✅ fully operational)
- **Kenya** (dr_case5): 2020-2023 drought (✅ fully operational)

Derives 80+ spatial variables from 10 raw GeoTIFF inputs and runs daily hydrological simulations.

## Commands

### Run Wflow Simulation
```bash
# Burundi (working)
julia -e 'using Wflow; Wflow.run("burundi_sbm.toml")'

# Eritrea (blocked by Wflow v1.0.1 bug)
julia -e 'using Wflow; Wflow.run("eritrea_sbm.toml")'
```

### Python Processing Scripts
```bash
# Generate staticmaps.nc from raw GeoTIFFs
python derive_staticmaps.py

# Fix LDD cycles (run if Wflow throws "LDD cycles detected" error)
python fix_ldd_pyflwdir.py

# Resample forcing data to match staticmaps grid resolution
python resample_forcing.py
```

## Architecture

### Data Flow
```
wflow_datasets_1km/*.tif  →  derive_staticmaps.py  →  data/input/staticmaps.nc
                                                            ↓
forcing_raw.nc            →  resample_forcing.py   →  data/input/forcing.nc
                                                            ↓
                              {region}_sbm.toml     →  Wflow.jl  →  data/output/output_{region}.csv
```

### Key Files by Region
**Burundi:**
- `burundi_sbm.toml` - Configuration (2021-2022, 245×212 grid)
- `data/output/output_burundi.csv` - Results (729 days)
- Grid: 29.23°E, -4.50°S (main outlet)

**Eritrea:**
- `eritrea_sbm.toml` - Configuration (2021-2023, 628×758 grid)
- Grid: 36.33°E, 14.27°N (main outlet, 63,956 km² upstream)
- **Issue**: Blocked by Wflow v1.0.1 "soil_layer_water__brooks_corey_exponent" error

**Rwanda (dr_case6):**
- `dr_case6/case_sbm.toml` - Configuration (2016-2017, 212×234 grid)
- `dr_case6/data/output/output_rwanda.csv` - Results (731 days)
- Grid: 30.90°E, -2.08°S (main outlet, 19,039 km² upstream)
- **Status**: ✅ Fully operational using 4-layer Brooks-Corey workaround

### Python Script Responsibilities
| Script | Input | Output | Purpose |
|--------|-------|--------|---------|
| `derive_staticmaps.py` | 10 GeoTIFFs | staticmaps.nc | Derive all Wflow variables from raw spatial data |
| `fix_ldd_pyflwdir.py` | staticmaps.nc | staticmaps.nc (updated) | Fix flow direction cycles using pyflwdir |
| `resample_forcing.py` | forcing_raw.nc | forcing.nc | Match forcing to staticmaps grid resolution |

## Key Technical Details

### Soil Layer Configuration
**Critical**: Wflow v1.0.1 requires **exactly 3 soil layers** [100, 300, 800] mm total depth in TOML.
- The TOML must specify `soil_layer__thickness = [100, 300, 800]`
- **WORKAROUND for Brooks-Corey Bug**: Create the 'c' variable with **4 layers** in staticmaps.nc, even though only 3 are used. This bypasses a bug in Wflow v1.0.1:
  ```python
  # Create 4-layer c variable (workaround for v1.0.1 bug)
  c_layers_4 = np.zeros((4, ny, nx), dtype=np.float64)
  for i in range(3):
      c_layers_4[i] = c_original[i]
  c_layers_4[3] = c_original[2] * 0.95  # 4th layer (not used by Wflow)
  ```
- Similarly, update `kv` and `sl` to have 4 layers for consistency

### Flow Direction Encoding
- **D8 (input)**: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
- **LDD (Wflow)**: 1=SW, 2=S, 3=SE, 4=W, 5=pit, 6=E, 7=NW, 8=N, 9=NE
- Conversion is non-trivial; use `derive_staticmaps.py` mapping

### LDD Cycle Detection
If Wflow throws "One or more cycles detected in flow graph":
1. Run `fix_ldd_pyflwdir.py` to regenerate LDD from DEM using pyflwdir
2. This recalculates upstream area, river network, and derived parameters
3. Creates backup before modifying: `data/input/staticmaps_backup.nc`

### Wflow Output Parameters (v1.0.1 naming)
- Discharge: `river_water__volume_flow_rate`
- Recharge: `soil_water_saturated_zone_top__recharge_volume_flux`
- Soil moisture: `soil_layer_water__volume_fraction` with `layer = N`

### Common Errors and Fixes

**"LDD cycles detected"**
→ Run `fix_ldd_pyflwdir.py` to fix flow direction

**"Cannot convert Missing to UInt8"**
→ LDD variable has NaN/Missing values; fix with:
```python
ldd_fixed = np.where(np.isnan(ldd), 5, ldd).astype(np.uint8)
```

**"type InputEntries has no field soil_layer_water__brooks_corey_exponent"**
→ Known Wflow v1.0.1 bug; **SOLUTION FOUND**:
- Create 'c' variable with **4 layers** in staticmaps.nc (not 3)
- Also create 'kv' and 'sl' with 4 layers for consistency
- Keep TOML soil_layer__thickness = [100, 300, 800] (3 layers)
- Wflow reads first 3 layers from the 4-layer data without error
- This workaround was successfully used for Rwanda (dr_case6)

## Eritrea Setup Issues & Fixes (2026-01-23)

### Issue 1: LDD Variable Data Type
**Problem:** Initial staticmaps.nc had NaN/Missing values in wflow_ldd
**Error:** `Cannot convert Missing to UInt8`
**Fix:** Convert LDD to uint8 and replace NaN with 5 (pit):
```python
ldd_fixed = np.where(np.isnan(ldd), 5, ldd).astype(np.uint8)
```

### Issue 2: LDD Cycles
**Problem:** Flow direction network had circular dependencies
**Error:** `One or more cycles detected in flow graph`
**Fix:** Ran `fix_ldd_pyflwdir.py` which:
- Regenerates LDD from DEM using pyflwdir.from_dem()
- Ensures cycle-free flow routing
- Recalculates upstream area and river network
- Increased file size from 7.3 MB to 104 MB (added detailed routing)

### Issue 3: Wflow v1.0.1 Brooks-Corey Bug
**Problem:** Software bug in Wflow.jl v1.0.1
**Error:** `type InputEntries has no field soil_layer_water__brooks_corey_exponent`
**Status:** UNSOLVED - confirmed software bug
**Versions Tested:**
- v0.7.3: Config format incompatible (no CF-standard names)
- v0.8.1: Config format incompatible (no CF-standard names)
- v1.0.1: Brooks-Corey parameter bug (latest stable)

**Why Burundi Works but Eritrea Doesn't:**
The Burundi log file (data/output/log.txt) shows the SAME Brooks-Corey error occurred, but the output file exists (Jan 16, 2026). Key differences:
- **Grid size:** Burundi 245×212 (52K cells) vs Eritrea 628×758 (476K cells)
- **Scale:** Eritrea is 6x larger, may trigger different code paths
- **Timing:** Burundi may have used different staticmaps generation method
- The error may be non-fatal or intermittent depending on data characteristics

**Data Quality Verified:**
- ✅ 'c' variable present: (3, 628, 758) shape, float32
- ✅ All 40 variables present and valid
- ✅ LDD cycle-free and proper uint8
- ✅ Forcing aligned with staticmaps grid
- ✅ 3-layer configuration correct

**Current Status:** Data 100% ready, waiting for Wflow bug fix or alternative tool

## Dependencies

**Python**: numpy, xarray, rioxarray, scipy, pyflwdir

**Julia**: Wflow.jl v1.0.1 (v0.7.3 and v0.8.1 have config incompatibilities)

## Multi-Region Setup

When adding new regions:
1. Create `{region}_sbm.toml` with proper outlet coordinates
2. Ensure `wflow_datasets_1km/` contains region-specific GeoTIFFs
3. Run `derive_staticmaps.py` (modify for region name/extent)
4. Run `fix_ldd_pyflwdir.py` to ensure cycle-free LDD
5. Verify forcing.nc grid matches staticmaps.nc dimensions
6. Test with: `julia -e 'using Wflow; Wflow.run("{region}_sbm.toml")'`

## Troubleshooting Eritrea Simulation

**Final Status (2026-01-23):**
- ✅ Staticmaps generated and validated (104 MB, 40 variables)
- ✅ LDD data type fixed (no NaN/Missing)
- ✅ LDD cycles fixed with pyflwdir
- ✅ Forcing data aligned (793 MB, 1095 days)
- ✅ Configuration validated
- ❌ Blocked by Wflow v1.0.1 software bug

**Solutions:**
1. **Recommended:** File bug report with reproducible test case
2. Try HydroMT-Wflow as alternative execution engine
3. Run in external environment with working Wflow setup
4. Wait for Wflow v1.0.2+ bug fix

**Files Ready:**
- `eritrea_sbm.toml` - Configuration
- `data/input/staticmaps.nc` - 104 MB, cycle-free LDD, validated
- `data/input/forcing.nc` - 793 MB, 2021-2023

See `WFLOW_VERSION_TESTING_REPORT.md` for detailed version testing results.

## Rwanda Setup (dr_case6) - 2026-01-27

### Overview
- **Period:** 2016-01-01 to 2017-12-31 (730 days)
- **Impact:** 250,000 people affected by food shortages
- **Grid:** 212 × 234 cells (~1km resolution)
- **Outlet:** 30.8976°E, 2.0796°S (Akagera River, 19,039 km² upstream)

### Issues Encountered and Fixes

**Issue 1: Brooks-Corey Bug**
- Same error as Eritrea: `type InputEntries has no field soil_layer_water__brooks_corey_exponent`
- **FIX:** Created 'c', 'kv', 'sl' variables with 4 layers instead of 3
- Wflow reads first 3 layers without triggering the bug
- ✅ RESOLVED

**Issue 2: LDD Cycles**
- Error: `One or more cycles detected in flow graph`
- **FIX:** Ran `fix_ldd_pyflwdir.py` to regenerate LDD from DEM
- Reduced pit cells from 888 to 109 (proper cycle-free routing)
- ✅ RESOLVED

**Issue 3: Missing N_River Values**
- Error: `arrays contains missing values`
- **FIX:** After pyflwdir regenerated 9,454 river cells, N_River had 7,409 NaN values
- Filled missing values with default 0.035
- ✅ RESOLVED

**Issue 4: Grid Dimension Mismatch**
- Error: `BoundsError: attempt to access 42×38 Matrix at index [234, 212]`
- Forcing was 38×42 (5km), staticmaps was 212×234 (1km)
- **FIX:** Resampled forcing using bilinear interpolation to match staticmaps grid
- File size increased from 3.7 MB to 435 MB
- ✅ RESOLVED

### Final Status
- ✅ Staticmaps: 101.7 MB, 81 variables, 4-layer soil configuration
- ✅ Forcing: 435 MB, resampled to 1km grid, NaN values filled
- ✅ LDD: Cycle-free, 109 pit cells
- ✅ Simulation: **COMPLETED** (25 min 17 sec, 731 days simulated)
- ✅ Output: `output_rwanda.csv` (74 KB, discharge + soil moisture)

### Files
- `dr_case6/case_sbm.toml` - Configuration
- `dr_case6/data/input/staticmaps.nc` - 101.7 MB
- `dr_case6/data/input/forcing.nc` - 435 MB (resampled)
- `dr_case6/data/output/output_rwanda.csv` - Results
- `dr_case6/Rwanda_simulation.md` - Detailed documentation
