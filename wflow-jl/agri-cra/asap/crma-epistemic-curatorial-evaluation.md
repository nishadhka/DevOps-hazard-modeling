# The agri-CRMA as a curatorial, epistemic IBF — a critical evaluation
# (is the Monitor · Evaluate · Assess · Review direction optimal, and is it doable?)

**What this document does.** It reads the reconstructed pipeline
(`agri-cra-pipeline.drawio`) and the committed engine
(`../pipeline/drought_bn_ibf_v1.jl`) through the lens argued out in
`gpt55_flight_sim_drm.md`, and then *critically* evaluates whether that
direction is the right one and whether it can actually be built here. It is not
a sales pitch for CRMA; the sharpest objection (that the current engine is "an
expert rule system in Bayesian dress") is taken as the central test, not a
footnote.

Companion reading: `gpt55_flight_sim_drm.md` (the source argument),
`../continuous-risk-monitoring-agri-advisory.md` (the curatorial direction),
`asap-crma-gap-and-bn-role.md` (what ASAP is missing / the BN as fusion layer),
`bn-approach-b-crop-stress-subbranch.md` (the Jaynes-consistent BN structure).

---

## 1. The reconstruction, and why it is not cosmetic

Two changes were made to the plan and the diagram, both taken directly from
`gpt55_flight_sim_drm.md`:

1. **`Actionable_Risk` → `Review`.** The four outcomes are now
   **Monitor · Evaluate · Assess · Review** — four *cognitive/analytical
   verbs*. The old ladder mixed three verbs with one decision-word
   (`Actionable_Risk`), which "sounds very close to a decision" and lets a DRM
   officer read *"ICPAC is telling us to act."* The verb-only ladder keeps CRMA
   answering **"how concerned should we be / how much analytical attention does
   this warrant?"** and never **"what should you do?"**

2. **Output reframed from *advisory/prescription* to *decision support +
   verification*.** The diagram's final column no longer emits a farmer/insurer
   *prescription*; it emits a **risk state with an auditable evidence trail**, a
   **triage gate** (run expensive hazard/impact models only at ≥ Assess), an
   explicit **institutional boundary** (CRMA owns the risk state; national DRM
   owns the action state), and a **closed epistemic-verification loop**.

These are not relabelling. They encode a claim about *what kind of object the
system is*: a **risk-cognition / triage layer**, analogous to real-time
mesoscale analysis for weather — "not making decisions itself, not replacing
forecasts, but continuously integrating evidence into the best available
estimate of the current state." The word change is the visible tip; the
substance is the refusal to cross into the decision domain.

---

## 2. Epistemic vs ontological — where each lives in our pipeline

`gpt55_flight_sim_drm.md` (from line 253) draws the distinction the user asked
to see reflected:

- **Epistemic:** *how good was our knowledge?* Were the probabilities sensible,
  did they improve with evidence, was `Review` justified given only that dekad's
  evidence? This is Jaynes / Bayesian epistemology / calibration.
- **Ontological:** *what counts as risk in the first place?* Which entities and
  relations are admitted into the model at all.

Mapped onto the diagram, the two layers are physically separable:

| Layer | Where it lives in the pipeline | What it commits to |
|---|---|---|
| **Ontological** | Columns 1–2 (data sources; **wflow.jl** as the one *physical/causal* engine) and the **node set** in column 5 (`cur, def, spa, trn, tail, cdi, wrsi10, fpar, phase, wrsi_seas`) | *This* is what we declare risk to be made of. wflow.jl is the heavy ontological commitment (a real water balance); everything else is admitted evidence. |
| **Epistemic** | Columns 5–6 (the BN belief update: soft evidence → CPTs → `risk` / `crop_water_stress` / `agri_risk` posterior) | *Given* those entities, how to reason under uncertainty. |
| **Curatorial** | Column 7 (audit trail, triage gate, framings, verification loop) | *Who decides* what counts, how it is weighed, and whether the assessment was good — relocated into the open. |

The important move `gpt55_flight_sim_drm.md` names is an **ontological shift**
that our engine already embodies: from

```
Risk = hazard-threshold exceedance          (classic IBF / ASAP)
```

toward

```
Risk = evolving belief about harmful future states   (CRMA)
```

Our `RISK_STATES` / `CRMA_STATES` are latent nodes — you cannot "walk outside
and measure Assess." That is the ontological contribution; the BN is then the
*epistemic mechanism* for updating belief about those latent states.

**Why this matters operationally (the paper's strongest claim).** Full IBF is
stuck on the *ontological* burden — which hazard model, which exposure layer,
which vulnerability curve, which return period — re-litigated per hazard, per
country, per cycle, which is why after 15+ years it stays project-based rather
than routine. CRMA is primarily an *epistemic* project: ingest streaming
analysis-ready evidence, update belief. That is a far lighter daily load. Our
pipeline honors this by keeping the single genuinely heavy ontological object,
**wflow.jl, behind the triage gate** — it runs where risk already justifies it,
not everywhere every dekad. The `crop_water_stress` intermediate node
(Approach B) is itself a small, explicit ontological commitment — the
proposition "realised crop water stress" through which the raw indices act —
and making it explicit (not buried) is exactly the curatorial stance.

---

## 3. The curatorial reading — relocate, record, verify

`continuous-risk-monitoring-agri-advisory.md` frames CRMA as a curatorial
institution: it does not eliminate judgment, it **relocates, records, and
verifies** it. The reconstructed column 7 is that institution made visible:

- **Relocate:** value-laden choices (which evidence, what thresholds, the
  cost-loss ratio) become explicit CPT/parameter artifacts, not analyst
  intuition held "in emails, PowerPoint, and WhatsApp."
- **Record:** the *audit trail* — evidence admitted this dekad + the
  recomputable posterior. Without CRMA, "nobody can easily reconstruct why"
  Monday's *Evaluate* became Thursday's *Assess*.
- **Verify:** the flight-simulator loop scores the belief itself against what
  happened, feeding the CPT.

This is the answer to *"what is worse today because CRMA does not exist?"* —
not worse forecasts, but risk synthesis that is implicit, inconsistent across
analysts, non-reproducible, and unverifiable. The curatorial value is turning
that into something explicit, consistent, and auditable.

---

## 4. The non-3D flight simulator: epistemic verification, not decision
##   verification

The diagram's new verification lane encodes the paper's key reframing: the
object verified is the **risk assessment**, not the intervention. A hospital
triage nurse is graded on whether the *priority* was right given the symptoms
present — not on whether surgery succeeded. Likewise:

> Given the evidence available at the time, did the system correctly assess the
> evolving risk state?

The four verification layers (all applied to **risk-state transitions**, not
rainfall):

1. **Calibration of belief** — when the BN says *Review = 0.7*, do ~70% of such
   situations become Review-worthy? (Brier / reliability.)
2. **Temporal accuracy** — did it escalate too late / too early; how many dekads
   of lead time before impact?
3. **Modal-ranking accuracy** — did the event evolution follow the posterior's
   ordering of plausible worlds? (Pritchard-style modal risk.)
4. **Evidence value** — did each stream (WRSI, CDI, FPAR, field reports) *reduce*
   uncertainty or degrade performance? Prune the ones that don't.

The **event-storyline archive is the verification dataset** — replay hundreds
of past droughts/floods and ask *"if CRMA had been running, how often would it
have classified the risk state correctly, and with what lead time?"* Our engine
already has the scaffolding for this: the per-member storyline picker
(`run_per_member_bn` / `select_storylines`) and the DBN sequence runner
(`run_dbn_sequence`). The simulator is the replay-and-score harness, not any
animation.

---

## 5. Critical evaluation — is this direction *optimal*?

Honest strengths and honest objections.

### 5.1 The strongest objection (must be answered, not waved away)
`gpt55_flight_sim_drm.md` itself lands the sharpest critique: the committed
script's *architecture* (virtual/soft evidence, cost-loss triggering,
entropy-responsive uncertainty) shows genuine probability-as-logic awareness,
but its *content* is **"an expert rule system in Bayesian dress"**:

- the CPT numbers in `compute_risk_probs` are hand-authored `elseif` vectors,
  not derived from data or MaxEnt-under-constraints;
- the SEAS5-derived nodes (`def`, `tail`, `agreement`) share a **common origin**
  and are treated as independent parents → double counting. **Separately** (and
  this is the new one introduced by Option 1): `wrsi10` is *not* SEAS5-derived —
  it comes from wflow.jl forced by **observed** rainfall — but it therefore
  shares its origin with `cur` (ERA5 SPI-3 obs) and with the precipitation
  component inside `cdi`. Those live on the met branch while `wrsi10` lives on
  the crop branch, and they meet at the `agri_risk` fusion, where `_CWS_SHIFT`
  applies a monotone upward push. So one missing-rain signal can escalate the
  posterior **twice**. Approach B does not cause this, but it does localise it
  to a single 100-entry `AGRI_CPT` — which is precisely where a
  correlation-aware fusion (or a shared latent "observed rainfall deficit"
  node) can fix it;
- the DBN uses a **posterior-recycling temporal hack** (`blend_temporal_prior`)
  rather than an explicit risk-persistence kernel;
- there is **no operational target proposition**, so the hidden risk node is not
  calibratable;
- and critically, **nothing updates from outcomes** — the CPTs are frozen.

Jaynes's two tests — *would two rational agents with the same information be
forced to the same plausibilities, and would the world's feedback revise them?*
— currently both fail. **So the direction is only optimal as a trajectory, not
as the present state.** The reconstruction (verb ladder, verification loop,
delete-the-action-node) is necessary but not sufficient; the content work in §6
is what makes the Bayesian dress into an actual Bayesian body.

### 5.2 The "just another dashboard / goalpost-shifting" critique
The fair skeptic asks: *are we relabelling "predict impacts" as "assess risk"
because the former is hard?* The paper's decisive test: **what changes when a
unit moves 🟡→🟠 or 🟠→🔴?** If the answer is "nothing," CRMA is a visualization
layer and the critics are right. Our diagram answers it structurally — the
**triage gate**: ≥ Assess *is* the event that activates wflow.jl / crop-impact
analysis. That is a real workflow transition (attention and compute
re-allocation), which is what distinguishes a triage system from a dashboard.
The burden is to keep every state tied to a defined analytical response.

### 5.3 The "Review is the highest level?" linguistic risk
`gpt55_flight_sim_drm.md` flags it directly: in normal usage *Review* reads as
*less* intensive than *Assess* (or as "after-action review"), so users may not
grasp that it is the top of the ladder. This is a genuine usability defect of
the chosen wording. It is defensible only if *Review* is consistently defined as
**"escalate for senior/organizational review — this can no longer be handled as
routine monitoring"** and is trained as such. If that framing does not stick, an
all-states ladder (Normal·Elevated·High·Critical) or `Alert` as the fourth term
would communicate the ordering better. This is a live risk, not a solved one.

### 5.4 You cannot fully abandon ontology
Decision-makers ultimately care about impacts ("which districts, how bad?"), not
posterior probabilities of a hidden node. The paper's own caution: CRMA must not
conclude *"therefore impacts don't matter."* Our architecture postpones rather
than abandons the ontology — impacts/exposure/vulnerability enter *minimally as
context*, and full impact modelling is **reserved for ≥ Assess**. That is the
balanced position, but it means CRMA's value depends on the gated models
actually existing and being good when triggered — the ontological work is
deferred, not deleted.

### 5.5 The institutional-tension ledger
Moving to a verb-only ladder and deleting the action node **reduces** the
"ICPAC is telling us to act" tension and preserves the elegant separation
(meteorology = *what do we know*; CRMA = *what does evidence imply about risk*;
DRM = *what to do*). It does **not eliminate** it — the boundary moves rather
than disappears, and *Review* can still be misread as an instruction. Net: the
direction eases the tension relative to `Actionable_Risk`, which is a real
improvement, without pretending to resolve it.

**Verdict on optimality:** *directionally yes, conditionally.* The framing
(risk cognition + triage + epistemic verification, sitting **above** Hazard
Watch, not replacing it) is the most defensible position available and fits a
regional centre's mandate. It is optimal **only if** (a) each state maps to a
defined analytical response, (b) the content deficits in §6 are closed so it
passes Jaynes's two tests, and (c) it never cannibalises the Hazard Watch
evidence layers it depends on.

---

## 6. Is it *doable* on this codebase? (what exists vs what's needed)

Doability is favourable because the operational burden is epistemic (ingest
analysis-ready streams + update belief), not a full daily impact-model chain for
11 countries. Concretely:

**Already in the committed engine (the hard scaffolding exists):**
- soft/virtual evidence per node (`*_p1..pk`, `diageye`), CDI fusion, the
  matmul contraction, cost-loss CRMA triggering (`compute_crma_state`);
- per-member storylines (`select_storylines`) and a DBN sequence runner
  (`run_dbn_sequence`) — the replay substrate for verification;
- **Option 1 shipped (commit `ff22268`)**: the full Approach-B structure —
  `crop_water_stress` (192-entry CPT), `agri_risk` (100-entry `AGRI_CPT`), the
  exact `cws=No_Stress` identity (`_CWS_SHIFT[1]=0.0`), the sum-rule fusion in
  `compute_agri_risk_probs`, and **CRMA already running on `agri_risk`** with
  `crma_state_met` retained. 14/14 self-tests pass.

**Reconstruction edits (orthogonal to Option 1 — different layer, no conflict):**
Option 1 touched the *evidence/fusion* layer; the reconstruction touches only
the *output/decision* layer, so they compose without collision.
- **Rename (trivially safe):** `CRMA_STATES = ["Monitor","Evaluate","Assess",
  "Review"]` + the `TRAFFIC_LIGHT` key. `compute_crma_state` returns an *index*
  and never references the names, so this cannot reach the agri layer. Rename the
  internal `p_act`/`θ_act` → `p_review`/`θ_review`; **the cost-loss rule stays** —
  the paper endorses cost-loss producing an *analytical posture*, not an action.
- **Delete the action node:** drop `ACTION_STATES` / `build_action_cpt`, unthread
  the `action_cpt` parameter (~10 functions), drop `recommended_action` +
  `action_*` CSV columns, fix self-tests 1–2 which assert on
  `ACTION_STATES[argmax(ap)]`.
- **The one non-mechanical decision:** `confidence = maximum(action_probs)` is
  *derived from the action node*, so deleting it orphans `confidence`. It must be
  redefined as a sharpness measure on the posterior itself — either
  `maximum(agri_probs)` (modal probability) or `1 − H/H_max` (normalised
  entropy). The entropy form fits the calibration framing better and is the
  recommended replacement.

**Content work (the real, but bounded, effort — turns dress into body):**
1. **Define the target proposition** operationally, e.g. `P(≥N cropland-ha /
   people affected in boundary b within horizon)`, so the hidden node becomes
   *calibratable*.
2. **Honest likelihoods:** replace the hand-authored categorizers with
   likelihood models built from forecast-verification statistics (IMERG/ECMWF/
   TAMSAT), so evidence enters as soft evidence with real reliability, not
   infallible one-hots.
3. **De-correlate the ensemble-derived nodes** into one latent
   rainfall/hazard-severity node observed through several noisy channels —
   removes the double counting.
4. **MaxEnt + Dirichlet CPTs:** derive/constrain the CPT columns by maximum
   entropy under elicited constraints (orderings, bounds), with Dirichlet priors
   so verified outcomes update them — this is what makes the CPT *institutional
   memory* and closes Jaynes's second test.
5. **Explicit persistence kernel** replacing `blend_temporal_prior`; condition on
   each forecast issuance once.
6. **Verification harness** over the event-storyline archive: Brier / reliability
   / hit-rate / FAR / lead-time / modal-ranking on risk-state transitions, wired
   back into the CPT posteriors and the calibration model.

None of these requires a continental EO operation or a full impact chain; they
are analysis and modelling tasks on evidence that already streams. That is why
the direction is doable where full IBF has struggled — **the daily cost is
bounded and the expensive machinery is gated.**

---

## 7. One-paragraph verdict

The reconstruction — Monitor · Evaluate · Assess · **Review**, an explicit
triage gate, the deleted action node, and a closed epistemic-verification loop —
correctly repositions the agri-CRMA as a **risk-cognition and attention-triage
layer that sits above the East Africa Hazard Watch evidence rather than
replacing it**, and it makes the epistemic/ontological split legible in the
pipeline: wflow.jl carries the heavy ontology (gated), the BN carries the
epistemics, and column 7 carries the curatorial audit-and-verification. This is
the most defensible and most operationally sustainable framing available, and it
is buildable on the committed engine with modest structural edits. But it is
*optimal only as a trajectory*: today the CPTs are hand-authored, the
ensemble-derived nodes double-count, the temporal coupling is a hack, there is
no calibratable target proposition, and nothing yet learns from outcomes — so by
Jaynes's own test the system is not yet forced-to-agree or outcome-revised. The
direction is right and doable; whether it is *good* depends entirely on closing
those six content gaps and on each risk state being tied to a real analytical
response — otherwise the strongest critics, who call it "another dashboard," are
correct.
