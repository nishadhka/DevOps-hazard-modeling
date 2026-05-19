# New-direction run: gridded soil-moisture output for WRSI (RWA validation)

Status: **validated** — Rwanda (`dr_case6`) re-run with Wflow.jl producing a
gridded NetCDF, used to derive the Water Requirement Satisfaction Index (WRSI).

## 1. Why a new direction

The original 11 case runs wrote **only a basin-mean CSV** (`[output.csv]`):
discharge + basin-average soil moisture per layer. WRSI is a *spatial,
per-pixel, season-accumulated* index, so the basin-mean CSV cannot produce it.
The new direction is to additionally enable Wflow's gridded NetCDF output
(`[output.netcdf_grid]`) with the variables WRSI needs.

This validation re-runs the already-built Rwanda case (inputs read-only by
absolute path; original `dr_case6/data/output/` left untouched) and writes a
fresh gridded file to `runs/rwa_wrsi/output/`.

## 2. The Julia / Wflow.jl version issue (recorded)

The first attempt **hung for >55 minutes at 100 % CPU and never produced
output**. Diagnosis from process inspection:

| Evidence | Reading |
|---|---|
| CPU time ≈ wall time (3306 s / 3308 s) | pure compute, ~zero I/O wait |
| `voluntary_ctxt_switches` = 602 (vs 16 240 non-vol) | not blocking on I/O, not deadlocked |
| `staticmaps.nc` + `forcing.nc` open, **`output_grid_wrsi.nc` never created** | stuck in **model setup, before the timestep loop** |
| memory flat ~1.2 GB | not a leak / OOM |

Root cause: **Julia 1.12.6 was installed (juliaup "release"), but Wflow.jl
v1.0.1 declares `julia = "1.10"` in `[compat]`** and was only tested on the
1.10 LTS. Julia 1.12 reworked compiler internals; Wflow's heavy use of
`Polyester` / `StaticArrays` / `Accessors` / generated functions triggered a
first-call JIT-compilation blow-up *before* timestepping. It was **not** the
output configuration, the data, or WRSI.

### Fix

1. Killed the stuck process.
2. `juliaup add 1.10` → Julia **1.10.11**.
3. Removed the 1.12-generated `Manifest.toml`; `Pkg.resolve()` +
   `Pkg.instantiate()` under 1.10. The resolver moved **Wflow v1.0.1 →
   v1.0.2** (a patch release in the same 1.0.x line; API- and
   result-compatible, includes newer-Julia compatibility fixes).
4. Re-ran with `julia +1.10 --project=julia_env`.

Result: **completed in 17 min 59 s** (vs the original `dr_case6` 25 min 17 s;
faster here due to 4 threads + this VM), gridded NetCDF written incrementally
per timestep exactly as designed.

**Pin for all future runs:** Julia **1.10.x**, Wflow **v1.0.2**. Do not use
the juliaup "release" channel for these runs.

## 3. Run configuration

`runs/rwa_wrsi/case_sbm_wrsi.toml` — identical physics to the original
`dr_case6/case_sbm.toml` (same staticmaps/forcing, period 2016-01-01 →
2017-12-31, 3 soil layers `[100,300,800]` mm), plus:

```toml
[output.netcdf_grid]
path = "output_grid_wrsi.nc"
compressionlevel = 1

[output.netcdf_grid.variables]
soil_layer_water__volume_fraction              = "vwc_layer"     # 3-D per layer
soil_water_root_zone__volume_fraction          = "vwc_rootzone"  # primary WRSI input
soil_water__transpiration_volume_flux          = "transpiration" # AETc component
land_surface__evapotranspiration_volume_flux   = "aet"           # total actual ET
land_surface_water__potential_evaporation_volume_flux = "pet"    # WRc denominator
```

Reproduce:

```bash
cd runs/rwa_wrsi
JULIA_NUM_THREADS=4 julia +1.10 \
  --project=../../julia_env \
  -e 'using Wflow; Wflow.run("case_sbm_wrsi.toml")'
```

## 4. Output verification

`output_grid_wrsi.nc` — 362 MB, 730 daily steps, grid 212 × 234, layer = 4
(Wflow's internal Brooks–Corey 4-layer expansion of the 3-layer config).

| Variable | Dims | Range | Mean | Valid |
|---|---|---|---|---|
| `vwc_rootzone` | (time, lat, lon) | 0.067–0.55 | 0.42 | 100 % |
| `vwc_layer` | (time, layer, lat, lon) | 0.052–0.55 | 0.43 | 58.6 %* |
| `transpiration` | (time, lat, lon) | 0–7.27 | 0.77 | 100 % |
| `aet` | (time, lat, lon) | 0–8.68 | 1.38 | 100 % |
| `pet` | (time, lat, lon) | 0–8.68 | 2.18 | 100 % |

\*NaN outside the catchment mask + absent deep layers in shallow-soil cells.
Units: VWC = m³/m³; ET fluxes = mm/day.

## 5. WRSI calculation from the gridded dataset

WRSI (FAO/USGS) compares seasonal actual crop water use to the crop water
requirement:

> **WRSI = 100 × Σ_season AETc / Σ_season WRc**

with WRc = Kc·PET (crop water requirement) and AETc the actual crop ET.

This validation uses the **water-balance form with Kc = 1**, i.e.

> **WRSI = 100 × Σ AET / Σ PET**

computed per pixel and accumulated over the period (and per calendar year).
This needs no crop calendar and is directly supported by the gridded `aet`
and `pet` from Wflow. FAO interpretation classes:

| WRSI | Class |
|---|---|
| ≥ 80 | no / minimal stress |
| 50–79 | water stress |
| < 50 | crop-failure likelihood |

`script: shared/hydrobasins/wrsi_analysis.py` reads
`output_grid_wrsi.nc`, computes the WRSI grid + a basin-mean dekadal
cumulative series, and writes:

- `wrsi/rwa_wrsi_grid.nc` — per-pixel WRSI (whole period + per year)
- `wrsi/rwa_original_output.png` — the raw Wflow basin-mean series
  (vwc_rootzone, transpiration, aet, pet, Q)
- `wrsi/rwa_wrsi_output.png` — the derived WRSI: spatial map(s) + the
  dekadal cumulative basin-mean WRSI with FAO class bands

### Known simplifications / future work

- **Kc = 1** (water-balance WRSI). A crop-specific FAO Kc curve + planting
  calendar (Rwanda Season A Sep–Jan, Season B Feb–Jun) would give the true
  agronomic WRSI. `thetaR`/`thetaS`/`RootingDepth` are present in the
  staticmaps for the soil-water-stress (Ks) refinement.
- Season windows here are calendar-year; replace with the agronomic season
  for operational use.
- Whole-catchment (no cropland mask). Masking to cropland (ESA WorldCover)
  would localise WRSI to agricultural pixels.
