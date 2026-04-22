# Drought Risk Case - Kenya (KEN)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case5
- **Region**: Tana River Basin / ASAL regions
- **Drought Period**: 2020-2023 (1,429 days)
- **Grid Size**: 1,083 x 881 cells (954,123 active) - **Largest active cell count**
- **Impact**: 4.5M food shortage, 222K children malnourished

## Key Findings
- Discharge: 0-119.31 m³/s (mean: 5.14)
- Recharge: 0-8.50 mm/day

## Simulation Details
- **Runtime**: ~4.5 hours
- **Outlet**: Tana River (41.90°E, 0.66°N), 166,337 km² upstream

## Technical Fixes Applied
- LDD cycles (67,748 → 64,553 pit cells)
- 64,068 negative upstream area cells corrected
- 159,929 missing N_River cells filled

## Directory Structure
- `dr_case5/` - Main case simulation
- `downloads/` - CHIRPS/ERA5 forcing data pipeline
- `complete_kenya_workflow.sh` - End-to-end orchestration

## Quick Links
- Workflow: `complete_kenya_workflow.sh`
- Simulation: `dr_case5/kenya_sbm.toml`
- Scripts: `dr_case5/scripts/`
- Downloads: `downloads/`
