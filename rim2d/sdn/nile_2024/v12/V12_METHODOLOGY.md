# RIM2D Nile High-Resolution — v11 Issues and v12 Rectifications

## Overview

v11 was the first compound flooding model for Abu Hamad (Aug 2024 event), combining
culvert overflow and Nile-blocked western wadi inflow. Post-simulation analysis
against ground observations and CLIMADA impact results revealed two problems that
are corrected in v12.

---

## Problem 1 — Unrealistic 8m flood depths at inflow boundary cells

### What was observed

The v11 `nile_v11_wd_max.nc` output showed water depths of **5–8m at the three
inflow boundary cells** (Culvert1, Culvert2, WesternWadi), far exceeding any
physically plausible urban flood depth.

| Inflow cell | DEM elevation | v11 peak WSE | Implied depth |
|---|---|---|---|
| Culvert1 (row=212, col=312) | 321.1 m | 325.9 m | **4.8 m** |
| Culvert2 (row=222, col=266) | 320.0 m | 325.8 m | **5.8 m** |
| WesternWadi (row=222, col=175) | 318.9 m | 321.8 m | 2.9 m |

### Root cause

The v11 `flow_to_wse()` function used a **pressurised overflow formula**:

```python
# v11 — PROBLEMATIC
q_excess = q - q_full
cd = 0.6
g = 9.81
h_overflow = (q_excess / (cd * w * (2.0 * g)**0.5))**(2.0/3.0)
depth = h + h_overflow          # no cap — grows unbounded with Q
depth = min(depth, 10.0)        # only capped at 10m!
return dem_elev + depth
```

When peak inflow (42–59 m³/s) greatly exceeds culvert capacity (~14–17 m³/s),
this formula applies an orifice overflow formula at **a single cell**, creating
an unrealistically large hydraulic head. The result is a deep localised pool
around each inflow point that does not represent real overtopping behaviour.

### Fix in v12 — WSE cap (`run_v12_setup.py`)

The function `flow_to_wse_capped()` in `run_v12_setup.py` replaces the
pressurised formula with a **hard cap** of `sill_elevation + WSE_CAP_M` (1.5 m):

```python
# v12 — FIXED  (run_v12_setup.py, function flow_to_wse_capped)
WSE_CAP_M = 1.5   # maximum depth above sill at any single boundary cell

if q <= q_full:
    # Free-flow: Manning bisection — unchanged from v11
    depth = <bisection result>
else:
    # Pressurised / overtopping: CAP at WSE_CAP_M instead of orifice formula
    depth = WSE_CAP_M

return sill_elev + depth
```

The same cap is applied to the open-channel western wadi via
`flow_to_wse_open_capped()` and to the new hospital wadi via
`flow_to_wse_wadi()`.

**Physical justification:** 1.5 m of head above the culvert sill is sufficient
to drive 3–4× the culvert's full-pipe capacity via weir overflow. Any additional
discharge above that head enters the settlement as sheet flow, which RIM2D
propagates naturally through its 2D routing. There is no physical mechanism that
would sustain 5–8 m of ponding at a single 30 m grid cell.

| Inflow cell | v11 peak depth above sill | v12 peak depth above sill |
|---|---|---|
| Culvert1 | 4.8 m ❌ | 1.9 m ✓ |
| Culvert2 | 5.8 m ❌ | 1.7 m ✓ |
| WesternWadi | 2.9 m ❌ | 1.5 m ✓ |
| HospitalWadi | — | 1.4 m ✓ (new) |

---

## Problem 2 — Hospital access wadi not captured

### What was observed

Ground observations confirm that the N-S drainage wadi at
**(19.539508°N, 33.330320°E)** — approximately 500 m west of Abu Hamad
hospital (19.536195°N, 33.335439°E) — flooded during the Aug 2024 event,
**cutting road access between the main settlement and the hospital**.

The CLIMADA impact analysis (analysis/analysis_note.md) counted "people losing
access to healthcare" as one of its key metrics. If this wadi flooding is not
represented, the access-disruption impact is under-estimated.

### Why v11 missed it

- The wadi cell (row=183, col=281, DEM=316.1 m) showed **9.74 m depth** in
  v11 — but this was an artefact of Culvert2's inflated WSE (325.9 m)
  spreading across low-lying cells, **not** a realistic representation of
  the wadi flooding.
- After Problem 1 is fixed and the culvert WSE drops to 321.7 m, the
  artificial inundation of the wadi cell disappears.
- The wadi has its own **~5 km² catchment** (low-lying strip between the
  settlement and the Nile bank) that generates real runoff during the
  Aug 26–28 rainfall event — but this was not included as a boundary in v11.

### Fix in v12 — 4th inflow boundary (`run_v12_setup.py`)

A fourth inflow point is added at the wadi cell using the same rational-method
hydrograph approach as the culverts:

```python
# v12 — run_v12_setup.py
HOSPITAL_WADI = {
    "name": "HospitalWadi",
    "lat": 19.539508, "lon": 33.330320,
    "catchment_km2": 5.0,   # low-lying strip between settlement and Nile bank
}

tc_hw = compute_tc_hours(5.0)   # Kirpich: 0.57 h (small urban catchment)
q_hw  = rational_method_hydrograph(
    basin_rain_intensified, catchment_m2=5e6,
    runoff_coeff=0.65, uh=triangular_uh(tc_hw), dt_s=1800
)
# Peak Q: ~10.6 m³/s  →  WSE: 317.5 m  (+1.4 m above 316.1 m bed)
wse_hw = [flow_to_wse_wadi(qi, hw_elev) for qi in q_hw_padded]
```

The resulting 1.4 m water depth in the wadi channel floods the road crossing,
correctly reproducing the observed loss of hospital access.

**Physical justification:** The 5 km² catchment is estimated from the DEM
topography of the low-lying area between the settlement (western boundary) and
the Nile bank (eastern boundary), at the latitude of the hospital. The
intensified IMERG rainfall (5× = 90 mm effective) over 5 km² with C=0.65
generates a peak flow consistent with a narrow urban flash-flood channel.

---

## Running the simulation

### v12 setup (boundary file generation)

Generates all 4 inflow boundary conditions from the cached v11 IMERG data
(**no re-download needed**):

```bash
cd /data/rim2d/nile_highres/v12
micromamba run -n zarrv3 python run_v12_setup.py
```

Output files written to `input/`:
- `fluvbound_mask_v12.nc` — 4-zone boundary mask raster
- `inflowlocs_v12.txt` — WSE timeseries for all 4 inflow cells
- `culvert_hydrographs_v12.npz` — cached hydrographs for visualisation
- `v12_metadata.json` — full parameter record

### v12 RIM2D simulation

```bash
cd /data/rim2d/nile_highres/v12
export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
/data/rim2d/bin/RIM2D simulation_v12.def --def flex
```

Output goes to `output/nile_v12_wd_*.nc` (6-hour snapshots) and
`output/nile_v12_wd_max.nc` (peak depth over full run).

---

## Reducing simulation duration for next iteration

The current simulation runs for **37 days** (SIM_DUR = 3,196,800 s,
Jul 25 – Aug 31) to capture the full Nile flood hydrograph context.
For sensitivity ensemble runs where only the **peak flood window matters**
(Aug 25–30, ~6 days), the simulation can be trimmed significantly.

### How to change duration

In `run_v12_setup.py` (or future `run_v<N>_setup.py`), edit:

```python
# Current (37 days — full Nile season)
SIM_DUR = 3_196_800   # seconds

# Reduced option 1: 10 days centred on the event (Aug 22 – Sep 1)
SIM_DUR = 864_000     # 10 days

# Reduced option 2: 6 days peak window (Aug 25 – Aug 31)
SIM_DUR = 518_400     # 6 days
```

Also adjust the IMERG start index to match:

```python
# In run_v12_setup.py, after loading basin_rain_int:
# IMERG step 0 = Jul 25 00:00 UTC; Aug 25 = step 31*48 = 1488
IMERG_START_STEP = 1488   # skip to Aug 25
basin_rain_int = basin_rain_int[IMERG_START_STEP : IMERG_START_STEP + SIM_DUR//DT_INFLOW]
nile_blocking  = nile_blocking [IMERG_START_STEP : IMERG_START_STEP + SIM_DUR//DT_INFLOW]
```

And update the RAIN references in `simulation_v12.def`:

```
**pluvial_raster_nr**
288          ← number of IMERG files for the reduced window
**pluvial_start**
1488         ← start at IMERG file t1489 (Aug 25)
```

### Next iteration — multiple scenario ensemble with reduced duration

For the sensitivity ensemble (Steps 2 & 3 in `sensitivity/`), the recommended
workflow once v12 is validated:

```bash
# 1. Edit SIM_DUR and IMERG_START_STEP in prepare_sensitivity_inputs.py
# 2. Re-generate boundary files (fast, <1 min)
micromamba run -n zarrv3 python sensitivity/prepare_sensitivity_inputs.py

# 3. Run all 5 scenarios sequentially (~15–20 min each at 6-day window vs ~60 min at 37 days)
bash sensitivity/run_sensitivity_ensemble.sh

# 4. Apply channel mask and package for CLIMADA
micromamba run -n zarrv3 python sensitivity/package_for_climada.py
```

Estimated GPU time per scenario at 6-day window: **~10–15 min** (vs ~60 min
for the full 37-day run).

---

## File summary

| File | Purpose |
|---|---|
| `run_v12_setup.py` | Generates v12 boundary conditions (WSE cap + 4th inflow) |
| `simulation_v12.def` | RIM2D flex-format simulation definition |
| `input/fluvbound_mask_v12.nc` | 4-zone boundary mask |
| `input/inflowlocs_v12.txt` | WSE timeseries, 4 cells × 1777 timesteps |
| `input/v12_metadata.json` | All parameters, peak flows, elevations |
| `output/nile_v12_wd_max.nc` | Peak flood depth (main output for CLIMADA) |
| `analysis/step1_nile_channel_mask.py` | Post-processing: mask Nile channel cells |

---

## Version comparison

| Metric | v11 | v12 |
|---|---|---|
| Inflow boundaries | 3 | **4** |
| Max WSE above sill | 5.8 m ❌ | **1.5 m** ✓ |
| Hospital wadi | not modelled | **included** |
| Hospital access road flooded | no ❌ | **yes** ✓ |
| Simulation duration | 37 days | 37 days (reducible to 6 days) |
| Output: `wd_max` max depth | 11.7 m ❌ | TBD after run |
| CLIMADA directly affected | 518 | TBD |
