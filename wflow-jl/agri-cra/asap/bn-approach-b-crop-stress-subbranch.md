# Approach B — the `crop_water_stress` sub-branch: carrying the crop-side axes
# (`wrsi10`, `fpar`, `phase`) without breaking RxInfer's five-parent cap

**Decision (this doc argues and specifies it):** carry the three new crop-side
axes for Options 1–3 **not** as flat parents of `risk`, but through an
intermediate node `crop_water_stress` that then fuses with the existing meteo
`risk` into a final `agri_risk` node. This is the classic *parent-divorcing*
move, it keeps every node ≤ 5 parents (RxInfer's exact-inference limit), and —
the deeper point — it is the **epistemically correct** structure under Jaynes'
"probability theory as extended logic," not merely a library workaround.

Companion reading:
- `RxInfer_BN_Limitations_Summary.md` — the five-parent constraint, in detail.
- `asap-crma-gap-and-bn-role.md` — what Options 1–3 are (ASAP mechanisms →
  CRMA nodes); read for the *why* of each axis.
- `../wrsi_bn_integration_plan.md` — already names the *"divorce-the-parents"*
  structure as Stage 1; this doc is the concrete realisation of it.
- `../pipeline/drought_bn_ibf_v1.jl` — the engine to extend (CDI is the
  template pattern).

---

## 1. The constraint, stated precisely

RxInfer's `DiscreteTransition(child, T, p1, p2, …)` primitive does exact
message-passing only up to **five conditioning parents**. The committed engine
sits exactly at that edge:

```julia
# drought_bn_ibf_v1.jl — the RxInfer-native model (5 parents, exact)
risk ~ DiscreteTransition(cur, T, def, spa, trn, tail)
```

The moment a sixth parent is added (agreement, or CDI), the code already has to
abandon exact message-passing and fall back to a hand-rolled tensor
contraction:

```julia
# build_risk_cpt_tensor docstring, verbatim:
# "Six conditioning parents exceed RxInfer's DiscreteTransition exact-rule cap,
#  so CDI runs use the matmul path (infer_soft_matmul_cdi) …"
```

So we are **already one parent over** the exact cap whenever CDI is on. Options
1–3 want to add **three more** axes (`wrsi10`, `fpar`, `phase`). The question is
purely *how they attach*.

### Why "flat parents" (Approach A) is the wrong attachment

Attaching the three axes directly to `risk` gives a single node with up to
**ten** parents and one monolithic CPT tensor. The tensor grows
*multiplicatively*:

| Structure | Conditioning tensor shape | Entries (×5 for the child) |
|---|---|---|
| Today (CDI on) | `cur·def·spa·trn·tail·cdi` = 5·5·3·3·4·6 | ~135 k |
| **Flat (A)**: + `wrsi10·fpar·phase` = ·4·4·3 | 5·5·3·3·4·6·4·4·3 | **~6.5 M** |
| **Approach B** (below) | three small tensors, summed | **~135 k + ~0.3 k** |

Flat parents inflate the CPT by ~50× to **~6.5 million numbers**, permanently
force the matmul path (never RxInfer-native), and — worse — commit us to a
CPT no human can elicit and no realistic amount of local verification data can
ever learn. The library limit is a symptom; the real problem is epistemic.

---

## 2. Approach B — the topology

Divorce the crop-side axes into their own intermediate hypothesis, then fuse:

```
  ── METEO BRANCH (existing; unchanged) ─────────────────────────────
   current_spi3 ─┐
   deficit       │
   spatial       ├─►  risk  (5 states)      [+ agreement / cdi as today]
   trend         │
   tail         ─┘
                                                    │
  ── CROP BRANCH (new; Options 1–3) ─────────────   │  ───────────────
   wrsi10 ─┐                                         │
   fpar    ├─►  crop_water_stress (4 states)         │
   phase  ─┘        │  (phase conditions the         │
                    │   wrsi10/fpar → cws map,        │
                    │   FAO-33 Ky-style)              │
                    │                                 │
  ── FUSION (new) ──┴─────────────────────────────────┴──────────────
        risk ──────────────┐
                           ├─►  agri_risk (5 states) ─► CRMA state
        crop_water_stress ─┘        (cost-loss rule, unchanged)
```

**In-degree of every node stays within the exact cap:**

| Node | Parents | Count | Exact in RxInfer? |
|---|---|---|---|
| `risk` (meteo) | cur, def, spa, trn, tail [, cdi] | 5 [6] | yes [matmul, as today] |
| `crop_water_stress` | wrsi10, fpar, phase | **3** | **yes** |
| `agri_risk` | risk, crop_water_stress | **2** | **yes** |

Approach B is the *only* option under which the crop extension can be
RxInfer-native. It also localises the CDI overflow to the meteo node instead of
letting it multiply against the crop axes.

---

## 3. Node specifications

### 3.1 `crop_water_stress` (cws) — 4 states, increasing stress

Reuse the existing `WRSI10_STATES` convention from `wflow_wrsi_prep.py`:

```
1 No_Stress   2 Mild   3 Moderate   4 Severe        (higher index = more stress)
```

Parents and their states:

| Parent | States | Origin (Option) | Convention |
|---|---|---|---|
| `wrsi10` | 4: No_Stress→Severe | wflow.jl WRSI, **crop-fraction-weighted** (Opt 1) | monotonic stress |
| `fpar` | 4: Healthy→Severe_Decline | ASAP `zFPARc` guarded by `mFPARd` (Opt 2) | monotonic stress |
| `phase` | 3: Vegetative, Flowering, Maturation | phenology tracker (Opt 3) | **modifier, not stress** |

`compute_cws_probs(wrsi10, fpar, phase)` → 4-vector. Structure mirrors the
existing `compute_risk_probs` idiom (base score + modifiers + expert rules +
MaxEnt smoothing):

- **Base:** monotone in `wrsi10` and `fpar` (both dry/veg stress raise cws).
- **Convergence rule (ASAP level-3 analogue):** `wrsi10` *and* `fpar` both
  stressed escalates harder than either alone — the Bayesian version of ASAP's
  "meteo AND vegetation firing" rung.
- **`mFPARd` guard (Opt 2):** `fpar` only counts as critical when the mean FPAR
  difference is also materially below normal (suppresses low-variability false
  positives, exactly as ASAP does).
- **Phenology (Ky) modifier (Opt 3):** `phase = Flowering` amplifies a given
  deficit (highest FAO-33 `Ky`, irreversible loss); `phase = Maturation` damps
  it. This is the one axis that is *not* monotone stress — it re-weights the
  others.

CPT size: `4 (cws) × [4·4·3] = 192` entries. Trivial to build, elicit, and
later learn.

### 3.2 `agri_risk` — 5 states, the fused posterior

Same 5-state ladder as `risk` (`Minimal…Extreme`), so the downstream
`compute_crma_state` cost-loss rule and CRMA ladder are **unchanged**.

`compute_agri_risk_probs(risk_idx, cws_idx)` → 5-vector, with the
**backward-compatibility no-op guarantee** (mirrors the `cdi=1` guarantee
already tested):

- `cws = No_Stress (1)` ⇒ `agri_risk = risk` (identity pass-through). With no
  crop evidence, the network reproduces today's meteo posterior exactly.
- `cws = Moderate/Severe` ⇒ shifts mass upward (crop reality confirms/adds to
  the meteo signal), but *bounded* — cws cannot by itself manufacture Extreme
  from a Minimal meteo state without corroboration (avoids single-index basis
  risk, concept doc §6.2).

CPT size: `5 (agri_risk) × [5·4] = 100` entries.

---

## 4. Why the library limit and good Bayesian practice coincide

This is the load-bearing argument, and it is where Jaynes matters.

A node with ten direct parents asserts that agricultural risk depends on ten
raw quantities *simultaneously and irreducibly* — that there is no intermediate
concept through which they act. That is almost never true and never elicitable.
Introducing `crop_water_stress` states the intermediate hypothesis our
reasoning **actually goes through**: raw WRSI, FPAR, and growth stage matter to
final risk *only insofar as they determine the plant's realised water-stress
state*. Written as a conditional-independence assertion:

```
P(agri_risk | risk, wrsi10, fpar, phase)
        = P(agri_risk | risk, crop_water_stress)
```

i.e. **given the crop-water-stress state, the raw indices carry no further
information about agricultural risk.** That is a real, testable modelling
commitment — and making it *explicit and contestable* is precisely the
curatorial-science stance (`asap-crma-gap-and-bn-role.md` §3). The five-parent
cap is not fighting us; it is pushing us toward the model we should build
anyway.

---

## 5. The Jaynes framing — probability as logic, and this extension as its
##   natural continuation on the Julia code base

E. T. Jaynes' *Probability Theory: The Logic of Science* treats probability as
**extended logic**: degrees of plausibility that, to stay consistent (the
Cox–Jaynes desiderata), *must* obey the product and sum rules. A Bayesian
network is nothing more than a factorisation of one joint plausibility
assignment that respects those rules. Read through that lens, every part of
Approach B is a standard Jaynesian move, and the code base is already most of
the way there.

**5.1 Parent-divorcing *is* the sum rule with an auxiliary proposition.**
Jaynes repeatedly introduces a well-chosen auxiliary proposition and eliminates
it with the sum rule to make inference tractable. `crop_water_stress` is exactly
such an auxiliary:

```
P(agri_risk | wrsi10, fpar, phase, risk)
  = Σ_cws  P(agri_risk | risk, cws) · P(cws | wrsi10, fpar, phase)
```

The intermediate node is not an approximation — it is the sum rule applied to a
deliberately introduced proposition. Its CPT `P(cws | …)` is a *logical
combination rule* for the crop evidence; the fusion CPT `P(agri_risk | risk,
cws)` is the combination rule for the two branches. The matmul contractions
already in the engine (`infer_soft_matmul`, `infer_soft_matmul_cdi`) are
literal implementations of that sum — Approach B just adds two more, small,
sums.

**5.2 Soft evidence is the product rule, not a hack.** The engine already
accepts `Categorical` soft evidence per parent (the `*_p1..pk` columns,
`diageye` observation transitions). In Jaynes' terms a soft-evidence vector is a
likelihood — a statement of how strongly the data bear on each state — and
message-passing multiplies it in by the product rule. `wrsi10`, `fpar`, and
`phase` enter as soft evidence in exactly the same way; nothing new is needed on
the inference side.

**5.3 Maximum entropy is the honest way to fill the small CPTs.** Where we have
no verification data, Jaynes' MaxEnt principle says: assign the distribution
that is maximally non-committal *subject to the constraints we are willing to
assert* (monotonicity in `wrsi10`/`fpar`, the Ky ordering in `phase`, the
convergence rule). The existing `compute_risk_probs` expert rules are already an
informal MaxEnt/elicitation; the 192-entry `cws` and 100-entry `agri_risk`
tables are small enough to make this *explicit and reviewable* — a table a
domain expert can read, contest, and sign off, which a 6.5 M-entry flat tensor
can never be.

**5.4 Learning is the same logic, continued — the Dirichlet update.** The
nine-point roadmap's item #7 (Dirichlet priors + CPT learning) is, in Jaynes'
framework, just Bayes' theorem applied to the CPT itself: a Dirichlet prior over
each column's plausibilities, updated by verified outcomes via
Dirichlet–multinomial conjugacy (the modern form of Laplace's rule of
succession that Jaynes derives from the desiderata). Because `cws` and
`agri_risk` have *small* CPTs, they are the **first nodes where learning is
actually feasible** — a 192-entry table can accumulate enough local
dekad-outcome counts to move; a 6.5 M-entry table never will. Approach B is
therefore the structure that makes the "CPT as institutional memory" promise
(concept doc §3) reachable rather than rhetorical.

**5.5 The whole system is a Jaynesian inference robot.** Given the same
evidence it must assign the same plausibility, and the derivation is inspectable
— which is exactly the audit-trail / recomputable-posterior requirement for the
insurance and equitable-risk-sharing direction (concept doc §6). The extension
does not change *what kind of object* the engine is; it keeps it a consistent
plausibility calculator while adding the crop branch.

**In one line:** the extension performed on this Julia code base is *keep
applying the product and sum rules consistently* — divorce the crop parents
through an intermediate proposition (sum rule), admit each index as soft
evidence (product rule), fill the small CPTs by maximum entropy, and let
Dirichlet updating turn them into memory. That is Jaynes' programme, expressed
in RxInfer.

---

## 6. Concrete migration on `drought_bn_ibf_v1.jl`

The CDI integration is the exact template — follow it node-for-node.

**6.1 Constants.**
```julia
const CWS_STATES  = ["No_Stress", "Mild", "Moderate", "Severe"]   # 4, = WRSI10_STATES
const FPAR_STATES = ["Healthy", "Mild_Decline", "Moderate_Decline", "Severe_Decline"]  # 4
const PHASE_STATES = ["Vegetative", "Flowering", "Maturation"]    # 3 (start minimal: 2)
# agri_risk reuses RISK_STATES (5). No change to CRMA_STATES / compute_crma_state.
```

**6.2 Categorisers** (mirror `categorize_cdi`): `categorize_wrsi10(class_or_idx)`,
`categorize_fpar(zfparc, mfpard_guard)`, `categorize_phase(label)`. Each has the
missing → least-stress / neutral branch (the no-op default).

**6.3 Two small CPT builders** (mirror `compute_risk_probs`):
```julia
compute_cws_probs(wrsi10::Int, fpar::Int, phase::Int)::Vector{Float64}   # length 4
compute_agri_risk_probs(risk::Int, cws::Int)::Vector{Float64}            # length 5
```
plus tensor builders `build_cws_cpt_tensor()` (4×4×4×3) and
`build_agri_cpt_tensor()` (5×5×4).

**6.4 Inference — two options, both viable because in-degrees ≤ 5:**

*Option (a) minimal migration (keep the meteo pipeline byte-for-byte):*
compute the meteo `risk_probs` exactly as today (matmul, CDI-aware), then two
tiny contractions:
```julia
cws_probs  = contract(build_cws_cpt_tensor(),  wrsi10_ev, fpar_ev, phase_ev)   # 192-entry sum
agri_probs = contract(build_agri_cpt_tensor(), risk_probs, cws_probs)          # 100-entry sum
crma_idx   = compute_crma_state(agri_probs; cost_loss_ratio)                   # unchanged
```

*Option (b) RxInfer-native (now possible — the point of Approach B):*
```julia
@model function agri_bn_model(T_risk, T_cws, T_agri, <obs...>)
    # ... existing meteo priors + diageye observations ...
    wrsi10 ~ Categorical(fill(1/4,4)); fpar ~ Categorical(fill(1/4,4)); phase ~ Categorical(fill(1/3,3))
    risk ~ DiscreteTransition(cur, T_risk, def, spa, trn, tail)   # 5 parents — exact
    cws  ~ DiscreteTransition(wrsi10, T_cws, fpar, phase)         # 3 parents — exact
    agri ~ DiscreteTransition(risk, T_agri, cws)                  # 2 parents — exact
    agri_data ~ DiscreteTransition(agri, diageye(5))
end
```
(CDI, if on, keeps the meteo `risk` on the matmul path and feeds its posterior
into the fusion as soft evidence — the branches stay divorced.)

**6.5 CSV / prep wiring.** `wflow_wrsi_prep.py` already emits `w10_p1..p4` soft
evidence — reuse it directly for `wrsi10_ev`. Add `fpar_p1..p4` (Opt 2 prep) and
`phase_p1..p3` (Opt 3 tracker) columns; `run_csv` reads them with the existing
`_soft(prefix,k,row)` helper. Absent columns ⇒ least-stress default ⇒ no-op.

---

## 7. Guarantees & self-tests (extend the existing `self_test`)

Add tests in the style of the current CDI tests (#4–#8):

1. **cws no-op:** `cws = No_Stress` ⇒ `agri_risk == risk` (max abs diff < 1e-12)
   — the backward-compatibility guarantee, exactly like `cdi=1`.
2. **Monotonicity:** raising `wrsi10` or `fpar` (phase fixed) never lowers
   `P(cws ≥ Moderate)`.
3. **Convergence:** `wrsi10=Severe ∧ fpar=Severe` gives higher `P(cws=Severe)`
   than either alone.
4. **Phenology:** the same `wrsi10` deficit yields higher `agri_risk` under
   `phase=Flowering` than under `phase=Maturation`.
5. **Fusion escalation is bounded:** `cws=Severe` on a `Minimal` meteo `risk`
   does *not* reach `Extreme` without meteo corroboration (basis-risk control).
6. **Tensor == direct:** the contraction path equals `compute_*_probs`
   (mirror CDI test #8).

---

## 8. Bottom line

- **Answer to the choice:** Approach B (crop-stress sub-branch). Approach A
  (flat parents) is ruled out by the five-parent cap *and* by Bayesian
  hygiene — it inflates the CPT ~50× to ~6.5 M unlearnable entries and can
  never run RxInfer-native.
- **Structural change is modest, not a rewrite:** two new 4-/5-state nodes, two
  small CPTs (192 + 100 entries), three categorisers, and the same
  soft-evidence / matmul machinery already in the engine — the CDI integration
  is the exact template. The meteo branch and the CRMA cost-loss rule are
  untouched.
- **It advances the Jaynes programme on this code base:** parent-divorcing =
  the sum rule with an auxiliary proposition; soft evidence = the product rule;
  MaxEnt fills the small CPTs; Dirichlet updating turns them into local memory.
  The small tables are what make explicit elicitation *and* real learning
  feasible for the first time — the flat alternative forecloses both.
- **It is the realisation of the plan's own "divorce-the-parents" Stage 1**
  (`wrsi_bn_integration_plan.md`), now specified concretely and grounded in the
  committed engine.
