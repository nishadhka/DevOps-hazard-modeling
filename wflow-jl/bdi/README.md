# Drought Risk Case - Burundi (BDI)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case1
- **Region**: Ruzizi River Basin
- **Drought Period**: 2021-2022 (730 days)
- **Grid Size**: 245 x 212 cells (~35,000 active)
- **Impact**: Drought impact on Ruzizi basin

## Key Findings
- **22 consecutive days of zero recharge** during mid-2021 drought
- Discharge near-zero Jun-Aug 2021 (range: 2.35-1,932 m³/s)
- Recharge: 0.13-3.28 mm/day

## Simulation Details
- **Runtime**: ~12.5 minutes
- **Outlet**: Ruzizi River (29.23°E, 4.50°S), ~5,000 km² upstream
- **Role**: First successful Wflow.jl v1.0.1 simulation; baseline for all cases

## Directory Structure
- `dr_case1/` - Main case simulation
- `exploration/` - Initial HydroMT experiments (bdi_trail1)

## Quick Links
- Simulation: `dr_case1/case_sbm.toml`
- Scripts: `dr_case1/scripts/`
- Output: `dr_case1/data/output/`
