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
```

## CDI evidence node

CDI is a genuine BN parent (not a post-hoc update): `compute_risk_probs(...; cdi)`
applies an additive modifier (Alert +0.55 … Full_recovery −0.15) plus two expert
rules (Alert+high-deficit→Extreme; Full_recovery+improving→Minimal). Gated by
`--cdi`; needs a `cdi_level_idx` (1–6), `cdi_level` string, or soft `cdi_p1..p6`
column. Absent → `cdi=1` (No_drought), a strict no-op — existing runs unchanged.

## Still to add (wflow.jl + TAMSAT sides)

- `wflow_wrsi_prep.py` — ensemble wflow.jl `output_grid_wrsi.nc` → `wrsi10` +
  `flood_lik` admin-1 columns (needs the basin↔admin-1 cropland crosswalk).
- `tamsat_alert_prep.py` — run/ingest TAMSAT-ALERT_API_V2 → `wrsi_seas` (schema
  already pinned by `tamsat_alert_probe.py`).
- BN `crop_water_stress` / `agri_risk` branches (see `../wrsi_bn_integration_plan.md`).

## Provenance

Copied 2026-07 from `bn-ibf/drought_ibf`. The `cdi` evidence node and
`tamsat_alert_probe.py` were added in that repo (branch `jua-bnet`, commit
`f2489cc`) and the CDI CLI wiring + self-tests completed here.
