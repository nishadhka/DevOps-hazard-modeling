# Wflow.jl Hydrological Modeling - East Africa Drought Risk Cases

Regional hydrological model builds and simulations using **Wflow.jl v1.0.1 (SBM)** for drought impact analysis across East Africa. Each subdirectory represents a country/region with its own model configuration, forcing data pipeline, and simulation outputs.

## Project Status

| Case | Region | Drought Period | Grid Size | Status |
|------|--------|---------------|-----------|--------|
| dr_case1 | Burundi | 2021-2022 | 245 x 212 | Simulation complete |
| dr_case2 | Djibouti | 2021-2023 | 201 x 224 | Simulation complete |
| dr_case3 | Eritrea | 2021-2023 | 628 x 758 | Blocked (BoundsError bug) |
| dr_case4 | Ethiopia | 2020-2023 | 1671 x 1351 | Simulation complete |
| dr_case5 | Kenya | 2020-2023 | 1083 x 881 | Simulation complete |
| dr_case6 | Rwanda | 2016-2017 | 212 x 234 | Simulation complete |
| dr_case10 | Tanzania | 2022-2023 | 1198 x 1248 | Simulation complete |
| dr_case11 | Uganda | 2021-2022 | 313 x 235 | Simulation complete |

**Overall: 7 of 8 cases operational (87.5%)**

---

## Directory Structure

```
wflow-run/
├── README.md                          # This file
├── complete_ethiopia_workflow.sh       # End-to-end Ethiopia data pipeline
├── complete_kenya_workflow.sh          # End-to-end Kenya data pipeline
│
├── bdi_trail1/                        # Burundi - Initial HydroMT model exploration
│   ├── download_all_datasets.sh       # Global dataset download script
│   ├── download_global_datasets.py    # Python downloader for MERIT, ESA, SoilGrids
│   ├── download_merit_hydro.sh        # MERIT Hydro DEM download
│   ├── combine_spatial_data.py        # Merge spatial layers
│   ├── run_on_vm.sh                   # VM execution script
│   ├── burundi_region.geojson         # Burundi boundary polygon
│   ├── burundi_data_catalog*.yml      # HydroMT data catalog (v1, v2, v3)
│   ├── wflow_build_*.yml              # 13 HydroMT build config variants
│   ├── burundi_*/hydromt.log          # Build logs per variant
│   └── *.log                          # Download and build logs
│
├── bdi_trail2/                        # Main drought risk simulation cases
│   ├── CLAUDE.md                      # Project documentation and guidelines
│   ├── README.md                      # Project overview
│   ├── derive_staticmaps.py           # Top-level staticmaps derivation
│   ├── fix_ldd_pyflwdir.py            # LDD cycle fix utility
│   ├── resample_forcing.py            # Forcing resampling utility
│   ├── fix_eritrea_staticmaps.py      # Eritrea-specific data fixes
│   ├── burundi_sbm.toml               # Burundi Wflow config
│   ├── eritrea_sbm.toml               # Eritrea Wflow config
│   ├── WFLOW_VERSION_TESTING_REPORT.md
│   ├── ERITREA_SIMULATION_STATUS.md
│   ├── TUTORIAL_VS_BURUNDI_COMPARISON.md
│   │
│   ├── dr_case1/                      # BURUNDI
│   │   ├── case_sbm.toml             # Wflow SBM configuration
│   │   ├── scripts/
│   │   │   ├── derive_staticmaps.py   # Generate 81 Wflow variables from GeoTIFFs
│   │   │   └── fix_ldd_pyflwdir.py    # Fix flow direction cycles
│   │   └── data/output/
│   │       ├── case_sbm.toml          # Runtime config copy
│   │       └── log.txt                # Simulation log
│   │
│   ├── dr_case2/                      # DJIBOUTI
│   │   ├── djibouti_sbm.toml         # Main Wflow config
│   │   ├── djibouti_small.toml        # Reduced domain test config
│   │   ├── scripts/
│   │   │   ├── derive_staticmaps.py
│   │   │   ├── fix_ldd_pyflwdir.py
│   │   │   └── prepare_forcing_optimized.py
│   │   ├── 02_Djibouti_2021_2023/     # Data download sub-pipeline
│   │   │   ├── scripts/
│   │   │   │   ├── 01_download_chirps_djibouti.py
│   │   │   │   ├── 02_download_era5_djibouti.py
│   │   │   │   └── 03_prepare_forcing_djibouti.py
│   │   │   ├── extent/
│   │   │   │   ├── region_bounds.geojson
│   │   │   │   └── region_config.json
│   │   │   └── cdi_data/cdi_metadata.json
│   │   ├── logs/                      # Forcing prep logs
│   │   └── data/output/
│   │
│   ├── dr_case3/                      # ERITREA (blocked)
│   │   ├── case_sbm.toml             # Main config
│   │   ├── case_sbm_nobc.toml        # No Brooks-Corey variant
│   │   ├── case_sbm_nosnow.toml      # Snow disabled variant
│   │   ├── case_sbm_test.toml        # Test config
│   │   ├── case_sbm_default_c.toml   # Default c-parameter variant
│   │   ├── scripts/
│   │   │   ├── derive_staticmaps.py
│   │   │   └── fix_ldd_pyflwdir.py
│   │   ├── Eritrea_simulation.md      # Detailed issue analysis
│   │   └── data/output/
│   │
│   ├── dr_case4/                      # ETHIOPIA
│   │   ├── ethiopia_sbm.toml         # Wflow config
│   │   ├── combine_ethiopia_output.py # Merge segmented outputs
│   │   ├── scripts/
│   │   │   ├── 01_download_chirps_ethiopia.py
│   │   │   ├── 02_download_era5_ethiopia.py
│   │   │   ├── 03_prepare_forcing_ethiopia.py
│   │   │   ├── derive_staticmaps.py
│   │   │   ├── fix_ldd_pyflwdir.py
│   │   │   ├── resample_forcing.py
│   │   │   ├── resample_forcing_batch.py
│   │   │   ├── resample_forcing_xr.py
│   │   │   ├── resample_dask.py
│   │   │   ├── resample_incremental.py
│   │   │   ├── resample_subset.py
│   │   │   ├── resample_yearly.py
│   │   │   ├── subset_forcing.py
│   │   │   ├── fix_forcing_fillvalues.py
│   │   │   └── merge_outputs.py
│   │   ├── extent/
│   │   │   ├── region_bounds.geojson
│   │   │   └── region_config.json
│   │   ├── cdi_data/cdi_metadata.json
│   │   ├── forcing/forcing_info.json
│   │   └── data/output/
│   │
│   ├── dr_case5/                      # KENYA
│   │   ├── kenya_sbm.toml
│   │   ├── scripts/
│   │   │   ├── 01_download_chirps_kenya.py
│   │   │   ├── 02_download_era5_kenya.py
│   │   │   ├── 03_prepare_forcing_kenya.py
│   │   │   ├── derive_staticmaps.py
│   │   │   ├── fix_ldd_pyflwdir.py
│   │   │   ├── resample_forcing.py
│   │   │   └── subset_forcing.py
│   │   ├── extent/
│   │   │   ├── region_bounds.geojson
│   │   │   └── region_config.json
│   │   ├── cdi_data/cdi_metadata.json
│   │   ├── forcing/forcing_info.json
│   │   └── data/output/
│   │
│   ├── dr_case6/                      # RWANDA
│   │   ├── case_sbm.toml
│   │   ├── scripts/
│   │   │   ├── 01_download_chirps_rwanda.py
│   │   │   ├── 02_download_era5_rwanda.py
│   │   │   ├── 03_prepare_forcing_rwanda_fine.py
│   │   │   ├── derive_staticmaps.py
│   │   │   └── fix_ldd_pyflwdir.py
│   │   ├── extent/
│   │   │   ├── region_bounds.geojson
│   │   │   └── region_config.json
│   │   ├── cdi_data/cdi_metadata.json
│   │   ├── Rwanda_simulation.md
│   │   └── data/output/
│   │
│   ├── dr_case10/                     # TANZANIA
│   │   ├── case_sbm.toml
│   │   ├── scripts/
│   │   │   ├── derive_staticmaps.py
│   │   │   ├── fix_ldd_pyflwdir.py
│   │   │   └── resample_forcing.py
│   │   ├── extent/
│   │   │   ├── region_bounds.geojson
│   │   │   └── region_config.json
│   │   ├── cdi_data/cdi_metadata.json
│   │   ├── Tanzania_simulation.md
│   │   └── data/output/
│   │
│   ├── dr_case11/                     # UGANDA
│   │   ├── case_sbm.toml
│   │   ├── scripts/
│   │   │   ├── 01_download_chirps_uganda.py
│   │   │   ├── 02_download_era5_uganda.py
│   │   │   ├── 03_prepare_forcing_uganda_fine.py
│   │   │   ├── derive_staticmaps.py
│   │   │   ├── fix_ldd_pyflwdir.py
│   │   │   └── resample_forcing.py
│   │   ├── extent/
│   │   │   ├── region_bounds.geojson
│   │   │   └── region_config.json
│   │   ├── cdi_data/cdi_metadata.json
│   │   ├── Uganda_simulation.md
│   │   ├── forcing/forcing_info.json
│   │   ├── logs/
│   │   └── data/output/
│   │
│   ├── wflow_tutorial/                # Moselle reference tutorial
│   │   ├── sbm_config.toml
│   │   ├── sbm_simple.toml
│   │   └── data/output/
│   │
│   └── wflow_datasets_1km/           # Shared 1km dataset downloads
│       └── download_summary.json
│
├── ethiopia_downloads/                # Ethiopia forcing data pipeline
│   ├── run_downloads.sh               # Main download orchestrator
│   ├── 01_download_chirps.py          # CHIRPS precipitation (daily TIFs)
│   ├── 03_prepare_forcing.py          # Merge CHIRPS+ERA5 into forcing.nc
│   ├── data/chirps/download_info.json
│   └── *.log                          # Download/processing logs
│
└── kenya_downloads/                   # Kenya forcing data pipeline
    ├── 01_download_chirps.py
    ├── 03_prepare_forcing.py
    ├── data/chirps/download_info.json
    └── *.log
```

---

## Case Details

### dr_case1: Burundi (2021-2022)

- **Extent:** 28.83E-30.89E, 4.50S-2.29S
- **Outlet:** Ruzizi River (29.23E, 4.50S), ~5,000 km2 upstream
- **Resolution:** ~1 km (245 x 212 cells, ~35,000 active)
- **Simulation:** 730 days, completed in ~12.5 min
- **Output highlights:** Discharge 2.35-1,932 m3/s; recharge 0.13-3.28 mm/day
- **Key finding:** 22 consecutive days of zero recharge during mid-2021 drought; discharge near-zero Jun-Aug 2021
- **Role:** First successful Wflow.jl v1.0.1 simulation; baseline for all subsequent cases

### dr_case2: Djibouti (2021-2023)

- **Extent:** 41.50E-43.50E, 10.90N-12.70N
- **Outlet:** 41.60E, 11.20N, ~6,316 km2 upstream
- **Resolution:** ~1 km (201 x 224 cells, 39,708 active)
- **Simulation:** 1,095 days, completed in ~6 min
- **Output highlights:** Discharge 0.46-15.30 m3/s; soil moisture L1: 0.023-0.101
- **Impact context:** 194,000 people affected (food insecurity, Oct 2022), 6.1% inflation
- **Issues fixed:** Brooks-Corey 4-layer workaround, LDD cycles, 518 cells with thetaS=0, 6-9% forcing NaN filled

### dr_case3: Eritrea (2021-2023) - BLOCKED

- **Extent:** 36.33E-43.15E, 12.40N-18.00N
- **Resolution:** ~1 km (628 x 758 cells, 312,179 active) - largest domain, 6x Burundi
- **Status:** Simulation fails at first timestep with `BoundsError: attempt to access NTuple{4, Float64} at index [0]`
- **Data readiness:** 95% complete. Staticmaps (104 MB), forcing (793 MB), config all validated
- **Fixes attempted (11+):** LDD dtype fix, LDD cycle fix, 40-variable verification, 3-layer soil config, 4-layer workaround, thetaS validation (875 cells), RootingDepth zeros (3,447 cells), minimum slope, snow disabled, single thread - all failed
- **Root cause hypothesis:** Layer index calculation in Wflow returns 0; possibly kv scaling issue (48-255 vs expected 0.07-0.25) or water table depth calculation anomaly
- **5 TOML variants tested:** default, nobc, nosnow, test, default_c
- **Next steps:** Deep comparison with Djibouti staticmaps; subset domain test; file Wflow bug report

### dr_case4: Ethiopia (2020-2023)

- **Extent:** 33.0E-48.0E, 3.0N-15.1N (Blue Nile headwaters region)
- **Outlet:** 33.15E, 15.12N
- **Resolution:** ~1 km (1,671 x 1,351 cells) - largest staticmaps at 4.4 GB
- **Simulation:** 1,429 days, run in 3 segments (~6 hrs each) due to interruptions
  - Part 1: 2020-01-02 to 2021-10-03 (641 days)
  - Part 2: 2021-10-05 to 2022-07-11 (280 days)
  - Part 3: 2022-07-13 to 2023-11-30 (506 days)
- **Post-processing:** `combine_ethiopia_output.py` merges segments, interpolates 2 missing dates
- **Output highlights:** Discharge 0-53,612 m3/s (mean: 8,273); recharge 0-4.65 mm/day
- **Impact context:** 24.1M people in drought areas, 4.5M livestock deaths
- **16 scripts** covering download, forcing prep, resampling (multiple approaches), and output merging

### dr_case5: Kenya (2020-2023)

- **Extent:** 34.0E-41.9E, 4.7S-5.0N (Tana River basin / ASAL regions)
- **Outlet:** Tana River (41.90E, 0.66N), 166,337 km2 upstream
- **Resolution:** ~1 km (1,083 x 881 cells, 954,123 active) - largest active cell count
- **Simulation:** 1,429 days, completed in ~4.5 hrs
- **Output highlights:** Discharge 0-119.31 m3/s (mean: 5.14); recharge 0-8.50 mm/day
- **Impact context:** 4.5M food shortage, 222K children malnourished (ASAL regions)
- **Issues fixed:** LDD cycles (67,748 to 64,553 pit cells), 64,068 negative upstream area cells, 159,929 missing N_River cells

### dr_case6: Rwanda (2016-2017)

- **Extent:** 28.80E-30.90E, 2.90S-1.00S (Akagera River basin)
- **Outlet:** Akagera River (30.90E, 2.08S), 19,039 km2 upstream
- **Resolution:** ~1 km (212 x 234 cells, 49,608 total)
- **Simulation:** 730 days, completed in **25 min 17 sec**
- **Impact context:** 250,000 people affected by food shortages, eastern province
- **Key role:** First successful application of the 4-layer Brooks-Corey workaround. This case became the **reference template** for all subsequent simulations.
- **Issues fixed:** LDD cycles (888 to 109 pit cells), 7,409 missing N_River values, grid mismatch (forcing 38x42 at 5km resampled to 212x234 at 1km, 3.7 MB to 435 MB)

### dr_case10: Tanzania (2022-2023)

- **Extent:** 29.30E-40.50E, 11.70S-1.00S (Kagera River basin to Lake Victoria)
- **Outlet:** Kagera River (29.30E, 3.36S), 292,488 km2 upstream
- **Resolution:** ~1 km (1,198 x 1,248 cells, 1,495,104 total)
- **Simulation:** 730 days, staticmaps 3.062 GB
- **Impact context:** 2.2M people affected by food shortage, 70% crop failure in northern regions
- **Issues fixed:** 339,261 river cells identified, 268,269 missing N_River filled, 94,866 cycle-free pit cells

### dr_case11: Uganda (2021-2022)

- **Extent:** 32.80E-34.90E, 1.00N-3.80N (Karamoja subregion)
- **Outlet:** 32.80E, 1.52N, 34,773 km2 upstream
- **Resolution:** ~1 km (313 x 235 cells, 73,555 total)
- **Simulation:** 730 days, completed in ~2 hrs
- **Impact context:** 518K in emergency conditions, 900+ hunger deaths (Karamoja)
- **Issues fixed:** LDD cycles (1,092 to 118 pit cells), LDD uint8 conversion

### wflow_tutorial: Moselle River (Reference)

- **Purpose:** Validate Wflow.jl installation using official tutorial data
- **Result:** 10-day simulation successful (82 variables)
- **Significance:** Proves software is correctly installed; all dr_case failures are data/configuration issues, not installation problems

---

## bdi_trail1: Initial HydroMT Exploration

The first round of Burundi model building experiments using HydroMT (Python-based model builder). This explored 13 different build configurations before settling on the direct Python approach used in bdi_trail2.

**Build variants tested:**
- `wflow_build_simple.yml` / `wflow_build_simple_bbox.yml` - Basic bounding box builds
- `wflow_build_config_FINAL.yml` - Final HydroMT config attempt
- `wflow_build_AUTODOWNLOAD.yml` - Auto-download approach
- `wflow_build_combined.yml` - Combined data catalog
- `wflow_build_custom_data.yml` - Custom local datasets
- `wflow_build_minimal.yml` / `wflow_build_outlet.yml` - Minimal configs

**Data catalogs:** 3 versions of `burundi_data_catalog.yml` progressively refined

**Outcome:** HydroMT auto-download approach was ultimately replaced by the direct `derive_staticmaps.py` Python script approach used across all dr_case simulations, which gave more control over the 81+ variables needed.

---

## Forcing Data Pipelines

### ethiopia_downloads / kenya_downloads

Standalone data download directories with 3-step pipelines:

1. **`01_download_chirps.py`** - Download daily CHIRPS precipitation GeoTIFFs (2020-2023)
2. **`02_download_era5_*.py`** (in dr_case scripts) - Download ERA5 temperature and PET via CDS API
3. **`03_prepare_forcing.py`** - Merge CHIRPS + ERA5 into a single `forcing.nc` for Wflow

### Workflow scripts

- **`complete_ethiopia_workflow.sh`** - Orchestrates the full Ethiopia pipeline (CHIRPS check/download, ERA5 download, forcing.nc preparation, copy to dr_case4)
- **`complete_kenya_workflow.sh`** - Same pipeline for Kenya/dr_case5

---

## Common Model Building Pipeline

Each dr_case follows this standard workflow:

```
1. Define region extent        -> extent/region_bounds.geojson, region_config.json
2. Download GeoTIFF inputs     -> 10 core datasets (DEM, landcover, soil, LAI, etc.)
3. Derive static parameters    -> derive_staticmaps.py -> staticmaps.nc (81 variables)
4. Fix LDD flow directions     -> fix_ldd_pyflwdir.py -> cycle-free LDD
5. Download climate forcing    -> 01_download_chirps.py, 02_download_era5.py
6. Prepare forcing.nc          -> 03_prepare_forcing.py -> forcing.nc
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
| Soil (thetaS) | SoilGrids | Saturated water content |
| Soil (thetaR) | SoilGrids | Residual water content |
| Soil (KsatVer) | SoilGrids | Saturated hydraulic conductivity |
| Soil (SoilThickness) | SoilGrids | Total soil depth |
| Soil (c) | SoilGrids | Brooks-Corey exponent |
| LAI | MODIS | Leaf area index (12 monthly maps) |
| CHIRPS | UCSB | Daily precipitation forcing |
| ERA5 | ECMWF CDS | Temperature, potential evaporation forcing |

---

## Key Technical Workarounds

### 4-Layer Brooks-Corey Workaround

Wflow.jl v1.0.1 has a bug reading 3-layer Brooks-Corey parameter (`c`) from NetCDF. The fix: store `c`, `kv`, and `sl` with 4 layers in staticmaps.nc while the TOML config specifies 3 layers. Wflow reads the first 3 layers without error.

```python
# In derive_staticmaps.py
c_layers_4 = np.zeros((4, ny, nx), dtype=np.float64)
for i in range(3):
    c_layers_4[i] = c_original[i]
c_layers_4[3] = c_original[2] * 0.95  # 4th layer (unused dummy)
```

First applied in **dr_case6 (Rwanda)**, then replicated across all cases.

### LDD Cycle Resolution

D8-to-LDD conversion creates circular flow paths in flat terrain. Fixed using `pyflwdir`:

```python
# In fix_ldd_pyflwdir.py
flwdir = pyflwdir.from_dem(dem, transform=transform, latlon=True)
ldd = flwdir.to_ldd()  # Cycle-free flow direction
```

Pit cell reduction examples: Rwanda 888->109, Kenya 67,748->64,553, Uganda 1,092->118

### Soil Parameter Validation

Common issues fixed across cases:
- `thetaS <= thetaR`: Set `thetaS = thetaR + 0.15`
- Zero slope: Set minimum `slope = 0.001`
- Zero RootingDepth: Set to first layer thickness (100 mm)
- NaN in N_River at river cells: Fill with default `0.035`

---

## Runtime Notes

- All simulations use `JULIA_NUM_THREADS=4` for parallel processing
- Large domains (Ethiopia, Tanzania) may need ~6-7 hours per run
- Small domains (Burundi, Rwanda, Djibouti) complete in 6-25 minutes
- Long runs may be interrupted; segment and combine outputs as done for Ethiopia
