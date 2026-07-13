# ASAP → CRMA-BN: per-aspect implementation plan (plan-before-build)

**Status: PLAN ONLY. Nothing here is implemented.** This turns the four build
steps in `asap-crma-gap-and-bn-role.md` (§4) into implementation-ready specs,
each reviewable and buildable on its own. Every option is presented as: ASAP
anchor (with the exact thresholds pinned from `note.txt` + the schema PNG),
current-code touchpoints, the concrete change, data source (consumed, not
produced), self-tests, verification, non-goals, and a definition-of-done
checklist. Approve one, I build it, we verify, then the next.

Companion: `asap-crma-gap-and-bn-role.md` (the gap analysis this plans),
`../pipeline/drought_bn_ibf_v1.jl` (BN engine + the CDI template),
`../pipeline/wflow_wrsi_prep.py` (the `wrsi10` prep Option 1 extends).

---

## 0. Shared foundations (read once, applies to all options)

### 0.1 ASAP trigger semantics (pinned)
- A unit is warned when **> 25 % of the active area** shows a **large negative
  anomaly (Z-score < −1)** for ≥1 indicator. Z < −1 ≈ P(0.16) — a 1-in-6-year
  event. (note.txt L123.)
- **Active area** = crop OR rangeland fraction, from ASAP's 500 m Area-Fraction
  Image (% cover per class). (note.txt L114.)
- Indicators: **zWSI** (Z of Water Satisfaction Index for crops — the
  standardized WRSI analogue), **SPI3**, **zFPARc** (Z of cumulative FPAR from
  season start).
- **mFPARd guard:** `zFPARc` is critical only where `zFPARc < −1 AND
  mFPARd < −(10/100)·AVG(mFPAR)`. (note.txt L133.)
- **Phenology:** two phases — *expansion/maturation* vs *senescence*. In
  senescence, meteo-only → no warning; FPAR/convergence → level 4. (PNG.)

### 0.2 The CDI node is the exact template
Every "wire X as a BN node" below mirrors the committed CDI integration. The
seven touchpoints in `drought_bn_ibf_v1.jl` (all additive, backward-compatible,
default = no-op):
1. `X_STATES` constant (monotonic increasing-stress order).
2. `categorize_X(value|idx)` with NaN/missing → state 1 (no-op).
3. `compute_risk_probs(...; X=1)` — additive modifier + ≤2 expert rules.
4. `build_risk_cpt_tensor(; include_X)` — one extra tensor dimension.
5. `infer_soft_matmul_*` — one extra contraction loop.
6. `BoundaryInput` gains `X_idx` + `X_probs`; `process_boundary_*` threads it.
7. `run_csv` reads `X`/`X_p*` columns, `--X` flag, output column; self-tests.
CDI proved this end-to-end (8 self-tests; Alert lifted a boundary
Assess→Actionable_Risk). We reuse it verbatim.

### 0.3 ONE architecture decision to make before Option 1
Options 1–3 add three axes (`wrsi10`, `fpar`, `phenology`) on top of today's 7
parents. Two ways to carry them:

- **Approach A — flat parents (mirror CDI).** Each is another conditioning
  dimension on the matmul tensor. Simple, consistent, matches the note's
  "additive, not a rewrite." Tensor-size after all three:
  `5·5·3·3·4·6(cdi)·4(wrsi10)·4(fpar)·2(phase) = 1,382,400` cells × 5 risk ≈
  33 MB, ~7 M mults/boundary — fine for hundreds of basins, but growing.
- **Approach B — crop-stress sub-branch (divorce parents).** `wrsi10`+`fpar`
  (+phenology as its conditioner) form a small `crop_water_stress` node
  (≈4×4×2→4) that then modifies `risk`. Keeps the main tensor at 7-D; matches
  `../wrsi_bn_integration_plan.md`. More structure, less tensor growth.

**Recommendation:** start **Approach A** (Option 1 wires `wrsi10` flat, exactly
like CDI — lowest risk, reuses the proven template). Re-evaluate before Option 2:
if the tensor or CPT authoring feels unwieldy, switch the crop-side axes to
Approach B (a contained refactor, not a rewrite). This is the one decision I need
confirmed before building Option 1.

> **DECIDED (2026-07-11): Approach B.** The crop-side axes form a
> `crop_water_stress` sub-branch, phenology conditions it, and `agri_risk =
> f(met_risk, crop_water_stress)`. The existing 7-parent `risk` becomes
> `met_risk` (unchanged CPT); a new small `compute_crop_stress_probs` (4→4 for
> Option 1, 4×4→4 with fpar in Option 2, ×phase in Option 3) and
> `compute_agri_risk_probs(met_risk, crop_stress)` (5×4→5) are added. CRMA runs
> on `agri_risk`; `crma_state_met` is emitted alongside for comparison. Main
> met tensor stays 7-D. Also decided: cropland source = **ASAP 500 m crop
> AFI**; wrsi10 axis = **absolute FAO bands** for now (§0.4).

### 0.4 Standardisation note (affects Options 1 & 2)
ASAP triggers on **Z < −1** (standardized anomaly). Our `wrsi10` today is
**absolute** WRSI (100·ΣAET/ΣPET) binned on FAO bands (50/65/80). Two sub-
options, decided per node:
- **Keep absolute FAO bands** (simplest; agronomically interpretable). ✔ default.
- **Add a standardized `zWSI` variant** (WRSI Z-score vs a wflow climatology) to
  match ASAP's exact trigger — needs a multi-year wflow baseline per basin.
  Defer until a climatology exists; note it as a calibration upgrade.

---

## Option 1 — Cropland-fraction crosswalk + wire `wrsi10` as a BN node

> **✅ DONE (2026-07-13).** Built under Approach B, conforming to
> `bn-approach-b-crop-stress-subbranch.md` (the authoritative node spec).
>
> **Prep** — `wflow_wrsi_prep.py` crop-weights WRSI with the ASAP crop AFI
> (`/mnt/wflow-data/asap/asap_mask_crop_v04.tif`, EPSG:4326 500 m, value =
> crop % 0-100 — verified against Iowa/Punjab; **no ×0.5 scaling in v04**),
> emits `crop_active_frac` + crop-weighted `wrsi10_*` / `w10_p*`, and applies
> the CAF>25 % soft evidence-strength gate.
>
> **BN** — `crop_water_stress` (cws) + `agri_risk` per spec §3:
> * `compute_cws_probs(wrsi10, fpar, phase)` → 4-vector; `build_cws_cpt()` is
>   the 4×[4·4·3] = **192-entry** CPT. The ASAP-L3 convergence rung and the
>   FAO-33 `Ky` phenology modifier (Flowering amplifies / Maturation damps,
>   never creates stress) are pre-wired for Options 2–3.
> * `build_agri_cpt()` → 5×[5·4] = **100-entry** `AGRI_CPT[agri, risk, cws]`.
>   Fusion is the **sum rule** `Σ_{m,c} P(agri|risk,cws)·P(risk)·P(cws)`
>   (spec §5.1) — *not* an expected-shift heuristic.
> * **No-op guarantee (§3.2):** `cws = No_Stress` ⇒ `agri_risk == risk`
>   **exactly** (`_CWS_SHIFT[1] = 0.0`), mirroring the `cdi=1` / `tail=1`
>   guarantees. **Bounded (§3.2):** `cws = Severe` alone cannot lift a Minimal
>   met state to High/Extreme (no single-index basis risk).
> * In-degree stays inside RxInfer's 5-parent exact cap: `cws` has 3 parents,
>   `agri_risk` has 2.
>
> `--agri` flag adds `crop_stress`, `agri_risk_*`, `agri_risk_level`; CRMA runs
> on `agri_risk` with `crma_state_met` / `confidence_met` kept alongside.
> **15/15 self-tests pass** (9–14 agri; 15 entropy-confidence + verb-only
> ladder). `run_csv` driven end-to-end (`--tail-risk --cdi --agri`): no
> `action_*` columns, `crma_state ∈ {Monitor,Evaluate,Assess,Review}`.
> Verified on `runs/rwa_wrsi`: crop weighting moves basin WRSI (96.7 flat →
> 88.4 crop-weighted where cropland is patchy); with identical met evidence,
> `agri_risk_level` escalates Moderate→Extreme as wrsi10 goes No_Stress→Severe.
>
> **✅ Double-counting FIXED (2026-07-13).** `wrsi10` is wflow-derived from
> **observed** rainfall, so it shares an origin with `cur` (ERA5 SPI-3) and the
> precipitation term inside `cdi` — both on the met branch. Meeting at
> `agri_risk` under a constant upward push, one missing-rain signal would
> escalate the posterior **twice**. Fixed exactly where Approach B localises it:
> the 100-entry `AGRI_CPT` is now a **correlation-aware fusion column**, scaling
> the cws shift by `λ(m) = 1 − κ·(m−1)/4` (`κ = _SHARED_SIGNAL_KAPPA = 0.5`),
> so escalation shrinks as met_risk — which already counted that rain signal —
> rises. Escalation runs **1.50 → 1.31 → 1.12 → 0.94** across met=Minimal→High
> (self-test 16). Crucially the **divergence case is not discounted**: met
> Minimal + cws Severe keeps full escalation, because "rain looked fine but the
> water balance says the crop is failing" *is* wflow's marginal information.
> Both standing guarantees survive (self-test 17): exact identity at
> `cws=No_Stress`, and boundedness. **17/17 self-tests pass.**
>
> κ is a first-pass **expert** value, not a measurement — calibrate from the
> empirical `cws`↔`cur`/`cdi` correlation over the hindcast and log the revision.

**ASAP mechanism #1 (CAF > 25 %).** Anomalies counted only on active crop area;
warn when > 25 % of *active* area is anomalous. **Dependency: FIRST** — it
changes the spatial values every later node reasons over.

### 1a. Cropland weighting in `wflow_wrsi_prep.py`
- **Touchpoint:** `aggregate()`, currently
  `sel = (mask == r) & np.isfinite(wrsi)` then flat median / min / pixel-
  fraction `w10_p1..p4` / `stress_prob`.
- **Data (consumed):** an existing cropland Area-Fraction layer — ASAP's 500 m
  crop AFI, or an equivalent public cropland fraction (e.g. ESA WorldCover
  aggregated to fraction). Ingested as a `crop_frac` grid regridded to the WRSI
  grid. *We compute no new land-cover product.*
- **Change:**
  1. Load + regrid `crop_frac` to the WRSI grid (reuse the `rasterize_basins` /
     regrid pattern already in the prep and `cdi_data_prep.py`).
  2. Crop-fraction-weighted reduction per basin: weighted median (or weighted
     mean) of WRSI using `crop_frac` as pixel weight; soft bins `w10_p1..p4`
     become crop-fraction-weighted class shares.
  3. New columns: `crop_active_frac` (basin mean crop fraction),
     `wrsi10_crop_stressed_share` (crop-weighted fraction with WRSI < 80).
  4. **CAF>25% as a soft evidence-strength gate:** if `crop_active_frac` is
     low, shrink `w10_p*` toward uniform (weak evidence → BN no-op), rather than
     a hard drop — the Bayesian analogue of ASAP's active-area threshold.
- **Non-goals:** no change to the WRSI definition; no new anomaly. Purely
  *where-measured* + *how-weighted*.
- **Verify:** re-run on `runs/rwa_wrsi`; show crop-weighted vs flat WRSI differ
  where cropland is patchy; confirm low-crop basins get near-uniform `w10_p*`.

### 1b. Wire `wrsi10` into `drought_bn_ibf_v1.jl` (the 7 CDI touchpoints)
- `WRSI10_STATES = ["No_Stress","Mild","Moderate","Severe"]` (idx1..4).
- `categorize_wrsi10(v)` — FAO bands (≥80→1, 65–80→2, 50–65→3, <50→4); NaN→1.
  (Mirrors the Python `classify_wrsi` already in the prep.)
- `compute_risk_probs(...; wrsi10=1)`: additive modifier (Severe +0.55, Moderate
  +0.30, Mild +0.10, No_Stress 0 — same shape as the CDI modifier) + 1 expert
  rule (Severe WRSI + High forecast deficit → escalate toward Extreme).
- Tensor/matmul: `include_wrsi10` dimension (Approach A) → `infer_soft_matmul_agri`.
- `BoundaryInput` + `run_csv`: read `wrsi10_class`/`wrsi10_value` (join on
  `id=HYBAS_ID`) + soft `w10_p1..p4`; `--wrsi10` flag; `wrsi10_class` output.
- **Self-tests:** wrsi10=1 no-op; Severe escalates P(High∪Extreme); matmul==direct.
- **Verify:** synthetic CSV — same met inputs, Severe vs No_Stress wrsi10 moves
  the CRMA state (exactly the CDI end-to-end test we already ran).

**DoD:** crop-weighted `wrsi10` CSV feeds the BN via `--wrsi10`; all self-tests
pass; end-to-end demonstration on a real WRSI grid.

---

## Option 2 — FPAR / vegetation-response node

> **✅ DONE (2026-07-13).** `fpar_prep.py` + the `fpar` axis on the crop branch.
>
> **Data** — GDO fAPAR anomaly (`gdo_fpar_icechunk`, var `fpanv`, dekadal
> 2012→now), the `zFPARc` analogue. Crop-fraction-weighted with the same ASAP
> crop AFI and HydroBASINS boundaries as `wrsi10`, so the two align row-for-row.
> Consumed, not produced.
>
> **`fpar` has 5 states, not 4** — `Unknown` is explicit. "No vegetation
> evidence" and "vegetation observed healthy" are different propositions: the
> first must be a strict no-op; the second is *positive* evidence that the crop
> has not yet responded to a water deficit (ASAP L1) and must **temper** it. A
> 4-state Healthy-default would silently turn missing data into a tempering
> claim.
>
> **`compute_cws_probs` is graded, not `max()`.** The first cut used
> `base = max(w10, fpar)`, which SATURATES: with either axis Severe the other
> added nothing, and ASAP's L1/L2/L3 rungs all collapsed to one. Replaced with
> `s = α·w + β·f + γ·min(w,f)` (α=0.70, β=0.80, γ=0.25), interpolated smoothly
> onto the cws states. **β > α by design**: vegetation is *realised impact*, a
> water deficit only a precursor — which is exactly why ASAP ranks FPAR-only
> (L2) above meteo-only (L1). Scores are interpolated, not hard-binned, or a Ky
> re-weighting that doesn't cross a state boundary would vanish.
>
> **Verified — the ASAP ladder now reproduces end-to-end** (identical met):
> L0 neither → agri P(H∪E) **0.350 = met exactly** (no-op); L1 meteo-only
> (veg observed healthy) → 0.582; L2 fpar-only → **0.731** (outranks L1); L3
> both → **0.847**. Self-test 18 asserts `L1 < L2 < L3` and that observed-healthy
> veg ranks below the same deficit with no veg data. **18/18 pass.**
>
> ⚠️ **`mFPARd` guard is NOT active by default.** ASAP flags a pixel critical
> only when `zFPARc < −1 AND mFPARd < −10%·AVG(mFPAR)` — the second condition
> suppresses false positives where inter-annual FPAR variability is tiny. It
> needs **raw** FPAR + its historical mean; the GDO store carries only the
> anomaly, so it cannot be computed from it. Pass `--mfpard-nc` +
> `--mfpar-avg-nc` to switch the exact guard on; otherwise the run says so
> loudly. Crop weighting confines the signal to cropland (removing most of the
> arid low-variability pixels the guard targets) but does **not** replace it.
>
> ✅ **Vegetation double-count handled structurally.** The JRC CDI's Alert
> classes (7–10) *already require* `fAPAR < −1` — the same signal. `cdi` is on
> the met branch, `fpar` on the crop branch; they meet at `agri_risk`, so both
> together would count vegetation twice (the same bug class as wrsi10↔cur).
> Fix: build CDI with `cdi_data_prep.py --fapar-source none`, so CDI carries
> only precipitation + soil moisture and the vegetation evidence lives solely in
> the separable `fpar` node. `run_csv` reads CDI's `fapar_source` provenance and
> **warns loudly** if `--fpar` is used against a fAPAR-bearing CDI.
>
> **Also fixed (bug found in Option 1):** `wflow_wrsi_prep.py` blended no-data /
> thin-crop basins toward a *uniform* `w10_p*`, which puts 3/4 of the mass on
> stressed states — escalating the posterior purely for lack of data. Both preps
> now route that mass to the node's identity state (`No_Stress` / `Unknown`).

**ASAP mechanism #2 (the `zFPARc` rung).** Escalation from "deficit possibly
evolving into poor growth" (meteo) to "evidence of poor growth" needs an
independent plant-response signal. **Dependency: after Option 1.**

### 2a. FPAR prep → `fpar_prep.py` (new, small)
- **Data (consumed):** ASAP's existing `zFPARc` and `mFPARd` anomalies (public,
  already computed) — OR the GDO fAPAR store already used by `cdi_data_prep.py`
  (`gdo_fpar_icechunk`, var `fpanv`). Reuse `cdi_data_prep.py`'s openers +
  zonal reducer.
- **Change:** per basin, compute the crop-fraction-weighted share with
  **`zFPARc < −1 AND mFPARd < −0.10·AVG(mFPAR)`** (the exact ASAP guard) →
  `fpar_stressed_share`; bin a `fpar_class` (4 states) + soft `fp_p1..p4`.
- **Non-goals:** no FPAR retrieval; no MODIS/VIIRS processing.

### 2b. Wire `fpar` into the BN (7 touchpoints)
- `FPAR_STATES` (4, monotonic), `categorize_fpar`, modifier + a **convergence
  expert rule**: `fpar` stressed **AND** (`wrsi10` or `def`) stressed escalates
  harder than either alone — the Bayesian analogue of ASAP level-3 "both
  firing". This is the payoff of a *separable* veg axis (CDI carries veg only
  compositely).
- Tensor/matmul dimension (Approach A) or the `crop_water_stress` sub-branch
  (Approach B, if switched at the 0.3 checkpoint).
- Self-tests: fpar no-op; convergence rule escalates beyond single-axis.
- **Verify:** three synthetic rows — meteo-only, fpar-only, both — reproduce
  ASAP's level 1 / 2 / 3 ordering in the CRMA state.

**DoD:** `fpar` node live with the mFPARd guard; convergence rule tested;
ASAP L1/L2/L3 ordering reproduced.

---

## Option 3 — Phenology gating

**ASAP mechanism #3 (expansion vs senescence).** Same anomaly → different
warning by phase; irreversible at flowering. **Dependency: LAST** — it modulates
how Option-1/2 nodes combine.

### 3a. Growth-stage tracker → `phenology.py` (new, light lookup)
- **Data (consumed):** existing planting-window data + degree-days (concept doc
  §7.2). A lookup, **not** a model run.
- **Change:** per zone×crop×date → `phase ∈ {expansion, senescence}` (start
  minimal, 2 phases, exactly like ASAP); later refine toward FAO-33 `Ky` stage
  weights.

### 3b. Wire `phenology` as a *conditioner* (not a stress axis)
- `PHENO_STATES = ["Expansion","Senescence"]`. Unlike wrsi10/fpar, phenology is
  a **conditioning** variable: it changes *how* `wrsi10`/`fpar` enter
  `compute_risk_probs`, not a stress level itself.
- Rule (from the PNG): in **senescence**, meteo-only stress → damped (no
  escalation, ASAP "-"); FPAR/convergence → hold at a high level (ASAP L4). In
  **expansion**, full escalation.
- Implementation: cleanest under **Approach B** (phenology conditions the
  `crop_water_stress` sub-branch). Under Approach A it is a 2-state tensor
  dimension that reweights the wrsi10/fpar modifiers — heavier; a reason the
  0.3 checkpoint may flip to B before Option 3.
- Self-tests: identical WRSI/FPAR, expansion vs senescence → different CRMA
  state, matching the PNG's phase columns.

**DoD:** phase-conditioned escalation reproduces the PNG's expansion-vs-
senescence columns; the "stage-timed prescription" claim in the concept doc is
now real.

---

## Option 4 — TAMSAT `wrsi_seas` (orthogonal, parallelisable)

Feeds the **monthly strategic** layer; independent of 1–3 (the dekadal tactical
layer). Status today: schema pinned (`tamsat_alert_probe.py`), no prep, no node.

- **4a. `tamsat_alert_prep.py`** — run/ingest TAMSAT-ALERT_API_V2 (`-weights=
  ECMWF_S2S`) → per-zone `wrsi_seas_prob_below` (lower-tercile prob, reuse
  `categorize_deficit`), `wrsi_seas_pct_normal`, `wrsi_seas_ens_min`. Schema
  already frozen by the probe.
- **4b. Wire `wrsi_seas`** as a BN node (7 touchpoints); `prob_below` reuses the
  `def` categoriser, so minimal new binning.
- **Double-counting control:** `wrsi_seas` (TAMSAT, S2S-weighted) and `def`/
  `tail` (SEAS5) share the SEAS/S2S driver → discount at the CPT (or the
  `crop_water_stress` node under Approach B), per `../wrsi_bn_integration_plan.md`.
- **Can start now**, in parallel with Option 1.

---

## Sequencing & what I need to proceed

```
Option 1 (crop-weight + wire wrsi10)  ── must be first
        └─► Option 2 (fpar node)      ── after 1
                └─► Option 3 (phenology conditioning) ── last
Option 4 (wrsi_seas)  ── parallel, any time
```

**Decisions I need before building Option 1:**
1. **Architecture:** confirm **Approach A** (flat parents, mirror CDI) to start,
   with a re-check before Option 2 (§0.3). — *my recommendation.*
2. **`wrsi10` axis:** keep **absolute FAO bands** now, defer the standardized
   `zWSI` variant until a wflow climatology exists (§0.4). — *my recommendation.*
3. **Cropland source for Option 1a:** ASAP 500 m crop AFI vs ESA WorldCover
   fraction — whichever you can point me at; I'll wire whichever is available.

On confirmation I build **Option 1** end-to-end (crop-weighting in the prep +
`wrsi10` as a BN node + self-tests + a real-grid demonstration), present the
result, and only then move to Option 2. Each option ships as its own commit with
passing self-tests, exactly as the CDI node did.
```
