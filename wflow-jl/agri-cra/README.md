# agri-cra — Continuous Agricultural Risk Management Advisory

Self-contained home for the agricultural CRMA (Continuous Risk Management &
Advisory) operation: a wflow.jl-centred, multi-evidence Bayesian chain that
turns hydrological hazard modelling + seasonal forecasts + observations into a
continuously-updated agricultural risk state and a smallholder advisory.

The organising idea (see the concept docs): **wflow.jl is the hydrological
hazard engine** — one distributed model producing both the dekadal WRSI *dry
tail* and the discharge *flood wet tail* for the same field — feeding, alongside
the **TAMSAT-ALERT** seasonal WRSI and a diverse evidence chain (SEAS5.1 SPI,
JRC CDI, ERA5 obs), a single Bayesian network whose posterior only becomes
actionable when independent lines of evidence converge.

## Read in this order

1. **`wflow_hazard_evidence_chain.md`** — the operation, with wflow.jl at the
   spine: what the model produces, the multi-evidence chain, the dekadal loop,
   and the evidence-node map. *Start here.*
2. **`continuous-risk-monitoring-agri-advisory.md`** — the CRMA / curatorial-
   science direction: why continuous + dual-hazard, phenology-timed WRSI, and
   the line to crop insurance / equitable risk sharing.
3. **`wrsi_bn_integration_plan.md`** — staged plan to fold SEAS5.1, 10-day
   wflow.jl WRSI, and TAMSAT-ALERT seasonal WRSI into the BN (divorce-the-
   parents structure, double-counting control).
4. **`gpt55_flight_sim_drm_agri-advisory.md`** — the seed argument: CRMA as the
   reasoning engine; hazard/impact models become evidence, gated by CRMA state.

## Runnable pipeline

**`pipeline/`** — the canonical working code (BN engine + data-prep scripts),
self-contained with its own Julia environment. See `pipeline/README.md` for the
quickstart. Highlights:

- `drought_bn_ibf_v1.jl` — BN engine with SEAS5 SPI + tail + **CDI** evidence
  nodes → risk → CRMA state. `julia --project=. drought_bn_ibf_v1.jl --test`
  runs 8 self-tests (all pass).
- `tamsat_alert_probe.py` — pins the TAMSAT-ALERT WRSI schema before the
  `wrsi_seas` node is frozen.
- `drought_data_prep.py`, `cdi_data_prep.py` — build the admin-1 evidence CSVs.

## Status

| Evidence stream | BN node | Status |
|---|---|---|
| ERA5 SPI-3 obs | `cur`, `trn` | live |
| SEAS5.1 SPI-3 forecast | `def`, `tail`, `agreement` | live |
| JRC CDI (EADW / recompute) | `cdi` | **live — wired as a BN node** |
| TAMSAT-ALERT seasonal WRSI | `wrsi_seas` | schema pinned; node wiring next |
| wflow.jl 10-day WRSI | `wrsi10` | **prep wired** (`pipeline/wflow_wrsi_prep.py`, HydroBASINS L5/L6); awaits Malawi wflow output |
| wflow.jl discharge (flood tail) | `flood_lik` | flood-IBF exists; fold in next |

Next build steps (per the plan): `pipeline/wflow_wrsi_prep.py`
(ensemble `output_grid_wrsi.nc` → `wrsi10` + `flood_lik`), the basin↔admin-1
cropland crosswalk, `tamsat_alert_prep.py` (→ `wrsi_seas`), and the
`crop_water_stress` / `agri_risk` BN branches.

## Provenance

The pipeline was copied 2026-07 from `bn-ibf/drought_ibf` to make this operation
self-contained in the DevOps-hazard-modeling repo. `agri-cra/pipeline/` is now
the canonical working copy. `2026-07-07-crm-agri-advisory.txt` is an exported
working session log (kept for reference; not part of the pipeline).
