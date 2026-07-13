# agri-cra pipeline — self-contained drought/agri CRMA evidence chain

Canonical working copy of the drought Bayesian-network evidence chain for the
agricultural CRMA advisory operation. Copied from `bn-ibf/drought_ibf` and
maintained here so the whole agri-advisory operation is self-contained inside
the DevOps-hazard-modeling repo. See the concept docs one level up:

- `../wflow_hazard_evidence_chain.md` — wflow.jl-centric operation (start here)
- `../continuous-risk-monitoring-agri-advisory.md` — CRMA / curatorial direction
- `../wrsi_bn_integration_plan.md` — staged WRSI/SEAS5/TAMSAT-ALERT plan
- `../gpt55_flight_sim_drm_agri-advisory.md` — CRMA-as-reasoning-engine

## Files

| File | Role |
|---|---|
| `drought_bn_ibf_v1.jl` | BN engine: SEAS5 SPI + tail + **CDI** evidence nodes → risk → CRMA state. RxInfer + matmul, DBN, per-member storylines. |
| `Project.toml`, `Manifest.toml` | Julia environment (CSV, DataFrames, RxInfer). |
| `drought_data_prep.py` | ERA5 obs + SEAS5.1 SPI-3 → admin-1 evidence CSV. |
| `cdi_data_prep.py` | JRC Combined Drought Indicator (EADW / recompute) → admin-1 CDI CSV. |
| `cdi_evidence_update.py` | Legacy post-hoc CDI likelihood update (superseded by the in-BN `cdi` node). |
| `tamsat_alert_probe.py` | Pin the TAMSAT-ALERT WRSI schema before freezing the `wrsi_seas` node. |
| `wflow_wrsi_prep.py` | **wflow.jl `output_grid_wrsi.nc` (aet/pet) → `wrsi10` node** per HydroBASINS level-5/6 polygon (WRSI = 100·ΣAET/ΣPET, dekadal or period). |
| `plot_drought_bn_choropleth.py` | CRMA traffic-light choropleths. |
| `cdi_bn_integration.md`, `evidence_nodes.md` | Design notes. |

## Quickstart

```bash
# 0. Julia env (one-time; resolves against the shared depot)
julia --project=. -e 'using Pkg; Pkg.instantiate()'

# 1. Self-test the BN (includes CDI-node tests 4–8)
julia --project=. drought_bn_ibf_v1.jl --test

# 2. Build evidence CSVs (anonymous source.coop reads)
uv run drought_data_prep.py --init 2026-01 ... --out bn_inputs/drought_2026-01.csv
uv run cdi_data_prep.py --cdi-source eadw --date 2026-01 \
    --adm1 icpac_adm1v3.geojson --out bn_inputs/cdi_2026-01.csv
# merge cdi_* columns onto the drought CSV on `id` (cdi_level_idx / cdi_level)

# 3. Run the BN with the CDI evidence node
julia --project=. drought_bn_ibf_v1.jl \
    --input-csv  bn_inputs/drought_2026-01.csv \
    --output-csv output/drought_bn_2026-01.csv \
    --tail-risk --cdi

# 4. Pin the TAMSAT-ALERT WRSI schema (before wiring wrsi_seas)
uv run tamsat_alert_probe.py --year 2026 --month 01

# 5. Build the wflow.jl wrsi10 node (Malawi, HydroBASINS level 6), crop-weighted
#    by the ASAP crop AFI (Option 1). Once the wflow run has written
#    output/output_grid_wrsi.nc:
uv run wflow_wrsi_prep.py \
    --wrsi-nc /mnt/wflow-secondary/v4_models/mwi/output/output_grid_wrsi.nc \
    --level 6 --mode dekadal \
    --crop-afi /mnt/wflow-data/asap/asap_mask_crop_v04.tif \
    --out bn_inputs/wrsi10_mwi_2026-07.csv
# → one row per Malawi level-6 sub-basin (9 within the level-5 anchor),
#   id=HYBAS_ID, crop_active_frac + wrsi10_value/class/min/stress_prob + w10_p1..p4

# 6. Merge wrsi10 onto the met evidence CSV (on id) and run the BN with the
#    agri layer (Approach B): agri_risk = f(met_risk, crop_water_stress(wrsi10)).
julia --project=. drought_bn_ibf_v1.jl \
    --input-csv bn_inputs/merged_2026-07.csv \
    --output-csv output/agri_bn_2026-07.csv --tail-risk --cdi --agri
# → adds crop_stress, agri_risk_*, agri_risk_level; primary crma_state now
#   reflects agri_risk, with crma_state_met kept alongside for comparison.
```

## CDI evidence node

CDI is a genuine BN parent (not a post-hoc update): `compute_risk_probs(...; cdi)`
applies an additive modifier (Alert +0.55 … Full_recovery −0.15) plus two expert
rules (Alert+high-deficit→Extreme; Full_recovery+improving→Minimal). Gated by
`--cdi`; needs a `cdi_level_idx` (1–6), `cdi_level` string, or soft `cdi_p1..p6`
column. Absent → `cdi=1` (No_drought), a strict no-op — existing runs unchanged.

## wrsi10 node (wflow.jl)

`wflow_wrsi_prep.py` turns a wflow.jl `output_grid_wrsi.nc` (daily `aet`, `pet`)
into per-HydroBASINS WRSI evidence. WRSI = 100·ΣAET/ΣPET (project canonical form,
`shared/hydrobasins/wrsi_analysis.py`), 4 stress states No_Stress/Mild/Moderate/
Severe on FAO bands (50/65/80). `--mode dekadal` (default) gives the season-to-
date cumulative WRSI at the latest dekad — the operational 10-day node; `--mode
period` the whole-run field. Boundaries are HydroBASINS Africa level 5 (country-
scale anchor) or 6 (sub-basins), auto-subset to the WRSI grid and clipped to the
run's `*_v4_basin.geojson` domain. For Malawi the level-5 anchor (HYBAS_ID
1051472390) holds 9 level-6 sub-basins. Basins with no grid overlap get uniform
soft evidence (a BN no-op). Verified on the rwa case; launch-ready for Malawi
once its wflow output exists (`/mnt/wflow-secondary/v4_models/mwi/output/` is
currently empty; the model has `forcing_s2s.nc` for the 10-day forecast).

## Agri layer — `crop_water_stress` + `agri_risk` (ASAP Option 1, Approach B)

The met BN (7 parents → `risk`) is untouched and becomes `met_risk`. A separate
crop-water-stress branch fuses wflow.jl WRSI into the posterior:

```
met parents (7) ─► met_risk (5)
        wrsi10  ─► crop_stress (4)        [+ fpar (Option 2), phenology (Option 3)]
   met_risk ⊕ crop_stress ─► agri_risk (5) ─► CRMA state
```

`agri_risk = Σ_m met[m]·bump(m + E)` where `E = Σ_c crop[c]·shift[c]` is the
crop-stress expected escalation (shift = −0.3/+0.3/+0.8/+1.3 for
No_Stress/Mild/Moderate/Severe). No crop stress → `E ≲ 0` → agri ≈ met (and
*tempers* an over-called met risk — the "forecast says drought but the crops are
fine" divergence case). Severe crop stress → escalates toward High/Extreme.
Enabled with `--agri`; absent wrsi10 columns → disabled, behaviour unchanged.

**ASAP mechanism #1 (CAF > 25 %) is implemented in the prep**: WRSI is reduced
**crop-fraction-weighted** using the ASAP 500 m crop AFI, so rangeland/bare area
neither dilutes nor fabricates the crop signal, and basins with thin crop area
get soft-gated toward uniform evidence (a BN no-op) — the Bayesian analogue of
"no warning unless >25 % of active area is hit".

## Still to add (Options 2–4 + flood)

- **Option 2** — `fpar` vegetation-response node (ASAP `zFPARc` with the
  `mFPARd < −10 %·AVG(mFPAR)` guard) + the meteo↔veg convergence rung.
  `compute_crop_stress_probs(w10, fpar)` already accepts it (self-test 12).
- **Option 3** — phenology conditioning (expansion vs senescence).
- **Option 4** — `tamsat_alert_prep.py` → `wrsi_seas` (schema already pinned).
- `flood_lik` node — wflow.jl discharge/runoff (wet tail) per basin.
- Ensemble WRSI — per-member `wrsi10` once multi-member S2S forcing is run
  (current `forcing_s2s.nc` is a single trace).
See `../asap/asap-crma-implementation-plan.md`.

## Provenance

Copied 2026-07 from `bn-ibf/drought_ibf`. The `cdi` evidence node and
`tamsat_alert_probe.py` were added in that repo (branch `jua-bnet`, commit
`f2489cc`) and the CDI CLI wiring + self-tests completed here.
