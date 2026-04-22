# Djibouti Wflow Drought Simulation (2021-2023)

## Overview
Wflow-SBM hydrological simulation for the Djibouti drought event (2021-2023) as documented by E4DRR.

## Simulation Details
| Parameter | Value |
|-----------|-------|
| Model Type | SBM (Soil-Based Model) |
| Period | Jan 1, 2021 - Dec 31, 2023 |
| Duration | 1095 days (3 years) |
| Resolution | ~1 km (201 x 224 grid) |
| Grid Size | 45,024 cells (39,708 valid) |
| Main Outlet | 41.5965°E, 11.1975°N |
| Upstream Area | 10,776 km² |

## Geographic Extent
- Longitude: 41.50°E to 43.50°E
- Latitude: 10.90°N to 12.70°N
- Center: 42.50°E, 11.80°N

## Input Data
- **Precipitation**: CHIRPS v2.0 daily rainfall (1064 files, 9.6GB)
- **Temperature**: ERA5 reanalysis
- **PET**: ERA5 potential evapotranspiration
- **Static Maps**: DEM, soil, land cover, flow direction (derived from 10 GeoTIFF inputs)

## Key Files
- **Configuration**: `djibouti_sbm.toml`
- **Static Maps**: `data/input/staticmaps.nc` (1.0 MB, 37 variables)
- **Forcing Data**: `data/input/forcing.nc` (to be generated)
- **Output**: `data/output/output_djibouti.csv`

## Setup Steps Completed
1. ✅ Created `derive_staticmaps.py` - generates all 81 Wflow variables
2. ✅ Created `fix_ldd_pyflwdir.py` - backup LDD cycle fixing script
3. ✅ Generated `staticmaps.nc` - all spatial parameters derived
4. ✅ Created `djibouti_sbm.toml` - Wflow configuration
5. ⏳ Generating `forcing.nc` - combining CHIRPS + ERA5 data

## Scripts

### Data Preparation
```bash
# Generate staticmaps from GeoTIFFs
cd /mnt/hydromt_data/bdi_trail2/dr_case2
python3 scripts/derive_staticmaps.py

# Prepare forcing file (optimized for memory)
python3 scripts/prepare_forcing_optimized.py

# Fix LDD cycles if needed (run only if Wflow reports cycle errors)
python3 scripts/fix_ldd_pyflwdir.py
```

### Run Simulation
```bash
cd /mnt/hydromt_data/bdi_trail2/dr_case2
julia -e 'using Wflow; Wflow.run("djibouti_sbm.toml")'
```

## Workflow Structure
```
dr_case2/
├── djibouti_sbm.toml              # Wflow configuration
├── data/
│   ├── input/
│   │   ├── staticmaps.nc          # Spatial parameters
│   │   └── forcing.nc             # Climate forcing
│   └── output/
│       └── output_djibouti.csv    # Simulation results
├── scripts/
│   ├── derive_staticmaps.py       # Generate static maps
│   ├── fix_ldd_pyflwdir.py        # Fix LDD cycles
│   └── prepare_forcing_optimized.py  # Create forcing file
├── 02_Djibouti_2021_2023/
│   ├── wflow_datasets_1km/        # Raw GeoTIFF inputs (10 files)
│   ├── data/
│   │   ├── chirps/daily/          # CHIRPS precipitation (1064 files)
│   │   └── era5/                  # ERA5 climate data
│   └── extent/                    # Region metadata
└── logs/                          # Processing logs
```

## Technical Details

### Soil Layer Configuration
- **Layers**: 3 layers [100, 300, 800] mm (matches Burundi)
- **Total Depth**: 1200 mm
- Consistent with Wflow v1.0.1 requirements

### River Network
- **Threshold**: 100 km² upstream area
- **River Cells**: 601 (1.51% of valid area)
- **Max Upstream Area**: 10,776 km²
- **River Width**: 35.3 - 477.6 m

### Flow Direction
- **Input Format**: D8 (power-of-2 encoding)
- **Wflow Format**: LDD (PCRaster 1-9 encoding)
- Conversion handled by derive_staticmaps.py
- Cycle-free LDD ensured

## Output Variables
The simulation produces:
- `Q`: River discharge (m³/s) at main outlet
- `recharge`: Basin-average groundwater recharge (mm/day)
- `soil_moisture_L1`: Basin-average soil moisture, Layer 1 (fraction)
- `soil_moisture_L2`: Basin-average soil moisture, Layer 2 (fraction)

## Software Requirements
- **Python**: numpy, xarray, rioxarray, scipy, pyflwdir
- **Julia**: Wflow.jl v1.0.1
- **System**: ~4GB RAM for forcing preparation, ~2GB for simulation

## Status
- **Data Preparation**: In Progress
- **Staticmaps**: ✅ Complete (1.0 MB)
- **Forcing**: ⏳ In Progress
- **Simulation**: Pending

## Notes
- Following the same workflow as Burundi (dr_case1) and Eritrea (dr_case3)
- Using Wflow v1.0.1 (same version that worked for Burundi)
- Grid size (201x224 = 45K cells) is between Burundi (52K) and Eritrea (476K)
- Should avoid the Brooks-Corey bug that blocked Eritrea

## Impact
According to E4DRR:
- **People Affected**: 194,000 (food insecurity, Oct 2022)
- **Economic Impact**: 6.1% inflation
- **Scope**: National

## References
- E4DRR Drought Events: https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/
- Wflow Documentation: https://deltares.github.io/Wflow.jl/dev/
- Data Sources: CHIRPS v2.0, ERA5, MERIT-Hydro, ESA WorldCover, SoilGrids
