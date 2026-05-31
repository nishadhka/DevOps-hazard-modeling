# ETH — fresh-session resume guide  ✅ RESOLVED 2026-05-30 (11/11)

**DONE — ETH no longer needs resuming.** The blocker was the **river**
network, not the land ldd: `wflow_river` was stale after ldd rebuilds, so
75 river cells drained to non-river cells → Wflow's `NetworkRiver.flowgraph`
(searchsortedfirst, no membership check) made spurious edges → cycle. Fixed
on the existing grid with `eth_river_fix.py --fix` (downstream-closure of the
river mask, +246 cells, then median-fill river params). Wflow then ran clean
(13h50m) → valid `eth/output/output_grid_wrsi.nc`. The IHU path (`eth_ihu.py`,
Step 1 below) is a **dead end** — `pyflwdir.upscale(ihu)` is non-terminating
on this VM (8h37m CPU, no output). Full write-up in `ETH_BLOCK.md` and memory
`v4-wflow-wrsi-status.md`. The recipe below is **historical**.

---

# ETH — fresh-session resume guide (historical)

**Use this file as the single entry point** when starting a new Claude
context to finish the ETH (Ethiopia / Blue Nile Abbay) v4 wflow run.
All other state — basins, runs, science — is in companion docs; this
file is just the *recipe to pick up where we stopped*.

## Where things stand

- **10 / 11 v4 WRSI grids are complete and safe** on
  `/mnt/wflow-secondary/v4_models/<iso>/output/output_grid_wrsi.nc`:
  `BDI DJI ERI KEN RWA SDN SOM SSD TZA UGA`.
- **ETH is the only open case.** All built inputs are on disk:
  `/mnt/wflow-secondary/v4_models/eth/`
  (`staticmaps.nc` 84 MB, `forcing.nc` 6.0 GB, plus `tif/`).
  Wflow aborts at `Wflow.Domain` init: **"One or more cycles detected
  in flow graph"**.

## What has already been tried (all failed)

1. build `fix_ldd_pyflwdir` (default) — cycle
2. `repair_v4_staticmaps` median-fill **+** `fix_ldd` after repair — cycle
3. `rebuild_ldd.py` — `pyflwdir.from_dem` (priority-flood) — cycle
4. `rebuild_ldd.py` — `from_dem` on **depression-filled** DEM — cycle
5. `rebuild_ldd.py --merit` — MERIT-Hydro D8 reprojected to 1 km — cycle
6. `eth_clip_try.py` — clip out Lake Tana (lat ≤ 11.4°N), `from_dem` — cycle
7. `eth_ihu.py` (full-native IHU upscale of MERIT 90 m d8 → 1 km) —
   >3 h CPU-bound, no output (on this 8 GB VM, native ~80 M cells is
   unviable)
8. `eth_ihu.py` with **K=3 d8 decimation** (~9 M cells) → `from_array`
   + `upscale(4,'ihu')` — background runs **exited silently** (empty
   captured log, no traceback) despite the foreground run producing
   no error in 5 min before being timed out

## Next steps (do in this order)

### Step 1 — surface the real traceback (foreground, no timeout)

```bash
cd /home/sa_112625140081245282401/DevOps-hazard-modeling/wflow-jl
export PATH="$HOME/.local/bin:$PATH" PYTHONUNBUFFERED=1
rm -rf /mnt/wflow-secondary/v4_models/eth_ihu
uv run python -u shared/hydrobasins/eth_ihu.py
```

Run it **foreground, no `timeout`, no background flag**. The session's
background launches kept exiting before stdout/stderr were captured;
foreground shows real errors. Read the first error/traceback that
appears — that pinpoints what's wrong (likely the `rasterio.Affine`
import path, the decimated-d8 dtype to `pyflwdir.from_array`, or a
`rioxarray.reproject_match` mismatch on the reduced grid).

### Step 2 — if Step 1 finishes without error → run is OK

`/mnt/wflow-secondary/v4_models/eth_ihu/output/output_grid_wrsi.nc`
will be present → **11 / 11 v4 WRSI complete**. Then upload + commit
per the established pattern (`upload_to_hf.py`, etc).

### Step 3 — if it errors

Fix the error revealed in Step 1, re-run Step 1. Common things to
check in `eth_ihu.py` near the top of the script:

- `from rasterio import Affine` — keep it inside the script (don't
  rely on a global) and use `tr90 = Affine(tr90.a*K, tr90.b, tr90.c,
  tr90.d, tr90.e*K, tr90.f)`.
- `d8` dtype must be `uint8` for `pyflwdir.from_array(ftype='d8')`.
- `flw.upscale(scale_factor, method='ihu')` — `scale_factor` is
  positional, no `uparea=` (sizes mismatched).
- After upscale, reproject staticmaps and forcing onto the IHU grid
  with `rioxarray.reproject_match` to a target DA built from
  `flw1.transform` and `flw1.shape`.

### Step 4 — fallback if IHU stays unviable

- Run the same script on a **larger-memory machine** where full-native
  ETH IHU (~80 M cells) is feasible — that yields the highest-quality
  acyclic ldd by construction.
- Or accept **10 / 11** as the final deliverable and treat ETH as a
  known out-of-scope case (already documented).

## Critical toolchain pins / paths

- Julia **1.10.x** (juliaup `+1.10`); Wflow **v1.0.2**; project
  `wflow-jl/julia_env`. **Never** use Julia 1.12 (JIT-hangs Wflow
  before timestepping).
- ERA5 forcing source: EarthDataHub via `~/.netrc` (`de_personal`
  token, in gitignored `wflow-jl/.env`).
- GEE key: `wflow-jl/.secrets/ee-service-account.json` (gitignored).
- Heavy outputs live on `/mnt/wflow-secondary/v4_models/`
  (~280 GB volume); the small home disk cannot hold them.

## Companion docs (do not duplicate; cross-reference)

- `SCIENCE_AND_METHODS.md` — what AET/PET/LDD/WRSI mean; the
  terrain-driven ldd-fix ladder.
- `V4_BASINS.md` — finalised basin selection per case.
- `V4_RUN_OVERVIEW.md` — per-case run-time + staticmaps/forcing/
  WRSI-output sizes + ldd-method tag.
- `ETH_BLOCK.md` — the deeper analysis of why ETH resists.
- `SIMULATION_WORKFLOW.md` — the operational living workflow.

## How to invoke this from a fresh Claude session

Paste this into the new context as your opening message:

> Continue the v4 ETH wflow rework. State, history, and exact next
> steps are in `wflow-jl/shared/hydrobasins/ETH_RESUME.md` — read it
> first, then run Step 1 (foreground `eth_ihu.py`, no timeout) and
> proceed from the captured traceback. 10/11 v4 WRSI is already
> done; only ETH remains.
