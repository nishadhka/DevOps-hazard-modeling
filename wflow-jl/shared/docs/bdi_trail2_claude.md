# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Wflow SBM hydrological modeling for drought simulations in East Africa. Currently supports:
- **Burundi**: 2021-2022 drought (✅ fully operational)
- **Eritrea**: 2021-2023 drought (⚠️ 95% complete, Wflow v1.0.1 compatibility issue)
- **Djibouti**: 2021-2023 drought (⚠️ 95% complete, Wflow v1.0.1 compatibility issue)

Derives 80+ spatial variables from 10 raw GeoTIFF inputs and runs daily hydrological simulations.

## Commands

### Run Wflow Simulation
```bash
# Burundi (working)
julia -e 'using Wflow; Wflow.run("burundi_sbm.toml")'

# Eritrea (blocked by Wflow v1.0.1 bug)
julia -e 'using Wflow; Wflow.run("eritrea_sbm.toml")'

# Djibouti (blocked by Wflow v1.0.1 bug)
cd dr_case2 && julia -e 'using Wflow; Wflow.run("djibouti_sbm.toml")'
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

**Djibouti:**
- `dr_case2/djibouti_sbm.toml` - Configuration (2021-2023, 201×224 grid)
- Grid: 42.37°E, 11.82°N (main outlet, 6,316 km² upstream)
- **Issue**: Blocked by Wflow v1.0.1 "soil_layer_water__brooks_corey_exponent" error

### Python Script Responsibilities
| Script | Input | Output | Purpose |
|--------|-------|--------|---------|
| `derive_staticmaps.py` | 10 GeoTIFFs | staticmaps.nc | Derive all Wflow variables from raw spatial data |
| `fix_ldd_pyflwdir.py` | staticmaps.nc | staticmaps.nc (updated) | Fix flow direction cycles using pyflwdir |
| `resample_forcing.py` | forcing_raw.nc | forcing.nc | Match forcing to staticmaps grid resolution |

## Key Technical Details

### Soil Layer Configuration
**Critical**: Wflow v1.0.1 requires **exactly 3 soil layers** [100, 300, 800] mm total depth.
- Do NOT use 4-layer configurations with this version
- The 'c' variable (Brooks-Corey) must be 3D: (layer=3, lat, lon)
- Static maps with 4 layers will trigger initialization errors

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
→ Known Wflow v1.0.1 bug; try:
- Downgrade to Wflow v0.7.3 (config format incompatible)
- Verify 'c' variable is 3D (layer, lat, lon)
- Check soil_layer__thickness = [100, 300, 800] in TOML
- Report to: https://github.com/Deltares/Wflow.jl/issues

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

## Djibouti Setup Issues & Fixes (2026-01-27)

### Location
All Djibouti files are in `dr_case2/` directory.

### Data Preparation
- **Forcing**: 78 MB, 2021-2023 (1095 days), CHIRPS + ERA5
- **Staticmaps**: 63 variables derived from raw GeoTIFFs
- **Grid**: 201 x 224 (39,708 active cells)
- **Main outlet**: 42.37°E, 11.82°N (6,316 km² upstream)

### Issues Encountered & Resolutions

**Issue 1: Corrupted forcing.nc**
- System stuck during initial forcing generation
- **Fix**: Used pre-existing forcing.nc (78 MB) from parent directory

**Issue 2: LDD Data Type**
- **Error**: `Cannot convert Missing to UInt8`
- **Fix**: Regenerated LDD using pyflwdir with proper float32 format

**Issue 3: LDD Cycles**
- **Error**: `One or more cycles detected in flow graph`
- **Fix**: Ran pyflwdir.from_dem() to derive cycle-free LDD (200 pits)

**Issue 4: Missing Values in Active Cells**
- **Error**: `arrays contains missing values`
- **Fix**: Filled NaN values in Slope, RiverSlope with median values

**Issue 5: Mask Mismatch**
- wflow_subcatch had no mask while wflow_ldd had 5316 masked cells
- **Fix**: Applied consistent mask to all 2D variables

**Issue 6: Wflow v1.0.1 Brooks-Corey Bug (BLOCKING)**
- **Error**: `type InputEntries has no field soil_layer_water__brooks_corey_exponent`
- **Status**: UNSOLVED - Same bug as Eritrea

### Tests Performed

| Test | Details | Result |
|------|---------|--------|
| Small dataset | 10,019 cells (25% of original) | Same bug |
| More variables | 63 vars (vs initial 37) | Same bug |
| 4 soil layers | Instead of 3 | Same bug |

**Conclusion**: Bug is NOT caused by:
- Dataset size
- Missing variables
- Layer configuration

### Current Status (2026-01-27)
- ✅ Forcing data ready (78 MB, 3 years)
- ✅ Staticmaps ready (63 variables, cycle-free LDD)
- ✅ Configuration validated
- ❌ Blocked by Wflow v1.0.1 Brooks-Corey bug

### Files Ready
- `dr_case2/djibouti_sbm.toml` - Configuration
- `dr_case2/data/input/staticmaps.nc` - 63 variables
- `dr_case2/data/input/forcing.nc` - 78 MB, 2021-2023
- `dr_case2/Djibouti_simulation.md` - Detailed documentation

See `dr_case2/Djibouti_simulation.md` for complete issue documentation.
