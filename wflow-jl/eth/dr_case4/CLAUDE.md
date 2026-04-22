# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ethiopia Wflow SBM drought simulation for 2020-2023 East African drought. Part of the multi-region drought modeling project (see parent `../CLAUDE.md`).

- **Region:** Ethiopia (Blue Nile headwaters)
- **Period:** 2020-01-01 to 2023-12-31 (1,461 days)
- **Grid:** 1,671 × 1,351 cells (~1km resolution)
- **Extent:** 33.0°E-48.0°E, 3.0°N-15.1°N
- **Outlet:** 33.1523°E, 15.1231°N
- **Status:** ✅ Fully operational

## Commands

### Run Wflow Simulation
```bash
julia -e 'using Wflow; Wflow.run("ethiopia_sbm.toml")'
```

### Data Preparation Pipeline
```bash
# Download climate data (requires CDS API for ERA5)
python3 scripts/01_download_chirps_ethiopia.py
python3 scripts/02_download_era5_ethiopia.py
python3 scripts/03_prepare_forcing_ethiopia.py

# Generate spatial parameters from raw GeoTIFFs
python3 scripts/derive_staticmaps.py

# Fix LDD cycles if needed
python3 scripts/fix_ldd_pyflwdir.py

# Resample forcing to match staticmaps grid
python3 scripts/resample_forcing.py
```

### Post-Processing
```bash
# Combine output segments (if simulation was interrupted)
python3 combine_ethiopia_output.py
```

## Architecture

### Data Flow
```
wflow_datasets_1km/*.tif  →  scripts/derive_staticmaps.py  →  data/input/staticmaps.nc (4.4 GB)
                                                                       ↓
CHIRPS + ERA5             →  scripts/01-03_*.py            →  forcing_raw.nc
                                                                       ↓
                              scripts/resample_forcing.py  →  data/input/forcing.nc (536 MB)
                                                                       ↓
                              ethiopia_sbm.toml            →  Wflow.jl  →  data/output/output_ethiopia.csv
```

### Key Files
| File | Purpose |
|------|---------|
| `ethiopia_sbm.toml` | Wflow configuration (time period, inputs, outputs) |
| `data/input/staticmaps.nc` | 80+ spatial variables (4.4 GB, 4-layer soil) |
| `data/input/forcing.nc` | Daily precip/temp/PET (536 MB, 1,461 days) |
| `data/output/output_ethiopia_combined.csv` | Final results (1,429 days) |

### Script Responsibilities
| Script | Purpose |
|--------|---------|
| `scripts/derive_staticmaps.py` | Generates all Wflow variables from 10 raw GeoTIFFs |
| `scripts/fix_ldd_pyflwdir.py` | Regenerates cycle-free LDD from DEM |
| `scripts/resample_forcing.py` | Bilinear interpolation to match staticmaps grid |
| `combine_ethiopia_output.py` | Combines interrupted simulation segments |

## Technical Details

### Wflow v1.0.1 Brooks-Corey Workaround
This simulation uses the 4-layer workaround for the Brooks-Corey bug:
- staticmaps.nc has `c`, `kv`, `sl` with **4 layers**
- TOML specifies `soil_layer__thickness = [100, 300, 800]` (3 layers)
- Wflow reads first 3 layers without error

### Output Variables
| Variable | Units | Description |
|----------|-------|-------------|
| `Q` | m³/s | River discharge at outlet |
| `recharge` | mm/day | Basin-average groundwater recharge |
| `soil_moisture_L1` | vol fraction | Top 100mm soil moisture |
| `soil_moisture_L2` | vol fraction | 100-400mm root zone moisture |
| `soil_moisture_L3` | vol fraction | 400-1200mm deep soil moisture |

### Simulation Segments
Due to interruptions, the simulation ran in 3 parts:
1. 2020-01-02 to 2021-10-03 (641 days)
2. 2021-10-05 to 2022-07-11 (280 days)
3. 2022-07-13 to 2023-11-30 (506 days)

Missing dates (2021-10-04, 2022-07-12) were interpolated in `output_ethiopia_combined.csv`.

## Input Data Sources

### Raw GeoTIFFs (wflow_datasets_1km/)
- Elevation: MERIT-Hydro DEM
- Land cover: ESA WorldCover
- Soil: SoilGrids (clay, sand, silt, ksat, porosity)
- Flow routing: MERIT-Hydro (flow direction, accumulation)

### Climate Forcing
- Precipitation: CHIRPS v2.0 (0.05°, daily)
- Temperature & PET: ERA5 reanalysis (0.25°, daily)

## Dependencies

**Python:** numpy, xarray, rioxarray, scipy, pyflwdir, pandas

**Julia:** Wflow.jl v1.0.1
