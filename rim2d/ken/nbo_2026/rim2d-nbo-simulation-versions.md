# RIM2D NBO/Nairobi Simulation — Version History
**Case study:** Nairobi, Kenya — 2026-03-06 flash flood event
**Model folder:** `/data/rim2d/nbo_2026/`
**Grid:** 30m resolution, UTM Zone 37S (EPSG:32737)
**Domain:** lat −1.402 to −1.098, lon 36.6 to 37.1 (~55 km × 34 km)

---

## Quick Reference Table

| Version | Key change | Date | Status |
|---------|-----------|------|--------|
| v1 | Initial setup — domain, DEM, buildings, roughness, April 2025 long rains | 2026-03-07 | Complete |
| v2 | 2026-03-06 flash flood event — IDW rainfall, compound pluvial+fluvial | 2026-03-09 | Complete |
| v3 | Stream-burn IWD via ESA WorldCover class 80 channel mask | 2026-03-09 | Complete |
| v4 | Steady-state pre-simulation IWD via baseflow run | 2026-03-11 | Complete |
| v5 | TDX-Hydro river network burn IWD (width/depth by stream order) | 2026-03-27 | Complete |
| v6 | Combined MERIT HND + TDX-Hydro IWD (two-layer approach) | 2026-03-27 | Complete |

---

## Background

Earlier NBO context sessions (before v1 of the `nbo_2026` folder):
- `20250920/rim2d-nbo-case.md` — initial NBO case scoping
- `20250923/nbo-rim2d.md` — early domain and data exploration
- `20250923/nbo-rim2d-stac-dem-download.md` — STAC-based DEM download attempts
- `20251007/rim2d-nbo-run.md` — prototype NBO run (pre-2026)

The 2026 work started fresh in `/data/rim2d/nbo_2026/` in March 2026, targeting the specific 2026-03-06 flash flood event.

---

## v1 — Initial Domain Setup (April 2025 Long Rains)

**Date:** 2026-03-07
**Session files:** `20260307/nbo-flood-simulation-rim2d-setup.md`, `20260308/rim2d-nbo-input-prepare.md`
**Scripts:** `setup_v1.py`, `run_v1_river_inflow.py`, `run_v1_synthetic_flood.py`, `visualize_v1.py`, `delineate_watershed_v1.py`, `download_imerg_v1.py`, `download_river_network_v1.py`, `download_roads_v1.py`, `extract_river_entries_v1.py`, `analyze_river_network_v1.py`

**What it established:**
Full input pipeline for the Nairobi domain at 30m UTM-37S resolution. Modelled on the Nile v7 workflow (same GEE downloads, same RIM2D input format), adapted for the tropical urban setting.

**Domain:**
- BBOX: 36.6°E – 37.1°E, −1.402°S – −1.098°S
- CRS: EPSG:32737 (UTM Zone 37S)
- Resolution: 30m (SCALE = 30)
- Period modelled: April 1–30, 2025 (Nairobi long rains season)

**Input generation steps (setup_v1.py):**
1. Download Copernicus DEM from GEE → `v1/tif/dem.tif`
2. Download ESA WorldCover (roughness + raw classes) → `v1/tif/worldcover_classes.tif`
3. Download MERIT Hydro (HND) → `v1/tif/merit_elv.tif`
4. Download GHSL sealed/pervious → `v1/tif/sealed_100m.tif`, `v1/tif/pervious_100m.tif`
5. Compute native 30m HAND via pyflwdir (shared `compute_hnd.py` from nile_highres)
6. Stream-burn DEM at WorldCover class 80 cells
7. Create IWD at burned channel cells
8. Rasterize roughness, buildings, sealed/pervious, sewershed → `v1/input/`
9. Download IMERG for April 2025 → `v1/input/rain/`
10. Extract river entry points from MERIT flow network → `v1/input/river_entries_v1.csv`
11. Write `simulation_v1.def`

**River entry boundary conditions (run_v1_river_inflow.py):**
- 90 entry points from `river_entries_v1.csv` (HydroATLAS order-5: 400–3000 km²; lower orders scaled by Hack's law: `A = 10 × 4^(order−2)`)
- WSE from Manning wide-rectangular channel formula
- Rational method `Q = C × i × A`

**Key parameters:**
- `SIM_DUR` = April 1–30 (30 days)
- `DT_RAIN_S = 1800` s (30 min IMERG)
- `SCALE = 30` m

**Key scripts:**
| Script | Purpose |
|--------|---------|
| `setup_v1.py` | Master input pipeline |
| `delineate_watershed_v1.py` | HydroATLAS watershed delineation |
| `download_imerg_v1.py` | GPM IMERG download for April 2025 |
| `download_river_network_v1.py` | River network download |
| `download_roads_v1.py` | Overture Maps road network |
| `extract_river_entries_v1.py` | Entry point extraction from network |
| `analyze_river_network_v1.py` | River network analysis + GEOGloWS check |
| `run_v1_river_inflow.py` | River inflow boundary generation |
| `run_v1_synthetic_flood.py` | Synthetic flood scenario |
| `visualize_v1.py` | Input/output visualization |

---

## v2 — 2026-03-06 Flash Flood Event (Compound Pluvial + Fluvial)

**Date:** 2026-03-09
**Session files:** `20260309/rim2d-nbo-run.md`, `20260311/2026-03-11-rim2d-nbo-output.txt`
**Scripts:** `run_v2_event_flood.py`, `visualize_v2.py`, `visualize_v2_focused.py`, `visualize_v2_animation.py`

**What changed:**
Switched from the April 2025 long-rains scenario to the specific **2026-03-06 Nairobi flash flood event**. This was a well-documented event with 5 rain gauges reporting 59–160mm in a single day.

**Event description:**
- 2026-03-05: Intermittent rainfall throughout the day → fully saturated soil
- 2026-03-06 16:00: Simulation start (t=0)
- 2026-03-06 17:30: Heavy rainfall onset (t=5,400 s)
- 2026-03-06 17:30–21:30: Intense 4-hour burst → river overflow
- Observed damage: cars washed at −1.311°N/36.821°E and Kirinyaga Road −1.280°N/36.827°E

**Rainfall data (24h totals from 5 gauges):**
| Gauge | Total (mm) |
|-------|-----------|
| Dagoretti | 112.2 |
| Moi Airbase | 145.4 |
| Wilson Airport | 160.0 |
| Kabete | 117.4 |
| Thika | 59.6 |
| Domain mean (IDW) | ~119 mm |

**Rainfall method:**
- Spatial: IDW (power=2) from 5 gauges → 30m grid
- Temporal: Modified Huff Type-II curve; 65% of total in 4-hour burst centred at 19:30 UTC
- Antecedent: fully saturated → `inf_rate = 0`, IWD = channel seed

**Fluvial boundary conditions:**
- Rational method: `Q = C × i × A`, `C_eff = 0.85` (saturated antecedent)
- 90 entry points from `river_entries_v1.csv`
- UP_AREA from HydroATLAS (order-5: 400–3000 km²; lower orders scaled by Hack's law)
- WSE from Manning wide-rectangular channel

**Key parameters:**
- `SIM_START_UTC = "2026-03-06T16:00:00Z"`
- `SIM_DUR_S = 86400` s (24 hours)
- `DT_RAIN_S = 1800` s (30 min, 48 steps)
- `BURST_START_S = 5400` (t=1.5h → 17:30)
- `BURST_END_S = 19800` (t=5.5h → 21:30)
- `RUNOFF_COEFF = 0.85` (saturated)

**Outputs:**
- `v2/input/rain/rain_v2_t{1..48}.nc` — 48 half-hourly rainfall rasters
- `v2/input/fluvbound_mask_v2.nc` — boundary cell mask
- `v2/input/inflowlocs_v2.txt` — WSE timeseries (90 entry points)

---

## v3 — Stream-Burn IWD via ESA WorldCover

**Date:** 2026-03-09
**Session files:** `20260309/rim2d-nbo-run.md`, `20260311/2026-03-11-rim2d-nbo-output.txt`
**Scripts:** `setup_v3.py`

**What changed:**
Adapted the Nile v7 stream-burn IWD methodology for Nairobi. The MERIT HND-derived IWD from v1 produced artefacts (HND=0 boundary issue, headwater noise). This version replaced it with a direct satellite-based channel mask.

**Three-step method (from Nile v7):**

**Step 1 — ESA WorldCover channel mask:**
WorldCover class 80 (permanent water bodies) → binary channel mask. Class 80 covers the major rivers including Nairobi River, Athi River, and Mathare.

**Step 2 — Stream-burn the DEM:**
DEM lowered by `BURN_DEPTH = 3.0` m at all channel cells. Creates a physically consistent river channel carved into the terrain.

**Step 3 — Compute IWD from burn depth:**
`IWD = BURN_DEPTH` at channel cells, 0 elsewhere. The initial water exactly fills the carved channel back to the original surface — a flat, stable initial condition.

**Parameters:**
- `BURN_DEPTH = 3.0` m
- `NORMAL_DEPTH = 3.0` m (IWD at channel = BURN_DEPTH)
- `WATER_CLASSES = [80]` (permanent water bodies only)

**All other inputs copied unchanged from v1** (roughness, buildings, sealed, pervious, sewershed).

**Outputs → `v3/input/`:**
- `channel_mask.nc` — binary water mask
- `dem.nc` — stream-burned DEM
- `iwd.nc` — initial water depth

---

## v4 — Steady-State Pre-Simulation IWD

**Date:** 2026-03-11
**Session files:** `20260311/2026-03-11-rim2d-nbo-output.txt`
**Scripts:** `setup_v4.py`, `visualize_v4_animation.py`

**What changed:**
Generated a **physically realistic IWD by running RIM2D with constant low baseflow** until steady state, then using the final water depth output as the IWD for the event simulation.

**Method (adapted from RIM2D `example_fluvial` IWD162.5m.nc approach):**
Nairobi terrain is steeply sloped (1440–2400m elevation), so gravity-driven steady state should converge in ~12 hours.

**Workflow:**
1. Compute baseflow Q per CROSSING entry from catchment area using FAO low-flow yield formula: `Q_base = BASEFLOW_YIELD × UP_AREA` (m³/s)
2. Convert Q_base → constant WSE via Manning's equation: `depth = (Q × n / (W × S^0.5))^(3/5)`
3. Write `inflowlocs_v4ss.txt` (constant WSE, N+1 steps, 12h run)
4. Run RIM2D: steady-state sim, no rain, IWD=0, fluv_bound=TRUE
5. Extract IWD from last water-depth output (`--extract-iwd` flag)

**Key parameters:**
- `SS_DUR_S = 43200` s (12 hours)
- `SS_DT_S = 1800` s (30 min WSE update interval)
- `MANNINGS_N = 0.035`
- `CHANNEL_W_BY_ORDER = {5: 25.0, 4: 15.0, 3: 8.0, 2: 4.0}` m

**Usage:**
```bash
# Step 1-3: generate steady-state inputs
micromamba run -n zarrv3 python setup_v4.py
# Step 4: run steady-state simulation
cd v4 && export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
../../bin/RIM2D simulation_v4ss.def --def flex
# Step 5: extract IWD from final output
micromamba run -n zarrv3 python setup_v4.py --extract-iwd
```

---

## v5 — TDX-Hydro River Network Burn IWD

**Date:** 2026-03-27
**Session files:** `20260327/2026-03-27-rim2d-nbo-iwd-geglows-method-docs.txt`
**Scripts:** `setup_v5.py`

**What changed:**
Replaced ESA WorldCover channel mask with the **pre-downloaded TDX-Hydro v2 river network** (`v1/input/river_network_tdx_v2.geojson`, 141 segments, orders 2–5). Width and depth assigned by stream order using tropical-river hydraulic scaling.

**Stream-order width/depth table (Nairobi tropical rivers):**
| Order | Width (m) | Depth (m) | Description |
|-------|-----------|-----------|-------------|
| 2 | 15 | 0.5 | Headwater streams |
| 3 | 30 | 1.0 | Minor tributaries |
| 4 | 60 | 1.5 | Major tributaries |
| 5 | 120 | 2.5 | Nairobi / Athi main stem |

**Method:**
1. Load TDX-Hydro v2 GeoJSON (orders 2–5)
2. Assign width + depth by stream order
3. Buffer each segment centerline by `rivwth/2`, create channel footprint
4. Burn DEM: lower by `rivdph` within the footprint
5. IWD = `original_dem − burned_dem` (clipped to ≥ 0)

**Roughness:** Switched from ESA WorldCover to **Dynamic World** land cover classification via `v3b` inputs.

**Inputs reused from v1:**
- `v1/tif/dem.tif` — 30m Copernicus DEM
- `v1/input/river_network_tdx_v2.geojson` — TDX-Hydro river network

**Outputs → `v5/input/`:** `dem.nc`, `iwd.nc`, `channel_mask.nc`, `roughness.nc`, + buildings, sealed, pervious, sewershed

**New dependencies:** `geopandas`, `rasterio.features.rasterize`, `shapely.ops.linemerge`

---

## v6 — Combined MERIT HND + TDX-Hydro IWD

**Date:** 2026-03-27
**Session files:** `20260327/2026-03-27-rim2d-nbo-iwd-geglows-method-docs.txt`
**Scripts:** `setup_v6.py`, `v6/extract_v6ss_iwd.py`, `compare_iwd.py`, `compare_iwd_v1_v6.py`

**What changed:**
Merged the two complementary IWD methods into a **two-layer approach**:

**Layer A — TDX-Hydro geometry burn (from v5):**
River segments orders 2–5, width/depth by stream order. Buffer each centerline by `rivwth/2`, lower DEM by `rivdph`. Orders 3–5 get full geometry; order-2 gets narrow/shallow burn.

**Layer B — MERIT HND drainage fill (gap-filler):**
Cells where `HND = 0` (exactly on a drainage line) that are NOT already covered by a TDX channel footprint. Applied with a small headwater burn depth (`HND_BURN_DEPTH = 0.3m`).

**Priority rule:** TDX footprint always wins — HND fill only applied in gaps between mapped TDX channels.

**Result:**
- Physically correct width/depth on 141 mapped TDX channels
- Continuous drainage connectivity via HND=0 headwater cells
- No double-counting between layers

**Parameters:**
```python
ORDER_WIDTH  = {2: 15,  3: 30,  4: 60,  5: 120}   # metres
ORDER_DEPTH  = {2: 0.5, 3: 1.0, 4: 1.5, 5:  2.5}  # metres
HND_BURN_DEPTH = 0.3   # m — headwater channel seed depth
```

**Comparison scripts:**
- `compare_iwd.py` — compare IWD between any two versions
- `compare_iwd_v1_v6.py` — side-by-side v1 vs v6 IWD maps

---

## File Locations Summary

| Version | Setup script | Simulation def | Output |
|---------|-------------|----------------|--------|
| v1 | `setup_v1.py` | `v1/simulation_v1.def` | `v1/output/` |
| v2 | `run_v2_event_flood.py` | `v2/simulation_v2.def` | `v2/output/` |
| v3 | `setup_v3.py` | `v3/simulation_v3.def` | `v3/output/` |
| v4 | `setup_v4.py` | `v4/simulation_v4ss.def` | `v4/output/` |
| v5 | `setup_v5.py` | `v5/simulation_v5.def` | `v5/output/` |
| v6 | `setup_v6.py` | `v6/simulation_v6.def` | `v6/output/` |

## Run command (all versions)
```bash
cd /data/rim2d/nbo_2026/<version_dir>
export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
../../bin/RIM2D simulation_vX.def --def flex
```

## Python environment
```bash
micromamba run -n zarrv3 python <script>.py      # most scripts
micromamba run -n hydromt-wflow python <script>.py  # v5, v6 (needs geopandas/rasterio extras)
```

## Key Python files
| Script | Purpose |
|--------|---------|
| `setup_v1.py` | Master input pipeline — DEM, IWD, roughness, buildings, IMERG |
| `run_v2_event_flood.py` | 2026-03-06 event — IDW rainfall + rational method fluvial BCs |
| `setup_v3.py` | ESA WorldCover stream-burn IWD |
| `setup_v4.py` | Steady-state baseflow pre-simulation IWD |
| `setup_v5.py` | TDX-Hydro geometry burn IWD |
| `setup_v6.py` | Combined MERIT HND + TDX-Hydro two-layer IWD |
| `delineate_watershed_v1.py` | HydroATLAS watershed delineation |
| `download_imerg_v1.py` | GPM IMERG download for April 2025 |
| `download_imerg_v10.py` | IMERG download (v10 style, reused) |
| `download_river_network_v1.py` | TDX-Hydro river network download |
| `download_roads_v1.py` | Overture Maps road network |
| `extract_river_entries_v1.py` | River entry point extraction |
| `extract_entry_points.py` | Entry points for boundary conditions |
| `analyze_river_network_v1.py` | Network analysis + GEOGloWS forecast check |
| `run_v1_river_inflow.py` | River inflow boundary conditions (April scenario) |
| `visualize_v1.py` | Input/output visualization |
| `visualize_v2.py` | v2 event visualization |
| `visualize_v2_focused.py` | v2 focused area visualization |
| `visualize_v2_animation.py` | v2 animation |
| `visualize_v4_animation.py` | v4 steady-state animation |
| `visualize_v7_analysis.py` | Post-sim analysis (shared with nile_highres) |
| `visualize_v10.py` | v10 visualization |
| `visualize_v11.py` | v11 visualization |
| `compare_iwd.py` | IWD comparison between versions |
| `compare_iwd_v1_v6.py` | v1 vs v6 IWD side-by-side |
| `v6/extract_v6ss_iwd.py` | Extract steady-state IWD from v6 output |
| `setup_v10.py` | v10 setup (reused from nile workflow) |

## Key external data sources
| Source | Used for |
|--------|---------|
| Copernicus GLO-30 DEM (GEE) | Base terrain |
| ESA WorldCover class 80 (GEE) | Channel mask (v1, v3) |
| MERIT Hydro HND (GEE) | Headwater gap-fill for IWD (v6) |
| GHSL (GEE) | Sealed/pervious surface fractions |
| GPM IMERG V7 (GEE) | Rainfall input |
| Overture Maps building + road polygons | Buildings, roads |
| TDX-Hydro v2 river network GeoJSON | Stream burning, width/depth IWD (v5, v6) |
| HydroATLAS level-12 sub-basins | Catchment delineation, upstream areas |
| GEOGloWS v2 retrospective Zarr | River discharge forecasts (analyze_river_network_v1.py) |
| 5 ground rain gauges (Nairobi) | IDW spatial rainfall field (v2) |

## IWD method progression summary

| Version | IWD method | Strength | Weakness |
|---------|-----------|---------|---------|
| v1 | MERIT HND pyflwdir (30m native HAND) | Physically derived | Boundary artefacts, headwater noise |
| v3 | ESA WorldCover class 80 stream burn (3m) | Satellite-observed channels | Misses unmapped channels |
| v4 | Steady-state baseflow RIM2D run | Hydraulically consistent | Computationally expensive |
| v5 | TDX-Hydro geometry burn (width+depth by order) | Correct channel geometry | Gaps between mapped segments |
| v6 | TDX-Hydro + MERIT HND gap-fill (two-layer) | Geometry + connectivity | Most complete method |
