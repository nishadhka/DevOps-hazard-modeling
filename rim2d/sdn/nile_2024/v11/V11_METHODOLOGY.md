# v11 Methodology — Synthetic Hydrograph from Basin-Derived Catchment Rainfall

## 1. Overview

v11 simulates the August 2025 Abu Hamad (Sudan) flash flood using a basin-derived
synthetic hydrograph approach. Rather than relying solely on IMERG rainfall over the
small simulation domain (~11 km x 9 km), v11 captures rainfall over the **full upstream
catchment** that drains through the settlement's culvert openings.

### Why v10 underestimated flooding

v10 used IMERG rainfall averaged over the simulation domain only. At IMERG's
0.1-degree resolution (~11 km), the domain captured only 18.2 mm of rainfall over
38 days. Combined with small assumed catchment areas (30/20 km2), the resulting
culvert inflow peaked at ~3.9 m3/s — well below the pressurized-flow threshold
needed to match observed flooding.

The actual flooding was devastating: most buildings were inundated to ~2 feet
(0.6 m), and the railway embankment parallel to the Nile was washed away.

## 2. Scientific Basis

### 2.1 Observation-Constrained Scenario Modeling

Using real-world observations to calibrate and constrain flood models is standard
practice in operational hydrology. This approach follows WMO guidelines for
impact-based forecasting (WMO No. 1150) and is used by:

- National Weather Services for flash flood guidance calibration
- FEMA for regulatory flood mapping (calibrated HEC-RAS models)
- European Flood Awareness System (EFAS) for ensemble post-processing
- Insurance loss modeling (AIR, RMS, CoreLogic)

The principle: when satellite rainfall resolution is insufficient to capture the
spatial variability driving localized flooding, the model is constrained against
observed impacts to produce physically consistent results.

### 2.2 HydroATLAS Basin Delineation

Catchment areas are derived from WWF HydroATLAS v1 (Linke et al., 2019), a
global dataset of sub-basin delineations based on:

- HydroSHEDS flow direction grids (Lehner et al., 2008)
- SRTM 3-arcsecond DEM
- Validated against national hydrographic databases

HydroATLAS provides nested basin polygons at 12 hierarchical levels (01-12).
For v11, we use the finest available level where both culverts fall within
distinct basins (typically level 10 or 12).

**Key attribute:** `SUB_AREA` (km2) — the sub-basin area that drains to each
basin outlet. This replaces the estimated 30/20 km2 values used in v10.

### 2.3 Basin-Scale Rainfall from IMERG

Instead of computing rainfall only over the simulation domain, v11 downloads
IMERG precipitation over the **full basin polygon extent**. This is critical
in arid environments where:

- Storms are highly localized (convective cells ~10-20 km diameter)
- Upstream rainfall may be intense while the domain itself remains dry
- Runoff from bare, crusted soil can travel 100+ km through ephemeral channels
  (wadis) with minimal transmission losses during intense events

The basin-mean IMERG rainfall is computed using GEE `reduceRegion` with the
actual basin polygon, providing a spatially averaged intensity that accounts
for rainfall distribution across the entire catchment.

### 2.4 Rational Method Hydrograph

The rational method is applied at basin scale:

```
Q(t) = C_eff × I_basin(t) × A_basin
```

Where:
- `C_eff` = effective runoff coefficient (0.30 base, calibrated up to 0.80)
- `I_basin(t)` = basin-average IMERG rainfall intensity (m/s) at time t
- `A_basin` = HydroATLAS-derived catchment area (m2)

The instantaneous runoff is convolved with a triangular unit hydrograph whose
time of concentration is estimated empirically from catchment area:

```
t_c = 0.3 × A^0.4  (hours, A in km2)
```

### 2.5 Runoff Coefficient Calibration

The base runoff coefficient (C = 0.30) represents average conditions for arid
terrain. During extreme flash flood events, effective C values can be
significantly higher:

| Surface type | C range (literature) | Reference |
|---|---|---|
| Bare crusted soil | 0.50 – 0.90 | Wheater et al. (2008) |
| Rocky desert | 0.60 – 0.85 | Morin & Yakir (2014) |
| Sparse vegetation | 0.30 – 0.60 | Pilgrim et al. (1988) |
| Urban areas | 0.70 – 0.95 | ASCE (2017) |

v11 applies a calibration factor to the hydrograph if the raw peak flow is
insufficient to generate observed flooding depths. The effective C is capped
at 0.80 — a physically defensible upper bound for arid catchments during
extreme events.

## 3. Workflow

### 3.1 Prerequisites

Run watershed delineation first:
```bash
cd /data/rim2d/nile_highres
micromamba run -n zarrv3 python delineate_watershed_v10.py
```

This produces:
- `v10/input/watersheds/watershed_summary.json` — catchment areas per level
- `v10/input/watersheds/*.geojson` — basin polygon files

### 3.2 Generate Hydrograph + Simulation Files

```bash
micromamba run -n zarrv3 python run_v11_synthetic_flood.py
```

Outputs to `v11/`:
- `input/fluvbound_mask_v11.nc` — boundary mask (same cells as v10)
- `input/inflowlocs_v11.txt` — WSE timeseries with basin-derived hydrograph
- `input/culvert_hydrographs_v11.npz` — flow data for visualization
- `input/v11_metadata.json` — metadata (areas, calibration, etc.)
- `simulation_v11.def` — RIM2D definition file

### 3.3 Run Simulation

```bash
cd v11
../../bin/RIM2D simulation_v11.def --def flex
```

### 3.4 Visualize

```bash
cd /data/rim2d/nile_highres
micromamba run -n zarrv3 python visualize_v11.py --inputs
micromamba run -n zarrv3 python visualize_v11.py --results
```

## 4. Comparison with v10

| Aspect | v10 | v11 |
|---|---|---|
| Catchment area source | Estimated (30/20 km2) | HydroATLAS (scientific) |
| Rainfall extent | Domain only (11x9 km) | Full basin polygon |
| Domain-mean rainfall | 18.2 mm | Same (unchanged) |
| Basin-mean rainfall | N/A | Computed per catchment |
| Peak culvert flow | ~3.9 m3/s | Expected 25-200+ m3/s |
| Building flooding | 0 buildings wet | Target ~0.6m depth |
| Calibration | None | Observation-constrained C |
| Simulation domain | 386x297, ~30m | Same (no change) |

## 5. Verification Criteria

1. **Watershed containment**: Culvert points lie within basin polygons at all
   HydroATLAS levels
2. **Rainfall capture**: Basin-average rainfall exceeds domain-average rainfall
   (confirms upstream storm contribution)
3. **Pressurized flow**: Peak culvert flow exceeds full-pipe capacity (2.5 m3/s)
   during main events
4. **Building flooding**: Buildings inundated to ~0.6 m depth (matching
   anecdotal 2-foot observation)
5. **Railway impact**: High velocity/depth at the railway embankment area
   consistent with structural washout

## 6. Data Sources

All inputs are from publicly available datasets:

- **DEM**: Copernicus GLO-30 (ESA, 30m resolution)
- **Rainfall**: GPM IMERG V07 (NASA, 0.1°, 30-min)
- **Basins**: WWF HydroATLAS v1 (Linke et al., 2019)
- **Land cover**: ESA WorldCover 2021 (10m)
- **Buildings**: Overture Maps Foundation (2024)
- **Built surface**: GHSL 2020 (100m)

## 7. References

- Linke, S., et al. (2019). Global hydro-environmental sub-basin and river reach
  characteristics at high spatial resolution. *Scientific Data*, 6, 283.
- Morin, E., & Yakir, H. (2014). Hydrological impact and potential flooding of
  convective rain cells in a semi-arid environment. *Hydrol. Sci. J.*, 59, 1353-1364.
- Pilgrim, D.H., et al. (1988). Problems of rainfall-runoff modelling in arid and
  semiarid regions. *Hydrol. Sci. J.*, 33, 379-400.
- Wheater, H.S., et al. (2008). Hydrological processes in arid and semi-arid areas.
  *Hydrological Modelling in Arid and Semi-Arid Areas*, Cambridge University Press.
- WMO (2015). WMO Guidelines on Multi-hazard Impact-based Forecast and Warning
  Services. WMO No. 1150.
