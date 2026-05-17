# Wflow.jl Drought Simulation — Running Workflow

Living document for the end-to-end Wflow.jl SBM workflow behind the 11 ICPAC
East-Africa drought cases: basin selection → model build → simulation →
gridded NetCDF → WRSI. Updated as the work progresses.

Heavy/generated artifacts (PNGs, GeoJSONs, NetCDFs, run outputs) are published
to the HuggingFace dataset `E4DRR/wflow.jl-simulations`; only code + docs live
in this (public) git repo.

---

## 1. Basin selection with HydroBASINS → v4

The case domains evolved through four iterations, each published to HF under
`hydrobasins/`:

| Ver | Method | Outcome |
|----|--------|---------|
| v1 | Walk upstream from each case outlet through HydroBASINS `NEXT_DOWN`; smart-snap to the polygon whose upstream area best matches the storyline | First contributing-area polygons; exposed bad/missing outlet coords |
| v2 | CDI (Combined Drought Indicator) overlay + HydroBASINS lvl 4/5/6 boundary plots with `HYBAS_ID` labels for manual sub-basin picking | Tooling to choose the right unit per event |
| v3 | One **recommended** drainage system per event (analyst table), `basin` (BFS upstream) vs `unit` (single tile) modes, area sanity vs the recommendation | 11 single-basin selections, ratios 0.6–2.3× |
| **v4** | Reviewed corrections: BDI→Ruvubu (south), ERI→Anseba/Red-Sea (east, lev-6), SSD→Bahr el Ghazal (SSD-internal, no Uganda), SDN→Lower Blue Nile, TZA→Pangani | **Current.** All 11 within 0.6–1.5× of target |

**v4 artifacts per event** (`shared/hydrobasins/v4_recommended.py` → HF
`hydrobasins/v4/`):

- `<ev>_v4.geojson` — the **hydrobasin bounding box** (5-vertex rectangle).
  This is the *run extent*: what the model domain is built/clipped to.
- `<ev>_v4_basin.geojson` — the detailed basin polygon. Used only as the
  final **WRSI spatial mask**.
- `<ev>_v4.png` — basin + bbox run-extent; `overview_v4.png` — all 11.

Why a bbox and not the polygon for the run: a rectangular domain is what the
gridded model is built on; the basin polygon is applied afterwards to mask
the WRSI result to the true catchment shape.

## 2. Wflow.jl install & configuration (toolchain pin)

Julia is installed via `juliaup`. **Critical version pin:**

- **Julia 1.10.x** (currently 1.10.11). Wflow.jl v1.0.x declares
  `julia = "1.10"`. On Julia 1.12 the first `Wflow.run()` enters a
  **JIT-compilation hang**: it sits at ~100 % CPU in model *setup* (before
  the timestep loop, no output NetCDF ever created) for >55 min. Same TOML,
  same data, runs fine in ~18 min on 1.10. **Do not use the juliaup
  `release` channel for these runs.**
- **Wflow v1.0.2**, pinned in `julia_env/Project.toml` (a patch over the
  1.0.1 the original cases used; resolves the newer-Julia compatibility,
  results compatible).

Run a model:

```bash
JULIA_NUM_THREADS=4 julia +1.10 \
  --project=julia_env \
  -e 'using Wflow; Wflow.run("case.toml")'
```

Wflow SBM is largely single-threaded; 4 threads gives a sub-linear (~3–4×)
speed-up, not 4×.

## 3. Gridded NetCDF output + the WRSI routine

The original case runs wrote a **basin-mean CSV only** (`[output.csv]`) —
discharge + per-layer mean soil moisture. WRSI is spatial and
season-accumulated, so the CSV can't produce it. The new direction adds:

```toml
[output.netcdf_grid]
path = "output_grid_wrsi.nc"
compressionlevel = 1

[output.netcdf_grid.variables]
land_surface__evapotranspiration_volume_flux          = "aet"
land_surface_water__potential_evaporation_volume_flux = "pet"
# (optionally: soil_water_root_zone__volume_fraction, per-layer VWC,
#  vegetation transpiration — for the soil-water-stress WRSI form)
```

WRSI (water-balance form, Kc = 1):

> **WRSI = 100 × Σ_period AET / Σ_period PET**, per pixel, accumulated over
> the event period (and per calendar year), then masked to
> `<ev>_v4_basin.geojson`. FAO classes: ≥80 no/low stress, 50–79 stress,
> <50 crop-failure likelihood.

Wflow writes the NetCDF incrementally per timestep. The 2-variable
(`aet`+`pet`) "WRSI-minimal" output keeps files small (a few MB even for the
largest v4 bbox at 1 km) and adds negligible runtime over CSV-only.

Validation (`shared/hydrobasins/wrsi_analysis.py`, `wrsi_batch.py`):

- **RWA** reproduced the documented 2016 drought (mean WRSI **64.8**, 19 %
  crop-failure) vs the 2017 recovery (**86.5**, 68 % no-stress).
- **BDI** 61.1 (93 % stress) and **UGA** 43.3 (68 % failure) independently
  tracked their 2021–22 droughts.
- **DJI** ≈ 3 — degenerate: WRSI is a cropland index; an arid endorheic
  basin needs a cropland mask (future work).
- **ERI** still fails the documented `dr_case3` staticmaps `BoundsError`
  (a soil-layer-index data bug, **not** version-related; v1.0.2 didn't fix
  it — needs a staticmaps repair).

## 4. Model build for the v4 domain (fresh static maps)

Rather than subset/clip the old country-extent staticmaps (which breaks the
lateral drainage network at the cut edges), a **new model is built per v4
bounding box**. Pipeline per case:

1. **10 input GeoTIFFs** at 1 km for the v4 bbox (see §5).
2. `derive_staticmaps.py` → `staticmaps.nc` (81 SBM variables).
3. `fix_ldd_pyflwdir.py` → repair LDD cycles.
4. Forcing: CHIRPS (precip) + ERA5 (PET, temp) → `forcing.nc` resampled to
   the staticmaps grid.
5. Run (§2) → gridded NetCDF → WRSI (§3).

The 10 TIFFs and the variables `derive_staticmaps.py` expects:

| TIFF | Source | Notes |
|------|--------|-------|
| `1_elevation_merit_1km` | MERIT-Hydro `elv` | hydrologically consistent with dir/upa |
| `2_landcover_esa_1km` | ESA WorldCover v200 | class codes |
| `3_soil_{sand,silt,clay}_1km` | SoilGrids `*_mean` | renormalised in derive |
| `4_soil_rootzone_depth_1km` | soil-column proxy | used as SoilThickness |
| `5_soil_ksat_1km` | Cosby pedotransfer (sand/clay) | clipped 1–5000 mm/day |
| `5_soil_porosity_1km` | 1 − bulk-density/2.65 | texture fallback if implausible |
| `6_river_flow_{direction,accumulation}_1km` | MERIT-Hydro `dir`/`upa` | D8 + km² |

Big daily NetCDFs and the per-case model inputs are stored on the 280 GB
secondary volume, not in the repo or on the small home disk.

## 5. Source data via Google Earth Engine

The 10 TIFFs are exported from Google Earth Engine
(`shared/hydrobasins/gee_export_tiffs.py`). GEE clips and resamples global
collections (MERIT-Hydro, ESA WorldCover, SoilGrids) to 1 km **server-side**
and returns small per-bbox GeoTIFFs — no multi-tens-of-GB global download.
At 1 km even the largest v4 bbox is a few MB per band, so a single
`getDownloadURL` per layer suffices (no tiling).

**Earth Engine auth — and the service-account secret:**

- Authentication uses a Google service account that is *legacy
  EE-registered*. Initialise with
  `ee.Initialize(ee.ServiceAccountCredentials(email, key))` **without** a
  `project=` argument — passing `project=` triggers a Cloud
  `serviceusage.services.use` permission check that fails (it is **not** an
  IAM grant problem; the bare init works).
- **SECURITY: the service-account JSON must never be committed.** This repo
  is public. The key is referenced only by a path:
  - default: `wflow-jl/.secrets/ee-service-account.json` (the `.secrets/`
    directory and all `*.json` / `*service-account*.json` are gitignored
    repo-wide),
  - or override via the env var `EE_SERVICE_ACCOUNT_KEY`.
  No key material is embedded in any script — only a path reference.

## 6. Status

- ✅ v4 basin selections finalised, reviewed, on HF (`hydrobasins/v4/`).
- ✅ Wflow.jl toolchain validated (Julia 1.10 / Wflow v1.0.2; RWA WRSI).
- ✅ WRSI routine validated (RWA/BDI/UGA track documented droughts).
- ✅ GEE access verified; 10-TIFF exporter built + validated on BDI.
- ⏭️ Next: parameterise the staticmaps/LDD driver, run Phase-1
  (export → staticmaps → fix_ldd) for all 11 v4 bboxes, then forcing + runs.
- ⚠️ ERI needs a staticmaps `BoundsError` fix (data bug, independent of the
  build pipeline).

## Script map (`shared/hydrobasins/`)

| Script | Role |
|--------|------|
| `v4_recommended.py` | v4 basin selection → bbox + basin geojson + plots |
| `gee_export_tiffs.py` | GEE → 10 input TIFFs per v4 bbox |
| `wrsi_analysis.py` | WRSI from a gridded run (single case) |
| `wrsi_batch.py` | WRSI over multiple built cases, v4-clipped |
| `wrsi_v4_run.py` | bbox-subset run + WRSI for a v4 case |
| `upload_to_hf.py` | publish artifacts to the HF dataset |
