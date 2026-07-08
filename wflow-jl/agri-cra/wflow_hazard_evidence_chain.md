# wflow.jl as the hydrological hazard engine of the agri-CRMA operation

**How the wflow.jl distributed hydrological model sits at the centre of the
continuous agricultural risk operation — driving the 10-day WRSI and the flood
tail, coupled to the TAMSAT-ALERT seasonal WRSI, and feeding one Bayesian
multi-evidence chain.**

Companion to `continuous-risk-monitoring-agri-advisory.md` (the CRMA / curatorial
direction) and `wrsi_bn_integration_plan.md` (the staged plan). This document is
the **hazard-model-centric** view: it puts wflow.jl, not the forecast, at the
spine of the operation.

---

## 1. Why wflow.jl is the *engine*, not just another input

Most agricultural climate services treat the forecast as the product and any
model as a post-processing convenience. In this operation the relationship is
inverted: **wflow.jl is the physical process model that converts every forcing
stream into the state variables that actually matter to a crop** — root-zone
soil moisture, actual vs. potential transpiration, runoff, and river discharge.
Rainfall and SEAS5 anomalies are *forcings*; the crop does not experience
rainfall, it experiences the **soil-water balance** that wflow.jl integrates.

wflow_sbm gives us, on the same grid and from the same physics, both tails of
the agricultural water risk:

```
                         ┌─────────────────────────────┐
   forcing (obs +        │        wflow.jl (sbm)        │
   ensemble forecast) ─► │  distributed soil-water +    │ ─► root-zone soil moisture
                         │  routing, per basin case     │ ─► actual/pot. transpiration → WRSI
                         │                              │ ─► overland runoff + river Q → flood
                         └─────────────────────────────┘
                                     │            │
                              dry tail (WRSI)   wet tail (flood likelihood)
```

This is the single most important design fact: **one hydrological model
produces both the drought-side WRSI evidence and the flood-side likelihood
evidence for the same field.** The v4 work already proved the WRSI capability
(11/11 basin cases produce `output_grid_wrsi.nc`; DJI/KEN/ERI/ETH reproduce
their historical drought events), and the flood-IBF line already uses wflow.jl
discharge. The agri-CRMA operation unifies them.

---

## 2. What wflow.jl produces for the chain

| wflow.jl output | Physical meaning | Agricultural role | Horizon |
|---|---|---|---|
| `output_grid_wrsi.nc` | Water Requirement Satisfaction Index (AET/PET accumulation over the season) | **Crop water stress** — the dry tail | dekadal / sub-seasonal (10–30 d) |
| root-zone soil moisture | plant-available water in the profile | antecedent state; stress onset | continuous |
| overland runoff + river discharge | routed water excess | **waterlogging / flood** — the wet tail | event / daily |
| actual transpiration deficit | AET shortfall vs. demand | direct yield-stress driver for impact models | dekadal |

Two properties make these *evidence-grade* rather than merely diagnostic:

1. **Ensemble-native.** Driven by an ensemble forcing (S2S / SEAS5), each output
   is a distribution over members, not a point value — so it enters the BN as a
   soft-evidence vector and a tail (worst-member) statistic, exactly like the
   existing SEAS5 SPI `tail` node.
2. **Warm-state continuity.** wflow.jl is run to the present with observed
   forcing, its state saved, and ensemble forecast branches launched from that
   warm state each dekad. The model therefore *remembers* antecedent conditions
   — the dry-spell-then-rain trajectory a one-shot seasonal forecast cannot
   represent.

---

## 3. The multi-evidence chain (wflow.jl at the hub)

The Bayesian network integrates streams that are deliberately **diverse in
physics and horizon**, so that confidence to act accrues only when independent
lines of evidence converge (the CRMA thesis). wflow.jl anchors the chain by
supplying the *process-based* evidence that the statistical streams (SPI) and
the observational streams (CDI, remote sensing) cannot:

```
 OBSERVED (what is)                 PROCESS MODEL (what the water balance is doing)
 ─────────────────                  ──────────────────────────────────────────────
 ERA5 SPI3        ─► cur, trn ┐         wflow.jl 10-day WRSI  ─► wrsi10  (dry tail)
 JRC CDI (EADW)   ─► cdi       │        wflow.jl discharge    ─► flood_lik (wet tail)
 remote sensing   ─► (future)  │              │        │
                               ▼              ▼        ▼
 FORECAST (what will be)        ┌──────────────────────────────┐
 ─────────────────────          │   Bayesian evidence chain     │
 SEAS5.1 SPI3   ─► def, tail ──►│   (drought_bn_ibf_v1.jl)      │
 ECMWF S2S terciles ─┐          │                               │
                     └─► TAMSAT-ALERT ─► wrsi_seas (seasonal)   │
                        (WRSI, weighted by S2S/SEAS terciles)   │
                               └───────────────┬───────────────┘
                                               ▼
                                   met_drought_risk  ⊕  crop_water_stress
                                               ▼
                                          agri_risk (5)
                                               ▼
                                     CRMA state → advisory / insurance trigger
```

Key couplings:

- **wflow.jl ↔ TAMSAT-ALERT** are the *two horizons of the same WRSI concept*:
  wflow.jl gives the physically-resolved **dekadal** WRSI (this basin, this
  ensemble, warm-started), TAMSAT-ALERT gives the **seasonal** WRSI outlook
  (historical soil-moisture ensemble re-weighted by the seasonal tercile
  forecast). The dekadal stream continuously *corrects* the seasonal prior.
- **SEAS5.1 is shared forcing, counted once.** SEAS5/S2S drives (a) wflow.jl's
  forecast branch and (b) TAMSAT-ALERT's tercile weights (`-weights=ECMWF_S2S`
  in TAMSAT-ALERT_API_V2). Because the two WRSI streams share this driver, the
  BN keeps them in one `crop_water_stress` branch and discounts their
  correlation there (divorce-the-parents; see the integration plan) rather than
  double-counting a single model as independent evidence.
- **CDI is the observational anchor** — the JRC convergence-of-evidence signal
  (SPI + soil-moisture + vegetation all firing) is now a genuine BN node
  (`categorize_cdi` / `compute_risk_probs(...; cdi)` in `drought_bn_ibf_v1.jl`).
  When CDI Alert and the wflow.jl WRSI dry tail agree, confidence is highest;
  when they diverge, the posterior widens rather than over-committing.

---

## 4. wflow.jl in the operational loop

The dekadal cadence of the operation is set by the crop water-accounting clock
(FAO WRSI is dekadal) and realised by wflow.jl runs:

```
Every dekad (1st / 11th / 21st):
  1. Advance the warm state with observed forcing to today
     (ERA5-Land / CHIRPS + PET via penman-monteith_tdew — the mwi/compute_pet.py pattern).
  2. Branch N ensemble runs from the warm state with S2S/SEAS5 forcing
     (mwi/download_s2s_forcing.py pattern), 10–30 day horizon.
  3. Read output_grid_wrsi.nc defensively (guard the known concurrent-batch
     missing/time=0/corrupt failure mode), reduce to admin-1 over a cropland
     mask via the basin↔admin-1 crosswalk.
  4. Emit wrsi10 (+ soft bins, ens-min tail) and flood_lik into the BN CSV.

Monthly (on SEAS5.1 release, ~5th):
  5. Refresh SEAS5 SPI nodes (drought_data_prep.py) and call TAMSAT-ALERT with
     the S2S/SEAS terciles → wrsi_seas node.
  6. Refresh CDI (cdi_data_prep.py, EADW or recompute).

Then:
  7. Run drought_bn_ibf_v1.jl → agri_risk posterior + CRMA state per admin-1.
  8. Gate: crop-specific impact models + farmer advisories run only where
     CRMA state ≥ Assess. Insurer/exceedance framing emitted from the same posterior.
```

The expensive step (ensemble wflow.jl runs) is what makes wflow.jl the engine;
the BN is the cheap integrator that decides *when that expense is warranted* and
fuses its output with the cheaper statistical and observational streams.

---

## 5. Evidence-node map (current + planned)

| BN node | Source model / product | Status |
|---|---|---|
| `cur`, `trn` | ERA5 SPI-3 observations | live (`drought_data_prep.py`) |
| `def`, `tail`, `agreement` | SEAS5.1 SPI-3 forecast | live |
| `cdi` | JRC CDI (EADW / recompute) | **live — now a BN node** (`drought_bn_ibf_v1.jl`) |
| `wrsi_seas` | **TAMSAT-ALERT_API_V2** WRSI product (S2S-weighted) | schema pinned (`tamsat_alert_probe.py`); node wiring next |
| `wrsi10` | **wflow.jl** 10-day WRSI (ensemble, warm-started) | model proven (v4); crosswalk + node wiring next |
| `flood_lik` | **wflow.jl** discharge / runoff (flood tail) | flood-IBF exists; fold into agri chain next |
| `crop_water_stress`, `agri_risk` | derived BN branches | design in integration plan |

---

## 6. Self-contained pipeline (this directory)

Everything needed to run the evidence chain now lives under
`wflow-jl/agri-cra/pipeline/` in this repo (copied from `bn-ibf/drought_ibf`,
now the canonical working copy for the agri-CRMA operation):

```
pipeline/
  drought_bn_ibf_v1.jl     BN engine — SEAS5 SPI + tail + CDI evidence node,
                           CRMA cost-loss decision, RxInfer + matmul, DBN,
                           per-member storylines
  Project.toml/Manifest    Julia environment (CSV, DataFrames, RxInfer)
  drought_data_prep.py     ERA5 obs + SEAS5.1 SPI3 → admin-1 evidence CSV
  cdi_data_prep.py         JRC CDI (EADW / recompute) → admin-1 CDI CSV
  cdi_evidence_update.py   (legacy) post-hoc CDI likelihood update
  tamsat_alert_probe.py    pin the TAMSAT-ALERT WRSI schema before freezing nodes
  plot_drought_bn_choropleth.py   CRMA traffic-light maps
  cdi_bn_integration.md    CDI-as-parent design (Path B)
  evidence_nodes.md        node inventory
```

Still to add here (wflow.jl side): `wflow_wrsi_prep.py` (ensemble WRSI →
`wrsi10` + `flood_lik`), the basin↔admin-1 cropland crosswalk, and a
`tamsat_alert_prep.py` that runs / ingests TAMSAT-ALERT_API_V2 into `wrsi_seas`.

---

## 7. One-paragraph synthesis

The operation is built around a hydrological model, not a forecast. wflow.jl
integrates every forcing stream into the soil-water and routing states a crop
and a floodplain actually experience, producing — from one physics, one grid,
one warm-started ensemble — both the dekadal WRSI dry tail and the discharge
wet tail for the same field. Around that engine a deliberately diverse
multi-evidence chain (SEAS5 SPI forecast, JRC CDI observation, ERA5 antecedent,
and the TAMSAT-ALERT seasonal WRSI that shares SEAS5's tercile driver) is fused
in one Bayesian network whose posterior only reaches an actionable state when
independent lines converge. The BN's job is cheap integration and confidence
accounting; wflow.jl's job is the expensive, decisive physics — and the CRMA
loop exists precisely to decide, each dekad, when that physics and the
downstream crop-impact and advisory work are warranted.
