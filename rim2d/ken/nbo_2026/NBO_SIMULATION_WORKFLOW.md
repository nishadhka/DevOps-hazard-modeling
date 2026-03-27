# Nairobi (NBO) v1 RIM2D Flood Simulation — Workflow Documentation

## Overview

Compound pluvial + fluvial flood simulation for Nairobi, Kenya using the
RIM2D GPU-accelerated 2D hydraulic model. The simulation covers the April 2025
long-rains period over a ~55 km × 33 km domain at 30 m resolution.

| Item | Value |
|---|---|
| Domain (WGS84) | 36.6–37.1°E, -1.402–-1.098°N |
| Grid (UTM 37S) | 1858 × 1123 cells, dx = 30 m |
| DEM source | Copernicus GLO-30 (ESA, 30 m) |
| Simulation period | April 2025 (30 days) |
| Flood type | Compound pluvial + fluvial (river inflow) |
| Working directory | `/data/rim2d/nbo_2026/` |

---

## Step 1 — Terrain & Domain Setup

**Script:** `setup_v1.py`

**Method:**

Downloads all geospatial inputs via Google Earth Engine (GEE) and prepares
RIM2D-format NetCDF grid files for the Nairobi domain.

Steps performed inside the script:
1. **DEM** — Copernicus GLO-30 clipped to domain, reprojected to UTM 37S (EPSG:32737), saved as `dem.tif`
2. **Sealed surface** — ESA WorldCover 2021 impervious fraction (10 m → 30 m), `sealed_100m.tif`
3. **Manning's n** — land-cover-based roughness grid, `mannings.tif`
4. **GHSL built fraction** — Global Human Settlement Layer 100 m built-up raster, regridded with `rasterio.warp.reproject` (replaces xesmf which caused an 11-hour hang on the 2M-cell grid)
5. **Channel mask** — flow accumulation via `pyflwdir` with threshold `flwacc >= 5000` (27,515 cells, 1.3% of domain); channel cells are stream-burned by subtracting 2 m from the DEM
6. **Buildings** — `nbo.geojson` (1,473,476 Microsoft ML Building footprints) rasterised onto the 30 m grid → 763,740 building cells (36.6%), saved as `buildings.nc`
7. **Sewershed** — full-domain (all 1.0), `sewershed_v1_full.nc`
8. **Simulation definition** — `simulation_v1.def` (flex format)

Key outputs in `v1/input/`:
```
dem.nc            iwd.nc            buildings.nc
mannings.nc       sealed.nc         sewershed_v1_full.nc
```
Key outputs in `v1/tif/`:
```
dem.tif    sealed_100m.tif    mannings.tif
```

**Command:**
```bash
cd /data/rim2d/nbo_2026
micromamba run -n zarrv3 python setup_v1.py
```

**Visualization outputs:** `v1/visualizations/v1_inputs_overview.png`

---

## Step 2 — IMERG Rainfall Download

**Script:** `download_imerg_v1.py`

**Method:**

Downloads GPM IMERG V07 half-hourly precipitation for April 2025 (1440
timesteps at 30-min intervals) over a region wider than the domain
(36.4–37.3°E, -1.6–-0.9°N) to capture surrounding rainfall. Each timestep
is saved as an individual NetCDF file on the UTM 37S grid.

- **Source:** NASA GPM IMERG Final Run V07 via GEE `ImageCollection`
- **Resolution:** 0.1° (~11 km) regridded to 30 m via `rasterio.warp.reproject`
- **Period:** 2025-04-01 00:00 UTC → 2025-04-30 23:30 UTC

**Command:**
```bash
micromamba run -n zarrv3 python download_imerg_v1.py
```

**Outputs:** `v1/input/rain/imerg_v1_t{0001..1440}.nc`

---

## Step 3 — Watershed Delineation (HydroATLAS)

**Script:** `delineate_watershed_v1.py`

**Method:**

Queries the WWF HydroATLAS v1 basin dataset via GEE at hierarchical levels
4, 6, 8, 10, and 12 for each of the 8 auto-detected river entry points
(from `run_v1_river_inflow.py`). Extracts `SUB_AREA` (sub-basin area in km²)
and `UP_AREA` (total upstream area in km²) attributes.

These scientifically-derived catchment areas replace the flow-accumulation
pixel estimates used in the initial entry point detection.

**Command:**
```bash
micromamba run -n zarrv3 python delineate_watershed_v1.py
```

**Outputs:**
```
v1/input/watersheds/entry{N}_level{LL}.geojson   (40 files)
v1/input/watersheds/watershed_summary.json
v1/visualizations/v1_watersheds.png
```

---

## Step 4 — River Network Download (TDX-Hydro v2)

**Script:** `download_river_network_v1.py`

**Method:**

Downloads the GEOGloWS TDX-Hydro v2 river network for the basin extent
(buffered to cover all upstream watersheds) from the TIPG OGC API Features
endpoint. River segments are attributed with `stream_order` (Strahler order
1–5 for Nairobi) and `linkno` (unique segment ID).

Produces two plots:
1. **Watershed outlines + rivers + buildings raster** — watershed boundaries
   as coloured dashed outlines (no fill), rivers sized by stream order,
   `buildings.nc` shown as 30 m raster cells (orange)
2. **Building footprints + rivers + watershed outlines** — 1.47M individual
   building polygons from `nbo.geojson` overlaid with river network and
   watershed boundaries

**API:**
```
https://tipg-tiler-template.replit.app/collections/public.ea_river_networks_tdx_v2/items
```

**Command:**
```bash
micromamba run -n zarrv3 python download_river_network_v1.py
```

**Outputs:**
```
v1/input/river_network_tdx_v2.geojson   (141 segments, 7 MB)
v1/visualizations/v1_river_network.png
v1/visualizations/v1_buildings_rivers_watersheds.png
```

---

## Step 5 — Road Network Download (Overture Maps)

**Script:** `download_roads_v1.py`

**Method:**

Downloads road segments for the simulation domain from the Overture Maps
Foundation dataset using the `overturemaps` Python CLI. The `segment` type
covers all road classes from motorways to footpaths. Segments are styled by
road class for visualization:

| Class | Count | Style |
|---|---|---|
| Motorway / Trunk | 1,839 | dark red, 2.5 px |
| Primary | 1,172 | orange, 1.8 px |
| Secondary | 4,087 | yellow, 1.2 px |
| Tertiary | 3,194 | grey, 0.7 px |
| Residential / Local | 113,889 | light grey, 0.4 px |
| Other (paths, tracks) | 11,916 | very light, 0.3 px |

Produces two plots:
1. **Roads + rivers + watershed outlines** — clean white-background map
2. **Buildings + roads + rivers + watershed outlines** — full context map

**Command:**
```bash
micromamba run -n zarrv3 python download_roads_v1.py
```

**Outputs:**
```
v1/input/roads_overture.geojson    (136,097 segments, 96 MB)
v1/visualizations/v1_roads_rivers_watersheds.png
v1/visualizations/v1_buildings_roads_rivers_watersheds.png
```

---

## Step 6 — River Entry Point Extraction

**Script:** `extract_river_entries_v1.py`

**Method:**

Derives river inflow boundary conditions directly from the TDX-Hydro v2
network geometry rather than from DEM flow-accumulation at grid edges.
Two categories of entry point are identified:

### Boundary Entries (▲)
Segment **start-points** that lie within `BOUNDARY_BUF = 0.06°` (~7 km)
of the domain edge AND inside the domain. These mark the locations where
rivers cross into the simulation domain from upstream catchments.

### Confluences (●)
Points shared by **3 or more segment endpoints** within the domain interior.
These are major tributary junctions where flow concentrates and can be used
as distributed inflow points to represent converging sub-catchments.

### Deduplication
Nearby candidates within `DEDUP_DEG = 0.05°` (~6 km) are merged, retaining
the highest stream-order representative. This prevents multiple inflow cells
being placed on the same river reach.

### Filter
Only stream order ≥ 3 is considered, excluding minor headwater channels that
carry negligible flow relative to the main Nairobi river system (Nairobi,
Mathare, Ngong, Athi tributaries).

**Results:**

| ID | Type | Lon | Lat | Order |
|---|---|---|---|---|
| 1 | boundary | 37.01933 | -1.38922 | 5 |
| 2 | boundary | 37.07244 | -1.31367 | 5 |
| 3 | boundary | 36.84844 | -1.39389 | 4 |
| 4 | boundary | 37.05867 | -1.20911 | 4 |
| 5 | boundary | 36.78267 | -1.38867 | 3 |
| 6 | confluence | 37.07240 | -1.31370 | 5 |
| 7 | confluence | 36.91230 | -1.23820 | 4 |
| 8 | confluence | 36.82120 | -1.38330 | 4 |
| 9 | confluence | 37.03830 | -1.21310 | 4 |
| 10 | confluence | 37.08170 | -1.16930 | 4 |

**Command:**
```bash
micromamba run -n zarrv3 python extract_river_entries_v1.py
```

**Outputs:**
```
v1/input/river_entries_v1.csv
v1/input/river_entries_v1.geojson
v1/visualizations/v1_river_entries.png
```

---

## Step 7 — Synthetic Hydrograph Generation (Basin-Scale IMERG)

**Script:** `run_v1_synthetic_flood.py`

**Method:**

Implements the v11 methodology from the Abu Hamad case study (see
`/data/rim2d/nile_highres/V11_METHODOLOGY.md`) adapted for Nairobi:

1. **Channel mask rebuild** — re-derives `dem.nc` and `iwd.nc` using
   `flwacc >= 5000` (27,515 cells, 1.3%) via `pyflwdir`; this replaces
   the ESA WorldCover class-80 mask which only captured Nairobi Dam
   and reservoirs (8,966 cells, 0.4%)

2. **HydroATLAS basin areas** — loads `watershed_summary.json` to obtain
   scientifically-derived catchment areas (`UP_AREA` km²) per entry point

3. **Basin-scale IMERG** — downloads basin-mean rainfall for April 2025
   using GEE `reduceRegion` over the full HydroATLAS polygon extent for
   each entry (not just the domain). Basin totals: 207–243 mm (consistent
   with Nairobi long rains)

4. **Rational method hydrograph:**
   ```
   Q(t) = C_eff × I_basin(t) × A_basin
   ```
   - `C_eff = 0.55` (urban tropical, vs 0.30 for arid Abu Hamad)
   - Instantaneous runoff convolved with triangular unit hydrograph
   - Time of concentration: `tc = 0.3 × A^0.4` hours (A in km²)

5. **Manning's WSE** — converts peak discharge to water surface elevation
   for the RIM2D boundary condition using wide rectangular channel formula

6. **RIM2D inputs written:**
   - `fluvbound_mask_v1.nc` — boundary cell mask
   - `inflowlocs_v1.txt` — WSE timeseries at all entry points
   - `synthetic_hydrographs.npz` — flow data for visualization

Peak flows computed: entry1=103, entry2=247, entry3=33, entry4=210,
entry5=89, entry6=232, entry7/8=121 m³/s

**Command:**
```bash
micromamba run -n zarrv3 python run_v1_synthetic_flood.py
```

**Outputs:**
```
v1/input/fluvbound_mask_v1.nc
v1/input/inflowlocs_v1.txt
v1/input/synthetic_hydrographs.npz
v1/input/v1_metadata.json
```

---

## Step 8 — Input Visualization

**Script:** `visualize_v1.py --inputs`

**Method:**

Generates a 6-panel overview of all RIM2D input rasters plus hydrograph
summaries for quality control before running the simulation.

Panels:
1. DEM overview (hillshade + elevation colormap)
2. Channel mask and stream-burned DEM
3. Manning's roughness
4. Sealed surface fraction
5. Building footprint raster
6. Boundary condition mask and entry locations

**Command:**
```bash
micromamba run -n zarrv3 python visualize_v1.py --inputs
```

**Outputs:** `v1/visualizations/v1_inputs_*.png`

---

## Step 9 — Run Simulation

**Method:**

RIM2D flex-format definition file (`simulation_v1.def`) controls the GPU
2D shallow-water solver. The simulation uses:
- **Pluvial forcing:** IMERG rainfall on every grid cell (sewershed = full domain)
- **Fluvial forcing:** synthetic hydrograph WSE timeseries at 10 river entry points
- **Buildings:** treated as elevated terrain (blocked cells)
- **Manning's n:** spatially variable from land cover

**Command:**
```bash
cd /data/rim2d/nbo_2026/v1
../../bin/RIM2D simulation_v1.def --def flex
```

**Runtime:** ~30 min on RTX 5050 GPU (1858 × 1123 × 1440 timesteps)

**Outputs:** `v1/output/` (NetCDF flood depth/velocity time series)

---

## Step 10 — Results Visualization

**Script:** `visualize_v1.py --results`

**Command:**
```bash
micromamba run -n zarrv3 python visualize_v1.py --results
```

**Outputs:** `v1/visualizations/v1_results_*.png`

---

## File Inventory

```
nbo_2026/
├── setup_v1.py                    # Step 1: terrain setup
├── download_imerg_v1.py           # Step 2: rainfall download
├── delineate_watershed_v1.py      # Step 3: HydroATLAS watershed delineation
├── download_river_network_v1.py   # Step 4: TDX-Hydro v2 river network
├── download_roads_v1.py           # Step 5: Overture Maps road network
├── extract_river_entries_v1.py    # Step 6: river entry point extraction
├── run_v1_river_inflow.py         # (legacy) DEM flow-acc entry detection
├── run_v1_synthetic_flood.py      # Step 7: basin IMERG + hydrograph + BCs
├── visualize_v1.py                # Steps 8 & 10: input/result visualization
├── nbo.geojson                    # 1.47M Microsoft ML building footprints
├── extent_polygon.geojson         # Domain boundary polygon
└── v1/
    ├── input/
    │   ├── dem.nc                 # 30 m DEM (stream-burned)
    │   ├── iwd.nc                 # Initial water depth (channel seeding)
    │   ├── buildings.nc           # Building raster
    │   ├── mannings.nc            # Manning's roughness
    │   ├── sealed.nc              # Sealed surface fraction
    │   ├── sewershed_v1_full.nc   # Full-domain sewershed
    │   ├── fluvbound_mask_v1.nc   # Fluvial boundary mask
    │   ├── inflowlocs_v1.txt      # RIM2D WSE boundary condition
    │   ├── river_entries_v1.csv   # 10 river entry points
    │   ├── river_entries_v1.geojson
    │   ├── river_network_tdx_v2.geojson  (141 segments)
    │   ├── roads_overture.geojson        (136,097 segments)
    │   ├── watersheds/            # HydroATLAS GeoJSON + summary
    │   └── rain/                  # IMERG NetCDF (1440 files)
    ├── visualizations/
    │   ├── v1_inputs_overview.png
    │   ├── v1_watersheds.png
    │   ├── v1_river_network.png
    │   ├── v1_buildings_rivers_watersheds.png
    │   ├── v1_roads_rivers_watersheds.png
    │   ├── v1_buildings_roads_rivers_watersheds.png
    │   ├── v1_river_entries.png
    │   └── v1_results_*.png
    ├── simulation_v1.def
    └── output/
```

---

## Environment

```bash
micromamba run -n zarrv3 <script>   # Python 3.11, zarrv3 conda env
../../bin/RIM2D simulation_v1.def --def flex  # RIM2D GPU solver
```

**GPU:** NVIDIA GeForce RTX 5050 (8 GB VRAM), CUDA 13.0
**Key Python packages:** `earthengine-api`, `pyflwdir`, `rasterio`, `netCDF4`,
`numpy`, `matplotlib`, `shapely`, `pyproj`, `requests`, `overturemaps`

---

## Methodological Notes

### Why rasterio instead of xesmf for regridding
`xesmf.regrid_to_target` computes ESMF regridding weights on first call.
For a 2M-cell target grid (1858 × 1123) the weight computation ran for
11+ hours without completing. Replaced with `rasterio.warp.reproject`
which completes in < 1 second using bilinear interpolation.

### Why flwacc ≥ 5000 for channel mask
ESA WorldCover class 80 (permanent water) only captured Nairobi Dam
and a few reservoirs (8,966 cells, 0.4%). Nairobi's rivers (Nairobi,
Mathare, Ngong, Athi) are seasonal and not classified as permanent water.
Flow accumulation threshold 5000 cells captures the full dendritic river
network (27,515 cells, 1.3%) consistent with field knowledge.

### River entry points from TDX-Hydro vs DEM flow accumulation
The initial `run_v1_river_inflow.py` detected 8 entry points at domain
grid edges using DEM-derived flow accumulation. The improved
`extract_river_entries_v1.py` uses the downloaded TDX-Hydro v2 vector
network directly, identifying both boundary crossing points and internal
confluences. This avoids DEM artefacts at domain edges and better
captures the hydrologically significant inflow locations.

### RUNOFF_COEFF = 0.55 for Nairobi
Abu Hamad (arid, bare soil): C = 0.30 base.
Nairobi (tropical urban): C = 0.55 reflects higher imperviousness
and soil moisture during the long-rains season (April). Literature
range for mixed urban tropical: 0.40–0.75 (ASCE 2017, Wheater 2008).
