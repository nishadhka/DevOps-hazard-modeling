# ASAP ↔ CRMA-BN: what ASAP is, what it is missing, and the role of the
# Bayesian network — *a fusion layer, not a new remote-sensing product*

**Purpose.** This document sits beside `note.txt` (the ASAP / East Africa
Agriculture Warning Explorer field notes) and `warning_levels_schema_6.png`
(ASAP's warning-classification table). It does three things:

1. States precisely **what ASAP already does** and, from a smallholder /
   continuous-risk standpoint, **what it structurally cannot do**.
2. Maps that to the three near-term build steps (options 1–3) and shows **how
   the current CRMA plan addresses each gap** — grounded in the code as it
   stands today, not as the README aspires.
3. Fixes the framing that must not drift: the CRMA-BN is a **curatorial fusion
   and reasoning layer over evidence ASAP and others already produce**. We are
   **not** proposing a new satellite product, a new anomaly index, or a rival
   to ASAP / AgricultureWatch.

Companion reading: `../continuous-risk-monitoring-agri-advisory.md` (the
curatorial-science direction), `../wflow_hazard_evidence_chain.md` (wflow.jl at
the spine), `../pipeline/drought_bn_ibf_v1.jl` (the BN engine), and
`../pipeline/wflow_wrsi_prep.py` (the `wrsi10` prep this plan extends).

---

## 0. Ground truth — the committed code today (so the plan is honest)

Read before planning; the README status table is aspirational, the code is not.

**BN engine (`drought_bn_ibf_v1.jl`).** `compute_risk_probs` conditions the
`risk` posterior on exactly seven parents:

| Parent | States | Source |
|---|---|---|
| `current_spi3` (`cur`) | 5 | ERA5 SPI-3 observation |
| `deficit` (`def`) | 5 | SEAS5.1 forecast deficit probability |
| `spatial` (`spa`) | 3 | SPI spatial coverage fraction |
| `trend` (`trn`) | 3 | SPI-3 trend (slope) |
| `agreement` (`agr`) | 3 | SEAS5.1 ensemble agreement |
| `tail` | 4 | worst-case ensemble-min SPI |
| `cdi` | 6 | JRC Combined Drought Indicator |

`risk` (5 states) → CRMA state (`Monitor → Evaluate → Assess → Actionable_Risk`)
via the cost-loss rule in `compute_crma_state`.

**What is NOT in the BN yet:** `wrsi10` (dekadal crop-water stress),
`wrsi_seas` (TAMSAT seasonal), any FPAR / vegetation-response node, and any
phenology / growth-stage conditioning. `spatial` is *SPI* coverage — it is
**not** a cropland fraction.

**WRSI prep (`wflow_wrsi_prep.py`).** Produces the `wrsi10` CSV from a wflow.jl
`output_grid_wrsi.nc`, but `aggregate()` reduces over **every finite pixel in
the basin** (`sel = (mask == r) & np.isfinite(wrsi)` → median / min / pixel-
fraction soft evidence). There is **no cropland mask, no crop-area-fraction
weighting, and no active-area (>25%) gate.** The output node is also not yet
consumed by the BN.

**Bottom line:** options 1–3 are all *unimplemented*. This is a forward plan,
and the three steps have a hard dependency order (see §5).

---

## 1. What ASAP *is* (from the PNG schema + note.txt)

ASAP — and the ICPAC–JRC East Africa Agriculture Warning Explorer built on the
same engine — is a **remote-sensing anomaly-classification system**. Its
warning logic (the PNG) has three moving parts, and all three are things the
CRMA should learn from, because they encode real agronomic wisdom:

1. **Cropland / rangeland masking with an active-area gate ("CAF > 25 %").**
   Anomalies are only counted where they fall on active crop or rangeland
   pixels (a 500 m Area-Fraction Image of % crop / % rangeland), and a warning
   fires only when the anomalous share exceeds **25 % of the unit's active
   area**. The land-cover fraction is the *denominator* of the whole system.

2. **Evidence-tier laddering (convergence, not a single index).**
   - Meteo-only anomalies (`zWSI`, `SPI3`) → level **1 / 1+**
     — *"water deficit possibly evolving into poor growth."*
   - Vegetation-response anomaly (`zFPARc`, guarded by `mFPARd`) → level **2**
     — *"evidence of poor growth."*
   - Meteo **and** vegetation converging → level **3 / 3+**
     — *"poor growth & negative prospects."*

3. **Phenology gating.** The same indicator combination yields a different
   warning in *expansion / maturation* vs *senescence* (where the schema
   collapses everything to level 4 — the crop is past the point of
   intervention).

ASAP is genuinely excellent at this. It is continental, operational, dekadal,
and free. **We consume it; we do not rebuild it.**

---

## 2. What ASAP is *missing* (the gaps CRMA exists to fill)

These are not criticisms of ASAP — they are outside ASAP's design envelope. A
continuous, per-field, dual-hazard, insurance-grade advisory needs them; a
continental anomaly-classifier does not.

| # | Gap in ASAP | Why it matters for smallholder CRMA |
|---|---|---|
| G1 | **No physical / causal hydrology.** ASAP classifies *observed anomalies* against a historical distribution. It has no water-balance model of the catchment — it cannot route water, represent soil storage, or say *why* a deficit is occurring. | wflow.jl gives an **ontological** water balance: the same distributed model yields the dry tail (WRSI) *and* the wet tail (discharge/flood) for one field, from one causal mechanism. |
| G2 | **Single hazard.** ASAP is a drought/growth-anomaly system. It has no flood / waterlogging tail. | A smallholder plot faces dry spells *and* washout in one season. CRMA carries both as evidence into **one** `agri_risk` posterior. |
| G3 | **Diagnosis without forecast horizon.** ASAP's forward look is a single 10-day rainfall forecast; there is no probabilistic seasonal outlook. | TAMSAT-ALERT (seasonal WRSI) + SEAS5.1 give the **strategic prior**, continuously corrected by the dekadal reality — the two-horizon design in the concept doc §4.2. |
| G4 | **Classification, not a recomputable posterior.** ASAP outputs a warning level from a fixed lookup table. It is not an auditable, contestable, per-stakeholder probability object. | The BN posterior is **recomputable and logged**: a farmer, insurer, or regulator can rerun it, remove a stream, and see why the state moved — the basis-risk / trigger-integrity argument (concept doc §6). |
| G5 | **No local memory / calibration loop.** ASAP thresholds are global-harmonised (that is its job). It does not learn *this* region's agronomy. | The BN's CPT is version-controlled institutional memory: verified local outcomes update parameters over seasons (concept doc §3). |
| G6 | **Unit-scale, not action-scale.** ASAP warns at GAUL-1/2 units. It is not a per-crop, per-growth-stage prescription. | CRMA separates diagnosis (BN) from prescription (crop-stage impact → advisory), gating expensive models on confidence (concept doc §5). |

**The symmetry that defines the build:** ASAP holds three mechanisms we lack
(§1: cropland masking, evidence laddering, phenology gating). We hold six
capabilities ASAP lacks (G1–G6). Options 1–3 are precisely the act of
**importing ASAP's three mechanisms into a framework that also has G1–G6** —
so the result is ASAP's agronomic discipline expressed as a causal,
dual-hazard, auditable, learning posterior.

---

## 3. The role of the BN — *fusion layer, not a new product* (read this twice)

The single most important framing, and the one most likely to drift:

> **The CRMA-BN produces no new pixels.** It ingests evidence that already
> exists — ASAP/JRC anomalies, CHIRPS/IMERG rainfall, ERA5, SEAS5.1,
> TAMSAT-ALERT, the JRC CDI, and the one genuinely model-derived stream,
> wflow.jl hydrology — and fuses them into a single recomputable risk
> posterior with an audit trail. Its contribution is **epistemic
> (how evidence is weighed, recorded, and verified)**, not **observational
> (a new sensor or index).**

Concretely, what the BN *is* and *is not*:

- **Is:** a Bayesian fusion + reasoning engine (`compute_risk_probs` → CPT →
  RxInfer/matmul → CRMA state). A curatorial institution with memory (the CPT),
  an audit trail (logged evidence admission), and a verification loop.
- **Is not:** a remote-sensing pipeline. It never computes an anomaly from raw
  imagery. Even wflow.jl — the one thing we *do* run — is a physical model
  consuming existing forcing, not a new EO product.

**Why this framing is load-bearing for the three worries you raised
(complex / sustainable / cost-effective):**

- **Complexity stays bounded** because every option below is *one more evidence
  node or one more conditioning axis on an existing 7-parent CPT* — additive,
  not a rewrite. The engine already demonstrates the pattern (CDI was folded in
  as a 6-state parent with a matmul fallback and 8 passing self-tests).
- **Sustainability holds** because we do not operate a continental EO system —
  ASAP does, and we consume it. Our only heavy compute is wflow.jl, which the
  architecture runs **selectively** (gate: physics only where cheaper streams
  already raise confidence).
- **Cost stays low** for the same reason: the expensive tail (wflow.jl, crop-
  impact models) sits behind cheap always-on evidence (SPI, CDI, ASAP
  anomalies, TAMSAT seasonal). Most zones sit in `Monitor` and cost ~nothing.

If at any point the plan starts *reproducing* an ASAP-like anomaly product
instead of *consuming* it, that is the signal we have left the fusion-layer
lane — and complexity, cost, and sustainability all break at once.

---

## 4. The three build steps — ASAP mechanism → CRMA implementation

Each option imports one ASAP mechanism (§1) into the BN, while keeping the
fusion-layer discipline (§3). For each: the ASAP anchor, the current-code gap,
the concrete change, and what it explicitly does **not** add.

### Option 1 — Cropland-fraction crosswalk (ASAP mechanism #1: CAF > 25 %)

**ASAP anchor.** Anomalies counted only on active crop pixels; unit flagged
only when > 25 % of active area is anomalous.

**Current-code gap.** `wflow_wrsi_prep.py::aggregate()` reduces WRSI over *all*
basin pixels — a rangeland-heavy or bare basin dilutes (or fabricates) the crop
signal. `wrsi10` is basin-uniform, not crop-weighted, and not yet a BN node.

**Change (fusion-layer, no new product).**
1. Ingest an **existing** cropland Area-Fraction layer (ASAP's own 500 m crop
   AFI, or an equivalent public cropland fraction) — *consumed, not computed*.
2. In `aggregate()`, replace the flat pixel reduction with a **crop-fraction-
   weighted** reduction: weight each pixel's WRSI by its crop fraction when
   forming the basin median / soft-evidence vector `w10_p1..p4`, and compute a
   `crop_active_frac` per basin.
3. Emit an ASAP-style **active-area stressed share** (fraction of *crop* area
   with WRSI < 80) and carry the CAF>25% idea as a soft gate on the `wrsi10`
   evidence strength (low crop area → weak/near-uniform evidence, a BN no-op).
4. Wire `wrsi10` as a BN parent (mirror the CDI integration: a monotonic
   stress axis, `categorize_wrsi10`, a modifier in `compute_risk_probs`, and a
   `cdi=1`-style no-op default so absence changes nothing).

**Does NOT add:** any new anomaly computation; any change to how WRSI itself is
defined (still `100·ΣAET/ΣPET` from wflow.jl). Purely a *where-measured* +
*how-weighted* + *wire-as-node* change.

**Dependency:** must come **first** — it changes the spatial values every later
node reasons over.

### Option 2 — FPAR / vegetation-response node (ASAP mechanism #2: the zFPARc rung)

**ASAP anchor.** The escalation from "deficit possibly evolving into poor
growth" (meteo only) to "evidence of poor growth" requires an **independent
plant-response** signal — `zFPARc`, guarded by `mFPARd` to suppress
low-variability false positives.

**Current-code gap.** Every BN parent today is water-side (SPI, WRSI, deficit,
tail) or a composite (CDI). There is no explicit, independent vegetation-
response axis, so the BN cannot represent ASAP's level-2/3 distinction
natively.

**Change (fusion-layer, no new product).**
1. Ingest ASAP's **existing** FPAR anomaly (`zFPARc` / `mFPARd`) — public,
   already computed. *Consumed, not produced.*
2. Add a `fpar` (or `veg_response`) BN parent, monotonic-stress, with the same
   `mFPARd`-style guard ASAP uses (only flag critical when the mean FPAR
   difference is also materially below normal).
3. Give it a convergence modifier in `compute_risk_probs`: FPAR-confirmed
   stress + meteo stress escalates harder than either alone — the Bayesian
   analogue of ASAP's level-3 "both firing" rung.

**Does NOT add:** a new FPAR retrieval; we do not touch MODIS/VIIRS processing.
Note the CDI node already carries *some* vegetation signal compositely — the
value here is an **independent, separable** axis so convergence is explicit and
auditable, not hidden inside a composite.

**Dependency:** after Option 1 (so FPAR conditions correct crop-weighted
values).

### Option 3 — Phenology gating (ASAP mechanism #3: expansion vs senescence)

**ASAP anchor.** The same anomalies mean different warnings by phenological
phase; sensitivity is stage-dependent and irreversible at flowering.

**Current-code gap.** `--mode dekadal` accumulates season-to-date WRSI but has
no growth-stage awareness; the BN interprets a deficit identically regardless
of stage.

**Change (fusion-layer, no new product).**
1. Build a per-zone, per-crop **growth-stage tracker** from *existing*
   planting-window data + degree-days (concept doc §7.2) — a light lookup, not
   a model run.
2. Start minimal, exactly as ASAP's schema does: two phases
   (*expansion/maturation* vs *senescence*), later refined toward the FAO-33
   `Ky` stage weights in concept doc §4.1.
3. Use the stage as a **conditioning variable** on how `wrsi10` (and `fpar`)
   enter `compute_risk_probs`: a flowering-stage deficit escalates; a maturity-
   stage deficit is damped. This is the piece that turns diagnosis into
   *stage-timed* prescription.

**Does NOT add:** any crop-model run per pixel; the tracker is a phenology
lookup, and the expensive crop-impact model still runs only at CRMA ≥ `Assess`.

**Dependency:** last — it modulates how the Option-1 and Option-2 nodes already
combine.

---

## 5. Why all three, in order 1 → 2 → 3 (not one, not any order)

All three live inside the ASAP schema, but they are three *different structural
pieces* of it and cannot be collapsed:

| ASAP schema element | Pipeline piece it becomes | Option |
|---|---|---|
| CAF > 25 % active-area masking | crop-fraction weighting in the `wrsi10` prep | 1 |
| `zFPARc` "evidence of poor growth" rung | independent FPAR BN node | 2 |
| expansion vs senescence columns | phenology conditioning of WRSI/FPAR | 3 |

The order is forced by dependency, not preference:

1. **Option 1 first** — it fixes *where and how* evidence is measured (crop
   pixels, crop-weighted). Every later node reasons over these values, so doing
   it first means 2 and 3 are built on correct numbers.
2. **Option 2 second** — adds the independent vegetation *axis* that lets the
   BN express ASAP's meteo→veg convergence. Standalone once crop-weighting
   exists.
3. **Option 3 last** — the *conditioning* that makes both WRSI and FPAR mean
   the right thing at the right stage.

**Option 4 (TAMSAT `wrsi_seas`) is orthogonal** to 1–3: it feeds the *monthly
strategic* layer (ICPAC-style monthly advisory), while 1–3 harden the *dekadal
tactical* layer (the AgricultureWatch-style 10-day product). It can proceed in
parallel. Its current status: schema pinned (`tamsat_alert_probe.py`), **no**
prep script, **no** BN node — i.e. ~one-third done, not done.

---

## 6. Net assessment (complexity / sustainability / cost)

- **Complexity: manageable.** Each option is one additive node or conditioning
  axis on a proven 7-parent CPT with a matmul fallback and a self-test harness.
  The CDI integration is the template; nothing here is a rewrite.
- **Sustainability: yes, if wflow.jl stays gated.** The one operational
  fragility is wflow.jl runs (partial/corrupt `output_grid_wrsi.nc` under
  concurrent batches — see project memory). Sustainability depends on running
  physics *selectively* (only at CRMA ≥ `Assess`) and hardening the WRSI I/O,
  **not** on operating any EO system — because we consume ASAP/FPAR/CHIRPS
  rather than produce them.
- **Cost: favourable by design.** Expensive compute sits behind cheap,
  always-on evidence; most zones idle in `Monitor`. The gate is the cost lever,
  and it is already the architecture.

**Conclusion.** The git-committed CRMA can be enhanced into an
AgricultureWatch-grade dekadal product **plus** a monthly advisory, and it will
be *more* capable than ASAP (adds G1–G6: causal hydrology, flood tail, seasonal
forecast, auditable posterior, local memory, action-scale prescription) — **so
long as it remains a fusion layer over existing evidence and never becomes a
new remote-sensing product.** Import ASAP's three mechanisms (options 1→2→3),
keep diagnosis and prescription separate, keep wflow.jl selective, and add
evidence nodes incrementally. On those terms it is buildable, sustainable, and
cost-effective on the pipeline already committed.
