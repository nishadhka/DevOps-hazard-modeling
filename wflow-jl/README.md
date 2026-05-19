# Wflow.jl Hydrological Modeling - East Africa Drought Risk Cases

Regional hydrological model builds and simulations using **Wflow.jl v1.0.2 (SBM) on Julia 1.10** for drought impact analysis across East Africa. Cases are organized by ISO country code, mirroring the rim2d repo structure.

> **End-to-end workflow** (basin selection → model build → simulation → gridded NetCDF → WRSI) is documented in **[`SIMULATION_WORKFLOW.md`](SIMULATION_WORKFLOW.md)** — the living document for this work.
>
> Heavy/generated artifacts (PNGs, GeoJSONs, NetCDFs, run outputs) are published to the HuggingFace dataset **`E4DRR/wflow.jl-simulations`**; only code + docs live in this public repo.
>
> **Toolchain pin:** Julia **1.10.x** + Wflow **v1.0.2**. Julia 1.12 causes a pre-timestep JIT-compile hang — do not use the juliaup `release` channel. **Security:** the GEE service-account JSON must never be committed (this repo is public); it is referenced from the gitignored `.secrets/` path only.

## Project Status — v4 (current)

The work has moved to the **v4** pipeline: HydroBASINS basin selection →
fresh GEE staticmaps build (`../hazard-model-api/`) → **single-source
EarthDataHub ERA5** forcing → Wflow SBM (Julia 1.10 / Wflow v1.0.2) →
gridded WRSI. This supersedes the original per-country `dr_case*`
v1.0.1 builds.

**10 / 11 v4 WRSI grids complete** (`/mnt/wflow-secondary/v4_models/<iso>/
output/output_grid_wrsi.nc`); **ETH** is the sole open case (ldd-cycle —
documented).

| | Done (10) | Open (1) |
|--|--|--|
| ISO | BDI DJI ERI KEN RWA SDN SOM SSD TZA UGA | **ETH** |

Notably v4 also delivers SOM/SSD/SDN — previously "planned" with **no
inputs at all** — and unblocked ERI (the old v1.0.1 BoundsError does not
recur on the v4 build).

**Session docs (read these for the current state):**

- [`SIMULATION_WORKFLOW.md`](SIMULATION_WORKFLOW.md) — end-to-end living workflow
- [`shared/hydrobasins/V4_BASINS.md`](shared/hydrobasins/V4_BASINS.md) — finalised per-case basin selection
- [`shared/hydrobasins/V4_RUN_OVERVIEW.md`](shared/hydrobasins/V4_RUN_OVERVIEW.md) — per-case staticmaps/forcing/run-time + ldd-method tables
- [`shared/hydrobasins/ETH_BLOCK.md`](shared/hydrobasins/ETH_BLOCK.md) — the one open case (6-method ldd block + IHU plan)

v4 pipeline scripts: `shared/hydrobasins/{v4_recommended, build_v4_models,
build_v4_forcing, repair_v4_staticmaps, rebuild_ldd, run_v4_wflow,
eth_ihu, upload_to_hf}.py`.

> The original-build details below (`dr_case*`, per-case
> `derive_staticmaps.py`, CHIRPS+ERA5) are **historical** — retained for
> provenance; the v4 pipeline above is current.

Reference: [ICPAC drought events](https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/) | [`region_configs.py`](region_configs.py)

---

## Directory Structure

```
wflow-jl/
├── README.md                    # This file
├── region_configs.py            # All 11 case configs (bbox, period, status, impact)
├── shared/                      # Shared scripts and reference data
│   ├── derive_staticmaps.py     # Generate 81 Wflow variables from GeoTIFFs
│   ├── fix_ldd_pyflwdir.py      # LDD cycle fix utility
│   ├── resample_forcing.py      # Forcing resampling utility
│   ├── docs/                    # Version testing reports and tutorials
│   └── wflow_tutorial/          # Moselle reference tutorial (sbm_config.toml)
│
├── bdi/                         # Burundi
│   ├── burundi_sbm.toml
│   └── dr_case1/
│       ├── case_sbm.toml
│       ├── scripts/
│       └── data/output/
│
├── dji/                         # Djibouti
│   └── dr_case2/
│       ├── djibouti_sbm.toml
│       ├── djibouti_small.toml
│       ├── scripts/
│       ├── logs/
│       ├── 02_Djibouti_2021_2023/   # Forcing download sub-pipeline
│       └── data/output/
│
├── eri/                         # Eritrea (blocked)
│   ├── eritrea_sbm.toml
│   ├── fix_eritrea_staticmaps.py
│   ├── docs/ERITREA_SIMULATION_STATUS.md
│   └── dr_case3/
│       ├── case_sbm*.toml           # 5 config variants tested
│       ├── scripts/
│       └── data/output/
│
├── eth/                         # Ethiopia
│   ├── complete_ethiopia_workflow.sh
│   └── dr_case4/
│       ├── ethiopia_sbm.toml
│       ├── combine_ethiopia_output.py
│       ├── scripts/             # 16 scripts (download, forcing, resample, merge)
│       ├── extent/
│       ├── forcing/
│       └── data/output/
│
├── ken/                         # Kenya
│   ├── complete_kenya_workflow.sh
│   └── dr_case5/
│       ├── kenya_sbm.toml
│       ├── scripts/
│       ├── extent/
│       ├── forcing/
│       └── data/output/
│
├── rwa/                         # Rwanda
│   └── dr_case6/
│       ├── case_sbm.toml
│       ├── scripts/
│       ├── extent/
│       └── data/output/
│
├── sdn/                         # Sudan (planned)
├── som/                         # Somalia (planned)
├── ssd/                         # South Sudan (planned)
│
├── tza/                         # Tanzania
│   └── dr_case10/
│       ├── case_sbm.toml
│       ├── scripts/
│       ├── extent/
│       └── data/output/
│
└── uga/                         # Uganda
    └── dr_case11/
        ├── case_sbm.toml
        ├── scripts/
        ├── extent/
        ├── forcing/
        ├── logs/
        └── data/output/
```

---

## Case Details

### bdi/dr_case1: Burundi (2021-2022)

- **Extent:** 28.83E–30.89E, 4.50S–2.29S | **Outlet:** Ruzizi River (29.23E, 4.50S), ~5,000 km²
- **Simulation:** 730 days, completed in ~12.5 min
- **Key finding:** 22 consecutive days of zero recharge mid-2021; discharge near-zero Jun–Aug 2021
- **Role:** First successful Wflow.jl v1.0.1 simulation; baseline for all subsequent cases

### dji/dr_case2: Djibouti (2021-2023)

- **Extent:** 41.50E–43.50E, 10.90N–12.70N | **Outlet:** 41.60E, 11.20N, ~6,316 km²
- **Simulation:** 1,095 days, completed in ~6 min
- **Impact:** 194,000 people food insecure (Oct 2022), 6.1% inflation
- **Fixes:** Brooks-Corey 4-layer workaround, LDD cycles, 518 cells thetaS=0, 6–9% forcing NaN filled

### eri/dr_case3: Eritrea (2021-2023) — BLOCKED

- **Extent:** 36.33E–43.15E, 12.40N–18.00N | Largest domain (6× Burundi)
- **Status:** Fails at first timestep with `BoundsError: attempt to access NTuple{4, Float64} at index [0]`
- **Fixes attempted (11+):** LDD dtype, LDD cycles, 40-variable verification, 3-layer/4-layer soil, thetaS (875 cells), RootingDepth zeros (3,447 cells), slope floor, snow disabled, single thread — all failed
- **5 TOML variants:** `case_sbm.toml`, `_nobc`, `_nosnow`, `_test`, `_default_c`

### eth/dr_case4: Ethiopia (2020-2023)

- **Extent:** 33.0E–48.0E, 3.0N–15.1N | Staticmaps 4.4 GB (1,671 × 1,351 cells)
- **Simulation:** 1,429 days run in 3 segments (~6 hrs each); `combine_ethiopia_output.py` merges outputs
- **Impact:** 24.1M in drought areas, 4.5M livestock deaths

### ken/dr_case5: Kenya (2020-2023)

- **Extent:** 34.0E–41.9E, 4.7S–5.0N | **Outlet:** Tana River (41.90E, 0.66N), 166,337 km²
- **Simulation:** 1,429 days, ~4.5 hrs | Largest active cell count (954,123)
- **Impact:** 4.5M food shortage, 222K children malnourished (ASAL)
- **Fixes:** LDD cycles (67,748→64,553 pits), 64,068 negative upstream area cells, 159,929 missing N_River

### rwa/dr_case6: Rwanda (2016-2017)

- **Extent:** 28.80E–30.90E, 2.90S–1.00S | **Outlet:** Akagera River (30.90E, 2.08S), 19,039 km²
- **Simulation:** 730 days, 25 min 17 sec
- **Impact:** 250,000 people affected, eastern province
- **Key role:** First case using the 4-layer Brooks-Corey workaround — **reference template** for all others

### tza/dr_case10: Tanzania (2022-2023)

- **Extent:** 29.30E–40.50E, 11.70S–1.00S | **Outlet:** Kagera River (29.30E, 3.36S), 292,488 km²
- **Simulation:** 730 days | Staticmaps 3.062 GB (1,495,104 total cells)
- **Impact:** 2.2M food shortage, 70% crop failure in northern regions

### uga/dr_case11: Uganda (2021-2022)

- **Extent:** 32.80E–34.90E, 1.00N–3.80N | **Outlet:** 32.80E, 1.52N, 34,773 km²
- **Simulation:** 730 days, ~2 hrs
- **Impact:** 518K emergency conditions, 900+ hunger deaths (Karamoja subregion)

---

## Common Model Building Pipeline

Each dr_case follows this standard workflow:

```
1. Define region extent        -> extent/region_config.json
2. Download GeoTIFF inputs     -> 10 core datasets (DEM, landcover, soil, LAI)
3. Derive static parameters    -> derive_staticmaps.py -> staticmaps.nc (81 variables)
4. Fix LDD flow directions     -> fix_ldd_pyflwdir.py -> cycle-free LDD
5. Download climate forcing    -> 01_download_chirps.py, 02_download_era5.py
6. Prepare forcing.nc          -> 03_prepare_forcing.py
7. Resample forcing (if needed)-> resample_forcing.py -> match staticmaps grid
8. Configure Wflow             -> *_sbm.toml (3 soil layers, daily timestep)
9. Run simulation              -> julia --project wflow_cli.jl *_sbm.toml
10. Analyze outputs            -> output_*.csv (discharge, recharge, soil moisture)
```

### Input datasets (10 core GeoTIFFs per region)

| Dataset | Source | Variables Derived |
|---------|--------|-------------------|
| DEM | MERIT Hydro | elevation, slope, flow direction, upstream area |
| Land cover | ESA WorldCover | Manning's n, rooting depth, canopy parameters |
| thetaS | SoilGrids | Saturated water content |
| thetaR | SoilGrids | Residual water content |
| KsatVer | SoilGrids | Saturated hydraulic conductivity |
| SoilThickness | SoilGrids | Total soil depth |
| Brooks-Corey c | SoilGrids | Brooks-Corey exponent |
| LAI | MODIS | Leaf area index (12 monthly maps) |
| CHIRPS | UCSB | Daily precipitation forcing |
| ERA5 | ECMWF CDS | Temperature, potential evaporation forcing |

---

## Key Technical Workarounds

### 4-Layer Brooks-Corey Workaround

Wflow.jl v1.0.1 has a bug reading 3-layer Brooks-Corey `c` from NetCDF. Fix: store `c`, `kv`, and `sl` with 4 layers in staticmaps.nc while TOML specifies 3 layers. First applied in **rwa/dr_case6**, replicated across all cases.

```python
c_layers_4 = np.zeros((4, ny, nx), dtype=np.float64)
for i in range(3):
    c_layers_4[i] = c_original[i]
c_layers_4[3] = c_original[2] * 0.95  # dummy 4th layer
```

### LDD Cycle Resolution

D8-to-LDD conversion creates circular flow paths in flat terrain. Fixed with `pyflwdir`:

```python
flwdir = pyflwdir.from_dem(dem, transform=transform, latlon=True)
ldd = flwdir.to_ldd()
```

Pit cell reduction: Rwanda 888→109, Kenya 67,748→64,553, Uganda 1,092→118.

### Soil Parameter Validation

Common cross-case fixes: `thetaS ≤ thetaR` → set `thetaS = thetaR + 0.15`; zero slope → `slope = 0.001`; zero RootingDepth → first layer thickness (100 mm); NaN N_River at river cells → fill with `0.035`.

---

## Runtime Notes

- All simulations use `JULIA_NUM_THREADS=4`
- Large domains (eth, tza): ~6–7 hours per run
- Small domains (bdi, rwa, dji): 6–25 minutes
- Long runs may be interrupted; segment and merge as done for Ethiopia (`combine_ethiopia_output.py`)
