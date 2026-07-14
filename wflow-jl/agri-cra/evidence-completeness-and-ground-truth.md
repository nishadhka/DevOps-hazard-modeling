# Missing evidence, and the role of hard / soft / virtual evidence

**How the CRMA-BN issues an advisory when part of its evidence is absent or
stale — declaring what was missing rather than hiding it — and how sparse,
opportunistic ground readings (a soil-moisture probe stuck in a field, no
continuity, no fixed site) enter the network and make it better.**

Companion to `pipeline/evidence_nodes.md` (the evidence taxonomy and the
per-node data sources), `asap/asap-crma-gap-and-bn-role.md` (the fusion-layer
framing), and `continuous-risk-monitoring-agri-advisory.md` (the curatorial
direction).

Status labels used below: **[built]** exists in the engine today,
**[proposed]** is a design not yet implemented.

---

## 1. The claim, in one sentence

A Bayesian network does not *need* all its evidence, because absent variables
are **marginalised out** rather than guessed — but "degrades gracefully" is an
engineering property that has to be **built and tested**, not a philosophical
one you get for free, and the advisory must **say what it did not know**.

---

## 2. Why a BN tolerates missing evidence, and a rule table does not

ASAP's warning classification is a lookup: it needs `zWSI`, `SPI3`, `zFPARc`
and a phenological phase to reach a cell in its table. Take one away and the
rule does not fire — the system is silent, and silence is indistinguishable
from "no risk".

The BN is defined over a **joint distribution**, so an unobserved parent is
integrated out by the sum rule:

```
P(risk | observed subset)  =  Σ_unobserved  P(risk, unobserved | observed)
```

The posterior is still a well-formed probability — just wider. **Missing
evidence costs you sharpness, not validity.** That is the single most
operationally valuable property of the whole architecture, and it is why the
CRMA-BN can run every dekad on whatever actually arrived, while a threshold
system cannot.

---

## 3. Encoding absence: three wrong ways and one right one

This section is written from bugs I actually shipped and then fixed, because
they are the most convincing argument that this is subtle.

**Wrong (1) — impute a default value.** `fpar` originally had four states with
`Healthy` as the default when data was absent. But "we have no vegetation
observation" and "we observed the vegetation and it is healthy" are **different
propositions**. Observed-healthy vegetation under a water deficit is positive
evidence that the crop has not yet responded (ASAP's level-1 rung) and should
*temper* the risk. So the 4-state default silently converted **missing data
into a tempering claim** — the network became *less* worried precisely because
it knew *less*. Fixed by giving `fpar` an explicit fifth state, `Unknown`.
**[built]**

**Wrong (2) — spread the mass uniformly.** It is tempting to say "we know
nothing, so put 1/4 on each of the four states". On a **monotone stress
ladder** that is not neutral at all: a uniform vector puts **three quarters of
the mass on stressed states** and escalates the posterior. `wflow_wrsi_prep.py`
did exactly this for basins with no crop pixels, so a basin escalated *because*
we had no data for it. **[fixed]**

**Wrong (3) — drop the row.** Excluding a boundary from the advisory because
one node is missing reproduces the rule-table failure: the map goes blank where
we are least informed, which is usually where we should be most careful.

**Right — route absent mass to the node's identity state.** Every node in the
crop branch has a state whose CPT column is the **identity map** on the
posterior (`wrsi10` → `No_Stress`, `fpar` → `Unknown`, `cdi` → `No_drought`,
`tail` → `Nil`). Sending "we don't know" to that state leaves the posterior
**provably unchanged**, which is exactly what not knowing should do. The engine
asserts this: `cws = No_Stress ⇒ agri_risk == risk` to machine precision, and
`cdi = 1` / `tail = 1` are tested no-ops. **[built]**

> **The design rule:** a node's absent-evidence sink must be the state that is
> an *identity on the posterior*, never a "typical" value and never a uniform
> vector. If a node has no such state, it needs one.

---

## 4. Stale evidence is missing evidence wearing a disguise

Measured on 2026-07-13 against the stores the pipeline actually reads:

| store | nominal cadence | latest | lag |
|---|---|---|---|
| GDO fAPAR anomaly (`fpanv`) | dekadal | 2026-03-21 | **114 days** |
| GDO soil moisture (`smang`) | dekadal | 2026-03-21 | **114 days** |
| ICPAC EADW CDI | dekadal | 2026-04-01 | **103 days** |
| CHIRPS SPI | monthly | 2026-02-01 | **162 days** |

Today a 114-day-old vegetation reading enters the BN with **exactly the same
confidence as a fresh one**. That is worse than the data being absent: absence
widens the posterior honestly, whereas staleness produces a *confident, current-
looking, wrong* posterior. It is the failure mode most likely to burn an
early-warning system's credibility.

**[proposed] The staleness discount.** Because every node already has an
identity sink (§3), age can be handled in one line of the same shape as the
existing crop-area gate:

```
soft_evidence ← strength(age)·soft_evidence + (1 − strength(age))·onehot(identity)
```

with a node-specific half-life (`fpar` ~2–3 dekads; SPI-derived nodes ~1–2
months; `wrsi10` ~1 dekad). Evidence then **decays back toward "we don't know"**
instead of pretending to be current. This is, in my view, more urgent than any
remaining Option — it is the difference between a system that is quiet when
blind and one that is confidently wrong.

---

## 5. The three kinds of evidence, and what each is actually for

Extending the taxonomy in `pipeline/evidence_nodes.md`:

| Kind | Form | What it asserts | Where it belongs |
|---|---|---|---|
| **Hard** | `P(X = k) = 1` | *This variable is in state k, with certainty.* | Almost nowhere. It asserts zero measurement error. |
| **Soft** | `P(X = k) = p_k` | *I am uncertain which state the variable is in.* | Gridded/zonal evidence. The `*_p1..pk` columns: the spatial distribution of pixels across classes **is** the distribution. **[built]** |
| **Virtual** (Pearl's noisy channel) | auxiliary node `L` with `P(L \| X)`; update `P(X\|L) ∝ P(X)·P(L\|X)` | *I have a **noisy observation** of the variable; here is how reliable that instrument is.* | Any real sensor or report. `cdi_evidence_update.py` already does this with a 6×5 column-stochastic matrix. **[built]** |

The distinction that matters most, and that is routinely muddled:

> **Soft evidence** models uncertainty **about the world**.
> **Virtual evidence** models the unreliability **of the instrument**.

A satellite composite over a basin is soft evidence: many pixels, a genuine
distribution over states. A person kneeling in one field with a probe is *not*
that — it is a **noisy measurement**, and the right question is not "what
distribution over basin states does this imply?" but "**how likely is this
reading, given each possible true state?**" That is precisely a likelihood, and
precisely virtual evidence.

---

## 6. The case: sparse, opportunistic ground soil-moisture readings

The situation: readings taken **wherever someone happened to be**, with **no
continuity**, **no fixed sensor placement**, possibly different probes, depths
and operators.

### 6.1 Why this cannot be an ordinary soft-evidence node

- **No climatology, so no anomaly.** A reading of 0.22 m³/m³ is meaningless
  without knowing what is normal *at that spot*. Every other node in the BN is
  an **anomaly** (SPI, `fpanv`, `smang`, WRSI-vs-normal) precisely because
  absolute values are not comparable across soils. One opportunistic point has
  no local baseline and never will.
- **Spatial support mismatch.** One probe does not summarise a 5,000 km²
  basin. Treating it as a basin-level soft-evidence vector is a category error.
- **No series, so no trend.** Half the BN's met evidence is trend-shaped
  (`trn`, `spi3_trend`); a scattered set of one-off readings cannot supply it.

Forcing this data into a normal node would require inventing all three.

### 6.2 Why it is a textbook virtual-evidence case

The BN **already has the latent variable this reading is about.** Soil moisture
sits inside the chain in two places: wflow.jl integrates root-zone soil moisture
to produce WRSI, and CDI's Warning classes turn on the SMA term. The crop
branch's `crop_water_stress` (`cws`) node *is* the "how water-stressed is this
crop, really" proposition. **A soil-moisture probe is a direct — if noisy —
observation of exactly that latent.**

So: do not build a new node. Attach a **noisy channel** to `cws`. **[proposed]**

```
P(cws | ground readings)  ∝  P(cws | wrsi10, fpar, phase) · Π_j  L[ obs_j , cws ]
                             └─── the model's prior ───┘   └─ one channel per reading ─┘
```

`L[obs, cws]` is a small, deliberately **flat** column-stochastic matrix: given
that the crop is truly in each `cws` state, how likely is a random field probe
to read Dry / Normal / Wet? It is elicited (or later fitted), and it absorbs
**all** the messiness — instrument error, depth mismatch, representativeness,
operator variation — into **one auditable object**. That concentration is the
whole point of the noisy-channel formulation, and it is the same move
`cdi_evidence_update.py` already makes.

### 6.3 Why the awkward properties stop being awkward

- **No continuity needed.** A likelihood is evaluated per reading. It never
  asks for a series.
- **No climatology needed** *for the channel*, if the reading is compared
  against **the model's own soil moisture at that pixel** — wflow.jl gives you a
  modelled value at the probe's location, so the informative quantity is the
  *discrepancy*, not the absolute.
- **Evidence accumulates by the product rule.** Three probes all reading dry
  multiply three channels and sharpen the posterior more than one does. Sparse
  is not useless — sparse is just *weak*, and weakness is representable.
- **Zero readings is an empty product = 1 = the identity.** No coverage → no
  effect, automatically. The graceful-degradation property of §3 falls out for
  free, with no special-casing.
- **Representativeness can be weighted** — scale a reading's channel by the crop
  fraction (the ASAP AFI is already loaded) at that pixel, so a probe in a
  cropped field counts for more than one in a rangeland corner.

### 6.4 The trap to avoid

Ground data carries enormous **felt authority** — "we actually measured it."
Resist letting that become **hard evidence**. One probe in a large basin is, in
information terms, **weaker** than a satellite composite over thousands of crop
pixels, and a channel matrix that is too sharp will let a single unrepresentative
reading override the entire model. The channel must be **honestly noisy**. This
is a curatorial judgment — whose evidence is trusted how much — and it belongs in
the open, logged, and contestable, exactly like the CPT.

---

## 7. Reporting missingness: separating *low risk* from *low information*

This is the part the advisory must not fudge.

A `Monitor` state because every stream says conditions are fine, and a `Monitor`
state because almost nothing arrived, are **completely different claims** — and
the current output cannot tell them apart. Both produce an unalarming posterior.

**[built]** `confidence = 1 − H/H_max` (entropy sharpness) partially exposes
this: a diffuse posterior scores low. But entropy cannot say *why* it is
diffuse.

**[proposed] Emit the evidence ledger with every advisory:**

- `evidence_completeness` — fraction of nodes carrying fresh, non-identity
  evidence.
- `evidence_log` — per node: `observed` / `stale(age)` / `absent`, plus the
  source and its provenance (the preps already write `fapar_source`,
  `cdi_source`, `fpar_guard`, `deficit_threshold_source`).
- A plain-language line on the bulletin: *"Issued without vegetation evidence
  (fAPAR 114 days stale); soil-moisture and rainfall streams current."*

**Never suppress an advisory for missing evidence — always label it.** Silence
is read as safety.

---

## 8. The loop this closes — and why it is the good part

The CRMA ladder already contains the right rung for missing evidence, and I do
not think this was noticed:

> **`Assess` does not mean "act". It means *the evidence is insufficient or
> ambiguous — go and look*.**

Which makes sparse ground readings not an awkward afterthought but **the
designed response to an incomplete posterior**:

```
   thin / stale evidence  →  wide posterior  →  CRMA: Assess ("go look")
                                                        │
                                    field officer takes a few probe readings
                                                        │
                              virtual evidence: Π_j L[obs_j , cws]
                                                        │
                                       posterior sharpens
                                                        │
                                 → Review (act on it)   or   → Monitor (stand down)
```

Sparse, discontinuous, opportunistically-sited ground data is **precisely** what
this architecture wants, because it is targeted: you spend a scarce field visit
where the model says it is *uncertain*, not where it is already sure. That is
the cost-effectiveness argument for CRMA restated at the level of a single soil
probe — and it is also, over seasons, how the channel matrix `L` and eventually
the CPTs get **fitted from reality** rather than elicited (the Dirichlet loop in
`continuous-risk-monitoring-agri-advisory.md` §3). Sparse ground data has two
lives: **weak evidence today, calibration data forever**. The second is probably
worth more.

---

## 9. What to build, in order

1. **[proposed] Staleness discount** (§4) — decay each node's evidence toward
   its identity state with a node-specific half-life. Highest value: without it
   the system is confidently wrong on 3-month-old data. ~20 lines, reuses the
   crop-area-gate shape.
2. **[proposed] Evidence ledger** (§7) — `evidence_completeness` +
   `evidence_log` on every row, and on the bulletin. Cheap; makes the two-speed
   (dekadal/monthly) reality honest.
3. **[proposed] Ground virtual-evidence channel** (§6) — `ground_obs_update`
   applying `Π_j L[obs_j, cws]` to the crop-stress posterior, weighted by crop
   fraction, defaulting to the identity with zero readings.
4. **[later] Fit `L` from accumulated readings**, then the CPTs — the
   verification loop.

## 10. Honest limits

- The channel matrix `L` will start as **expert-elicited**, i.e. a guess. It
  must be labelled as such (as `κ` and the `cws` weights already are) and
  revised against data. An elicited `L` that is too sharp is actively dangerous.
- Comparing a probe against wflow's own soil moisture (§6.3) makes the evidence
  **partly circular** — it is no longer independent of the model it is updating.
  The channel must be built to test the *discrepancy*, and this correlation
  belongs in the same "shared signal" ledger as the `wrsi10`↔`cur` double-count
  already fixed at the agri fusion.
- None of this rescues a stream that is simply not being ingested. The 103–162
  day lags in §4 are an **operations** failure, not a modelling one, and no
  amount of principled discounting substitutes for re-ingesting the mirrors.
