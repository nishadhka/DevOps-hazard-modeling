# Planning: WRSI evidence integration into the drought BN

Integrates three new evidence streams into the CRMA/BN architecture of
`gpt55_flight_sim_drm_agri-advisory.md`:

1. **ECMWF SEAS5.1** seasonal forecast (raw fields, not just SPI3)
2. **10-day WRSI** from wflow.jl (subseasonal crop water stress)
3. **TAMSAT-ALERT API** seasonal WRSI (6-month / season outlook)

and then extends `bn-ibf/drought_ibf/drought_bn_ibf_v1.jl` +
`drought_data_prep.py` to consume them.

---

## Stage 0 — What exists today (baseline)

| Component | State |
|---|---|
| `drought_data_prep.py` | Builds admin-1 evidence CSV from ERA5 SPI obs + **SEAS5.1 SPI-3** icechunk (`seas51_spi3_10km_icechunk_v2`, 51 members × 6 leads). Nodes: `cur`, `def`, `spa`, `trn`, `agreement`, `tail` + soft bins `*_p1..pN`. |
| `drought_bn_ibf_v1.jl` | 5-parent BN (cur, def, spa, trn, tail; agreement as blend modifier) → `risk` (5 states) → CRMA cost-loss state. RxInfer + matmul tensor fallback, DBN monthly chaining, per-member storylines. |
| wflow.jl v4 | 11/11 basin cases produce `output_grid_wrsi.nc` (WRSI capability proven); MWI case 12 staged. Event eval: DJI/KEN/ERI/ETH reproduce their droughts. |
| `mwi/download_s2s_forcing.py`, `compute_pet.py` | CDS S2S ensemble downloader + hydromt PET (penman-monteith_tdew) — the forcing pattern for forecast-driven wflow runs. |

Key observation: **the current BN is purely meteorological** (all six nodes
derive from SPI). The three new streams add *agricultural* drought evidence
at two horizons (dekadal + seasonal). That is exactly the CRMA claim in the
advisory doc: hazard models become evidence, they don't replace the engine.

---

## Stage 1 — Evidence semantics (design before code)

Decide, per stream, what the node *means*, its states, and its cutoffs.

### Node A: `wrsi10` — subseasonal crop water stress (wflow.jl)
- Source chain: S2S/extended-range ensemble forcing → wflow_sbm run per
  basin case → `output_grid_wrsi.nc` → dekadal WRSI → cropland-masked zonal
  aggregation to admin-1 → per-member stress fraction.
- States (4), FAO WRSI classes collapsed:
  `No_Stress (≥95)`, `Mild (80–95)`, `Moderate (60–80)`, `Severe (<60)`.
- Scalar column: `wrsi10_value` (zonal median over cropland), plus
  `wrsi10_stress_prob` = fraction of ensemble members with WRSI < 80.
- Soft bins `w10_p1..p4` from ensemble spread (not a sigma kernel —
  the ensemble *is* the distribution).

### Node B: `wrsi_seas` — seasonal WRSI outlook (TAMSAT-ALERT)
- TAMSAT-ALERT method: historical weather ensemble re-weighted by the
  seasonal forecast's tercile probabilities. **SEAS5.1 supplies those
  tercile weights** — this is the designed coupling between stream 1 and 3,
  not two independent downloads.
- API call per admin-1 (or per representative point/zone): returns
  probability distribution of end-of-season WRSI (or yield-proxy) vs
  climatology.
- States (4): `Above_Median`, `Near_Median`, `Below_Median`, `Well_Below`
  (or FAO classes if the API returns absolute WRSI — confirm response
  schema first; see Stage 2 risks).
- Scalar columns: `wrsi_seas_prob_below` (P(below-median)),
  `wrsi_seas_ens_min` (worst member, tail analogue). Soft bins `wse_p1..p4`.

### Node C: SEAS5.1 raw fields — not a new BN node
SEAS5.1 already feeds the BN via SPI-3 (`def`, `tail`, `agreement`). Its
*new* role is upstream: (a) raw precip/temp/radiation as wflow forcing for
seasonal-horizon WRSI runs, (b) tercile weights for TAMSAT-ALERT. Adding a
third SEAS5-derived met node to the BN would triple-count one model.

### Double-counting / conditional independence (the main design risk)
The BN assumes parents are independent given `risk`. But:
- `def`/`tail` (SEAS5 SPI3) and `wrsi_seas` (TAMSAT-ALERT weighted by
  SEAS5 terciles) share the same driving model → strongly correlated.
- `wrsi10` and `cur` share observed antecedent conditions.

Mitigation — **divorce the parents** (hierarchical BN):

```
cur  def  spa  trn  tail          wrsi10  wrsi_seas
  \   |    |    |   /                 \      /
   met_drought_risk (5)          crop_water_stress (4)
              \                     /
               agri_risk (5 states)
                      |
                CRMA state (cost-loss rule, unchanged)
```

- `met_drought_risk` = existing risk node, untouched CPT.
- `crop_water_stress` = new small CPT (4×4 → 4).
- `agri_risk` CPT (5×4 → 5) encodes the interaction: met-drought high but
  crops unstressed (irrigated / early season) tempers risk; met-drought
  moderate but WRSI collapsing escalates it.
- This keeps every CPT human-authorable and avoids exploding the existing
  6-D tensor to 8-D (5·5·3·3·4·4·4 = 14 400 combos of hand-tuned rules).
- The correlation between the met side and TAMSAT-ALERT is then absorbed
  at the `agri_risk` CPT level (one place to discount), not spread across
  a flat 7-parent rule set.

Fallback option (rejected): flat 7-parent risk node. Matmul handles it, but
`compute_risk_probs` rule authoring and validation become intractable.

---

## Stage 2 — Data pipelines (Python prep side)

Extend `drought_data_prep.py` (or add `agri_data_prep.py` that merges onto
its CSV by boundary `id` + `target_date` — preferred, keeps met prep pure).

### 2a. SEAS5.1 raw forcing
- CDS `seasonal-original-single-levels` (system 51) — reuse the
  `mwi/download_s2s_forcing.py` + `compute_pet.py` pattern (tp, t2m, tdew →
  PET penman-monteith_tdew), domain per v4 case.
- Regrid/downscale to each case's staticmaps grid; monthly → daily
  disaggregation choice needed (simplest: ESP-style — use SEAS5 monthly
  anomalies to weight historical daily traces, which is exactly the
  TAMSAT-ALERT trick; avoids inventing daily rain from monthlies).

### 2b. wflow.jl 10-day WRSI runs
- Warm state: run wflow to present with observed forcing (ERA5/CHIRPS),
  save instates; branch N ensemble runs with S2S forcing for the next
  10–30 days.
- Per run, read `output_grid_wrsi.nc` **defensively** (known issue:
  missing/time=0/corrupt under concurrent batch — guard reads).
- Zonal reduce to admin-1 over a cropland mask (ESA WorldCover or
  Copernicus LC); a basin↔admin-1 crosswalk table is a new required asset
  (v4 cases are basins, BN rows are admin-1).
- Output parquet: `id, target_date, member, wrsi10_value` → aggregated
  columns + soft bins into the BN CSV.

### 2c. TAMSAT-ALERT API client
- New `tamsat_alert_client.py`: auth/registration, request WRSI (or
  soil-moisture/yield proxy) forecast per zone for the target season,
  passing SEAS5.1 tercile weights; parse ensemble → probabilities.
- Cache responses (parquet per init-month); hard requirement: **missing
  evidence must degrade gracefully** — if the API is down, the node gets a
  uniform/absent prior, never a stale or fabricated value.
- First concrete task: probe the API and pin the actual response schema
  before freezing Node B's states.

### 2d. CSV schema addition (consumed by the Julia side)
```
wrsi10_value, wrsi10_stress_prob, w10_p1..w10_p4,
wrsi_seas_prob_below, wrsi_seas_ens_min, wse_p1..wse_p4
```
All optional columns — BN runs unchanged when absent (same pattern as
`ens_min_spi` / `--tail-risk`).

---

## Stage 3 — Julia script extension (`drought_bn_ibf_v1.jl` → v2)

Concrete changes, in dependency order:

1. **Constants**: `WRSI10_STATES` (4), `WRSI_SEAS_STATES` (4),
   `AGRI_RISK_STATES` (reuse `RISK_STATES`); FAO cutoffs
   `WRSI_THRESHOLDS = (no_stress=95, mild=80, moderate=60)`.
2. **Categorisers**: `categorize_wrsi10(v)`, `categorize_wrsi_seasonal(p)`
   with NaN → missing-evidence branch (uniform, *not* a default state —
   differs from current NaN handling, which silently maps to Normal).
3. **New CPTs**:
   - `compute_crop_stress_probs(w10, wseas)` → 4-vector (small, fully
     enumerable, expert-authored like `compute_risk_probs`).
   - `compute_agri_risk_probs(met_risk, crop_stress)` → 5-vector, with the
     discounting for met/agri evidence correlation.
   - Tensor builders `build_crop_cpt_tensor()` (4×4×4) and
     `build_agri_cpt_tensor()` (5×5×4).
4. **RxInfer model**: `drought_bn_model_agri` — existing 5-parent block
   plus `w10 ~ Categorical`, `wseas ~ Categorical`,
   `crop ~ DiscreteTransition(w10, Tc, wseas)`,
   `agri ~ DiscreteTransition(risk, Ta, crop)`; matmul fallback contracts
   the two small tensors after the existing 6-D contraction (cheap).
5. **CRMA rule**: apply `compute_crma_state` to the `agri_risk` posterior;
   keep emitting the met-only CRMA state alongside for comparison
   (`crma_state_met`, `crma_state_agri`) during a parallel-run period.
6. **CSV driver**: read new optional columns; `--agri` flag mirrors
   `--tail-risk` gating; output adds `crop_stress_*` and `agri_risk_*`
   probability columns.
7. **DBN cadence**: BN stays monthly; `wrsi10` updates dekadally →
   within-month policy = **worst dekad of the month** (conservative,
   matches early-warning posture). Optionally later: dekadal DBN steps
   with `lookback=18`.
8. **Per-member storylines**: extend `run_per_member_bn` to join wflow
   member WRSI with SEAS5 member SPI only if members can be physically
   paired; otherwise keep storylines met-only for now (document this).
9. **Self-tests**: worst case (Severe drought + Severe WRSI both horizons
   → Extreme/Actionable_Risk), divergence case (met Extreme + WRSI
   No_Stress → agri risk < met risk), missing-WRSI case (agri ≈ met),
   entropy check on missing evidence.

---

## Stage 4 — Validation & calibration

- **Hindcast replay**: rerun the v4 WRSI drought events (DJI 2011-OND,
  KEN/ERI/ETH cases already evaluated) through the extended BN; the agri
  CRMA state should lead or match the met-only state for the true events,
  without new false alarms in neutral seasons. TZA/SOM/SSD cases are known
  bad (wrong basin / degenerate WRSI) — exclude, don't tune to them.
- **Ablation**: run with (a) met only, (b) +wrsi10, (c) +wrsi_seas,
  (d) both — quantify what each stream adds (lead time, hit/false-alarm).
- **Correlation audit**: empirical corr between `def`-bin and `wrsi_seas`
  bin over the hindcast; if > ~0.8, strengthen the discount in the
  `agri_risk` CPT (they're nearly one evidence stream, not two).

## Stage 5 — Operations

- Cadence: SEAS5.1 release (~5th monthly) → SPI3 prep + TAMSAT-ALERT call
  same day; wflow 10-day runs every dekad (1st/11th/21st).
- Storage: member WRSI parquet + merged BN inputs alongside existing
  source.coop/HF layout; extend `run_drought_bn_backfill.py`,
  `generate_drought_bn_dag_json.py` (new nodes in the DAG viz) and the
  choropleth plotter.
- CRMA gating (from the advisory doc): the *expensive* per-crop impact
  models run only when `crma_state_agri ≥ Assess` — the BN extension is
  what makes that trigger crop-aware.

## Build order (first three concrete tasks)

1. TAMSAT-ALERT API probe → pin response schema → freeze Node B states.
2. Basin↔admin-1 cropland crosswalk + defensive WRSI zonal reducer over
   existing v4 `output_grid_wrsi.nc` (no new model runs needed to develop
   the whole prep→BN path with *historical* WRSI as stand-in evidence).
3. Julia v2 skeleton (steps 1–4 above) + self-tests, driven by a
   hand-written CSV — BN correctness proven before any pipeline exists.
