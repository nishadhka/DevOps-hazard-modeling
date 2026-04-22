# Burundi Wflow Drought Simulation (2021-2022)

## Overview
Wflow-SBM hydrological simulation for the Burundi drought event (2021-2022) as documented by E4DRR.

## Simulation Details
| Parameter | Value |
|-----------|-------|
| Model Type | SBM (Soil-Based Model) |
| Period | Jan 1, 2021 - Dec 31, 2022 |
| Duration | 730 days |
| Resolution | ~1 km (245 x 212 grid) |
| Variables | 81 (matching tutorial structure) |
| Runtime | ~12.5 minutes |

## Input Data
- **Precipitation**: CHIRPS daily rainfall
- **Temperature**: ERA5 reanalysis
- **PET**: ERA5 potential evapotranspiration
- **Static Maps**: DEM, soil, land cover, flow direction (derived from HydroMT datasets)

## Key Findings

### Drought Severity
- **July 2021**: Driest month with only 0.31 mm total groundwater recharge
- **22 consecutive days** of zero recharge during mid-2021
- River discharge dropped to near-zero during June-August 2021

### Annual Comparison
| Metric | 2021 | 2022 |
|--------|------|------|
| Zero Recharge Days | 47 | 25 |
| Max Consecutive Dry Days | 22 | 7 |
| Dry Season Avg Recharge | 0.13 mm/day | 0.24 mm/day |

## Output Files
- `output/output_burundi_drought_2021_2022.csv` - Daily simulation results
- `staticmaps-burundi-fixed.nc` - Static model parameters
- `forcing-burundi-fixed.nc` - Climate forcing data
- `wflow_burundi_full.toml` - Model configuration

## Software
- Wflow.jl v1.0.1
- Julia 1.10.10
