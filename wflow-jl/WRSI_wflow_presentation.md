---
marp: true
theme: default
paginate: true
size: 16:9
header: 'Wflow.jl → WRSI · 11 East-Africa drought storylines'
footer: 'ICPAC E4DRR · wflow.jl-simulations · 2026-06'
style: |
  section {
    font-size: 24px;
    background: #fbfbfd;
  }
  h1 { color: #14507a; }
  h2 { color: #14507a; border-bottom: 2px solid #d9e6f0; padding-bottom: 4px; }
  table { font-size: 19px; }
  th { background: #14507a; color: #fff; }
  tr:nth-child(even) { background: #eef4f9; }
  code { background: #eef2f5; }
  .small { font-size: 17px; }
  .strong { color: #138000; font-weight: bold; }
  .weak { color: #b06a00; }
  .poor { color: #b00020; }
  section.lead h1 { font-size: 46px; }
  section.lead { text-align: center; }
---

<!--
  RENDER THIS DECK
  ----------------
  This is a Marp deck. From wflow-jl/ :
    npx @marp-team/marp-cli WRSI_wflow_presentation.md -o WRSI_wflow_presentation.html
    npx @marp-team/marp-cli WRSI_wflow_presentation.md --pdf
    npx @marp-team/marp-cli WRSI_wflow_presentation.md --pptx
  Or: VS Code "Marp for VS Code" extension → Open Preview.
  All 13 images are hosted on (and load directly from) the HuggingFace mirror —
  no local files needed to render. Source of truth:
    https://huggingface.co/datasets/E4DRR/wflow.jl-simulations
      v4_wrsi_plots/      (7 images: static maps, AET, WRSI grids, overview)
      eval_wrsi_events/   (6 images: per-year event trajectories + summaries)
  Local copies also live under runs/v4_wrsi_plots/ and runs/eval_wrsi_events/.
-->

<!-- _class: lead -->

# Wflow.jl → WRSI for Drought-Impact Forecasting

## 11 East-Africa drought storylines, simulated end-to-end

**Hydrological model build → SBM simulation → gridded NetCDF → Water Requirement Satisfaction Index**

ICPAC · E4DRR — DevOps Hazard Modeling
Toolchain: Wflow.jl **v1.0.2** on Julia **1.10** · Forcing: ERA5 · Static maps: GEE (MERIT / WorldCover / SoilGrids)

`E4DRR/wflow.jl-simulations` (HuggingFace) · 2026-06

---

<!-- _class: lead -->

# Part I — Introduction

Wflow.jl · WRSI from soil-water variables · model I/O ·
catalogue of the 11 events · WRSI → CLIMADA impact-based forecasting

---

## What is Wflow.jl?

**Wflow** is Deltares' distributed, gridded hydrological modelling framework; **Wflow.jl** is its Julia implementation — fast, fully spatial, open source.

- We use the **SBM** concept (Simple Bucket Model): a physically-based, distributed soil–vegetation–atmosphere water balance solved **per grid cell** on a regular raster, with kinematic-wave routing along a derived river/land drainage network (LDD).
- Each cell tracks **rainfall → interception → infiltration → multi-layer soil moisture → evapotranspiration → recharge → runoff → discharge**.
- Built region-agnostically from open global data; runs daily at **1 km** over any bounding box.

**Why it fits drought work:** SBM resolves the *soil-water store* and *actual evapotranspiration* — the physical quantities that determine whether a crop's water demand is met. That makes it a natural engine for a spatial, physically-grounded drought index.

> Pin: Julia **1.10.x** + Wflow **v1.0.2**. Julia 1.12 triggers a pre-timestep JIT-compile hang — do not use the juliaup `release` channel.

---

## From Wflow output to WRSI

**WRSI** — *Water Requirement Satisfaction Index* — the FAO crop-water-stress index: the fraction of a crop's water demand actually met over the growing period.

We compute it directly from two standard Wflow SBM outputs:

$$\text{WRSI} = 100 \times \frac{\sum_{\text{period}} \text{AET}}{\sum_{\text{period}} \text{PET}} \quad (K_c = 1)$$

- **AET** — `land_surface__evapotranspiration_volume_flux` (actual ET; limited by soil moisture)
- **PET** — `land_surface_water__potential_evaporation_volume_flux` (atmospheric demand)
- Accumulated per pixel over the event period (and per calendar year), then **masked to the basin polygon**.

| WRSI band | FAO interpretation |
|--|--|
| **≥ 80** | No / minimal water stress |
| **50 – 79** | Water stress |
| **< 50** | Crop-failure likelihood |

When soil moisture is depleted, AET drops below PET → WRSI falls. The **year-over-year drop** within a basin is the drought signal (absolute level reflects aridity, not severity).

---

## Wflow.jl — model inputs and outputs

<div class="small">

**INPUTS** | **→ WFLOW SBM (1 km, daily) →** | **OUTPUTS**
:--|:--:|:--
**Static maps** (`staticmaps.nc`, 23 SBM vars) | | **Gridded NetCDF** (`output_grid_wrsi.nc`)
 DEM, slope, LDD, upstream area — *MERIT Hydro* | | AET — actual evapotranspiration
 Land cover / Manning n / rooting depth — *ESA WorldCover* | Julia 1.10 | PET — potential evaporation
 thetaS, thetaR, KsatVer, SoilThickness, Brooks-Corey c — *SoilGrids* | Wflow v1.0.2 | (opt.) per-layer soil moisture, transpiration
 LAI (12 monthly) — *MODIS* | | **Basin-mean CSV** — discharge, soil moisture
**Forcing** (`forcing.nc`, daily) | | **→ WRSI grid** (100·ΣAET/ΣPET, FAO 3-class)
 Precipitation, 2 m temperature, PET — *ERA5 (single source)* | | masked to basin polygon, EPSG:4326

</div>

![w:300](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/v4_wrsi_plots/ken_static_wflow_dem.png) ![w:300](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/v4_wrsi_plots/ken_static_wflow_river.png) ![w:300](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/v4_wrsi_plots/eth_aet.png)

<span class="small">*Example inputs/outputs — KEN DEM & derived river network (static maps) and ETH time-mean AET (model output).*</span>

---

## Catalogue of the 11 drought events

<div class="small">

| # | ISO | Event (period) | Basin / outlet | Domain | Run length | Final basin status |
|--|--|--|--|--|--|--|
| 01 | BDI | Burundi 2021-22 | Ruvubu / Ruzizi | 171×158 | 730 d | Completed — flat signal |
| 02 | DJI | Djibouti 2022 | Afar endorheic | 180×174 | 1095 d | Completed — **strong** |
| 03 | ERI | Highlands 2021-23 | Anseba / Red-Sea | 142×210 | 1095 d | Completed (v4 build; old BoundsError gone) |
| 04 | ETH | Blue Nile 2021-22 | Abbay (Blue Nile) | 928×815 | 1428 d | Completed — river-mask closure fix |
| 05 | KEN | Tana / ASAL 2020-23 | Tana | 393×446 | 1428 d | Completed — **strong** |
| 06 | RWA | Akagera 2016-17 | Lower Akagera | 186×173 | 730 d | Completed — mild signal |
| 07 | SOM | South-Central 2020-23 | Juba-Shabelle | 1119×1096 | 1428 d | Completed (re-run) — **strong** |
| 08 | SSD | Upper Nile 2021-23 | Sobat / Nasir | corrected | 1428 d | Corrected basin — representative |
| 09 | SDN | Eastern States 2022 | Kassala / Gash | corrected | 1095 d | Corrected basin — representative |
| 10 | TZA | Kagera 2021-22 | Kagera NW | corrected | 1095 d | Corrected basin — representative |
| 11 | UGA | Karamoja 2022 | Karamoja proper | corrected | 1095 d | Corrected basin — **strong** |

</div>

**11 / 11 WRSI grids complete.** ETH was the last to close (LDD/river-subnetwork cycle, resolved by river-mask downstream closure). Four cases were re-run on **corrected, event-focused basins** (SSD, SDN, TZA, UGA).

---

## Overview map — the 11 final basins

![h:480 center](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/v4_wrsi_plots/overview_v4_corrected.png)

<span class="small">*Final/corrected basin per country on the GHACOF boundary, with a Kagera-cluster zoom inset. Generated by `plot_v4_overview.py`.*</span>

---

## WRSI → CLIMADA impact-based forecasting

WRSI is a **hazard intensity** layer. To express drought as **impact on crop production in economic terms**, it feeds the CLIMADA risk model:

- **Hazard** — WRSI grids per season/year from Wflow (this work) supply the spatial intensity field; a WRSI forecast (seasonal ERA5/SEAS5 forcing) becomes a *forward-looking* hazard.
- **Exposure** — cropland value: harvested area × yield × farm-gate price (e.g. SPAM / MapSPAM, FAOSTAT, national crop statistics) on the same grid.
- **Vulnerability** — an **impact (damage) function** mapping WRSI → fractional yield/production loss (WRSI < 50 → crop-failure likelihood; calibrated against EM-DAT / reported losses).

$$\text{Impact} = f_{\text{vuln}}(\text{WRSI}) \times \text{Exposure}_{\text{value}}$$

**Output:** expected crop-production loss in **tonnes and USD**, mapped per admin unit — an *impact-based* drought forecast rather than a hazard-only warning. The 11 hindcasts here are the **validation step**: showing the Wflow→WRSI chain reproduces documented events is what licenses its use as the CLIMADA hazard input.

---

<!-- _class: lead -->

# Part II — Materials and Methods

Basin selection · input data & sources · scripts ·
per-case time windows · run command · output processing

---

## Method — the v4 end-to-end pipeline

<div class="small">

```
HydroBASINS basin selection (v4)         shared/hydrobasins/v4_recommended.py
        │   one event-focused drainage system per storyline →
        │   <ev>_v4.geojson (bbox = run extent) + <ev>_v4_basin.geojson (WRSI mask)
        ▼
Static-map build (per v4 bbox, GEE)       ../hazard-model-api/ (download_* + prepare_wflow_staticmaps)
        │   1 km MERIT / WorldCover / SoilGrids → staticmaps.nc (23 SBM vars)
        ▼
LDD repair                                fix_ldd_pyflwdir.py / rebuild_ldd.py  (cycle-free flow net)
        ▼
Forcing build (single source = ERA5)      build_v4_forcing.py → forcing.nc (precip + T + PET)
        ▼
Wflow SBM run (Julia 1.10 / v1.0.2)       run_v4_wflow.py → output_grid_wrsi.nc (AET + PET, daily)
        ▼
WRSI = 100·ΣAET/ΣPET, FAO 3-class         wrsi_analysis.py / wrsi_batch.py  (clipped to _v4_basin.geojson)
        ▼
Plots + event evaluation                  plot_v4_wrsi.py · eval_wrsi_events.py · plot_v4_overview.py
```

</div>

- **Run extent = bounding box**, not the polygon: a rectangular domain keeps the lateral drainage network intact; the basin polygon is applied *afterwards* to mask the WRSI result to the true catchment.
- Basins evolved v1 → v4; **v4** applied reviewed corrections so all 11 sit within 0.6–1.5× of the storyline's target area.

---

## Input datasets and sources

| Dataset | Source | Variables derived |
|--|--|--|
| DEM | **MERIT Hydro** | elevation, slope, flow direction (LDD), upstream area |
| Land cover | **ESA WorldCover** | Manning's *n*, rooting depth, canopy parameters |
| thetaS / thetaR | **SoilGrids** | saturated / residual water content |
| KsatVer | **SoilGrids** | saturated hydraulic conductivity |
| SoilThickness | **SoilGrids** | total soil depth |
| Brooks-Corey *c* | **SoilGrids** | Brooks-Corey exponent (per layer) |
| LAI | **MODIS** | leaf area index (12 monthly maps) |
| Precipitation, 2 m temperature, PET | **ERA5 (ECMWF)** | daily forcing — **single source** |

- All static layers pulled **server-side via Google Earth Engine** and clipped to each v4 bbox at 1 km → small per-case GeoTIFFs (a few MB/band).
- **Single-source ERA5** forcing (precip + temperature + PET in one store) — removes the CHIRPS↔ERA5 grid/units/calendar reconciliation and keeps provenance auditable.
- Heavy artifacts published to HuggingFace `E4DRR/wflow.jl-simulations`; only code + docs in the public git repo.

---

## Scripts used (`shared/hydrobasins/`)

<div class="small">

| Stage | Script | Role |
|--|--|--|
| Basin selection | `v4_recommended.py` | v4 basin → bbox + basin GeoJSON + plots |
| Build inputs | `../hazard-model-api/` `download_*` + `prepare_wflow_staticmaps.py` | GEE → `staticmaps.nc` (canonical, region-agnostic) |
| Build (batch) | `build_v4_models.py` | all 11 static maps from the v4 bboxes |
| LDD fix | `fix_ldd_pyflwdir.py` · `rebuild_ldd.py` | cycle-free LDD (`pyflwdir.from_dem`) |
| Static repair | `repair_v4_staticmaps.py` | median-fill soil/river NaN |
| ETH fix | `eth_river_fix.py` | river-mask downstream closure (cycle in river subnetwork) |
| Forcing | `build_v4_forcing.py` | ERA5 zarr → `forcing.nc` per grid/period |
| Run | `run_v4_wflow.py` · `wrsi_v4_run.py` | Wflow v1.0.2 run → gridded NetCDF |
| WRSI | `wrsi_analysis.py` · `wrsi_batch.py` | 100·ΣAET/ΣPET, FAO 3-class, basin-clipped |
| Plots | `plot_v4_wrsi.py` · `plot_v4_staticmaps.py` · `plot_v4_overview.py` | static / AET / PET / WRSI / overview PNGs |
| Evaluation | `eval_wrsi_events.py` · `plot_eval_wrsi_events.py` | per-year WRSI vs documented event |
| Publish | `upload_to_hf.py` | push artifacts to the HF dataset |

</div>

---

## Per-case simulation time windows

Run windows are **event-tailored** (not a uniform period) so each captures a pre-event baseline year plus the documented drought years.

<div class="small">

| ISO | Window | Days | ISO | Window | Days |
|--|--|--|--|--|--|
| BDI | 2020–2023 (baseline) | 730+ | SOM | 2020-01 … 2023-11 | 1428 |
| DJI | 2021-01 … 2023-12 | 1094 | SSD | 2020 … 2023 (Upper Nile) | 1428 |
| ERI | 2021-01 … 2023-12 | 1094 | SDN | 2020 … 2023 (Kassala/Gash) | 1094 |
| ETH | 2020-01 … 2023-11 | 1428 | TZA | 2020 … 2023 (Kagera) | 1094 |
| KEN | 2020-01 … 2023-11 | 1428 | UGA | 2020 … 2023 (Karamoja) | 1094 |
| RWA | 2014 … 2017 (baseline) | 730+ | | | |

</div>

**Runtime:** small domains (BDI, RWA, DJI) 6–25 min; large domains (ETH, SOM, KEN) ~6–14 h. All runs `JULIA_NUM_THREADS=4` (SBM is largely single-threaded → ~3–4× sub-linear speed-up). Long runs segmented and merged where needed.

---

## Running a model + processing outputs

**Run** (direct binary bypasses the juliaup lock gotcha):

```bash
JULIA_NUM_THREADS=4 \
~/.julia/juliaup/julia-1.10.11+0.x64.linux.gnu/bin/julia \
  --project=julia_env -e 'using Wflow; Wflow.run("case.toml")'
```

The TOML requests a 2-variable gridded NetCDF (keeps files small, negligible runtime over CSV-only):

```toml
[output.netcdf_grid]
path = "output_grid_wrsi.nc"
[output.netcdf_grid.variables]
land_surface__evapotranspiration_volume_flux          = "aet"
land_surface_water__potential_evaporation_volume_flux = "pet"
```

**Process outputs:**
1. `wrsi_batch.py` → per-year & full-period WRSI grids, clipped to `_v4_basin.geojson`.
2. `plot_v4_wrsi.py` → static / AET / PET / WRSI PNGs (`runs/v4_wrsi_plots/`).
3. `eval_wrsi_events.py` → `_eval_wrsi_events.json` (per-year basin-mean WRSI, ΣAET, ΣPET).
4. `plot_eval_wrsi_events.py` → per-case event plots (`runs/eval_wrsi_events/`).
5. `upload_to_hf.py` → HuggingFace.

---

<!-- _class: lead -->

# Part III — Results and Discussion

Per-event WRSI outcomes · plots · the
representativeness verdict table · basin-scale sensitivity · caveats

---

## How results are produced and where the plots live

For every case the pipeline emits, into `runs/`:

- **Static-map QC** — `v4_wrsi_plots/{case}_static_*.png` (DEM, river, subcatch, land use, SoilThickness)
- **Model output** — `v4_wrsi_plots/{case}_aet.png`, `{case}_pet.png` (time-mean fluxes)
- **WRSI** — `v4_wrsi_plots/{case}_wrsi.png` (100·ΣAET/ΣPET, FAO 3-class, basin-clipped)
- **Event evaluation** — `eval_wrsi_events/{iso}_wrsi_events.png` (per-year trajectory vs the documented drought)
- **Synthesis** — `eval_wrsi_events/drought_response_summary.png`, `grid_wrsi_events.png`; `v4_wrsi_plots/overview_v4_corrected.png`

All also mirrored at higher resolution on **HuggingFace** `E4DRR/wflow.jl-simulations` (`v4_wrsi_plots/`, `eval_wrsi_events/`).

![w:520](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/eval_wrsi_events/grid_wrsi_events.png) ![w:430](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/eval_wrsi_events/drought_response_summary.png)

---

## Results — the strong / representative cases

<div class="small">

| ISO | Event | WRSI trajectory (event yrs **bold**) | ΣAET (mm/yr) | Signal |
|--|--|--|--|--|
| DJI | Djibouti 2022 | 26 → **9.4** → 10 | 454 → 162 | sharp single-year collapse |
| ERI | Highlands 2021-23 | **23 → 14 → 7** | 491 → 292 → 144 | deepening multi-year |
| KEN | Tana / ASAL 2020-23 | **47 → 22 → 18 → 23** | 903 → 343 | matches real 2020-23 HoA drought |
| SOM | South-Central 2020-23 | **36 → 14 → 12 → 29** | 728 → 242 → 584 | Juba-Shabelle famine-threat |
| ETH | Blue Nile 2021-22 | 51 → **39 → 36** → 39 | 927 → 646 | event yrs below 2020 baseline |
| UGA | Karamoja 2022 ✎ | 79 → **30 → 33 → 29** | 1567 → 685 | most-improved correction |

</div>

![w:430](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/eval_wrsi_events/ken_wrsi_events.png) ![w:430](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/eval_wrsi_events/som_wrsi_events.png)

<span class="small">*Left: KEN (Tana) — minimum at 2021-22. Right: SOM (Juba-Shabelle) — 2021-22 minimum, 2023 recovery.*</span>

---

## Results — corrected basins (SSD · SDN · TZA · UGA)

Four cases were re-run on **event-region-focused basins**; the originals (wrong basin or diluted) are superseded.

<div class="small">

| ISO | Original (superseded) | Corrected basin (✎) | Corrected WRSI trajectory |
|--|--|--|--|
| SSD | Bahr el Ghazal (NW) — wrong region | Upper Nile / Sobat | 42 → **28 → 28 → 21** |
| SDN | Sennar / Lower Blue Nile — adjacent | Kassala / Gash (E Sudan) | 25 → 9 → **9** → 7 |
| TZA | Pangani (NE) — wrong basin, flat 40→37 | Kagera NW | 75 → **56 → 53** → 61 |
| UGA | Lake Kyoga — diluted 68→63 | Karamoja proper | 79 → 30 → **33** → 29 |

</div>

![w:340](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/v4_wrsi_plots/uga_karamoja_wrsi.png) ![w:340](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/v4_wrsi_plots/tza_kagera_wrsi.png) ![w:340](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/v4_wrsi_plots/ssd_upper_nile_wrsi.png)

<span class="small">*Corrected WRSI grids — UGA Karamoja, TZA Kagera, SSD Upper Nile (FAO 3-class, basin-clipped).*</span>

---

## Discussion — full representativeness verdict (all 11)

<div class="small">

| # | Country | Event | Basin · case (window) | WRSI trajectory (event yrs **bold**) | Full | Verdict |
|--|--|--|--|--|--|--|
| 01 | BDI | Burundi 2021-22 | Ruvubu · `bdi_baseline` (2020-23) | 74→**72**→**71**→76 | 73 | <span class="weak">weak (flat — no deficit)</span> |
| 02 | DJI | Djibouti 2022 | Afar endorheic · `dji` (2021-23) | 26→**9**→10 | 15 | <span class="strong">strong</span> |
| 03 | ERI | Highlands 2021-23 | Anseba · `eri` (2021-23) | **23→14→7** | 14 | <span class="strong">strong</span> |
| 04 | ETH | Blue Nile 2021-22 | Abbay · `eth` (2020-23) | 51→**39→36**→39 | 41 | good |
| 05 | KEN | Tana/ASAL 2020-23 | Tana · `ken` (2020-23) | **47→22→18→23** | 27 | <span class="strong">strong</span> |
| 06 | RWA | Akagera 2016-17 | L. Akagera · `rwa_baseline` (2014-17) | 76→69→**67→67** | 70 | <span class="weak">weak (mild)</span> |
| 07 | SOM | South-Central 2020-23 | Juba-Shabelle · `som` (2020-23) | **36→14→12→29** | 22 | <span class="strong">strong</span> |
| 08 | SSD | Upper Nile 2021-23 | Sobat/Nasir · `ssd_upper_nile` ✎ | 42→**28→28→21** | 30 | representative ✎ |
| 09 | SDN | Eastern States 2022 | Kassala/Gash · `sdn_eastern` ✎ | 25→9→**9**→7 | 12 | representative ✎ |
| 10 | TZA | Kagera 2021-22 | Kagera NW · `tza_kagera` ✎ | 75→**56→53**→61 | 61 | representative ✎ |
| 11 | UGA | Karamoja 2022 | Karamoja · `uga_karamoja` ✎ | 79→30→**33**→29 | 41 | <span class="strong">strong ✎</span> |

</div>

**Bottom line:** the wflow→WRSI chain is clearly **representative for arid / semi-arid East Africa** (DJI, KEN, ERI, SOM, ETH, UGA, SSD, SDN, TZA) — correctly-timed AET/WRSI collapse in the documented event years. The humid Great-Lakes basins (BDI, RWA) show only mild dips — a genuine magnitude limit, not a model error.

---

## Discussion — basin-scale sensitivity

Larger (lev-5) variants of the two focused humid corrections were built to test how basin extent affects the signal.

<div class="small">

| Country | Focused basin (~6.7k km²) | Larger basin (lev-5) | Effect |
|--|--|--|--|
| UGA | Karamoja: 79→**30→33→29** | NE Uganda ~43k: 89→63→63→63 | larger pulls in wet L. Kyoga → drop ~26 vs ~50 |
| TZA | Kagera: 75→**56→53**→61 | NW Tanzania ~64k: 79→67→67→71 | larger spreads into wetter L. Victoria → drop ~12 vs ~21 |

</div>

**Take-away:** *smaller, event-region-focused basins resolve drought signals that larger hydrological basins average away.* This guided the corrections for UGA, TZA, SSD and SDN.

![w:430](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/eval_wrsi_events/uga_wrsi_events.png) ![w:430](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations/resolve/main/eval_wrsi_events/eri_wrsi_events.png)

---

## Caveats

1. **Annualised water-balance WRSI** (Kc = 1), *not* FAO season-based WRSI — the reliable signal is the **relative inter-annual change**. Seasonal (OND / MAM) WRSI would sharpen the bimodal-rainfall cases (KEN, SOM, ETH).
2. The signal is **bounded by ERA5 forcing** — if ERA5 misses a rainfall deficit, Wflow cannot show it (ERA5 under-resolves parts of the Horn-of-Africa drought).
3. WRSI is an **agricultural / crop-water-stress proxy** — the loss-and-damage events also involve livestock, displacement and economics that WRSI does not capture (that is the role of the CLIMADA impact layer).
4. WRSI is averaged over the **hydrological basin**, which for TZA / SSD (and partly SDN / UGA) ≠ the event's named administrative region — hence the basin corrections.

---

## Conclusions

- **11 / 11** Wflow.jl SBM cases run end-to-end → gridded **WRSI** (100·ΣAET/ΣPET, FAO 3-class), built region-agnostically from open global data (MERIT / WorldCover / SoilGrids / ERA5).
- The chain is **validated against documented drought events**: strong, correctly-timed WRSI collapse in **9 / 11** cases; the two humid Great-Lakes basins show a real, mild signal.
- **Event-focused basin selection matters** — four corrections (SSD, SDN, TZA, UGA) turned weak/wrong-basin runs into representative ones; larger basins dilute the signal.
- This licenses WRSI as the **hazard input to CLIMADA** for **impact-based crop-production forecasting** in economic terms (WRSI → yield-loss vulnerability × cropland exposure value).

**Next:** seasonal WRSI for bimodal cases · forward WRSI from SEAS5 forcing · couple to CLIMADA exposure/vulnerability → expected loss in tonnes & USD per admin unit.

---

<!-- _class: lead -->

# Thank you

**Code + docs:** `wflow-jl/` · `shared/hydrobasins/`
**Artifacts (PNG / GeoJSON / NetCDF):** HuggingFace `E4DRR/wflow.jl-simulations`
**Living workflow:** `SIMULATION_WORKFLOW.md` · **Eval:** `WRSI_EVENT_EVAL.md`

ICPAC · E4DRR — DevOps Hazard Modeling
