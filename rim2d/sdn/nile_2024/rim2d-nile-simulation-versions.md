# RIM2D Nile High-Resolution Simulation — Version History
**Case study:** Abu Hamad, River State, Sudan (~19.53°N, 33.33°E)
**Event:** August 2024 flash flood
**Model folder:** `/data/rim2d/nile_highres/`
**Grid:** 30m resolution, UTM Zone 36N (EPSG:32636), ~8.4 km × 6.7 km domain

---

## Quick Reference Table

| Version | Key change | Date | Status |
|---------|-----------|------|--------|
| v1 | Regional 12_case parent domain run (1km, Sudan) | Jan 2026 | Complete |
| v2 | First 30m nile_highres domain, basic fluvial, return period IWD | 2026-03-04 | Complete |
| v3 | Return period IWD from pyflwdir HAND | 2026-03-04 | Complete |
| v4 | Copernicus GLO-30 DEM, native 30m HND, xesmf regridding | 2026-03-05 | Complete |
| v4-fix | Tighten river parameters — reduce over-deep/over-wide channel | 2026-03-05 | Complete |
| v5–v6 | HAND threshold fix (pyflwdir boundary artefact) | 2026-03-05 | Superseded by v7 |
| v7 | ESA WorldCover satellite channel mask, Overture Maps buildings | 2026-03-05 | Complete |
| v8 | Pluvial simulation — 20× amplified GPM rainfall | 2026-03-05 | Complete |
| v9 | Wadi inflow simulation — flash flood via north-side entry points | 2026-03-06 | Complete |
| v10 | Culvert inflow with real IMERG rainfall, 38-day Jul–Aug run | 2026-03-07 | Complete |
| v11 | Compound flooding — 3 inflows (culverts + Nile-blocked western wadi) | 2026-03-08 | Complete |
| v12 | Fix unrealistic 8m depths + add HospitalWadi 4th inflow | 2026-03-08 | Complete |
| v13 | TDX-Hydro stream burning + 6-day window (IMERG bug) | 2026-03-08 | Complete (bug) |
| v14 | Correct IMERG window via symlinks | 2026-03-13 | Complete (stagnation) |
| v15 | Fix Nile floodplain connectivity — DEM-based burn + railway burn | 2026-03-17 | Complete |
| v16 | Steady-state drainage connectivity diagnostic test | 2026-03-17 | Complete |
| v17 | Re-rasterize TDX-Hydro + fill tributary gaps + culvert burn | 2026-03-17 | Complete |
| v18 | Same root cause as v17, different burn approach | 2026-03-17 | Complete |
| v19 | Nile cells burned to exact target elevation, threshold raised 301→308m | 2026-03-17 | Complete |
| v20 | Iterative fix from v19, same burn strategy, re-tested | 2026-03-18 | Complete |
| v21 | Added pysheds 2-pass depression fill + resolve_flats | 2026-03-18 | Complete |
| v22 | Fix HospitalWadi→Nile connectivity (3-cell-wide channel burn) | 2026-03-18 | Complete |
| v23 | Fresh start from v10 DEM + ground-truth KML burns + pysheds fill | ~2026-03-27 | Complete |
| v24 | v23 + corr3.kml + 4-directional gap bridge (Fix G + H) | ~2026-03-30 | Complete |

---

## v1 — Regional Parent Domain (12_case)

**Date:** January 2026
**Folder:** `/data/rim2d/12_case/` and `/data/rim2d/12_case_nc/`
**Session files:** `20260125/rim2d-case12-run.md`, `20260127/xee-rim2d-run.md`

**What it was:**
First RIM2D run on the Sudan River Nile State regional domain at ~1km resolution. Used `12_Sudan_River_Nile_State_flood.def` covering the broader region (419×669 grid). GPM rainfall at 15-min intervals, 24-hour simulation. Purpose was to confirm RIM2D compiled and ran on the study region before zooming into the 30m sub-domain.

**Key files:**
- `12_case/12_Sudan_River_Nile_State_flood.def`
- `12_case/12_Sudan_River_Nile_State_DEM.asc`

**Outcome:** Confirmed RIM2D compilation and runtime. This parent case also provided the GPM rainfall files reused as rain input for v2–v8 of the nile_highres sub-domain.

---

## v2 — First 30m Sub-Domain, Return Period IWD

**Date:** 2026-03-04
**Git commit:** `7617374` — "added the case for 12_case_nc and then the case for nile high res v2"
**Session file:** `20260304/2026-03-04-rim2d-nile-simulation-v2.txt`
**Scripts:** `setup_nile_highres.py` (early version), `simulation.def`

**What changed:**
Carved out the Abu Hamad 30m sub-domain (BBOX: 33.28–33.36°E, 19.49–19.55°N). Used MERIT Hydro HND resampled from 90m to 30m for initial water depth. Rainfall extracted from the `12_case_nc` parent GPM run.

**Problem:** MERIT 90m HND resampled to 30m produced blocky artefacts — drainage lines 3-pixels wide at 90m became coarse/noisy at 30m.

---

## v3 — Native 30m HAND, Return Period IWD

**Date:** 2026-03-04
**Git commit:** `b250333` — "updated run for the version 3 with return period iwd"

**What changed:**
Switched from resampled MERIT HND to native 30m HAND computed directly from the Copernicus DEM using pyflwdir (Wang & Liu 2006 priority-flood, D8 flow directions). Return-period flow estimates used to set the IWD at channel cells.

**Problem:** pyflwdir assigns HND=0 at domain edges, causing the entire boundary to be classified as river. The IWD covered the full domain perimeter instead of only the channel.

**New module:** `compute_hnd.py` — encapsulates pyflwdir HAND pipeline.

---

## v4 — Copernicus GLO-30 DEM, xesmf Regridding

**Date:** 2026-03-05
**Git commit:** `0abf327` — "v4: Copernicus GLO-30 DEM, native 30m HND (pyflwdir), xesmf regridding"
**Session file:** `20260305/rim2d-mask-pluvial-simualtion-working-v8.md`

**What changed:**
- DEM upgraded from MERIT 90m (resampled) to Copernicus GLO-30 native 30m — sharper terrain.
- Regridding of MERIT 90m and GHSL 100m layers switched from `scipy.ndimage.zoom` to `xesmf` bilinear interpolation — eliminates nearest-neighbour blocky artefacts.
- HAND boundary artefact partially addressed: required BOTH low HND AND high flow accumulation to classify a cell as river.

**New module:** `regrid_xesmf.py`

**v4-fix** (`25ad759` — "v4-fix: tighten river parameters to reduce over-deep/over-wide channel"):
Narrowed the river channel parameters to reduce the artificial over-deepening and over-widening of the IWD initial condition.

---

## v5–v6 — HAND Threshold Tuning

**Date:** 2026-03-05
**Session files:** `20260203/rim2d-iwd.md`, `20260207/rim2d_burn_river_method_iwd.md`

**What changed:**
Multiple iterations tuning the pyflwdir HAND threshold and flow accumulation cutoff to eliminate the boundary artefact while preserving realistic channel coverage. v5 introduced the dual threshold (HND < X AND flow_acc >= Y). v6 refined values. Both were superseded by v7's switch to a satellite-based channel mask.

---

## v7 — ESA WorldCover Channel Mask + Overture Maps Buildings

**Date:** 2026-03-05
**Git commits:**
- `96d4c81` — "v7: satellite channel mask (ESA WorldCover class 80) replaces HND river mask"
- `7bd564b` — "v7: use Overture Maps building footprints for buildings/sewershed/sealed"
- `3df8d31` — "v7-fluvial: overflow analysis — river confined, buildings 19m above WSE"
- `daf9355` — "v7: add overflow and pluvial analysis visualization script"

**Session files:** `20260305/rim2d-lsdstreamburn-plan.md`
**Scripts:** `setup_nile_highres.py`, `visualize_v7_analysis.py`, `visualize_inputs.py`

**What changed:**
- **Channel mask:** Replaced HAND/flow-accumulation mask with ESA WorldCover class 80 (permanent water bodies) — direct satellite observation of actual river extent, no HAND boundary artefacts.
- **Stream burn:** DEM lowered 3m at all channel cells. IWD = 3m at those cells.
- **Buildings:** Switched from GEE GHSL building density to Overture Maps building polygon GeoJSON, rasterized at 30m using `all_touched=True`. Building count increased from ~950 to 7,861 cells.
- **Boundary selection:** Inflow/outflow cells selected from satellite channel mask.

**Analysis result:** Overflow analysis showed median bank freeboard = 9.7m, median building freeboard = 18.8m. Fluvial overflow would require a physically unrealistic 12m Nile rise. **Decision: pluvial / wadi flooding is the dominant mechanism.**

**Key scripts:**
| Script | Purpose |
|--------|---------|
| `setup_nile_highres.py` | Master input pipeline — DEM, IWD, roughness, buildings, rain, boundaries |
| `compute_hnd.py` | Native 30m HAND from pyflwdir |
| `regrid_xesmf.py` | MERIT/GHSL downscaling to 30m via xesmf |
| `rasterize_buildings.py` | Overture Maps polygons → 30m raster |
| `download_imerg_rain.py` | GPM IMERG V7 from GEE → NetCDF rain files |
| `visualize_inputs.py` | Input verification plots |
| `visualize_v7_analysis.py` | Overflow + pluvial analysis decision plots |

---

## v8 — Pluvial Simulation (20× Amplified Rainfall)

**Date:** 2026-03-05
**Git commits:**
- `cfce3ce` — "v8: pluvial simulation setup — 20x amplified GPM rainfall"
- `0ed6111` — "v8: pluvial flood simulation — full-domain sewershed fix, design storm"
- `6e00391` — "v8: add visualization scripts, README, and wadi entry analysis"

**Session files:** `20260305/rim2d-mask-pluvial-simualtion-working-v8.md`
**Scripts:** `run_v8_pluvial.py`, `visualize_v8_pluvial.py`, `analyse_rainfall.py`

**What changed:**
- GPM rainfall amplified 20× (8mm → 160mm total over 7 days) to simulate an extreme pluvial event.
- **Critical discovery:** RIM2D's GPU kernel multiplies rainfall by the sewershed mask. The v7 sewershed only covered building footprints → zero rainfall on open ground. Fixed with `sewershed_v8_full.nc` (all cells = 1.0) to apply rain domain-wide.
- Simulation: `simulation_v8_pluvial.def`, 604,800s (7 days), no fluvial boundary.

**Key parameters:**
- `RAIN_AMPLIFY = 20`
- `SIM_DUR = 604800` s (7 days)
- `DT_INFLOW = 1800` s (30 min)

---

## v9 — Wadi Inflow Simulation

**Date:** 2026-03-06
**Git commits:**
- `5e91ff5` — "v9: wadi inflow simulation setup — flash flood through north-side entry points"
- `79805ea` — "v9: wadi inflow simulation run + visualization"

**Session files:** `20260307/2026-03-07-rim2d-imerg-rain-geoglows-riverflow.txt`
**Folder:** `v9/`
**Scripts:** `v9/run_v9_wadi_inflow.py`, `v9/extract_entry_points.py`, `v9/visualize_v9_wadi.py`, `v9/visualize_wadi_entry.py`

**What changed:**
Flash flood via wadi entry points. The 8×7 km domain is too small to generate concentrated runoff locally — real flash floods at Abu Hamad arrive from upstream catchments (10–500 km²) through wadi channels at the north/west/east domain edges.

- Identified wadi entry cells at domain edges via flow accumulation.
- Generated a synthetic flash flood hydrograph (triangular: 2h rise, 1h peak, 6h fall).
- Peak flow: 150 m³/s from a 50 km² catchment (80mm rain, 30% runoff).
- Converted flow to WSE via Manning's equation at each entry cell.
- Combined wadi inflow with 20× amplified rainfall (compound flood).

**Key parameters:**
- `SIM_DUR = 259200` s (3 days)
- `PEAK_FLOW_M3S = 150.0`
- `WADI_ACC_THRESH = 50` cells
- `USE_RAINFALL = True` (compound: wadi + rainfall)

---

## v10 — Culvert Inflow with IMERG Rainfall

**Date:** 2026-03-07
**Session files:** `20260307/2026-03-07-rim2d-v10-plan.txt`
**Folder:** `v10/`
**Scripts:** `v10/run_v10_culvert_inflow.py`, `v10/setup_v10.py`, `v10/delineate_watershed_v10.py`, `v10/download_imerg_v10.py`, `v10/visualize_v10.py`

**What changed:**
Replaced synthetic hydrograph with **real IMERG rainfall + rational method** per catchment. The concrete channel on Abu Hamad's north side has 2 culvert openings; upstream runoff funnels through these during flash floods.

- Watershed delineated using HydroATLAS level-12 sub-basins.
- Rational method: `Q = C × I × A` with triangular unit hydrograph convolution.
- Culvert WSE from Manning's pressurised-flow formula.
- IMERG V7 downloaded for full Jul 25–Aug 31 (38 days, 1,824 half-hourly files).

**Key parameters:**
- `SIM_DUR = 3283200` s (38 days)
- `DT_INFLOW = 1800` s
- Culvert1: 30 km², Culvert2: 20 km²
- `CULVERT_WIDTH = 2.0` m, `CULVERT_HEIGHT = 2.0` m

**Problem:** Peak inflow only ~3.9 m³/s — far too low. IMERG at 0.1° captured only 18.2mm over the tiny domain. Upstream catchment rainfall missed entirely.

---

## v11 — Compound Flooding (Culverts + Nile-Blocked Western Wadi)

**Date:** 2026-03-08
**Git commit:** `daa8bc3` — "v9-v11: organize scripts into version folders, update README"
**Session files:** `20260308/rim2d-nile-highres-v11-complete.md`
**Folder:** `v11/`
**Scripts:** `v11/run_v11_synthetic_flood.py`, `v11/download_geoglows_rivers.py`, `v11/download_river_network.py`, `v11/download_roads_v11.py`, `v11/visualize_v11.py`, `v11/analysis/step1_nile_channel_mask.py`, `v11/sensitivity/prepare_sensitivity_inputs.py`, `v11/sensitivity/package_for_climada.py`

**What changed:**
Upgraded to **basin-scale IMERG** and added a third inflow. IMERG computed over the full HydroATLAS sub-basin polygon (not just the 8km domain), capturing rainfall over the entire upstream catchment.

**Three inflow boundaries:**
| Inflow | Location | Catchment | Peak Q |
|--------|---------|-----------|--------|
| Culvert1 | row=212, col=312 | 25 km² | 42.6 m³/s |
| Culvert2 | row=222, col=266 | 35 km² | 58.9 m³/s |
| WesternWadi | row=222, col=175 | 75 km² (Nile-blocked) | 108.3 m³/s |

WesternWadi was blocked by the Nile peak (31,694 m³/s on Aug 28 from GEOGloWS), causing compound backwater flooding. IMERG intensification factor: 5×.

River network: TDX-Hydro v2 GeoJSON downloaded (`v11/input/river_network_tdx_v2.geojson`), 141 segments.

**Results:**
- 24,845 cells > 0.1m flooded; max depth 11.7m (unrealistic — at inflow boundary cells)
- CLIMADA impact: 518 directly affected, 1,428 road access loss, 1,687 healthcare access loss
- Hospital area NOT flooded (missed)

**Problems identified:**
1. Inflow cells showing 5–8m depth — pressurised overflow formula unbounded
2. Hospital drainage wadi not included

---

## v12 — Fix Inflow Depths + Add HospitalWadi

**Date:** 2026-03-08
**Session files:** `20260308/rim2d-nile-highres-tipg-rivernetwork.md`
**Folder:** `v12/`
**Scripts:** `v12/run_v12_setup.py`, `v12/V12_METHODOLOGY.md`

**Fix 1 — WSE cap at sill + 1.5m:**
v11's `flow_to_wse()` used a pressurised orifice formula with no physical cap (only 10m ceiling). When peak inflow (42–59 m³/s) greatly exceeded culvert capacity (~14–17 m³/s), the formula produced 5–8m at a single cell. Replaced with a hard cap:
```python
WSE_CAP_M = 1.5  # max depth above sill
if q > q_full:
    depth = WSE_CAP_M   # cap instead of orifice formula
return sill_elev + depth
```
Result: max depth at Culvert2 → **1.58m** ✓

**Fix 2 — 4th inflow: HospitalWadi:**
Added boundary at 19.539508°N, 33.330320°E (row=183, col=281, DEM=316.1m). 5 km² catchment. Peak Q ≈ 10.6 m³/s → WSE 317.5m (+1.4m above sill). Ground observations confirmed this wadi cut road access to the hospital during the Aug 2024 event.

**Simulation parameters (inherited from v11):**
- `SIM_DUR = 3196800` s (37 days)
- `WSE_CAP_M = 1.5` m
- 4 inflow boundary conditions

---

## v13 — TDX-Hydro Stream Burning + 6-Day Window

**Date:** 2026-03-08
**Folder:** `v13/`
**Scripts:** `v13/run_v13_setup.py`

**Fix 3 — DEM stream burning using TDX-Hydro v2:**
Road embankments and urban artefacts in the MERIT DEM blocked flow along natural stream channels. TDX-Hydro Order 2/5/9 segments rasterized and burned into the DEM:

| Stream order | Burn depth | Purpose |
|---|---|---|
| Order 9 (Nile) | −5 m | Main Nile channel drainage |
| Order 5 (major wadis) | −3 m | Wadi channel connectivity |
| Order 2 (minor wadis) | −2 m | Urban secondary drainage |

Total: 1,684 cells burned. Saved as `v13/input/dem_v13.nc`.

**Simulation window reduced to 6 days** (Aug 25–31, SIM_DUR = 518,400 s).

**Critical bug discovered:** RIM2D ignores `pluvial_start=1488` — always loads IMERG starting from `t1`. v13 ran with **July rainfall files** (near-zero), not the intended Aug 25–31 storm. DEM improvement was valid but the forcing was wrong. Flooded cells: 11,709 → 9,834, but no storm response.

---

## v14 — Correct IMERG Window via Symlinks

**Date:** 2026-03-13
**Session files:** `20260313/2026-03-13-rim2d-v14.txt`, `20260315/2026-03-15-rim2d-nile-simulaiton-v14-input.txt`
**Folder:** `v14/`
**Scripts:** `v14/analysis/visualize_v14.py`, `v14/analysis/plot_v14_inputs.py`
**Note:** No new setup script — v13 inputs reused, only .def file and rain symlinks changed.

**Fix 4 — IMERG symlinks (workaround for RIM2D `pluvial_start` bug):**
Since RIM2D always loads from `t1`, the Aug 25–31 IMERG files were symlinked to renumber them starting from t1:
```
v14/input/rain/imerg_v14_t1.nc  →  v10/input/rain/imerg_v10_t1489.nc  (Aug 25 00:00)
...
v14/input/rain/imerg_v14_t288.nc → v10/input/rain/imerg_v10_t1776.nc  (Aug 31 00:00)
```
288 symlinks covering 6 days × 48 half-hourly steps.

**Results:**
- Storm correctly arrives at h40–48 (Aug 26–27) ✓
- HospitalWadi peaks at 1.47m at h48 ✓
- 18,480 cells > 0.1m flooded

**Remaining problem — stagnation:**
Deep pools (3–6m) formed on the Nile floodplain. TDX-Hydro burns only covered cols 0–130 and 306–385. The Nile meander through cols ~130–306 was entirely unburned — 8,780 flat DEM=299m cells with no drainage path.

---

## v15 — Fix Nile Floodplain Connectivity

**Date:** 2026-03-17
**Session files:** `20260317/2026-03-17-rim2d-run-v14-v15.txt`, `20260317/2026-03-18-rim2d-nile-v16-v18.txt`
**Folder:** `v15/`
**Scripts:** `v15/run_v15_setup.py`, `v15/analysis/visualize_v15.py`, `v15/analysis/plot_v15_inputs.py`

**Root cause:** MERIT DEM flat zones at DEM=299m (Nile floodplain/meander cells). TDX-Hydro GeoJSON covered Nile at cols 0–130 and 306–385 but left a ~176-column gap through the meander centre. A **railway embankment** at rows 78–92 (DEM ~302m) also formed a partial barrier.

**Fix 5a — DEM-based Nile floodplain burn:**
All cells where `DEM < 301m` lowered to 294m (Nile low-water estimate):
```python
NILE_ELEV_THRESH = 301.0
NILE_TARGET_ELEV = 294.0
nile_mask = dem < NILE_ELEV_THRESH
dem_v15[nile_mask] = NILE_TARGET_ELEV
```
Covered 8,780 cells — creates a continuously connected Nile channel east to west.

**Fix 5b — Railway crossing burn:**
At the ~302m ridge (rows 78–92, cols 100–313), applied extra −5m burn at TDX-Hydro Order-2/5 crossings within that row band.

**All changes accumulated in v15:**
| Change | Version introduced |
|---|---|
| WSE cap sill + 1.5m | v12 |
| HospitalWadi 4th inflow | v12 |
| TDX-Hydro Order 2/5/9 stream burns | v13 |
| Aug 25–31 IMERG window via symlinks | v14 |
| DEM-based Nile floodplain burn (`dem < 301m → 294m`) | **v15** |
| Railway crossing burn (rows 78–92, −5m extra) | **v15** |

---

## v16 — Steady-State Drainage Connectivity Diagnostic

**Date:** 2026-03-17
**Folder:** `v16/`
**Scripts:** `v16/run_v16_setup.py`, `v16/analysis/visualize_v16.py`

**Purpose:** Diagnostic only — no rainfall. All 4 inflow cells held at extreme constant WSE (sill + 5m) for 6 days to reveal remaining DEM drainage gaps before committing to full simulation.

**Key findings (revealed gaps):**
- **Gap 1 (eastern):** F17 tributary (cols 240–298) ends at row ~144–200. F22 Nile east bend starts at row ~128–146. Gap = 29–72 unburned rows at cols 255–298.
- **Gap 2 (western):** F18 tributary (cols 147–183) ends at row ~133–193. F19 Nile center starts at row ~106–117. Gap = 27–76 unburned rows at cols 147–183.
- **Culvert:** 8m culvert under railway at row=176, col=253 — DEM=315.85m — not burned.

**Key parameters:**
- `SIM_DUR = 518400` s (6 days)
- `EXTREME_DEPTH = 5.0` m above sill
- No rainfall

---

## v17 — Re-rasterize Tributaries + Fill Gaps + Culvert Burn

**Date:** 2026-03-17
**Folder:** `v17/`
**Scripts:** `v17/run_v17_setup.py`, `v17/analysis/visualize_v17.py`

**What changed (based on v16 diagnostic):**

- **Fix 6a:** Re-rasterized ALL TDX-Hydro stream features from GeoJSON (all Orders 2/5/9).
- **Fix 6b:** Burned connecting channels through Gap 1 and Gap 2 (dem − 3m, capped at Nile level).
- **Fix 6c:** Burned 8m culvert cell at row=176, col=253 (`dem − 8m` → invert ~307.85m).

**Burn depths:**
- Order 9 (Nile): −5m
- Order 5 (major wadis): −3m
- Order 2 (minor wadis): −2m
- Gap bridge cells: −3m (Order-5 equivalent)
- Culvert invert: `CULVERT_INVERT_BELOW_SURFACE = 8.0` m

---

## v18 — Tributary Gap Fix (Alternative Approach)

**Date:** 2026-03-17
**Folder:** `v18/`
**Scripts:** `v18/run_v18_setup.py`, `v18/analysis/visualize_v18.py`

**What changed:**
Same root cause and fixes as v17 (Fix 6a/6b/6c) but an alternative gap-bridge algorithm was tested. v17 and v18 were parallel diagnostic iterations — the approach was further refined from v19 onward.

---

## v19 — Exact Nile Target Elevation for Order-9 + Raised Threshold

**Date:** 2026-03-18
**Folder:** `v19/`
**Scripts:** `v19/run_v19_setup.py`

**Changes vs v18:**
- **Order-9 Nile cells** burned to exactly `NILE_TARGET_ELEV = 294m` (not `dem − 5m`) — fixes fragmented Nile channel at cols 209–241 where DEM ridges at 302–312m prevented the relative burn from reaching the channel floor.
- **Gap bridge cells** burned to exactly `NILE_TARGET_ELEV = 294m` (not `dem − 3m`) — fixes shallow channel floors at 312m blocking flow to the Nile at 294m.
- **Nile threshold raised** from 301m → 308m to capture the 302–307m ridge cells that are functionally part of the Nile floodplain.

---

## v20 — Iterative Refinement of v19 Burns

**Date:** 2026-03-18
**Session files:** `20260318/2026-03-18-rim2d-v20-plan-simple.txt`
**Folder:** `v20/`
**Scripts:** `v20/run_v20_setup.py`, `v20/analysis/dem_diagnostic.py`

**What changed:**
Re-applied v19 burn strategy with `dem_diagnostic.py` added to verify all 4 inflows drain to the Nile **before** committing to a full simulation. Same burn parameters as v19 (threshold 308m, exact 294m target for Order-9 and gap cells). Diagnostic confirmed flow paths through pysheds analysis.

---

## v21 — Pysheds 2-Pass Depression Filling

**Date:** 2026-03-18
**Session files:** `20260318/2026-03-18-rim2d-v21-diagnosis-run-complete.txt`, `20260318/rim2d-run-v21-diagnosis.md`
**Folder:** `v21/`
**Scripts:** `v21/run_v21_setup.py`, `v21/analysis/dem_diagnostic.py`, `v21/analysis/plot_dem_comparison.py`, `v21/analysis/visualize_v21.py`

**What changed:**
Added **pysheds 2-pass depression filling** (`Grid.fill_depressions` + `resolve_flats`, float64 precision) after all stream burns. Eliminated 4,255 DEM pits → 0.

New dependencies: `rasterio`, `pysheds.grid.Grid`

**Remaining issue:** DEM diagnostic still reported flow-path problems. Root cause: pysheds uses 8-directional routing and "saw" diagonal exits, but RIM2D uses strict 4-directional routing — a diagonal escape invisible to RIM2D.

---

## v22 — Fix HospitalWadi → Nile Connectivity

**Date:** 2026-03-18
**Folder:** `v22/`
**Scripts:** `v22/run_v22_setup.py`, `v22/analysis/dem_diagnostic.py`, `v22/analysis/plot_dem_comparison.py`, `v22/analysis/visualize_v21.py`

**Fix 8 — 3-cell-wide channel burn for HospitalWadi:**
Root cause from v21 output: F17 GeoJSON rasterised only rows 178–183 at col~281. A 29-row (870m) unburned ridge at 315–320m blocked HospitalWadi (row=183, col=281) from draining to the Nile 294m zone (row~153).

Fix: Burned a **3-cell-wide channel** (cols 278–280) from row=153 to row=183 at `dem − 8m`, capped at 294m. Creates a ~307m invert directly connecting HospitalWadi to the Nile 294m zone.

---

## v23 — Fresh Start from v10 DEM + Ground-Truth KML Burns

**Date:** ~2026-03-27
**Session files:** `20260327/2026-03-27-rim2d-source-code.txt`
**Folder:** `v23/`
**Scripts:** `v23/run_v23_setup.py`, `v23/analysis/dem_diagnostic.py`, `v23/analysis/visualize_v23.py`
**KML files:** `v23/cor1.kml`, `v23/cor2.kml`

**Strategy — complete reset:**
Base DEM reverted to **v10 raw MERIT DEM** (no prior modifications). All previous burns discarded.

- **Fix A:** Nile floodplain burn (`dem < 308m → 294m`)
- **Fix B:** GeoJSON stream burns — ALL features EXCEPT linkno=160245676 (confirmed wrongly positioned vs Google Earth satellite)
- **Fix C:** `cor1.kml` — ground-truth channel line digitized from Google Earth (dem − 8m)
- **Fix D:** `cor2.kml` — second ground-truth channel line (dem − 8m)
- **Fix E:** Gap bridge for F18→F19 narrow gaps (≤30 rows)
- **Fix F:** Pysheds 2-pass depression fill + resolve_flats (float64)

KML files digitized from Google Earth satellite imagery to trace the actual on-the-ground wadi and culvert positions, replacing the misaligned GeoJSON feature.

**Burn parameters:**
- `NILE_ELEV_THRESH = 308.0`, `NILE_TARGET_ELEV = 294.0`
- `BURN_ORDER9 = None` (burn to exact target, not relative)
- `BURN_ORDER5 = 3.0`, `BURN_ORDER2 = 2.0`
- `COR_BURN_DEPTH = 8.0` (KML channels)
- `SKIP_LINKNO = 160245676`

---

## v24 — Corr3.kml + 4-Directional Gap Bridge

**Date:** ~2026-03-30
**Session files:** `20260330/2026-03-30-rim2d-all-11cases-upload.txt`
**Folder:** `v24/`
**Scripts:** `v24/run_v24_setup.py`, `v24/analysis/dem_diagnostic.py`, `v24/analysis/visualize_v24.py`, `v24/analysis/bresenham_4connected_demo.py`
**KML files:** `v23/cor1.kml`, `v23/cor2.kml`, `v23/corr3.kml`

**Root cause of v23 stagnation:**
`cor2.kml` burned a channel along col~251 but the lowest cell (row=158, col=250 at 306.44m) was a **4-directional pit** — all 4 orthogonal neighbours were higher:
- N row=159,col=250: 320.87m | S row=157,col=250: 314.30m
- E row=158,col=251: 309.11m | W row=158,col=249: 314.14m

The only escape was diagonal to row=157,col=249 (302.79m) — visible to pysheds (8-dir) but **not routable by RIM2D (4-dir)**. Depression fill "passed" but RIM2D could never use the path.

**Fix G — corr3.kml (dem_orig − 1m):**
`corr3.kml` traces path from row=176 to row=158 along col~249–254. Burned at `dem_orig − 1m`, lowers blocking cells west of col=251 to create real 4-directional flow.

**Fix H — Programmatic 4-directional gap bridge:**
Algorithmically ensured 4-directional connectivity from the corr3 channel to the Nile 294m zone (rows ≤155):
1. Find minimum elevation along corr3 path in critical zone (rows 155–160, cols 247–255)
2. Trace a monotonically decreasing gradient south until reaching a Nile-zone cell (≤295m)
3. Burn cells to `max(linear_gradient, NILE_TARGET_ELEV)`

This **guarantees a 4-directional drainage path** that RIM2D can actually route through.

**New analysis tool:** `v24/analysis/bresenham_4connected_demo.py` — demonstrates the 4-connected path algorithm.

---

## File Locations Summary

| Version | Setup script | Simulation def | Max depth output |
|---------|-------------|----------------|-----------------|
| v7 | `setup_nile_highres.py` | `simulation.def` | `output/nile_highres_wd_max.nc` |
| v8 | `run_v8_pluvial.py` | `simulation_v8_pluvial.def` | `output_v8_pluvial/` |
| v9 | `v9/run_v9_wadi_inflow.py` | `v9/simulation_v9_wadi_inflow.def` | `v9/output/` |
| v10 | `v10/run_v10_culvert_inflow.py` | `v10/simulation_v10.def` | `v10/output/` |
| v11 | `v11/run_v11_synthetic_flood.py` | `v11/simulation_v11.def` | `v11/output/nile_v11_wd_max.nc` |
| v12 | `v12/run_v12_setup.py` | `v12/simulation_v12.def` | `v12/output/nile_v12_wd_max.nc` |
| v13 | `v13/run_v13_setup.py` | `v13/simulation_v13.def` | `v13/output/nile_v13_wd_max.nc` |
| v14 | *(v13 setup reused)* | `v14/simulation_v14.def` | `v14/output/nile_v14_wd_max.nc` |
| v15 | `v15/run_v15_setup.py` | `v15/simulation_v15.def` | `v15/output/nile_v15_wd_max.nc` |
| v16 | `v16/run_v16_setup.py` | `v16/simulation_v16.def` | `v16/output/` |
| v17 | `v17/run_v17_setup.py` | `v17/simulation_v17.def` | `v17/output/` |
| v18 | `v18/run_v18_setup.py` | `v18/simulation_v18.def` | `v18/output/` |
| v19 | `v19/run_v19_setup.py` | `v19/simulation_v19.def` | `v19/output/` |
| v20 | `v20/run_v20_setup.py` | `v20/simulation_v20.def` | `v20/output/` |
| v21 | `v21/run_v21_setup.py` | `v21/simulation_v21.def` | `v21/output/` |
| v22 | `v22/run_v22_setup.py` | `v22/simulation_v22.def` | `v22/output/` |
| v23 | `v23/run_v23_setup.py` | `v23/simulation_v23.def` | `v23/output/` |
| v24 | `v24/run_v24_setup.py` | `v24/simulation_v24.def` | `v24/output/` |

## Run command (all versions)
```bash
cd /data/rim2d/nile_highres/<version_dir>
export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
/data/rim2d/bin/RIM2D simulation_vXX.def --def flex
```

## Python environment
```bash
micromamba run -n zarrv3 python <script>.py
```

## Key Python files — shared utilities
| Script | Purpose |
|--------|---------|
| `setup_nile_highres.py` | Master input pipeline (v7 state) |
| `compute_hnd.py` | Native 30m HAND from pyflwdir |
| `regrid_xesmf.py` | MERIT/GHSL downscaling to 30m |
| `rasterize_buildings.py` | Overture Maps polygons → 30m raster |
| `download_imerg_rain.py` | GPM IMERG V7 from GEE → NetCDF |
| `v10/download_imerg_v10.py` | IMERG download for full Jul–Aug (38 days) |
| `analyse_rainfall.py` | Compare IMERG vs GPM vs amplified |
| `visualize_inputs.py` | Input verification plots |
| `visualize_flood_results.py` | General flood depth maps + GIF animation |
| `plot_imerg_august.py` | IMERG August rainfall analysis |
| `v11/download_geoglows_rivers.py` | GEOGloWS v2 Nile discharge from S3 Zarr |
| `v11/download_river_network.py` | TDX-Hydro v2 river network download |
| `v20/analysis/dem_diagnostic.py` | DEM drainage connectivity check (4 inflows → Nile) |
| `v24/analysis/bresenham_4connected_demo.py` | 4-connected path algorithm demo |

## Key external data sources
| Source | Used for |
|--------|---------|
| Copernicus GLO-30 DEM (GEE) | Base terrain (v4+) |
| ESA WorldCover class 80 (GEE) | Channel mask (v7+) |
| MERIT Hydro (GEE) | HND, river width (v1–v3, diagnostics) |
| GHSL (GEE) | Sealed/pervious surface fractions |
| GPM IMERG V7 (GEE) | Rainfall input (v2–v8) |
| GPM IMERG V7 (half-hourly, 38-day) | Rainfall input (v10+) |
| Overture Maps building polygons | Building footprint raster (v7+) |
| TDX-Hydro v2 river network GeoJSON | Stream burning (v11+) |
| HydroATLAS level-12 sub-basins | Catchment delineation (v11+) |
| GEOGloWS v2 retrospective Zarr | Nile discharge for backwater analysis (v11) |
| Google Earth satellite (KML digitizing) | Ground-truth channel positions (v23+) |
