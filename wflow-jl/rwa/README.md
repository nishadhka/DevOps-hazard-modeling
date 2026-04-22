# Drought Risk Case - Rwanda (RWA)

**Status**: ✅ COMPLETE ⭐ **Reference Template**

## Overview
- **Case Number**: dr_case6
- **Region**: Akagera River Basin
- **Drought Period**: 2016-2017 (730 days)
- **Grid Size**: 212 x 234 cells (49,608 total)
- **Impact**: 250,000 people affected by food shortages (eastern province)

## Key Role
🌟 **First successful 4-layer Brooks-Corey workaround**
This case became the **reference template** for all subsequent simulations.

## Simulation Details
- **Runtime**: 25 min 17 sec
- **Outlet**: Akagera River (30.90°E, 2.08°S), 19,039 km² upstream

## Technical Fixes Applied
- LDD cycles (888 → 109 pit cells)
- 7,409 missing N_River values filled
- Grid mismatch resolved (forcing 38x42 @ 5km → 212x234 @ 1km)

## Quick Links
- Simulation: `dr_case6/case_sbm.toml`
- Scripts: `dr_case6/scripts/`
- Documentation: `dr_case6/Rwanda_simulation.md`
