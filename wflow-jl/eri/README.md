# Drought Risk Case - Eritrea (ERI)

**Status**: 🚫 BLOCKED

## Overview
- **Case Number**: dr_case3
- **Drought Period**: 2021-2023
- **Grid Size**: 628 x 758 cells (312,179 active) - **Largest domain** (6x Burundi)
- **Impact**: Assessment pending simulation completion

## Current Status
⚠️ Simulation fails at first timestep with:
```
BoundsError: attempt to access NTuple{4, Float64} at index [0]
```

## Data Readiness
- ✅ 95% complete
- ✅ Staticmaps (104 MB) validated
- ✅ Forcing (793 MB) prepared
- ✅ Configuration files ready

## Troubleshooting History
11+ fixes attempted (all unsuccessful):
- LDD dtype fix
- LDD cycle resolution
- 40-variable verification
- 3-layer soil config
- 4-layer Brooks-Corey workaround
- thetaS validation (875 cells)
- RootingDepth zeros (3,447 cells)
- Minimum slope enforcement
- Snow disabled
- Single thread mode

## Root Cause Hypothesis
Layer index calculation in Wflow returns 0; possibly:
- kv scaling issue (48-255 vs expected 0.07-0.25)
- Water table depth calculation anomaly

## Next Steps
1. Deep comparison with Djibouti staticmaps
2. Subset domain test
3. File Wflow bug report with minimal reproducible example

## Quick Links
- Documentation: `docs/ERITREA_SIMULATION_STATUS.md`
- Simulation configs (5 variants): `dr_case3/*.toml`
- Scripts: `dr_case3/scripts/`
