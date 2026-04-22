# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Kenya Wflow SBM drought simulation for 2020-2023 East African drought. Part of the multi-region drought modeling project (see parent `../CLAUDE.md`).

- **Region:** Kenya (Tana River basin)
- **Period:** 2020-01-02 to 2023-11-30 (1,429 days)
- **Grid:** 1,083 × 881 cells (~1km resolution)
- **Extent:** 34.0°E-41.9°E, 4.7°S-5.0°N
- **Outlet:** 41.9019°E, 0.6603°N (166,337 km² upstream)
- **Status:** ✅ Completed

## Commands

### Run Wflow Simulation
```bash
JULIA_NUM_THREADS=4 julia -e 'using Wflow; Wflow.run("kenya_sbm.toml")'
```

### Fix LDD Cycles (if needed)
```bash
python3 scripts/fix_ldd_pyflwdir.py
```

## Key Files

| File | Purpose |
|------|---------|
| `kenya_sbm.toml` | Wflow configuration |
| `data/input/staticmaps.nc` | 1.95 GB, 81+ variables, 4-layer soil |
| `data/input/forcing.nc` | 224 MB, 1,430 timesteps |
| `data/output/output_kenya.csv` | Results (143 KB, 1,429 days) |
| `Kenya_simulation.md` | Full documentation |

## Simulation Results

| Variable | Min | Max | Mean |
|----------|-----|-----|------|
| Q (m³/s) | 0.0 | 119.31 | 5.14 |
| Recharge (mm/day) | 0.0 | 8.50 | 0.24 |
| Soil Moisture L1 | 0.12 | 0.54 | 0.43 |
| Soil Moisture L2 | 0.17 | 0.54 | 0.45 |

## Issues Fixed

1. **LDD Cycles** - Fixed using pyflwdir.from_dem()
2. **Negative Upstream Area** (64,068 cells) - Set to 0.99 km²
3. **Missing N_River** (159,929 cells) - Filled with 0.035
4. **4-Layer Workaround** - Applied for Brooks-Corey bug

## Dependencies

**Python:** numpy, xarray, pyflwdir, pandas
**Julia:** Wflow.jl v1.0.1
