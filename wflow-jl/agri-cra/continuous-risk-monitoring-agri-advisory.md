# Continuous Risk Monitoring for Smallholder Agricultural Advisory

**Role and direction of the CRMA-BN as a curatorial science for drought *and*
flood agricultural risk, and why a 10-day (dekadal) CRMA cycle keyed to
vegetative growth stages is indispensable — with a line of sight to crop
insurance and equitable risk sharing.**

Companion to:
- `gpt55_flight_sim_drm_agri-advisory.md` — the CRMA-as-reasoning-engine argument
- `wrsi_bn_integration_plan.md` — the WRSI/SEAS5/TAMSAT-ALERT integration plan
- `jupyter-herdr/curatorial-to-crma-bn-mapping.md` — the curatorial-science mapping
- `bn-ibf/drought_ibf/drought_bn_ibf_v1.jl` — the BN engine being extended

---

## 1. Thesis in one sentence

An agricultural advisory should not be a **forecast pushed at a farmer**; it
should be the **prescription that follows a continuously-updated, auditable
diagnosis** — and that diagnosis is a curatorial act (what evidence counts,
how it is weighed, whose thresholds are made visible) which the CRMA-BN
**relocates, records, and verifies** rather than hides.

That single move is what lets the same engine serve a smallholder *and* an
insurer *and* a risk-pool administrator from **one posterior**, fairly.

---

## 2. Why a *continuous* monitor, and why *both* hazards

Traditional agricultural climate services are **event-triggered and
single-hazard**: a seasonal forecast is issued, an advisory is written, and
the loop is closed until the next season. This fails smallholders in three
structural ways that continuous monitoring is built to repair:

1. **Agriculture is a continuous-risk problem, not a trigger problem.** The
   crop is exposed every dekad from planting to harvest. Risk *accrues and
   reverses* — a poor onset can be rescued by mid-season rains; a good onset
   can collapse at flowering. A one-shot seasonal advisory cannot represent a
   trajectory; a dekadal posterior can.

2. **Drought and flood are the same field's risk, not two programmes.** A
   smallholder plot faces waterlogging/washout *and* dry spells within one
   season — often weeks apart. Running two disconnected early-warning systems
   produces contradictory advice. In the CRMA-BN both are **evidence
   streams into one agricultural risk state**:
   - `wflow.jl` → flood likelihood / waterlogging (already the flood-IBF
     hazard model) **and** the same hydrology → 10-day WRSI (crop water
     stress) for the dry side.
   - SEAS5.1 SPI-3 and TAMSAT-ALERT seasonal WRSI → the slow, seasonal
     drought signal.
   One field, one evolving `agri_risk` posterior, two hazard tails.

3. **The bottleneck is not the forecast, it is confidence that action is
   warranted.** The advisory doc's key inversion: don't ask *"what will yield
   be?"* first — ask *"how confident are we, given all current evidence, that
   a specific agricultural risk is emerging?"* Advice is issued because
   **multiple evidence streams have collectively raised confidence**, not
   because one index crossed a line. Continuous monitoring is precisely the
   machinery that accumulates that multi-stream confidence over time.

---

## 3. The CRMA cycle as curatorial science

The curatorial mapping's core claim — CRMA-BN does not eliminate judgment, it
**relocates, records, and verifies** it — is what makes a continuous
agricultural advisory *defensible* rather than merely *automated*. Each turn
of the dekadal cycle is a sequence of curatorial acts, each now logged:

| CRMA cycle step | Curatorial dimension (from the mapping) | What is made explicit & logged each dekad |
|---|---|---|
| **Ingest** dekadal evidence (rain, soil moisture, 10-day WRSI, flood likelihood, field reports) | Evidence curation (Table 1 #1) | Which streams were admitted this dekad, their QC flags and weights |
| **Update** the `agri_risk` posterior | Evidence synthesis (Table 1 #2) | The full recomputable Bayesian update — nothing weighed in an analyst's head |
| **Archive** the complete posterior | Epistemic triage (Table 1 #3) | Nothing silently discarded; the advisory is a *selection from* a preserved object |
| **Frame** per audience | Salience curation (Table 1 #4) | Farmer threshold-crossing view vs. insurer exceedance view — from one posterior |
| **Gate action** (CRMA state → advisory / model run) | Action recommendation (Table 5, human-gated) | Trigger rules are explicit, contestable artifacts, not embedded judgments |
| **Score** last cycle's belief against what happened | Epistemic verification (Table 3 N2) | Was *Assess* reasonable given only that dekad's evidence? Feeds Dirichlet CPT updates |

The **CPT becomes institutional memory** (mapping Table 2 #10): every dekad's
verified outcome updates the network's parameters, timestamped and reversible.
Over seasons the advisory *learns the local agronomy* — which WRSI decline at
which growth stage actually preceded loss in *this* region — instead of
importing insurance-oriented, developed-world drought semantics
(mapping Table 4's central hazard). This is the curatorial-justice guarantee:
**local verification data must dominate the LLM/expert prior quickly**, and the
Dirichlet machinery is the formal instrument that lets it.

**Direction:** the advisory system is not "a model that outputs advice." It is
a **curatorial institution with a memory, an audit trail, and a verification
loop**, whose continuous cycle happens to emit farmer advisories as one of
several framings. That reframing is the science contribution; the dekadal
advisory is the visible product.

---

## 4. Why the 10-day cycle is indispensable: phenology, not the calendar

The dekad (10-day period) is not an arbitrary IT cadence — it is the **native
tempo of crop water accounting** (FAO WRSI is computed dekadally) *and* it is
short enough to resolve the **vegetative and reproductive growth stages** at
which water stress is decisive.

### 4.1 Stress is stage-dependent — a seasonal number cannot carry this
A maize crop's sensitivity to water stress is **not uniform across the
season**. The same WRSI deficit means very different things at different
stages:

```
Growth stage        Water-stress sensitivity (Ky, FAO-33)   Advisory leverage
------------------  --------------------------------------  -----------------------------
Establishment       low                                     re-plant / gap-fill window
Vegetative          moderate                                top-dressing / weeding timing
Flowering/tasseling HIGHEST (irreversible yield loss)       supplemental irrigation priority
Grain-fill          high                                    terminal-stress salvage
Maturity            low                                     harvest timing / aflatoxin risk
```

A single seasonal WRSI outlook (TAMSAT-ALERT) tells you the *season may be
poor*. Only a **dekadal WRSI trajectory aligned to the crop's phenological
clock** tells you *a stress is arriving in the two dekads that contain
flowering* — which is where a smallholder's single, low-cost intervention
(shift planting, choose a shorter-duration variety, prioritise the one
irrigation they can afford) actually changes the outcome. This stage-timed
actionability is what current seasonal-only advisories structurally cannot
deliver.

### 4.2 The two horizons are complementary, not redundant
- **Seasonal WRSI (TAMSAT-ALERT, ~6 months):** sets the *strategic* prior —
  variety choice, area planted, input investment, whether to insure at all.
  Issued pre-season and refreshed monthly with SEAS5.1.
- **10-day WRSI (wflow.jl, sub-seasonal):** provides the *tactical* update —
  is the emerging stress landing on a sensitive stage, and is confidence high
  enough (across streams) to act now. Issued every dekad.

The BN carries both as separate nodes (`wrsi_seas`, `wrsi10`) precisely so the
seasonal prior is *continuously corrected* by dekadal reality instead of
standing unrevised for six months. That correction loop is the whole point.

### 4.3 What the dekadal cycle overcomes (limitations of current advisories)

| Current agricultural advisory limitation | How the dekadal CRMA cycle repairs it |
|---|---|
| One seasonal forecast → generic advice ("plant early", "use drought-tolerant varieties") | Advice re-issued each dekad, conditioned on the *evolving* posterior and the crop's current growth stage |
| Forecast-driven, ignores what has actually happened since | Bayesian update fuses forecast **with** observed rain, soil moisture, WRSI, flood likelihood, and field reports each dekad |
| Single hazard (drought *or* flood programme) | One `agri_risk` state integrating both tails for the same field |
| No memory; same mistakes each season | Version-controlled CPT accumulates verified local outcomes — the advisory learns |
| Not calibrated / not contestable | Epistemic verification scores each dekad's belief; every trigger is an auditable artifact |
| Advice issued on a single threshold crossing (false alarms) | Advice gated on multi-stream *confidence*, not one index |
| Expensive crop models run everywhere, always (operationally impossible) | Crop-specific impact models run **only** when the CRMA state for that crop ≥ *Assess* — selective, affordable |

---

## 5. From diagnosis to smallholder prescription (the two-layer separation)

The CRMA-BN is the **doctor's diagnosis**; the farmer advisory is the
**prescription**. Keeping them separate is what makes both honest:

```
Dekadal evidence (both hazards)
        │
   CRMA-BN posterior  ── "how concerned should we be, given all evidence?"
        │                (recomputable, archived, verified)
   CRMA state per crop×zone
        │  ── gate: run crop impact models only at ≥ Assess
   Crop-stage-aware impact  ── "what does this stress mean for THIS crop, THIS stage?"
        │
   Farmer advisory engine   ── the prescription (never produced by CRMA directly)
        │
   Maize / Beans / Rice advisories, per zone, per growth stage
```

A worked dekad (drought tail), from the advisory doc, now stage-aware:

> **Marsabit, maize, dekad containing tasseling.** Poor onset + WRSI
> declining + soil moisture falling + SEAS5.1 below-normal + TAMSAT-ALERT
> below-median → CRMA posterior = **Assess (high confidence)**. Gate opens →
> maize impact model runs → P(>20% yield loss) = 0.72. Prescription:
> *prioritise the single supplemental irrigation for fields at tasseling;
> switch un-planted fields to a shorter-duration variety.*

A worked dekad (flood tail), same engine:

> **Lower Shire, rice, vegetative stage.** `wflow.jl` flood likelihood rising
> + IMERG heavy-rain + field waterlogging reports → CRMA = **Assess**. Gate →
> paddy/waterlogging impact model. Prescription: *delay top-dressing until
> drainage; do not transplant into low-lying blocks this dekad.*

Different crops and hazards **activate different downstream analyses** — beans
in *Monitor* consume no compute; rice in *Review* triggers irrigation and
reservoir models. The dekadal cadence is what makes this selective activation
a living process rather than a one-time seasonal decision.

---

## 6. Direction: crop insurance and equitable risk sharing

This is where continuous, auditable, multi-stakeholder monitoring becomes
more than advisory — it becomes **risk-transfer infrastructure**. The
curatorial mapping's *distributive epistemic justice* (Table 3 N1: every
stakeholder receives the same evidence trail and posteriors) is the ethical
and technical foundation for fair insurance.

### 6.1 The same posterior, framed for the insurer
Salience curation (mapping Table 1 #4): from the *one* archived posterior the
system emits, for the same field and dekad, an **exceedance-probability**
framing for insurers alongside the **threshold-crossing** framing for farmers.
Insurer and farmer are looking at the *same evidence and the same math* — the
transparency that index-insurance disputes usually lack.

### 6.2 Fixing basis risk — the core failure of index insurance
Classic Weather Index Insurance (WII) pays on a single rainfall or NDVI
index, producing **basis risk**: the index misses a loss the farmer actually
suffered (or pays when there was none), destroying trust. The CRMA-BN attacks
basis risk directly:
- The payout trigger is a **multi-stream, stage-aware posterior**
  (`agri_risk` / crop impact), not one raw index — so it tracks *realised
  crop water stress at sensitive stages*, which is far closer to actual loss
  than seasonal rainfall totals.
- WRSI/impact triggers are **agronomically meaningful and auditable**: the
  farmer can see *why* the posterior reached *Actionable_Risk* (the logged
  evidence trail), and so can the regulator.
- **Epistemic verification** (Table 3 N2) provides the hindcast calibration
  insurers and reinsurers require: were the belief trajectories that would
  have triggered payouts calibrated against realised events? This is the
  actuarial evidence base, produced natively by the monitoring loop.

### 6.3 Equitable risk sharing / pooling
- **Trigger integrity for pools & bonds:** contingency finance (index pools,
  regional risk facilities, forecast-based-finance windows) needs a trigger
  that is transparent, contestable, and reproducible by every party. The
  recomputable posterior + logged evidence (mapping Tables 2 #8, #9) *is* that
  trigger — any member can rerun it and challenge it ("remove stream X").
- **Forecast-based action (anticipatory finance):** the CRMA state ladder
  (*Monitor → Evaluate → Assess → Actionable_Risk*) maps directly onto
  pre-agreed, pre-financed action windows — releasing funds on *confidence*,
  ahead of loss, at the dekadal cadence that matches the intervention window
  in §4.1.
- **Distributive justice as architecture, not promise:** every farmer group,
  cooperative, and member state receives the *same* posterior, uncertainty,
  and rationale — not "trust the underwriter." That equal evidence trail is
  the precondition for pooling risk *fairly* across heterogeneous smallholders
  rather than cross-subsidising opaquely.

### 6.4 The human gates stay human (non-negotiable)
Per the curatorial mapping, what must **not** be automated: the payout
*policy* (justice weighting — whose thresholds and vulnerabilities are made
visible), the action mapping (risk state → payout), and structural CPT
revision. CRMA-BN forces these into the open as versioned, contestable
artifacts; it does not decide them. Scientists curate the knowledge and the
uncertainty; the risk-transfer *policy* remains a governance decision.

---

## 7. What this implies for the build (ties to the integration plan)

The direction above is realised by the concrete steps in
`wrsi_bn_integration_plan.md`, with these emphases:

1. **Dual-hazard, one posterior.** The BN extension must carry `wflow.jl`
   flood likelihood and dry-side WRSI as *co-equal evidence* into a single
   `agri_risk` node — not two pipelines. (Plan Stage 1: divorce-the-parents
   structure already separates a meteorological branch from a crop-water-stress
   branch; add a flood-likelihood parent to the latter.)
2. **Phenology layer is a first-class input.** A per-zone, per-crop
   planting-date / growth-stage tracker (from planting-window data + degree
   days) must condition the impact-model step so a dekadal WRSI deficit is
   interpreted *against the current stage* (§4.1). This is new work beyond the
   current plan and is what unlocks stage-timed advisories.
3. **Log every curatorial act from day one.** Evidence admission, prior
   elicitation (including any LLM-elicited CPT as a *weak* prior), thresholds,
   overrides — all timestamped and attributable (mapping Tables 2 #9, #10;
   Table 4). This is what later makes the insurance trigger auditable.
4. **Epistemic-verification harness alongside the hindcast replay.** Plan
   Stage 4's hindcast becomes not just skill scoring but *belief-trajectory*
   scoring (was *Assess* rational given only that dekad's evidence) — the
   calibration record insurers require.
5. **Parallel framings as an output target, not an afterthought.** The CSV/
   posterior archive should be shaped so farmer-threshold and
   insurer-exceedance bulletins are generated from the same object
   (mapping Table 1 #4).

## 8. One-paragraph synthesis

Continuous risk monitoring turns the agricultural advisory from a seasonal
forecast broadcast into a **dekadal curatorial cycle**: each 10 days it admits
declared evidence for *both* the drought and flood tails of the same field,
updates one recomputable `agri_risk` posterior, archives it whole, frames it
for farmer and insurer alike, gates expensive crop-impact models on
multi-stream *confidence* rather than a single threshold, and scores its own
belief against what happened — feeding a version-controlled CPT that learns
the local agronomy. The 10-day cadence is indispensable because crop water
stress is **stage-dependent and irreversible at flowering**, and only a
dekadal WRSI trajectory aligned to the crop's phenological clock can put a
smallholder's one affordable intervention in the right two dekads. The same
machinery — transparent, auditable, calibrated, and delivered as an equal
evidence trail to every stakeholder — is exactly what index insurance and
regional risk pools need to defeat basis risk and share risk *fairly*. The
advisory is the visible prescription; the enduring contribution is a
**curatorial institution with a memory, an audit trail, and a verification
loop**, whose value-laden choices are relocated into the open where they can
be logged, contested, and empirically evaluated against outcomes.
