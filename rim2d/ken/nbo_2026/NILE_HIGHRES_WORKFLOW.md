# RIM2D High-Resolution Flood Simulation Workflow

## A Step-by-Step Guide for Replicating Urban Flood Modelling at 30m Resolution

**Case study:** Abu Hamad, River State, Sudan (~19.53N, 33.33E)
**Model:** RIM2D GPU-accelerated 2D hydraulic inundation model (CUDA Fortran)
**Grid:** 281 x 223 cells, ~30m resolution, UTM Zone 36N (EPSG:32636)
**Domain:** ~8.4 km x 6.7 km (56 km2)

This document describes every script, its purpose, when to run it, and the lessons learned from 9 iterations (v1-v9) of progressively improving the simulation. It is written to be transferable to a different study area.

---

## Table of Contents

1. [Workflow Overview](#1-workflow-overview)
2. [Environment Setup](#2-environment-setup)
3. [Phase 1 — Input Generation](#3-phase-1--input-generation)
4. [Phase 2 — Input Verification](#4-phase-2--input-verification)
5. [Phase 3 — Fluvial vs Pluvial Decision](#5-phase-3--fluvial-vs-pluvial-decision)
6. [Phase 4 — Pluvial Simulation](#6-phase-4--pluvial-simulation)
7. [Phase 5 — Wadi Entry Analysis](#7-phase-5--wadi-entry-analysis)
8. [Phase 6 — Wadi Inflow Simulation](#8-phase-6--wadi-inflow-simulation)
9. [Phase 7 — Visualization and Validation](#9-phase-7--visualization-and-validation)
10. [Script Reference](#10-script-reference)
11. [Iteration History and Lessons Learned](#11-iteration-history-and-lessons-learned)
12. [Adapting to a New Study Area](#12-adapting-to-a-new-study-area)

---

## 1. Workflow Overview

```
Phase 1: Input Generation
    setup_nile_highres.py ──► DEM, IWD, roughness, buildings, rain, boundaries
         ├── compute_hnd.py (native 30m HAND from pyflwdir)
         ├── regrid_xesmf.py (downscale MERIT 90m / GHSL 100m → 30m)
         ├── rasterize_buildings.py (Overture Maps → raster)
         └── download_imerg_rain.py (GPM IMERG → RIM2D rain files)

Phase 2: Input Verification
    visualize_inputs.py ──► DEM, IWD, roughness, boundary verification plots

Phase 3: Fluvial/Pluvial Decision
    Run v7 fluvial simulation (../bin/RIM2D simulation.def --def flex)
    visualize_v7_analysis.py ──► Bank height, freeboard, wadi networks
    visualize_flood_results.py ──► Flood depth maps + animation
    Decision: fluvial overflow viable? → YES: done  |  NO: proceed to Phase 4

Phase 4: Pluvial Simulation
    run_v8_pluvial.py ──► 20x amplified rainfall + full-domain sewershed
    Run v8 simulation (../bin/RIM2D simulation_v8_pluvial.def --def flex)
    visualize_v8_pluvial.py ──► Pluvial flood depth maps
    analyse_rainfall.py ──► Rainfall comparison (GPM vs IMERG vs amplified)

Phase 5: Wadi Entry Analysis
    visualize_wadi_entry.py ──► Identify upstream catchment inflow points
    extract_entry_points.py ──► Export entry coords (CSV + GeoJSON)

Phase 6: Wadi Inflow Simulation (Compound Flood)
    run_v9_wadi_inflow.py ──► Hydrograph + boundary mask + inflowlocs
    Run v9 simulation (../bin/RIM2D simulation_v9_wadi_inflow.def --def flex)
    visualize_v9_wadi.py ──► Wadi inflow flood maps

Phase 7: Visualization and Validation
    All visualize_*.py scripts ──► Publication-ready maps + GIF animations
```

---

## 2. Environment Setup

### Python Environment

```bash
# Primary environment (input generation and visualization)
micromamba activate zarrv3

# Key packages: numpy, netCDF4, rasterio, xarray, xesmf, pyflwdir,
#               pyproj, shapely, matplotlib, earthengine-api, scipy

# GDAL environment (if needed for building rasterization comparison)
micromamba activate rim2d_20250926
```

### RIM2D Runtime

```bash
export LD_LIBRARY_PATH="/data/rim2d/lib:$LD_LIBRARY_PATH"
# Binary: ../bin/RIM2D
# Definition file format: flex (keyword-based, requires --def flex flag)
```

### Google Earth Engine

The setup script downloads data from GEE using a service account. You need a valid key file. The path is configured in `setup_nile_highres.py`:

```python
SA_KEY = "/path/to/earthengine-service-account-key.json"
```

---

## 3. Phase 1 — Input Generation

### 3.1 Main Setup Script

**Script:** `setup_nile_highres.py`
**Run:** `micromamba run -n zarrv3 python setup_nile_highres.py`
**Purpose:** Downloads all geospatial data from GEE and generates complete RIM2D input files.

This is the master script that orchestrates the entire input pipeline. It calls three auxiliary modules internally.

**What it does (step by step):**

| Step | Action | Output |
|------|--------|--------|
| 1 | Download Copernicus GLO-30 DEM from GEE | `tif/dem.tif` |
| 1 | Download ESA WorldCover (roughness + raw classes) | `tif/roughness.tif`, `tif/worldcover_classes.tif` |
| 1 | Download MERIT Hydro (elevation + river width) | `tif/merit_elv_90m.tif`, `tif/merit_wth_90m.tif` |
| 1 | Download GHSL sealed/pervious surface | `tif/sealed_100m.tif`, `tif/pervious_100m.tif` |
| 2 | Compute native 30m HAND via pyflwdir | `input/hnd_30m.nc`, `input/flwacc_30m.nc` |
| 2 | Create channel mask from WorldCover class 80 | `input/channel_mask.nc` |
| 2 | Stream-burn DEM: lower channel cells by 3m | `input/dem.nc` |
| 2 | Create IWD: uniform 3m depth in channel | `input/iwd.nc` |
| 3 | Regrid GHSL sealed/pervious (100m → 30m) via xesmf | `input/sealed_surface.nc`, `input/pervious_surface.nc` |
| 3 | Rasterize buildings from Overture Maps GeoJSON | `input/buildings.nc` |
| 3 | Create sewershed from building footprints | `input/sewershed.nc` |
| 4 | Generate fluvial boundary conditions | `input/inflowlocs.txt`, `input/outflowlocs.txt` |
| 5 | Extract rainfall from parent simulation | `input/rain/nile_highres_t{1..336}.nc` |
| 6 | Write Manning's n roughness raster | `input/roughness.nc` |
| 7 | Write simulation definition | `simulation.def` |

**Key parameters to change for a new study area:**

```python
# Bounding box (geographic coordinates)
LAT_S, LAT_N = 19.49, 19.55
LON_W, LON_E = 33.28, 33.36

# CRS (choose appropriate UTM zone)
CRS = "EPSG:32636"   # UTM Zone 36N

# Channel and IWD parameters
BURN_DEPTH = 3.0      # meters to lower DEM at channel cells
NORMAL_DEPTH = 3.0    # initial water depth in channel

# HND computation
DRAIN_ACC_THRESH = 100  # flow accumulation threshold for drainage cells
```

### 3.2 Auxiliary Module: compute_hnd.py

**Purpose:** Compute Height Above Nearest Drainage (HAND) at native DEM resolution using pyflwdir.

**Why it exists:** Early versions (v1-v3) used MERIT Hydro HND at 90m resampled to 30m. This caused resolution mismatch artefacts — drainage lines that were 3-pixel wide at 90m became blocky at 30m. Computing HAND natively at 30m from the DEM resolves this.

**Pipeline:**
1. Fill pits and depressions (Wang & Liu 2006 priority-flood)
2. Compute D8 flow directions
3. Derive flow accumulation (upstream cell count)
4. Identify drainage cells (acc >= threshold)
5. Compute HAND = height of each cell above its nearest drainage cell

**Returns:** `(hnd, drain_mask, flwacc, dem_filled)`

**Key dependency:** `pyflwdir >= 0.5` (numba-accelerated)

**Important note:** pyflwdir assigns HND=0 at domain edges (where water exits). This caused v4-v5 failures where the entire domain boundary was classified as river. The fix (v5+) requires BOTH low HND AND high flow accumulation.

### 3.3 Auxiliary Module: regrid_xesmf.py

**Purpose:** Downscale coarser rasters (MERIT 90m, GHSL 100m) to the 30m target grid using xesmf bilinear interpolation.

**Why it exists:** Earlier versions used `scipy.ndimage.zoom` for regridding. This caused blocky artefacts (nearest-neighbour) or edge ringing (bilinear without proper coordinate awareness). xesmf uses ESMF-based regridding that respects the actual source/destination grid geometries.

**NaN handling:** Two-pass approach — fills NaN with median before regridding, then restores the NaN mask afterward.

### 3.4 Auxiliary Module: rasterize_buildings.py

**Purpose:** Convert Overture Maps building polygon GeoJSON (WGS84) to a binary 30m raster on the UTM grid.

**Key detail:** Uses `all_touched=True` rasterization mode. At 30m resolution, the median building (34 m2 = 4% of a 900 m2 cell) would be missed entirely with center-of-pixel rasterization. `all_touched=True` captures any cell intersecting a polygon.

| Method | Cells detected |
|--------|---------------|
| Center-of-pixel (GDAL default) | 950 |
| `all_touched=True` (both rasterio and GDAL) | 7,861 |

Both GDAL and rasterio produce identical results when using the same mode. The resolution is the limitation, not the algorithm.

### 3.5 Rainfall Data: download_imerg_rain.py

**Purpose:** Download GPM IMERG V07 half-hourly rainfall from GEE and regrid to the RIM2D 30m UTM grid.

**How it works:**
1. Authenticates with GEE service account
2. Uses `ImageCollection.getRegion()` for server-side spatial subsetting
3. Parses getRegion output into a 3D array (time x lat x lon)
4. Nearest-neighbour remap from IMERG 0.1 deg → RIM2D 30m
5. Writes one NetCDF per timestep

**Output:** `input/rain_imerg/imerg_t{1..N}.nc` (one file per 30-min timestep)

**For the Abu Hamad case:** The actual GPM rainfall is only ~8mm over 7 days (arid climate). This is far too low for surface flooding. The v8 pluvial simulation amplifies it 20x. For a wetter study area, amplification may not be needed.

### 3.6 River Discharge Data: download_geoglows_rivers.py

**Purpose:** Download GEOGloWS v2 retrospective hourly streamflow for Nile region rivers from the S3-hosted Zarr store.

**Why it exists:** Provides observed river discharge context for calibrating the fluvial boundary inflow hydrograph. The script accesses `s3://geoglows-v2/retrospective/hourly.zarr` anonymously.

**Output:** CSV + time series plot of July-August 2024 discharge for specified river IDs.

---

## 4. Phase 2 — Input Verification

### 4.1 visualize_inputs.py

**Run:** `micromamba run -n zarrv3 python visualize_inputs.py`
**Purpose:** Generate verification plots for ALL input rasters before running any simulation.

**Why this is critical:** Multiple iterations (v1-v6) failed because of input errors that were only discovered after running the simulation. Always verify inputs first.

**Panels generated:**

| Plot | What to check |
|------|---------------|
| DEM + hillshade | Terrain features visible, no holes or artefacts |
| Channel mask | Covers actual river extent, not drainage network |
| IWD | Water only in channel, smooth cross-section, ~3% wet cells |
| Roughness | Sensible spatial pattern matching land cover |
| Buildings | Match settlement extent, not too sparse or dense |
| Sealed/pervious | Complement each other, sum to ~1.0 |
| Sewershed | Covers areas where rain should be applied |
| HND + flow accumulation | Drainage network realistic, HND smooth |
| Inflow boundaries | Cells at expected domain edge, within channel |
| Rainfall time series | Expected duration, peak rate, spatial pattern |

**Red flags to watch for:**
- IWD covering entire domain (HND threshold too high)
- IWD showing thin network lines (using flow acc without dilation)
- Channel mask extending to domain edges (pyflwdir HND=0 artefact)
- Buildings = 0 cells (CRS mismatch in rasterization)
- Rainfall all zeros (sewershed mask preventing rain application)

---

## 5. Phase 3 — Fluvial vs Pluvial Decision

### 5.1 Run v7 Fluvial Simulation

```bash
cd /data/rim2d/nile_highres
export LD_LIBRARY_PATH="/data/rim2d/lib:$LD_LIBRARY_PATH"
../bin/RIM2D simulation.def --def flex
```

### 5.2 visualize_v7_analysis.py

**Run:** `micromamba run -n zarrv3 python visualize_v7_analysis.py`
**Purpose:** The single most important analysis script. Determines whether fluvial overflow or pluvial flooding is the dominant mechanism at your study area.

**This script generates two multi-panel analyses:**

#### Panel set 1: Overflow Analysis (`v7_overflow_analysis.png`)
- E-W cross-sections through the domain showing DEM, burned channel, water surface, buildings
- Freeboard map: elevation difference between every cell and mean water surface
- Building freeboard histogram: how high buildings sit above the river
- FLOOD_RISE curve: how much river rise needed to flood X% of buildings

#### Panel set 2: Pluvial Analysis (`v7_pluvial_analysis.png`)
- Flow accumulation map with building overlay (wadi networks through settlement)
- Wadi cells at different accumulation thresholds (50, 200, 500)
- HND at wadi + building cells (low HND = natural drainage paths)
- Rainfall time series: original vs amplified

**Decision framework (from analysis results):**

| Indicator | Fluvial Viable | Pluvial Needed |
|-----------|---------------|----------------|
| Median bank freeboard | < 3m | > 5m |
| Median building freeboard | < 5m | > 10m |
| FLOOD_RISE for 10% buildings | < 5m | > 10m |
| Wadi networks through settlement | Few/none | Multiple paths |

**Abu Hamad results:** Median bank freeboard = 9.7m, median building freeboard = 18.8m. Fluvial overflow requires a physically unrealistic 12m rise. Pluvial/wadi flooding is the dominant mechanism.

**For a new study area:** If this analysis shows freeboard < 3m and buildings near river level, the fluvial simulation (v7) may be sufficient and you can skip phases 4-6.

### 5.3 visualize_flood_results.py

**Run:**
```bash
micromamba run -n zarrv3 python visualize_flood_results.py \
    --pattern "output/nile_highres_wd_*.nc" \
    --dem input/dem.nc \
    --output-dir visualizations/v7_run
```

**Purpose:** General-purpose flood result visualizer. Works for any simulation version. Generates per-timestep depth maps with hillshade background and a GIF animation.

**Command-line options:** `--pattern`, `--dem`, `--dpi`, `--fps`, `--no-animation`, `--no-gif`, `--no-mp4`

---

## 6. Phase 4 — Pluvial Simulation

### 6.1 run_v8_pluvial.py

**Run:** `micromamba run -n zarrv3 python run_v8_pluvial.py`
**Purpose:** Set up a pluvial (rainfall-only) simulation with amplified rainfall.

**What it does:**
1. Reads v7 rainfall files from `input/rain/`
2. Multiplies all values by 20x → writes to `input/rain_v8/`
3. Creates full-domain sewershed (`input/sewershed_v8_full.nc`) — all cells = 1.0
4. Writes `simulation_v8_pluvial.def`

**Critical discovery — the sewershed is the rainfall mask:**

In RIM2D, the GPU kernel multiplies rainfall by the sewershed mask:
```fortran
wdl = wdl + (rainadd/1000 * maskl)
```
If `sewershed = 0` at a cell, that cell receives **zero rainfall**. For pluvial simulations, the sewershed must cover the entire domain, not just buildings. The file `input/sewershed_v8_full.nc` (all 1.0) provides this.

### 6.2 Run v8 Simulation

```bash
../bin/RIM2D simulation_v8_pluvial.def --def flex
```

**Duration:** 604,800s (7 days), 20x amplified GPM rainfall, fluvial boundary disabled.

### 6.3 visualize_v8_pluvial.py

**Run:** `micromamba run -n zarrv3 python visualize_v8_pluvial.py`
**Purpose:** Dedicated v8 result visualizer with 0-8m flood depth color scale, building outlines, and channel overlay.

**Why a dedicated script:** The general `visualize_flood_results.py` uses a 0-3m scale that saturated to uniform red for v8 results (max depth 7.8m). This script uses an expanded 0-8m custom colormap and adds building contour overlays.

**Per-frame statistics:** wet cells, outside-channel cells, max depth, % domain wet.

### 6.4 analyse_rainfall.py

**Run:** `micromamba run -n zarrv3 python analyse_rainfall.py`
**Purpose:** Compare three rainfall datasets — IMERG actual (August 2024), v7 GPM (extracted from parent), and v8 20x amplified.

**What it shows:**
- Daily totals (mm, peak rate, wet timesteps)
- August 18-25 detailed breakdown (peak event window)
- Amplification verification (v8/v7 = 20.0x)
- IMERG vs amplified comparison

**Why it matters:** Understanding what rainfall amount produces what flood response guides the choice of amplification factor for a new study area.

### 6.5 plot_imerg_august.py

**Run:** `micromamba run -n zarrv3 python plot_imerg_august.py`
**Purpose:** Visualize daily IMERG rainfall for July-August 2024 as a bar chart. Color-codes days by intensity (< 5mm blue, 5-10mm orange, > 10mm dark red).

---

## 7. Phase 5 — Wadi Entry Analysis

### 7.1 visualize_wadi_entry.py

**Run:** `micromamba run -n zarrv3 python visualize_wadi_entry.py`
**Purpose:** Identify where upstream desert catchment runoff enters the domain through wadi drainage networks.

**Why this analysis matters:** The v8 pluvial simulation showed that local rainfall alone (even 20x amplified) produces only shallow ponding. The real flash flood mechanism at arid/semi-arid sites like Abu Hamad is concentrated runoff from upstream catchments (10-500 km2) entering through wadi channels.

**What the script does:**
1. Loads flow accumulation raster
2. Identifies cells at all four domain edges with flow accumulation >= 50
3. Classifies entries as "north-side" (above channel, flash flood pathways) vs "south-side"
4. Generates a map with wadi network layers at 3 accumulation thresholds (50, 200, 500)
5. Annotates top entries with flow accumulation and elevation

**Output:** `visualizations/wadi_entry_points.png`

**Abu Hamad result:** 15 north-side wadi entry points, largest with flow accumulation = 1054 cells.

### 7.2 extract_entry_points.py

**Run:** `micromamba run -n zarrv3 python extract_entry_points.py`
**Purpose:** Export wadi entry point coordinates as CSV and GeoJSON with named identifiers (N1, N2, ... for north entries, S1, S2, ... for south, etc.).

**Output:**
- `visualizations/wadi_entry_points.csv` — all entry points with lat/lon, UTM, elevation, flow accumulation
- `visualizations/wadi_entry_points.geojson` — for QGIS or geojson.io visualization

**Use case:** Share entry point locations with collaborators, overlay on external maps, or use for upstream catchment delineation.

---

## 8. Phase 6 — Wadi Inflow Simulation

### 8.1 run_v9_wadi_inflow.py

**Run:** `micromamba run -n zarrv3 python run_v9_wadi_inflow.py`
**Purpose:** Set up a compound flood simulation: wadi inflow from upstream catchments + 20x amplified rainfall.

**What it does:**
1. Loads flow accumulation and identifies 15 north-side wadi entry points
2. Generates a flash flood hydrograph (150 m3/s peak, 2h rise, 1h peak, 6h exponential fall)
3. Distributes flow proportionally to each entry's flow accumulation
4. Converts flow rate to Water Surface Elevation (WSE) via Manning's equation
5. Writes fluvial boundary mask raster (`input/fluvbound_mask_v9.nc`)
6. Writes inflow timeseries file (`input/inflowlocs_v9.txt`)
7. Writes simulation definition (`simulation_v9_wadi_inflow.def`)

**RIM2D fluvial boundary system (critical to understand):**

`fluv_bound = .TRUE.` requires TWO files:

1. **Boundary mask raster** (NetCDF) — each pixel has an integer zone ID (1 to N). Referenced after the `.TRUE.` flag in the simdef:
   ```
   **fluv_bound**
   .TRUE.
   input/fluvbound_mask_v9.nc
   ```

2. **inflowlocs.txt** — timeseries of WSE at each boundary zone. Format:
   ```
   259200              ← sim_dur (seconds)
   1800                ← dt_inflow (seconds)
   15                  ← n_cells (must equal max(mask))
   row col WSE_t0 WSE_t1 ... WSE_tn  ← per boundary zone (1-indexed)
   ```
   Each line has `sim_dur/dt_inflow + 3` values (2 for row/col + n_wse+1 for timesteps including t=0).

**Hydrograph parameters:**

```python
PEAK_FLOW_M3S = 150.0    # total peak across all entries
RISE_HOURS = 2.0          # quadratic rise to peak
PEAK_HOURS = 1.0          # plateau at peak
FALL_HOURS = 6.0          # exponential decay
```

**Manning's equation (WSE conversion):**
```python
depth = (Q * n / (w * S^0.5))^0.6    # wide rectangular channel
WSE = DEM_elevation + depth
```

### 8.2 Run v9 Simulation

```bash
../bin/RIM2D simulation_v9_wadi_inflow.def --def flex
```

**Duration:** 259,200s (72 hours), compound: wadi inflow + 20x amplified rainfall.

### 8.3 visualize_v9_wadi.py

**Run:** `micromamba run -n zarrv3 python visualize_v9_wadi.py`
**Purpose:** v9-specific visualizer with wadi entry point overlay, drainage network, and hydrograph-based discharge annotation.

**Per-frame info:** Time, inflow Q (m3/s), wet cells, outside-channel cells, buildings wet, max depth.

**Abu Hamad v9 result:** Max depth 7.81m (channel), max north 3.43m, **0 north-side buildings inundated**. Water at entries reached only 0.28-0.75m depth; buildings sit 0.9-4.7m above wadi thalwegs. Water drained efficiently through steep wadis to the Nile.

---

## 9. Phase 7 — Visualization and Validation

### Summary of all visualization scripts

| Script | Input | Output | When to use |
|--------|-------|--------|-------------|
| `visualize_inputs.py` | `input/*.nc` | Input verification plots | After Phase 1, before any simulation |
| `visualize_v7_analysis.py` | `input/*.nc` | Bank height + wadi analysis | After v7 fluvial simulation |
| `visualize_flood_results.py` | `output/*_wd_*.nc` | Generic flood maps + GIF | After any simulation |
| `visualize_v8_pluvial.py` | `output_v8_pluvial/*.nc` | Pluvial flood maps + GIF | After v8 simulation |
| `visualize_wadi_entry.py` | `input/flwacc_30m.nc` | Wadi entry point map | Before v9 setup |
| `visualize_v9_wadi.py` | `output_v9_wadi/*.nc` | Wadi inflow maps + GIF | After v9 simulation |
| `plot_imerg_august.py` | `input/rain_imerg/*.nc` | Daily rainfall bar chart | After rainfall download |
| `analyse_rainfall.py` | `input/rain*/*.nc` | Rainfall comparison tables | After v8 setup |
| `extract_entry_points.py` | `input/flwacc_30m.nc` | CSV + GeoJSON of entries | Before v9 setup |

---

## 10. Script Reference

### File structure

```
nile_highres/
├── NILE_HIGHRES_WORKFLOW.md     ← This document
├── README.md                     ← Project summary and key findings
├── IWD_ATTEMPTS.md               ← v1-v6 IWD iteration history
├── V7_OVERFLOW_ANALYSIS.md       ← Why fluvial overflow fails here
├── WORKFLOW.md                   ← Earlier v4 workflow (superseded)
│
├── setup_nile_highres.py         ← Master input generation (GEE + processing)
├── compute_hnd.py                ← Native 30m HAND via pyflwdir
├── regrid_xesmf.py               ← xesmf bilinear regridding utility
├── rasterize_buildings.py        ← Overture Maps → binary raster
├── download_imerg_rain.py        ← GPM IMERG → RIM2D rain NetCDF
├── download_geoglows_rivers.py   ← GEOGloWS discharge retrieval
│
├── run_v8_pluvial.py             ← v8 pluvial setup (20x rain)
├── run_v9_wadi_inflow.py         ← v9 wadi inflow setup (compound)
│
├── simulation.def                ← v7 fluvial simulation definition
├── simulation_v8_pluvial.def     ← v8 pluvial simulation definition
├── simulation_v9_wadi_inflow.def ← v9 compound simulation definition
│
├── visualize_inputs.py           ← Input verification (run FIRST)
├── visualize_v7_analysis.py      ← Fluvial/pluvial decision analysis
├── visualize_flood_results.py    ← Generic flood maps + animation
├── visualize_v8_pluvial.py       ← v8 pluvial results (0-8m scale)
├── visualize_v9_wadi.py          ← v9 wadi inflow results
├── visualize_wadi_entry.py       ← Wadi entry point identification
├── extract_entry_points.py       ← Entry point export (CSV/GeoJSON)
├── analyse_rainfall.py           ← Rainfall dataset comparison
├── plot_imerg_august.py          ← IMERG daily rainfall visualization
│
├── buildings_overture.geojson    ← Raw building footprints
│
├── input/                        ← RIM2D input files (NetCDF)
│   ├── dem.nc                    ← Stream-burned DEM
│   ├── buildings.nc              ← Building footprint mask
│   ├── iwd.nc                    ← Initial water depth
│   ├── roughness.nc              ← Manning's n from WorldCover
│   ├── channel_mask.nc           ← ESA WorldCover class 80
│   ├── pervious_surface.nc       ← Pervious fraction
│   ├── sealed_surface.nc         ← Sealed fraction
│   ├── sewershed.nc              ← Building-only sewershed (v7)
│   ├── sewershed_v8_full.nc      ← Full-domain sewershed (v8/v9)
│   ├── hnd_30m.nc                ← Height-above-nearest-drainage
│   ├── flwacc_30m.nc             ← Flow accumulation
│   ├── inflowlocs.txt            ← v7 fluvial boundary
│   ├── inflowlocs_v9.txt         ← v9 wadi inflow boundary
│   ├── fluvbound_mask_v9.nc      ← v9 boundary zone mask
│   ├── outflowlocs.txt           ← Outflow cells
│   ├── rain/                     ← Original GPM rainfall
│   ├── rain_v8/                  ← 20x amplified rainfall
│   └── rain_imerg/               ← Direct IMERG download
│
├── tif/                          ← Intermediate GeoTIFFs from GEE
├── output/                       ← v7 fluvial simulation output
├── output_v8_pluvial/            ← v8 pluvial simulation output
├── output_v9_wadi/               ← v9 compound simulation output
└── visualizations/               ← All generated plots and animations
```

### Dependencies

| Package | Purpose | Install |
|---------|---------|---------|
| `numpy` | Array operations | conda |
| `netCDF4` | NetCDF I/O (RIM2D format) | conda |
| `rasterio` | GeoTIFF I/O | conda |
| `pyproj` | CRS transformations | conda |
| `shapely` | Geometry operations | conda |
| `matplotlib` | Visualization | conda |
| `scipy` | Image processing, interpolation | conda |
| `xarray` | Labelled array manipulation | conda |
| `xesmf` | ESMF-based regridding | conda |
| `pyflwdir` | D8 flow + HAND computation | pip |
| `earthengine-api` | Google Earth Engine | pip |
| `s3fs`, `zarr` | GEOGloWS Zarr access | conda |
| `pandas` | Time series handling | conda |
| `PIL/Pillow` | GIF animation | conda |

---

## 11. Iteration History and Lessons Learned

### v1-v3: NASADEM + MERIT 90m HND

**Problem:** Resolution mismatch. MERIT Hydro HND at 90m resampled to 30m produced blocky artefacts and drainage network patterns instead of a smooth river channel.

| Version | Method | Wet % | Issue |
|---------|--------|-------|-------|
| v1 | Simple DEM burn where HND < threshold | 1.1% | Scattered patches, discontinuous |
| v2 | `min(NASADEM, MERIT_elv)` + burn | 25.6% | Continuous but too wide |
| v3 | `IWD = max(0, 2.0 - HND)` cross-section | — | 90m HND artefacts at 30m |

**Lesson:** Always compute HAND at native DEM resolution. Never resample 90m hydro data to 30m.

### v4: Copernicus DEM + Native 30m HND (pyflwdir)

**Fix:** Switched to Copernicus GLO-30 DEM and computed HAND natively at 30m.
**New problem:** 44.9% of domain classified as river (flat terrain near Abu Hamad gives low HND everywhere).

**Lesson:** In flat terrain, HND alone is insufficient to identify the river. Need additional constraints.

### v5: Combined HND + Flow Accumulation

**Root cause identified:** pyflwdir assigns HND=0 at domain edges (outlets). All cells near boundaries got artificially low HND.

**Fix:** `river_mask = (HND < 1.5m) AND (flow_acc >= 1000)`

**New problem:** IWD looked like a drainage network diagram — thin 1-pixel lines at uniform 2.0m depth. No cross-sectional variation.

**Lesson:** Flow accumulation identifies centreline cells only. Banks have high HND but low flow_acc, so they get excluded.

### v6: Multiple approaches to smooth cross-section

| Sub-version | Approach | Result |
|-------------|----------|--------|
| v6a | HND where acc >= 50 | Included all wadis, not just Nile |
| v6b | 25-year return period as IWD | 67.8% wet — extreme event, not baseline |
| v6c | Return period extent + HND depth | 26.5% wet — still too wide |
| v6d | Main Nile corridor (acc >= 20000 + 300m buffer + HND) | 3.6% wet — best result |

**Lesson:** The combination of (1) identifying the main channel via high flow_acc, (2) morphological dilation to capture the corridor, and (3) HND for smooth depth gives the best IWD. But it still looks somewhat artificial.

### v7: Satellite Channel Mask (ESA WorldCover)

**Breakthrough:** Replaced computed HND+flow_acc river mask with **ESA WorldCover class 80** (permanent water bodies observed by satellite). This captures the actual river extent — wide, realistic, not network-like.

**Changes:**
- Channel mask from satellite observation (~7,136 cells, 11.4%)
- Stream-burn DEM: `burned_dem = dem - 3.0m` where channel=1
- IWD: uniform 3.0m at channel cells
- Building footprints from Overture Maps (replacing empty GHSL thresholds)

**Fluvial simulation result:** Water constrained entirely to channel. No overflow reaches buildings. Median bank freeboard = 9.7m.

**Lesson:** Use satellite-derived water masks for the channel extent. Computed drainage networks are suitable for wadi identification but not for defining the main river.

### v8: Pluvial Simulation (20x Amplified Rainfall)

**Pivot:** After v7 showed fluvial overflow is not viable (19m building freeboard), switched to pluvial flooding.

**Key discovery:** RIM2D's sewershed raster controls where rainfall is applied. Setting it to building-only coverage prevented 87.5% of the domain from receiving rain.

**Fix:** Full-domain sewershed (`sewershed_v8_full.nc`, all 1.0).

**Result:** 55% domain wet, max 7.8m in channel, pluvial runoff along wadi paths. But still insufficient to flood north-side buildings — 160mm over 7 days produces only ~16cm of ponding on the plateau.

**Lesson:** The sewershed raster = rainfall mask. For pluvial simulations, it must cover the entire domain. Also: local rainfall alone cannot produce concentrated runoff sufficient for building inundation in a small domain.

### v9: Wadi Inflow Boundary (Compound Flood)

**Approach:** Simulate upstream catchment flash flood entering through 15 wadi entry points at domain edges, combined with 20x amplified rainfall.

**Result:** Max depth 7.81m (channel), 3.43m (north), but **0 north-side buildings inundated**. The 150 m3/s distributed across 15 entries created only 0.28-0.75m depth at entries. Water drained efficiently through steep wadis to the Nile.

**Lesson:** At Abu Hamad, building inundation requires either (1) much higher concentrated inflow (500+ m3/s through top 3 wadis only), or (2) a compound scenario where elevated Nile levels prevent wadi drainage, causing backwater flooding.

---

## 12. Adapting to a New Study Area

### Step-by-step checklist

1. **Define domain bounds** — choose lat/lon extent, determine UTM zone
2. **Update `setup_nile_highres.py`:**
   - Change `LAT_S`, `LAT_N`, `LON_W`, `LON_E`
   - Change `CRS` to appropriate UTM zone
   - Update GEE service account path
   - Adjust `BURN_DEPTH`, `NORMAL_DEPTH` based on expected river depth
3. **Run setup:** `micromamba run -n zarrv3 python setup_nile_highres.py`
4. **Verify inputs:** `micromamba run -n zarrv3 python visualize_inputs.py`
5. **Run v7 fluvial simulation** and check for overflow
6. **Run fluvial/pluvial analysis:** `visualize_v7_analysis.py`
7. **Decision point:**
   - If bank freeboard < 3m → fluvial simulation is sufficient
   - If bank freeboard > 5m → proceed to pluvial (Phase 4)
   - If wadi networks exist → proceed to wadi inflow (Phase 5-6)
8. **Adjust rainfall:** Check actual rainfall totals. If > 50mm/event, amplification may not be needed
9. **Adjust wadi inflow:** Estimate upstream catchment area and peak discharge for your region

### Key parameters to tune per site

| Parameter | Abu Hamad | Flat floodplain | Steep valley |
|-----------|-----------|-----------------|--------------|
| `BURN_DEPTH` | 3.0m | 1.5-2.0m | 3.0-5.0m |
| `DRAIN_ACC_THRESH` | 100 | 200-500 | 50-100 |
| `WADI_ACC_THRESH` | 50 | N/A | 30-100 |
| Rain amplification | 20x | 1-5x | 5-20x |
| `PEAK_FLOW_M3S` | 150 | N/A | 100-1000 |
| Simulation duration | 72h (v9) | 168h | 48-72h |

### Common pitfalls

1. **pyflwdir HND=0 at edges** — always combine with flow accumulation threshold
2. **Sewershed = rainfall mask** — use full-domain sewershed for pluvial simulations
3. **Building CRS mismatch** — ensure buildings are transformed to UTM before rasterization
4. **inflowlocs column count** — Fortran expects `sim_dur/dt_inflow + 3` values per line
5. **fluv_bound requires TWO files** — boundary mask raster + inflowlocs.txt
6. **wd_max_t.nc stores TIME** — not depth; use `wd_max.nc` for maximum depth
7. **Rainfall too low** — check actual GPM totals before running; may need amplification in arid regions

---

## Quick-Start Commands

```bash
# ── Phase 1: Generate inputs ──
cd /data/rim2d/nile_highres
micromamba run -n zarrv3 python setup_nile_highres.py

# ── Phase 2: Verify inputs ──
micromamba run -n zarrv3 python visualize_inputs.py

# ── Phase 3: Run v7 fluvial + analysis ──
export LD_LIBRARY_PATH="/data/rim2d/lib:$LD_LIBRARY_PATH"
../bin/RIM2D simulation.def --def flex
micromamba run -n zarrv3 python visualize_v7_analysis.py
micromamba run -n zarrv3 python visualize_flood_results.py \
    --pattern "output/nile_highres_wd_*.nc" --dem input/dem.nc

# ── Phase 4: Run v8 pluvial ──
micromamba run -n zarrv3 python run_v8_pluvial.py
../bin/RIM2D simulation_v8_pluvial.def --def flex
micromamba run -n zarrv3 python visualize_v8_pluvial.py

# ── Phase 5: Wadi entry analysis ──
micromamba run -n zarrv3 python visualize_wadi_entry.py
micromamba run -n zarrv3 python extract_entry_points.py

# ── Phase 6: Run v9 wadi inflow (compound) ──
micromamba run -n zarrv3 python run_v9_wadi_inflow.py
../bin/RIM2D simulation_v9_wadi_inflow.def --def flex
micromamba run -n zarrv3 python visualize_v9_wadi.py
```
