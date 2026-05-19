# ETH v4 — wflow ldd block (1 of 11 unresolved)

**Status:** 10/11 v4 WRSI grids complete; **ETH (Blue Nile / Abbay) is the
sole failure.** All outputs: `/mnt/wflow-secondary/v4_models/<iso>/output/
output_grid_wrsi.nc`.

## Symptom

ETH `Wflow.run` aborts during `Wflow.Domain` network init (seconds, before
timestepping, low memory — **not** a crash/OOM):

```
Error: Wflow simulation failed
One or more cycles detected in flow graph. The provided ldd may be unsound.
```

## Root cause

ETH's v4 domain is the largest and flattest: 928×815 @1 km over the Blue
Nile incl. **Lake Tana** and broad floodplain. Every grid-aligned ldd
derivation leaves ≥1 residual 2-cell loop that Wflow rejects. The 10
working cases either have steeper/well-defined networks or smaller flat
extents where the same methods produce an acyclic ldd.

## What was tried on ETH (all → same cycle error)

| # | Method | Result |
|--|--|--|
| 1 | `prepare_wflow_staticmaps` ldd + `fix_ldd_pyflwdir` (build default) | cycle |
| 2 | `repair_v4_staticmaps` (median-fill) + `fix_ldd` **after** repair | cycle |
| 3 | `rebuild_ldd.py` — `pyflwdir.from_dem` (priority-flood) | cycle |
| 4 | `rebuild_ldd.py` — `from_dem` on **depression-filled** DEM | cycle |
| 5 | `rebuild_ldd.py --merit` — MERIT-Hydro D8 reprojected→1 km, `from_array` | cycle |

Methods 3–5 cleared DJI/TZA/KEN/SOM (and SDN/SSD via repair-only); only
ETH resists. Nearest-resampling categorical D8 90 m→1 km (method 5)
itself introduces adjacent-cell loops.

## Why the 10 worked vs ETH

| Group | Cases | Fix that worked |
|--|--|--|
| River-NaN only | BDI, ERI, RWA, UGA, SDN, SSD | median-fill `repair_v4_staticmaps` (+ build fix_ldd) |
| Large, needed ldd rebuild | DJI, TZA, KEN, SOM | `pyflwdir.from_dem` cycle-free rebuild |
| **Persistent loop** | **ETH** | none of from_dem / depr-fill / MERIT-D8 |

ETH differs by **scale + flatness** (Lake Tana + Abbay floodplain) — at
1 km the priority-flood/D8 tie-breaks produce mutual-pointer loops the
local repairs can't resolve on a grid-locked ldd.

## Recommended fix (fresh session — scoped rework, not a quick retry)

Build the flow network at MERIT native 90 m and **upscale**, which
yields an acyclic network by construction, but on a *new* grid:

1. `flw = pyflwdir.from_array(merit_dir_90m, ftype='d8', latlon=True)`
2. `flw2 = flw.upscale(scale≈10, method='ihu')` → ~1 km, acyclic
3. Regenerate ETH `staticmaps.nc` **and** `forcing.nc` on `flw2`'s grid
   (the upscaled grid ≠ current ETH grid, so both must be rebuilt to
   stay aligned — `prepare_wflow_staticmaps` + `build_v4_forcing`
   pointed at the new grid).
4. `run_v4_wflow.py` (ETH only).

Alternative if rework is undesirable: shrink the ETH v4 bbox to exclude
the Lake Tana flat, or accept 10/11 and treat ETH as out-of-scope.

State persisted in memory `v4-wflow-wrsi-status.md`; basin table
`V4_BASINS.md`.
