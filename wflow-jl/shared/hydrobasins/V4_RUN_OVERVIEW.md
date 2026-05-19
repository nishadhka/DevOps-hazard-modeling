# v4 Case-Study Run Overview

Quick overview of the v4 wflow→WRSI runs (2026-05). **10/11 complete; ETH
open.** All artefacts on `/mnt/wflow-secondary/v4_models/<iso>/`.

## 1. Run summary (staticmaps build → forcing → wflow → WRSI)

| ISO | Basin (v4) | staticmaps | forcing.nc | WRSI out | wflow run time | ldd method |
|--|--|--|--|--|--|--|
| BDI | Ruvubu | 4 MB | 118 MB | 126 MB | 17 m 40 s | A river-NaN repair |
| DJI | Afar endorheic | 4 MB | 187 MB | 228 MB | 22 m 01 s | B from_dem rebuild |
| ERI | Anseba/Red-Sea | 4 MB | 180 MB | 214 MB | 22 m 05 s | A river-NaN repair |
| RWA | Lower Akagera | 4 MB | 145 MB | 153 MB | 25 m 17 s | A river-NaN repair |
| TZA | Pangani | 10 MB | 382 MB | 399 MB | 1 h 04 m | B from_dem rebuild |
| UGA | Lake Kyoga | 11 MB | 410 MB | 433 MB | 1 h 08 m | A river-NaN repair |
| SDN | Lower Blue Nile | 28 MB | 1.5 GB | 1.8 GB | 3 h 44 m | A river-NaN repair |
| KEN | Tana | 20 MB | 1.7 GB | 1.7 GB | 4 h 13 m | B from_dem rebuild |
| SSD | Bahr el Ghazal | 112 MB | 5.4 GB | 2.3 GB | ~4 h¹ | A river-NaN repair |
| SOM | Juba-Shabelle | 136 MB | 9.8 GB | 479 MB | ~5 h¹ | B from_dem rebuild |
| ETH | Blue Nile/Abbay | 84 MB | 6.0 GB | **FAIL** | — | C: 6 methods, all cyclic |

¹ duration line absent from log; output present so run completed.
Run time scales with grid cells × days (BDI 730 d / 171×158 → 18 min;
KEN 1429 d / 393×446 → 4 h). 4 threads, Julia 1.10 / Wflow v1.0.2.

## 2. Staticmaps creation — one pipeline, per-case ldd fix

**All 11** built identically via `../hazard-model-api/` (GEE, minutes/case,
static-only): `download_dem/worldcover/merit_hydro/soilgrids` →
`prepare_wflow_staticmaps.py` → `fix_ldd_pyflwdir.py`. Forcing: single
source EDH ERA5 (`build_v4_forcing.py`).

The **only per-case difference is the ldd-soundness fix**, needed because
`prepare_wflow_staticmaps` populated river params on a *variable* fraction
of `wflow_river` cells and produced cyclic ldd on large/flat domains:

| Method | Cases | What it does | Why |
|--|--|--|--|
| **A** river-NaN repair | BDI ERI RWA UGA SDN SSD | `repair_v4_staticmaps.py` median-fills NaN/0 in river+soil params; build `fix_ldd` sufficed | network already acyclic; only missing river-param values |
| **B** from_dem rebuild | DJI TZA KEN SOM | A **+** `rebuild_ldd.py` (`pyflwdir.from_dem`, priority-flood) for a cycle-free ldd | larger/endorheic; coarse-grid ldd had loops Wflow rejects |
| **C** unresolved | ETH | A; from_dem; depr-filled from_dem; MERIT-D8 reproject; Lake-Tana-clip; IHU (running) | largest+flattest (Lake Tana/Abbay) — every grid-aligned ldd stays cyclic |

Why methods differ: it is **terrain-driven**, not arbitrary — small/steep
basins need only value-filling (A); large or endorheic basins need a
fully re-derived drainage network (B); ETH's continental flat basin
defeats all grid-aligned derivations (C).

## 3. ETH — the 6-method block (see `ETH_BLOCK.md`)

1 build `fix_ldd` · 2 repair+`fix_ldd` · 3 `from_dem` · 4 depression-filled
`from_dem` · 5 MERIT-D8 reprojected→1 km · 6 Lake-Tana-clipped `from_dem`
→ **all "cycles detected in flow graph."** 7th attempt = IHU upscale
(`eth_ihu.py`: native 90 m MERIT → `flw.upscale(10,'ihu')`, acyclic by
construction) — running but CPU-bound (~80 M native cells) on this
8 GB VM; resume plan in memory `v4-wflow-wrsi-status.md` (clip native
window or use a bigger machine).

## 4. Pipeline / docs

`shared/hydrobasins/`: v4_recommended.py · build_v4_models.py ·
build_v4_forcing.py · repair_v4_staticmaps.py · rebuild_ldd.py ·
run_v4_wflow.py · eth_ihu.py · upload_to_hf.py.
Docs: `V4_BASINS.md` (selection), `ETH_BLOCK.md` (the open case),
this file (run overview). Toolchain pin: Julia **1.10** / Wflow
**v1.0.2**; forcing = single-source EDH ERA5 (netrc).
