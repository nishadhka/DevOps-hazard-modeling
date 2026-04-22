# Drought Risk Case - Ethiopia (ETH)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case4
- **Region**: Blue Nile Headwaters
- **Drought Period**: 2020-2023 (1,429 days)
- **Grid Size**: 1,671 x 1,351 cells - **Largest staticmaps** (4.4 GB)
- **Impact**: 24.1M in drought areas, 4.5M livestock deaths

## Key Findings
- Discharge: 0-53,612 m³/s (mean: 8,273)
- Recharge: 0-4.65 mm/day

## Simulation Details
- **Runtime**: ~18 hours total (3 segments due to interruptions)
  - Part 1: 2020-01-02 to 2021-10-03 (641 days)
  - Part 2: 2021-10-05 to 2022-07-11 (280 days)
  - Part 3: 2022-07-13 to 2023-11-30 (506 days)
- **Post-processing**: Segments merged with `combine_ethiopia_output.py`
- **Outlet**: Blue Nile headwaters (33.15°E, 15.12°N)

## Directory Structure
- `dr_case4/` - Main case simulation
- `downloads/` - CHIRPS/ERA5 forcing data pipeline
- `complete_ethiopia_workflow.sh` - End-to-end orchestration

## Scripts (16 total)
- Download, forcing prep, resampling (multiple approaches), output merging

## Quick Links
- Workflow: `complete_ethiopia_workflow.sh`
- Simulation: `dr_case4/ethiopia_sbm.toml`
- Scripts: `dr_case4/scripts/`
- Downloads: `downloads/`
