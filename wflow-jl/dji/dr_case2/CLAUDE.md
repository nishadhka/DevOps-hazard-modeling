# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Djibouti Wflow SBM drought simulation for 2021-2023 drought. Part of the multi-region East Africa drought modeling project.

- **Region:** Djibouti
- **Period:** 2021-01-01 to 2023-12-31 (1,095 days)
- **Grid:** 201 × 224 cells (~1km resolution)
- **Active Cells:** 39,708
- **Outlet:** 41.5965°E, 11.1975°N (6,315 km² upstream)
- **Status:** ✅ Completed

## Commands

### Run Wflow Simulation
```bash
JULIA_NUM_THREADS=4 julia -e 'using Wflow; Wflow.run("djibouti_sbm.toml")'
```

## Key Files

| File | Purpose |
|------|---------|
| `djibouti_sbm.toml` | Wflow configuration |
| `data/input/staticmaps.nc` | 15.6 MB, 4-layer soil workaround |
| `data/input/forcing.nc` | 83 MB, 1,095 timesteps |
| `data/output/output_djibouti.csv` | Results (1,094 days) |
| `Djibouti_simulation.md` | Full documentation |

## Simulation Results

| Variable | Min | Max | Mean |
|----------|-----|-----|------|
| Q (m³/s) | 0.46 | 15.30 | 1.68 |
| Recharge (mm/day) | 0.0 | 3.46 | 0.37 |
| Soil Moisture L1 | 0.023 | 0.101 | 0.027 |
| Soil Moisture L2 | 68.64 | 69.76 | 69.09 |

## Issues Fixed

1. **Brooks-Corey Bug** - 4-layer workaround (c, kv, sl with 4 layers, TOML uses 3)
2. **LDD Cycles** - pyflwdir regeneration from DEM
3. **Forcing NaN** - Spatial interpolation with nearest neighbor
4. **thetaS = 0** - Set minimum thetaS = thetaR + 0.15
5. **Slope = 0** - Set minimum slope = 0.001

## Dependencies

**Python:** numpy, xarray, scipy, pyflwdir
**Julia:** Wflow.jl v1.0.1
