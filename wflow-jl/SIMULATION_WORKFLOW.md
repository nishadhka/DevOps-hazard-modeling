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

## 4. Model build for the v4 domain — use `../hazard-model-api/`

**Do not write a bespoke exporter.** The repo already ships a canonical,
region-agnostic download/prepare pipeline in **`../hazard-model-api/`** (flat,
`--bbox`-driven, idempotent, `--dry-run` size estimates). It is the single
source of truth for building model inputs for *any* bbox; the v4 build just
feeds it each case's v4 bounding box. (An earlier session script,
`gee_export_tiffs.py`, duplicated this and has been removed.)

Rather than subset/clip the old country-extent staticmaps (which breaks the
lateral drainage network at the cut edges), a **new model is built per v4
bounding box**. Per case, with `BBOX` = the `<ev>_v4.geojson` bounds and
`OUT` on the 280 GB secondary volume:

```bash
cd ../hazard-model-api
# 1. base 1 km grids (GEE)
python download_dem.py        --bbox "$BBOX" --out "$OUT" --scale 1000 --target merit
python download_worldcover.py --bbox "$BBOX" --out "$OUT" --scale 1000
python download_merit_hydro.py --bbox "$BBOX" --out "$OUT"
python download_soilgrids.py  --bbox "$BBOX" --out "$OUT" --scale 1000
# 2. forcing — SINGLE SOURCE: ERA5 zarr (precip + temp + PET in one
#    dataset). CHIRPS is dropped — a single forcing source removes the
#    CHIRPS↔ERA5 grid/units reconciliation and keeps provenance simple.
#    (Phase deferred; static maps built first.)
# python download_era5.py  --bbox "$BBOX" --out "$OUT" --start "$START" --end "$END"
# 3. staticmaps + LDD fix
python prepare_wflow_staticmaps.py --bbox "$BBOX" --out "$OUT"
python fix_ldd_pyflwdir.py         --staticmaps "$OUT/staticmaps.nc"
# 4. run (see §2): julia +1.10 --project=julia_env ... ; then WRSI (§3)
```

`prepare_wflow_staticmaps.py` reads a documented `<out>/tif/` contract
(`dem.tif`, `worldcover_classes.tif`, `merit_dir_90m.tif`, `merit_upa_90m.tif`,
`soil_{sand,silt,clay}_250m.tif`, optional `soil_bedrock_depth_250m.tif`),
applies its own pedotransfer (thetaS/thetaR from texture), and writes
`staticmaps.nc` (80+ SBM variables) on the MERIT 1 km grid. The per-case
inputs + big daily NetCDFs live on the 280 GB secondary volume, not in the
repo or the small home disk.

See `../hazard-model-api/README.md` → "Workflow: prepare a Wflow case" for
the authoritative command list and per-source size table.

## 5. Source data via Google Earth Engine — auth & the secret

The `hazard-model-api` GEE scripts (`download_dem/worldcover/merit_hydro/`
`soilgrids/era5`) clip + resample global collections (MERIT-Hydro, ESA
WorldCover, SoilGrids, ERA5-Land) to the target grid **server-side** and
return small per-bbox GeoTIFFs — no multi-tens-of-GB global download. At
1 km even the largest v4 bbox is a few MB per band. `getDownloadURL` has a
50 MB/image cap; scripts tile internally when needed.

**Earth Engine auth — and the service-account secret:**

- `common.init_ee()` uses `ee.ServiceAccountCredentials(email, key)` then
  `ee.Initialize(credentials=creds)` **without** a `project=` argument.
  Passing `project=` triggers a Cloud `serviceusage.services.use` check that
  fails for this account — it is **not** an IAM-grant problem; the bare
  init works (verified: authenticates as the EE service account).
- Key is supplied via `--sa-key PATH` or the env var **`GEE_SA_KEY`**.
- **SECURITY — this repo is public; the service-account JSON must never be
  committed.** Local copy lives at the gitignored
  `wflow-jl/.secrets/ee-service-account.json`; `.secrets/`, `*.json`, and
  `*service-account*.json` are gitignored repo-wide. No key material is
  embedded in any script — only `--sa-key`/`GEE_SA_KEY` path references.

```bash
export GEE_SA_KEY=$PWD/wflow-jl/.secrets/ee-service-account.json
```

## 6. Status

- ✅ v4 basin selections finalised, reviewed, on HF (`hydrobasins/v4/`).
- ✅ Wflow.jl toolchain validated (Julia 1.10 / Wflow v1.0.2; RWA WRSI).
- ✅ WRSI routine validated (RWA/BDI/UGA track documented droughts).
- ✅ GEE access verified (canonical `hazard-model-api/common.init_ee` +
  our `.secrets` key; `download_dem.py --dry-run` on the BDI v4 bbox OK).
- ✅ Build method aligned to `../hazard-model-api/` (bespoke exporter
  removed).
- ✅ **All 11 v4 static maps built** via `build_v4_models.py` (static-only;
  forcing deferred). `/mnt/wflow-secondary/v4_models/<iso>/staticmaps.nc`,
  uniform `layer=4`, 23 SBM vars, grids matching the v4 bboxes:

  | case | size | grid (lat×lon) | | case | size | grid |
  |---|---|---|---|---|---|---|
  | BDI | 3.1 M | 171×158 | | SDN | 28 M | 591×420 |
  | DJI | 3.5 M | 180×174 | | ETH | 84 M | 928×815 |
  | ERI | 3.4 M | 142×210 | | SSD | 112 M | 1235×818 |
  | RWA | 3.6 M | 186×173 | | SOM | 136 M | 1119×1096 |
  | TZA | 9.4 M | 289×291 | | UGA | 11 M | 372×245 |
  | KEN | 20 M | 393×446 | | | | |

  Includes SOM/SSD/SDN — previously "planned" with **no inputs at all**;
  the fresh GEE build gives all 11 domains static maps. Two canonical-
  pipeline bugs fixed en route: `download_dem.py` merit target now writes
  `dem.tif` at 1 km (was 90 m); `common.download_ee_tif` now tiles over
  the GEE 48 MB `getDownloadURL` cap (was failing 7/11 large bboxes).
- 🔀 **Forcing detour — single source, ERA5 zarr only.** Drop CHIRPS;
  use the ERA5 zarr (total precipitation + 2 m temperature + potential
  evaporation in one store) as the sole forcing input. Rationale: one
  source removes the CHIRPS↔ERA5 grid/units/calendar reconciliation and
  keeps forcing provenance single and auditable. ERA5 covers all three
  Wflow SBM forcing fields. (Pending implementation.)
- ⏭️ Next: (a) ERA5-zarr forcing → `forcing.nc` per v4 grid/period;
  (b) wflow run (Julia 1.10 / Wflow v1.0.2) → gridded NetCDF → WRSI
  clipped to `_v4_basin.geojson`.
- ⚠️ ERI needs a staticmaps `BoundsError` fix (soil-layer-index data bug,
  independent of the build pipeline; surfaces at wflow run time).

## Script map

Build inputs — **`../hazard-model-api/`** (canonical, region-agnostic;
see its README). This folder (`wflow-jl/shared/hydrobasins/`):

| Script | Role |
|--------|------|
| `v4_recommended.py` | v4 basin selection → bbox + basin geojson + plots |
| `wrsi_analysis.py` | WRSI from a gridded run (single case) |
| `wrsi_batch.py` | WRSI over multiple built cases, v4-clipped |
| `wrsi_v4_run.py` | bbox-subset run + WRSI for a v4 case |
| `upload_to_hf.py` | publish artifacts to the HF dataset |
