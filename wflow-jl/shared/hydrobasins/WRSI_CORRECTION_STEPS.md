# Correcting the non-representative v4 WRSI runs — steps & methodology

How the v4 wflow→WRSI runs were checked against their documented drought
loss-and-damage events, what was found to be **non-representative**, and the
exact steps taken to correct each case. Companion to `WRSI_EVENT_EVAL.md`
(results/verdicts) and `ETH_BLOCK.md` (the ETH ldd story).

WRSI here = `100·ΣAET/ΣPET` (Kc=1 water balance), basin-mean, clipped to the
case's `_v4_basin.geojson`. The drought signal is the **year-over-year drop
within a basin** (a dry year suppresses AET vs PET); absolute WRSI between
countries reflects aridity, not severity.

---

## 1. Diagnosis — how non-representativeness was found

`eval_wrsi_events.py` computes **per-year** basin-mean WRSI + ΣAET/ΣPET for each
case and lines it up against the event's documented region + period
(icpac-igad/DevOps-hazard-modeling#drought-events). A run is *representative* if
WRSI drops in the event year(s) relative to a baseline, **in the basin that
matches the event's named region**. That surfaced four failure modes:

| Failure mode | Cases | Symptom |
|--|--|--|
| Degenerate output | SOM, SSD | `output_grid_wrsi.nc` had `time=0` (interrupted by the concurrent build batch — OOM on the shared 8 GB VM) |
| Wrong basin (region mismatch) | TZA, SSD, SDN, UGA | modeled a different basin than the event region → diluted/irrelevant signal |
| No baseline year | BDI, RWA | run window = event years only, so no pre-event year to measure a dip against |
| (already fine) | DJI, ERI, ETH, KEN | correctly-timed signal in the right basin |

---

## 2. Correction methodology (per case)

Each correction is built **alongside** the original (non-destructive: new case
dir under `/mnt/wflow-secondary/v4_models/<case>/`, originals untouched). Full
pipeline, all idempotent-ish:

1. **Basin select** — resolve a HydroBASINS unit/basin for the event region via
   `select.py` helpers (`_snap_outlet` / `_smart_snap` + `_bfs_upstream`) →
   write `outputs_v4/<stem>_v4{,_basin}.geojson`.
2. **Static** — `../hazard-model-api/` steps (download_dem/worldcover/
   merit_hydro/soilgrids → `prepare_wflow_staticmaps` → `fix_ldd_pyflwdir`) for
   the bbox → `staticmaps.nc` (GEE service-account key).
3. **Repair** — `repair_v4_staticmaps` median-fills soil/river NaN; verify the
   `wflow_river` mask is ldd-consistent (river-cycle violations = 0 — always
   true on a fresh build, since ldd + river come from the same step).
4. **Forcing** — subset EDH ERA5 (tp/t2m/pev) to bbox+window, hourly→daily,
   interp onto the staticmaps grid → `forcing.nc`.
5. **Run** — generate `wflow_v4.toml` (repoint dir + window), run Wflow v1.0.2
   on Julia 1.10 → `output/output_grid_wrsi.nc`.
6. **Eval + publish** — per-year WRSI vs event; plots (`plot_v4_wrsi`); upload
   plots + grid + geojson to HF `E4DRR/wflow.jl-simulations`.

Drivers: `build_tza_kagera.py`, `build_ssd_upper_nile.py`, and the
parameterized `build_v4_correction.py` (uga_karamoja / bdi_baseline /
rwa_baseline / sdn_eastern).

---

## 3. Corrections carried out

**Degenerate re-runs (SOM, SSD).** Re-ran the originals **sequentially** (one at
a time, full ~6 GB headroom) instead of the concurrent batch that OOM'd them.
SSD 11 h11 m → 7.25 GB; SOM 22 h25 m → 11.7 GB; both valid (`time>0`). SOM then
**strongly** reproduced the 2020-23 South-Central drought (WRSI 36→14→12→29).

**Basin corrections (build alongside):**

| Case | Original basin | → Corrected basin (case) | Window | Result |
|--|--|--|--|--|
| TZA | Pangani (NE) | Kagera NW lev-6 `tza_kagera` | 2020-23 | 75→56→53→61 — representative |
| SSD | Bahr el Ghazal (NW) | Sobat/Nasir lev-5 `ssd_upper_nile` | 2020-23 | 42→28→28→21 — representative |
| SDN | Sennar/L. Blue Nile | Kassala/Gash lev-5 `sdn_eastern` | 2020-23 | 25→9→9→7 — representative (arid) |
| UGA | Lake Kyoga (lev-5, lumps wet Kyoga + dry Karamoja) | Karamoja proper lev-6 `uga_karamoja` | 2020-23 | 79→30→33→29 — **strong** (biggest gain) |

**Baseline re-runs (BDI, RWA).** Same basins, extended windows for a pre-event
baseline: `bdi_baseline` 2020-23 (74→72→71→76, **flat** → confirmed genuinely
weak) and `rwa_baseline` 2014-17 (76→69→67→67, mild). These prove the humid
Great-Lakes weakness is real (no ERA5 deficit), not a missing-baseline artifact.

---

## 4. Technical issues hit (and fixes)

- **ETH ldd "cycles in flow graph".** Not the land ldd (it was acyclic) — the
  **river** subnetwork: `Wflow.NetworkRiver.flowgraph` wires each river cell's
  downstream via `searchsortedfirst` with no membership check, so a river cell
  pointing in-grid to a NON-river cell makes a spurious edge → cycle. Cause: the
  ldd had been rebuilt but `wflow_river` left stale. Fix `eth_river_fix.py`:
  downstream-closure of the river mask (every river cell is a pit or drains to a
  river cell). Fresh builds don't need this (ldd+river from the same step).
  Full story in `ETH_BLOCK.md`.
- **SOM/SSD degenerate `time=0`.** Concurrent-batch OOM on the 8 GB VM. Fix: run
  one model at a time.
- **juliaup config-lock hang.** `julia +1.10` routes through the juliaup
  launcher, which takes a config lock; a hung `juliaup self update` held it for
  >22 h and silently blocked a run ("Juliaup configuration is locked…"). Fix:
  kill the hung `juliaup self update`/`_post-update`, and launch via the
  **direct binary** `~/.julia/juliaup/julia-1.10.11+0.x64.linux.gnu/bin/julia`
  (no `+1.10`).
- **`PCR_DIR[255]` BoundsError in `NetworkLand` (sdn_eastern).** A unit-basin in
  a large bbox leaves nodata-`ldd=255` edge cells. `repair_v4_staticmaps` writes
  `_FillValue:None`, so the out-of-basin `subcatch` NaN isn't seen as `missing`
  and Wflow treats the whole bbox as active, hitting `ldd=255` → out-of-range.
  Fix: set `ldd 255→pit(5)` (now in `build_v4_correction.py` phase 3). WRSI is
  clipped to the basin polygon, so the extra edge pits don't affect results.
- **Memory-safe reads.** The big grids (7-12 GB) OOM a naive full-array load;
  `plot_v4_wrsi`/`eval_wrsi_events` open with `chunks={"time": …}` so
  Σ/mean-over-time stream in blocks.

---

## 5. Outcome

All basin/region mismatches are corrected and the degenerate runs are valid.
Final tally across the 11: **strong** = DJI, ERI, KEN, SOM, UGA✎ ·
**representative** = SSD✎, SDN✎, TZA✎ · **good** = ETH · **weak (confirmed real,
humid)** = BDI, RWA. (✎ = corrected this session.)

- Per-country results + the regenerated overview table: `WRSI_EVENT_EVAL.md`
- Overview map of the final basins: `plot_v4_overview.py` →
  HF `v4_wrsi_plots/overview_v4_corrected.png`
- Build reproducers: `build_tza_kagera.py`, `build_ssd_upper_nile.py`,
  `build_v4_correction.py`
- HF artifacts per case: `v4_wrsi_plots/<case>_*`,
  `wflow_runs/<case>_wrsi/output/output_grid_wrsi.nc`,
  `hydrobasins/v4/<stem>_v4*.geojson`
