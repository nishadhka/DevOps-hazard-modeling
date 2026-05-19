# Science & Methods — v4 Wflow.jl Drought Simulations (a basic primer)

A plain-language introduction to *what* we simulate, *how* Wflow.jl works,
*why* the drainage-network (LDD) handling matters, the ladder of LDD-fix
methods we used, and *how* the Water Requirement Satisfaction Index (WRSI)
is derived. Written so a new reader can follow the v4 trials end to end.

---

## 1. What we are doing and why

For 11 ICPAC East-Africa drought events we run a distributed hydrological
model over the event period and derive, per ~1 km pixel, a **drought
indicator (WRSI)** that says how well crop water demand was met. Inputs are
built per basin; the model is **Wflow.jl SBM**; the output is a gridded
NetCDF of actual/potential evapotranspiration from which WRSI is computed
and masked to the basin.

Pipeline: HydroBASINS basin selection (v1→**v4**) → GEE static maps →
single-source ERA5 forcing → Wflow.jl SBM → gridded WRSI.

---

## 2. Wflow.jl SBM — the hydrological model

**Wflow.jl** is Deltares' Julia implementation of distributed hydrology.
We use the **SBM** concept (a simple-bucket soil-water model) at 1 km,
daily timestep. For every cell and day it solves a vertical water balance:

```
precipitation → interception → infiltration → soil store(s)
              → evapotranspiration  → recharge → saturated zone
              → lateral subsurface + overland → river (kinematic wave)
```

Key outputs we use:

- **AET** — *actual* evapotranspiration: water the land/vegetation
  actually evaporated + transpired, limited by available soil moisture.
- **PET** — *potential* evapotranspiration: the atmospheric demand if
  water were unlimited (from the ERA5 forcing).
- (also soil moisture, recharge, river discharge.)

The ratio **AET/PET** is the physical fingerprint of water stress: when
soil water is plentiful AET≈PET (ratio→1); under drought the soil cannot
meet demand, AET falls below PET (ratio→0). **This ratio is the impetus
for the WRSI calculation** (§5).

**Inputs** come in two NetCDFs per case:

- `staticmaps.nc` — time-invariant parameters on the model grid: soil
  hydraulics (`thetaS`, `thetaR`, `KsatVer`, `c`, `f`, `SoilThickness`),
  vegetation (`RootingDepth`), terrain/river geometry (`Slope`,
  `RiverSlope/Width/Length/Depth`, Manning `N`/`N_River`), and the
  **drainage network** (`wflow_ldd`, `wflow_river`, `wflow_subcatch`,
  `wflow_pits`).
- `forcing.nc` — daily `precip`, `temp`, `pet` on the same grid.

Toolchain pin: **Julia 1.10 / Wflow v1.0.2** (Julia 1.12 triggers a
pre-timestep JIT-compile hang — a hard lesson from this work).

---

## 3. LDD — the Local Drain Direction (basic introduction)

Most readers new to hydrology stumble here, so: a **LDD (Local Drain
Direction) map** encodes, for every cell, *which one of its 8 neighbours
the water flows to* — the "D8" convention. PCRaster/Wflow code the 8
directions plus a sink as integers 1–9 (5 = pit/outlet). Stitching all
the per-cell arrows together gives the **flow network**: every cell's
water eventually reaches a pit (river mouth, lake, or domain edge).

**Why Wflow needs a *sound* LDD.** River and subsurface routing
(kinematic wave) processes cells in **upstream→downstream order**. That
ordering only exists if the network is a *directed acyclic graph* — a
tree of flow that terminates at pits. If two (or more) cells point at
each other directly or around a loop, there is **no valid ordering**:

```
A → B
↑   ↓      ← a cycle: B drains to C, C back to A — water never leaves
C ← ┘        → Wflow aborts: "One or more cycles detected in flow graph"
```

Cycles arise when a D8 direction is derived over **flat or
depression-filled terrain** (lakes, floodplains, coarsened grids): with
no elevation gradient the tie-break can make neighbouring cells point at
each other. Resolving this is the single hardest part of the v4 build.

Related fields: `wflow_river` (which cells are river), `wflow_subcatch`
(catchment id), `wflow_pits` (outlets). These must be **consistent with
the LDD** or Wflow errors on missing/loop topology.

---

## 4. Building the static maps, and the LDD-fix ladder

**Basin selection (v1→v4).** Cases were scoped on HydroBASINS (HydroSHEDS
sub-basin polygons): v1 upstream-walk from outlets, v2 CDI + level-4/5/6
plots, v3 one recommended basin per event, **v4** the reviewed final set
(see `V4_BASINS.md`). Each v4 basin's bounding box defines the model
domain.

**Static maps.** Built uniformly via `../hazard-model-api/` from Google
Earth Engine: MERIT-Hydro (elevation, flow dir/accum), ESA WorldCover,
SoilGrids → `prepare_wflow_staticmaps.py`. Forcing: a **single source**,
EarthDataHub ERA5 (precip + temp + PET in one store) regridded to each
grid — one source removes cross-dataset reconciliation.

**The problem.** `prepare_wflow_staticmaps` (a) left river-parameter and
some soil cells as NaN/0, and (b) produced a **cyclic LDD** on large/flat
domains. So a per-case LDD-soundness fix was needed. The methods, in
increasing strength:

| Method | What it is (science) |
|--|--|
| **median-fill repair** (`repair_v4_staticmaps.py`) | Fill missing river/soil params with the per-variable median of valid cells (0/NaN are non-physical sentinels). Fixes *values*, not topology. |
| **`pyflwdir.from_dem`** (`rebuild_ldd.py`) | Re-derive the D8 network from the DEM using a **priority-flood** algorithm: it "floods" the DEM from the edges so every cell has a strictly descending path to an outlet → the LDD is **acyclic by construction**. |
| **depression-filled `from_dem`** | Pre-fill internal sinks (e.g. Lake Tana) before priority-flood so flat lakes cannot leave a residual 2-cell loop. |
| **MERIT-D8 reprojected** | Use MERIT-Hydro's already hydro-conditioned D8 directly, reprojected to the model grid (nearest — risk: coarsening can re-introduce loops). |
| **IHU upscale** (`eth_ihu.py`) | Build the network at native 90 m, then **Iterative Hydrography Upscaling** to 1 km: pyflwdir traces the fine network and chooses coarse directions that preserve true connectivity → acyclic by construction even on flat terrain (the strongest, but heavy). |

**Why the 10 worked vs ETH — and why methods differ (terrain-driven).**

| Group | Cases | Fix that worked | Why |
|--|--|--|--|
| River-NaN only | BDI, ERI, RWA, UGA, SDN, SSD | median-fill repair (+ build `fix_ldd`) | steep/well-defined drainage — network already acyclic; only *values* were missing |
| Needed LDD rebuild | DJI, TZA, KEN, SOM | `pyflwdir.from_dem` cycle-free rebuild | large/endorheic; the coarse LDD had loops, so the *network* had to be re-derived |
| Persistent loop | **ETH** | none of from_dem / depr-fill / MERIT-D8 / Lake-Tana-clip | the **largest + flattest** domain (Lake Tana + Abbay floodplain); every grid-aligned derivation still loops → only IHU upscaling remains |

The split is not arbitrary: it tracks **terrain**. Hilly catchments have
unambiguous downhill directions (cheap value-fill suffices). Big, flat,
or endorheic basins have wide low-gradient areas where D8 is ambiguous,
so the whole network must be re-derived; ETH is the extreme case where
only native-resolution hydrography upscaling can guarantee acyclicity.

---

## 5. WRSI — the Water Requirement Satisfaction Index

**Agronomic idea (FAO).** Crops fail not from low rainfall per se but
from **unmet water demand over the growing season**. The FAO/USGS WRSI
expresses this as the season-cumulative ratio of water a crop *actually*
used to what it *required*:

```
WRSI = 100 × Σ_season AET_crop / Σ_season WR_crop
```

where `WR = Kc · PET` is the crop water requirement (Kc = crop
coefficient) and AET_crop is actual crop evapotranspiration. FAO
interpretation classes:

| WRSI | Meaning |
|--|--|
| ≥ 80 | no / minimal water stress |
| 50–79 | water stress |
| < 50 | crop-failure likelihood |

**How we compute it here.** Wflow.jl gives gridded **AET** and **PET**
directly. We use the **water-balance form with Kc = 1**:

```
WRSI(pixel) = 100 × Σ_period AET / Σ_period PET    (clipped 0–150)
```

then **mask to the v4 basin polygon** (`_v4_basin.geojson`) and
optionally split per calendar year. This needs no crop calendar and is
exactly what the gridded `aet`/`pet` support. It is the rigorous
seasonal water-stress signal (§2): a pixel that stayed near AET≈PET kept
its crops watered (high WRSI); a pixel where AET collapsed below PET was
moisture-starved (low WRSI). Validated on RWA, which reproduced the
documented 2016 drought (mean WRSI ≈ 65) vs the 2017 recovery (≈ 87).

**Known simplifications:** Kc = 1 (no crop curve / planting calendar);
whole-domain (no cropland mask, so arid endorheic basins like Djibouti
read degenerately low); calendar-year seasons. These are the documented
next-step refinements.

---

## 6. v4 trials & simulations done so far

- **Basin selection:** v1→v4, finalised + reviewed (`V4_BASINS.md`).
- **Static maps:** all 11 built (GEE pipeline) — incl. SOM/SSD/SDN that
  previously had *no* inputs.
- **Forcing:** all 11 from the single EDH-ERA5 source.
- **Wflow→WRSI:** **10/11 complete** (BDI DJI ERI KEN RWA SDN SOM SSD TZA
  UGA). Per-case run times, sizes, and the LDD method used are in
  `V4_RUN_OVERVIEW.md`.
- **ETH:** the sole open case — 6 LDD methods failed; IHU upscaling is
  the remaining path (`ETH_BLOCK.md`). Notably, the v4 build also
  *unblocked ERI* (the old v1.0.1 BoundsError does not recur).

Companion docs: `SIMULATION_WORKFLOW.md` (operational workflow),
`V4_BASINS.md` (selection), `V4_RUN_OVERVIEW.md` (run/method tables),
`ETH_BLOCK.md` (the open case).

---

## 7. References

- FAO Irrigation & Drainage Paper 56 (Allen et al., 1998) — Kc / WR /
  ETo basis of WRSI; FEWS NET/USGS GeoWRSI.
- Wflow.jl (Deltares) — distributed SBM hydrology.
- HydroSHEDS / HydroBASINS (Lehner & Grill, 2013) — basin polygons.
- MERIT-Hydro (Yamazaki et al., 2019) — conditioned hydrography.
- pyflwdir (Eilander et al.) — priority-flood `from_dem`, IHU upscaling.
- ERA5 / EarthDataHub (ECMWF / DestinE) — single-source forcing.
