# RxInfer.jl Bayesian Network: Architecture, Limitations & Issues

**Summary**: Migration of E4DRR flood IBF from pgmpy (Python) to RxInfer.jl (Julia) revealed multiple architectural challenges around multi-parent inference, soft evidence handling, and the library's readiness for production use.

---

## 1. Project Context

**Goal**: Implement Bayesian Network inference for Flood Impact-Based Forecasting (IBF) at admin-1 level in East Africa.

**Data Pipeline** (Apr 14–19, 2026):
- **Observations**: IMERG half-hourly precipitation (icechunk, s3://e4drr-project/observations/imerg_hh_icechunk)
- **Forecasts**: ECMWF TP ensemble (51 members, 53 lead times 0–168h)
  - Pancake (icechunk): s3://e4drr-project/forecasts/ecmwf_ea_tp_icechunk
  - Pencil (zarr): s3://e4drr-project/forecasts/ecmwf_ea_tp_pencil_zarr
- **Reference**: CMORPH return-period thresholds (7 durations: 3h–7day, 5-year RP default)

**Target**: 10-day operational forecast (Mar 1–10, 2026) → 227 admin-1 boundaries → per-boundary risk estimate

---

## 2. Bayesian Network Structure

### DAG (5 → 1 + action) — Five-Node Limitation

```
antecedent_rainfall (5 states)  ─┐
exceedance_prob (5 states)       ├─→ risk_level (5 states) → action (4 states)
spatial_coverage (3 states)      ├─→ [DEPRECATED: action node]
rainfall_trend (3 states)        ├→
forecast_agreement (3 states)    ┘
```

**CPT Dimensionality**: 5 parents × up to 5 states each = 675 parent combinations

**Inference**: Hard evidence selects one column from CPT matrix; soft evidence requires weighted sum over all 675 combos.

### Python Implementation (pgmpy)

- **Tools**: pgmpy, xarray, geopandas, regionmask
- **CPTs**: Expert-elicited transition matrices → hardcoded as pandas DataFrames
- **Inference**: Variable elimination (pgmpy.inference.VariableElimination)
- **Batch processing**: Single query() call per boundary per day

### Julia Port (RxInfer.jl)

- **Tools**: RxInfer.jl, CSV.jl, DataFrames.jl, uv run for Python pre-processor
- **CPTs**: Same expert tables, vectorized as Julia matrices
- **Inference**: Two modes (see §3 below)
- **Pipeline**: Python pre-processor (flood_data_prep.py) → CSV → Julia BN (flood_bn_ibf_v1.jl)

---

## 3. Core Limitation: The Five-Node Multi-Parent Problem

### The Issue

RxInfer's `DiscreteTransition(y, x, T)` primitive accepts **a single parent**.

Since `risk_level` has **5 parents**, the initial approach was:

```julia
# ❌ NOT POSSIBLE:
risk ~ DiscreteTransition(ant, exc, spa, trn, agr, risk_cpt)
```

### Workaround: Super-Parent Encoding (Apr 8)

Encode 5 discrete parents into a single "super-parent" index via Cartesian product:

```julia
function encode_parents(ant_idx, exc_idx, spa_idx, trn_idx, agr_idx)
    # 5×5×3×3×3 = 675 combinations
    return 1 + (ant_idx-1)*675 + (exc_idx-1)*135 + (spa_idx-1)*45 + (trn_idx-1)*15 + (agr_idx-1)
end

risk ~ DiscreteTransition(super_parent_idx, risk_cpt[:, super_parent_idx])
```

**Trade-off**: Works, but obscures the DAG semantics. The library sees one parent; the model hides a factored structure.

---

## 4. Current Implementation Status

### April 8: Python-Julia Comparison

**Two inference modes** in `flood_bn_ibf_v1.jl`:

| Mode | Implementation | Status | When Used |
|------|---|---|---|
| `infer_direct()` | Matrix index lookup: `risk_cpt[:, parent_idx]` | ✅ Production | Daily inference (hard evidence) |
| `infer_rxinfer()` | RxInfer @model macro + DiscreteTransition | ❌ Dead code | Never called; kept for future |

**Reality Check (Apr 19)**: 
- Project.toml does **not** list RxInfer as a dependency
- `@eval using RxInfer catch; HAS_RXINFER=false end` — optional, fails silently
- Real engine: **hand-rolled 2-line matmul** (lines 445–472)
- **Conclusion**: RxInfer is a "ghost dependency" — never actually used

---

## 5. The Nine-Point Forward Path (Probabilistic Logic v20260413)

### Current Status (Apr 19)

| # | Upgrade | Tier | Status | RxInfer Use? |
|---|---------|------|--------|---|
| 1 | Remove action node from BN (CRMA outside) | near | ✅ Done (commit 9e080ee) | No |
| 2 | Cost-loss-based CRMA thresholds | near | ✅ Done (cost_loss_ratio=0.2) | No |
| 3 | Per-member risk sidecar CSV | near | ✅ Done (--member-sidecar) | No |
| 4 | **Soft evidence** (prob-over-states) | medium | ⏳ Pending | **YES — unlocks library use** |
| 5 | **Dynamic BN** (P(risk[t]\|risk[t-1])) | medium | ⏳ Pending | **YES — natural fit** |
| 6 | Storyline selection (worst/median/best member) | medium | 🟡 Partial | No (sidecar exists) |
| 7 | **Dirichlet priors + CPT learning** | long | ⏳ Pending | **YES — critical** |
| 8 | Exposure × vulnerability (WorldPop/INFORM) | long | 🟡 In progress | No |
| 9 | **Hierarchical spatial BN** (MRF across admin-1) | long | ⏳ Pending | **YES — message passing** |

---

## 6. Soft Evidence (#4): The First Real RxInfer Use Case

### The Problem
Today, each parent is classified into **one discrete state** (hard evidence):
- antecedent_rainfall → "Very_Wet" (deterministic)
- exceedance_prob → "High" (deterministic)

But observations carry uncertainty:
- IMERG pixel at boundary edge: 55% "Wet", 45% "Very_Wet"
- ECMWF ensemble spread: P(exceed threshold) = 0.63 (not 0/1)

### RxInfer Solution (Apr 19)

**Native multi-parent soft-evidence model**:

```julia
@model function flood_bn(; risk_cpt_tensor, 
                          p_ant, p_exc, p_spa, p_trn, p_tail)
    # Soft evidence = Categorical prior on each parent
    # Hard evidence = one-hot vector (same code path)
    ant      ~ Categorical(p_ant)      # [0.0, 0.1, 0.55, 0.35, 0.0]
    exc      ~ Categorical(p_exc)      # [0.0, 0.2, 0.6, 0.2, 0.0]
    spa      ~ Categorical(p_spa)      # [0.33, 0.34, 0.33]
    trn      ~ Categorical(p_trn)      # [0.1, 0.8, 0.1]
    tail     ~ Categorical(p_tail)     # [0.0, 0.0, 0.5, 0.5]
    
    # Multi-parent tensor CPT (5×5×5×3×3×4)
    risk     ~ DiscreteTransition(ant, exc, spa, trn, tail, risk_cpt_tensor)
end

# Hard evidence: p_ant = [0,0,1,0,0] (one-hot)
# Soft evidence: p_ant = [0.0, 0.1, 0.55, 0.35, 0.0] (prob vector)
# Same model, same inference — library handles both.
```

**Advantage**: Message passing automatically marginalizes over parent uncertainty.

**Data requirement**: flood_data_prep.py must emit 5 probability columns per parent (instead of single state label).

---

## 7. Storage Backend: Pancake vs Pencil (Apr 19)

### Benchmark: Full Slice vs Per-Pixel-Member

| Access Pattern | Pancake (icechunk) | Pencil (zarr) | Winner |
|---|---|---|---|
| Full init slice (51×53×157×145) | 11.8 s | 52.2 s | **Pancake 4.4×** |
| Single pixel × 51 members × 53 leads | 9.3 s | 1.4 s | **Pencil 6.5×** |

**Current Pipeline** (#1–3): Loads full grid per day → pancake wins

**Soft Evidence Pipeline** (#4+): Per-pixel-member Gumbel posterior → pencil becomes optimal

**Recommendation** (Apr 19): 
- Keep pancake (icechunk) for items 1–3 ✅
- Switch to pencil (zarr) when #4 starts, behind `--pencil` flag
- Benefit: 6.5× speedup for per-pixel soft-evidence generation

---

## 8. RxInfer Adoption Bottleneck

### Why It's Currently Unused

1. **Hand-rolled matrix multiply is 2 lines** — overkill to spin up RxInfer for exact inference on 675-node DAG
2. **No soft evidence yet** — library's message passing has no payoff
3. **No learning loop** — expert CPTs are fixed; no reason to call the inference engine
4. **World-age issues** — RxInfer compilation cache can hit UndefVarError on dynamic imports

### When RxInfer Becomes Essential

| Item | Why RxInfer Wins |
|---|---|
| #4 (Soft Evidence) | Message passing marginalizes parent uncertainty natively |
| #5 (DBN) | Time-slice message passing is the library's core strength |
| #7 (Learning) | Dirichlet-posterior conjugacy built-in; custom updates would be complex |
| #9 (Hierarchical) | MRF (Markov Random Field) factorization requires belief propagation |

### Recommendation (Apr 19)

- **Use hand-rolled for #4 + #6** (soft evidence isn't message-passing yet; storytelling is post-inference)
- **Commit to RxInfer at #5** (Dynamic BN) or #7 (learning), whichever comes first
- **If choosing #5 first**: Add RxInfer to Project.toml; build time-slice CPT; keep state vectors for posterior tracking
- **If choosing #7 first**: Add Dirichlet / conjugate prior machinery; vectorize the update loop

---

## 9. Five-Node Limitation & Future Workarounds

### Current Constraint
- 5 parents → 675 combinations → manageable for exact inference
- Super-parent encoding hides structure but works

### Potential Future Issues

| Scenario | Impact | Solution |
|---|---|---|
| Add 6th parent (e.g., soil moisture) | 2025 combinations → still fast matmul | Stay hand-rolled; no library change needed |
| Add 8th parent | 15,625 combinations | Still O(1) lookup; explicit FactorGraph notation needed |
| Switch to approximate inference (belief propagation) | 675 parents becomes intractable | RxInfer is *designed* for this; library refactoring worth it |

### Architectural Shift (2027+)
If moving to **hierarchical spatial BN** (#9), the single "super-parent" becomes a liability:
- Each admin-1 node has a parent = "neighbor's risk" (4–6 neighbors)
- Factorization across the spatial MRF requires library-level support for non-tree structures

**Likely outcome**: Rewrite the model using RxInfer's `FactorGraph` primitive instead of @model macro.

---

## 10. Summary: Current State & Recommendations

### ✅ What Works Today
- Hard-evidence inference (April 1–30, 2026 runs succeeded)
- Super-parent encoding handles 5 parents cleanly
- Pencil zarr store ready for pixel-level access patterns

### ⚠️ What's Broken / Missing
- **RxInfer is not actually used** — it's a no-op in the current stack
- **Soft evidence (#4) is pending** — needed for operational forecast uncertainty
- **No Dynamic BN (#5)** — can't forecast risk tomorrow given today's state
- **No learning loop (#7)** — CPTs are frozen expert tables

### 🎯 Next Steps (Priority Order)

1. **Decision (this week)**: Soft evidence route?
   - Option A: Hand-rolled kron + matmul (quick, ~60 lines Python + 20 Julia)
   - Option B: Native RxInfer (commits the library; unlocks message passing for #5)
   
2. **If Option B**: Refactor flood_bn_ibf_v1.jl to accept `Categorical` inputs and call `infer()` (not matmul)

3. **If Option A**: After soft evidence stabilizes, revisit RxInfer for #5 (Dynamic BN), where library's strength is unambiguous

---

## Appendix: Files & Commits

- **flood_ibf/flood_bn_ibf_v1.jl** — Julia port (Apr 8, commit TBD)
- **flood_ibf/python_julia_bn_comparison.md** — Detailed comparison (Apr 8)
- **flood_ibf/flood_data_prep.py** — Data pipeline (Apr 14–19)
- **2026-04-14-jua-bnet-reflections.txt** — Planning session, admin-1 inference scope
- **2026-04-19-DBN-mark0v-issue-of-crma.txt** — RxInfer usage review, 9-point status, soft-evidence recommendation
- **probabilistic_logic_v20260413.md** (referenced) — The 9-point upgrade roadmap

---

**Document Updated**: 2026-07-11  
**Status**: RxInfer integration pending decision on soft-evidence approach
