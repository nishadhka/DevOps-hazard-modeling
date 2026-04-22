# Eritrea Drought Simulation (dr_case3)

## Overview

**Region:** Eritrea
**Drought Period:** 2021-01-01 to 2023-12-31 (1,095 days)
**Data Source:** ICPAC Combined Drought Indicator (CDI)

### Geographic Extent
| Parameter | Value |
|-----------|-------|
| Longitude | 36.33°E to 43.15°E |
| Latitude | 12.40°N to 18.00°N |
| Grid Size | 628 x 758 cells |
| Resolution | ~1 km (0.009°) |
| Active Cells | 312,179 |

### Main Outlet
| Parameter | Value |
|-----------|-------|
| Coordinates | 36.3324°E, 14.2697°N |
| Upstream Area | 63,956 km² |

---

## Simulation Status

**Status:** BLOCKED
**Wflow Version:** v1.0.1
**Model Type:** SBM (Soil-Bucket-Model)

---

## Blocking Error

```
BoundsError: attempt to access NTuple{4, Float64} at index [0]
```

**Location:** `hydraulic_conductivity_at_depth` function in `~/.julia/packages/Wflow/WvtN2/src/utils.jl:723`

**Called from:** `leakage!` function in `soil/soil.jl:1100`

**Description:** The error occurs during soil leakage calculations. The function attempts to access layer index 0 of a 4-element tuple, but Julia uses 1-based indexing. This indicates a layer index calculation is returning 0 instead of a valid layer (1-4).

**Behavior:**
- Simulation initializes successfully
- Progress bar reaches 100%
- Error occurs during first timestep's leakage calculation
- 454 cells trigger this error (visible as "...and 453 more exceptions")

---

## Fixes Attempted

### Fix 1: 4-Layer Brooks-Corey Workaround
**Issue:** Wflow v1.0.1 has a bug: `type InputEntries has no field soil_layer_water__brooks_corey_exponent`

**Solution Applied:**
- Created `c` (Brooks-Corey exponent) with 4 layers instead of 3
- Created `kv` (vertical hydraulic conductivity factor) with 4 layers
- Created `sl` (soil layer thickness) with 4 layers
- TOML still specifies 3 layers: `[100, 300, 800]` mm

**Result:** Bypasses Brooks-Corey bug but introduces BoundsError

---

### Fix 2: thetaS Validation
**Issue:** 875 active cells had thetaS = 0 or thetaS <= thetaR

**Solution Applied:**
```python
thetaS[invalid] = thetaR[invalid] + 0.15
```

**Result:** Fixed, but BoundsError persists

---

### Fix 3: RootingDepth Zeros
**Issue:** 3,447 active cells had RootingDepth = 0

**Solution Applied:**
```python
rd[rd_zero] = 100.0  # Set to first layer thickness
```

**Result:** Fixed, but BoundsError persists

---

### Fix 4: Slope Zeros
**Issue:** Some cells had Slope = 0

**Solution Applied:**
```python
slope[slope_zero] = 0.001
```

**Result:** Fixed (original backup had no zero slopes on active cells)

---

### Fix 5: Layer Coordinate Indexing
**Attempt 1:** Changed layer coordinate from `[1, 2, 3, 4]` to `[0, 1, 2, 3]`

**Result:** BoundsError persists

**Attempt 2:** Reduced to 3 layers to match TOML

**Result:** Triggers Brooks-Corey bug instead

---

### Fix 6: Snow Disabled
**Attempt:** Ran with `snow__flag = false`

**Result:** BoundsError persists

---

### Fix 7: Single Thread Execution
**Attempt:** Ran with `JULIA_NUM_THREADS=1`

**Result:** BoundsError persists (cleaner stack trace, same error)

---

### Fix 8: MaxLeakage Non-Zero
**Attempt:** Set MaxLeakage from 0 to 0.0001

**Result:** Not yet tested (Djibouti also has all-zero MaxLeakage and works)

---

## Comparison with Working Simulations

### Djibouti (dr_case2) - WORKS
| Parameter | Eritrea | Djibouti |
|-----------|---------|----------|
| Grid Size | 628 x 758 | 201 x 224 |
| Active Cells | 312,179 | 39,708 |
| c values | 0.10 - 0.50 | 0.095 - 0.50 |
| Layer coord | [1, 2, 3, 4] | [1, 2, 3, 4] |
| c dtype | float32 | float32 |
| MaxLeakage | 0 (all) | 0 (all) |
| thetaS min | 0.2159 | 0.2159 |

**Key Observation:** Data structures are nearly identical, yet Djibouti works and Eritrea fails.

### Kenya (dr_case5) - WORKS
- Uses same 4-layer workaround
- c values: 8.6 - 8.8 (higher than Eritrea/Djibouti)
- 954,123 active cells (3x Eritrea)

### Rwanda (dr_case6) - WORKS
- Uses same 4-layer workaround
- c values: 8.2 - 8.8

---

## Possible Root Causes

1. **Unknown Data Anomaly:** Some characteristic of the Eritrea data causes layer index calculation to return 0, but this characteristic is not obvious from comparing with working simulations.

2. **Grid Size/Memory Issue:** Eritrea has 312K active cells vs Djibouti's 40K. Possible memory or threading issue at scale.

3. **Wflow Bug:** The `hydraulic_conductivity_at_depth` function may have an edge case bug triggered by specific data values present in Eritrea but not other regions.

4. **Water Table Depth Issue:** The leakage function uses water table depth (zi) to determine layer index. If zi becomes 0 or negative during initialization or first timestep, it could cause index 0.

---

## Files

| File | Size | Description |
|------|------|-------------|
| `case_sbm.toml` | 3.3 KB | Wflow configuration |
| `data/input/staticmaps.nc` | ~125 MB | Static parameters (4-layer) |
| `data/input/forcing.nc` | 830 MB | Forcing data (1,095 days) |
| `data/output/log.txt` | varies | Simulation log with error |
| `data/output/output_eritrea.csv` | 1 line | Empty (only header) |

### Backup Files
- `staticmaps_backup.nc` - Original before any fixes
- `staticmaps_backup2.nc` - After initial 4-layer fix
- `staticmaps_1based.nc` - With 1-based layer indexing
- `staticmaps_backup3.nc` - Before MaxLeakage fix

---

## Next Steps to Try

1. **Deep comparison with Djibouti:** Cell-by-cell comparison of all variables to find any subtle differences

2. **Subset testing:** Create a small test domain with subset of Eritrea cells to isolate problematic cells

3. **Initial conditions:** Add explicit initial water table depth (zi) variable

4. **Alternative Wflow version:** Test with development version of Wflow if available

5. **File bug report:** Submit reproducible test case to Wflow developers

---

## Commands

### Run Simulation (Currently Failing)
```bash
JULIA_NUM_THREADS=4 julia -e 'using Wflow; Wflow.run("case_sbm.toml")'
```

### Verify Data
```python
import xarray as xr
ds = xr.open_dataset('data/input/staticmaps.nc')
print(ds['c'].shape)  # Should be (4, 628, 758)
print(ds.coords['layer'].values)  # Should be [1, 2, 3, 4]
```

---

*Document created: 2026-02-01*
*Status: BLOCKED - BoundsError in hydraulic_conductivity_at_depth*
