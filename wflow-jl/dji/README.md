# Drought Risk Case - Djibouti (DJI)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case2
- **Drought Period**: 2021-2023 (1,095 days)
- **Grid Size**: 201 x 224 cells (39,708 active)
- **Impact**: 194,000 people food insecure (Oct 2022), 6.1% inflation

## Key Findings
- Discharge: 0.46-15.30 m³/s
- Soil moisture L1: 0.023-0.101

## Simulation Details
- **Runtime**: ~6 minutes
- **Outlet**: Coastal outlet (41.60°E, 11.20°N), ~6,316 km² upstream

## Technical Fixes Applied
- Brooks-Corey 4-layer workaround
- LDD cycle resolution
- 518 cells with thetaS=0 corrected
- 6-9% forcing NaN values filled

## Quick Links
- Simulation: `dr_case2/djibouti_sbm.toml`
- Scripts: `dr_case2/scripts/`
- Output: `dr_case2/data/output/`
