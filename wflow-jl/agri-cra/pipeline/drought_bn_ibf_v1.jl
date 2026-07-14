#=
Drought Impact-Based Forecasting using Bayesian Networks — RxInfer.jl

Drought analogue of bn-ibf/flood_ibf/flood_bn_ibf_v1.jl. Same BN topology
(5 parents → risk_level → action), same RxInfer message-passing engine,
same direct-matmul + tensor-contraction fallback, same CRMA cost-loss
decision rule, same DBN temporal coupling and per-member storyline picker.

Only the parent semantics, bin cutoffs, and CPT stress weights are
domain-specific (drought-side: SPI ≤ RP rather than TP ≥ RP).

Reads the CSV from drought_data_prep.py:
    id, name, country,
    current_spi3, current_spi3_category,
    spi3_trend, trend_slope_spi_per_month,
    forecast_deficit_prob, deficit_prob_lead1,
    spatial_coverage, ...,
    forecast_agreement,
    ens_min_spi (p5 of ens-min across leads), ...,
    target_date,
    [optional cur_p1..cur_p5, def_p1..def_p5, spa_p1..spa_p3,
     trn_p1..trn_p3, tail_p1..tail_p4]

Usage:
    julia --project drought_bn_ibf_v1.jl \
        --input-csv  bn_inputs/drought_inputs_2026-04-01.csv \
        --output-csv output/drought_bn_v1_2026-04-01.csv
    julia --project drought_bn_ibf_v1.jl --test

Author: ICPAC IBF Team
Date: April 2026
=#

using LinearAlgebra
using Printf
using CSV
using DataFrames
using RxInfer

# ============================================================================
# CONSTANTS
# ============================================================================

# State labels — drought-side mapping. Order is increasing-stress for the
# numerical CPT logic (see compute_risk_probs).
const CURRENT_SPI3_STATES = ["Above_Normal", "Normal", "Mild_Drought",
                              "Moderate_Drought", "Severe_Drought"]            # 5
const DEFICIT_STATES      = ["Very_Low", "Low", "Medium", "High", "Very_High"] # 5
const SPATIAL_STATES      = ["Localized", "Moderate", "Widespread"]            # 3
const TREND_STATES        = ["Improving", "Stable", "Deteriorating"]           # 3
const AGREEMENT_STATES    = ["Low", "Medium", "High"]                          # 3
const TAIL_RISK_STATES    = ["Nil", "Low", "Moderate", "High"]                 # 4
# JRC-style Combined Drought Indicator level, in increasing-stress order to
# match the monotonic convention of the other parents. Index 1..6 maps
# directly to cdi_level_idx from cdi_data_prep.py (LEVEL_TO_IDX):
#   1 No_drought  2 Full_recovery  3 Partial_recovery  4 Watch  5 Warning  6 Alert
# Recovery classes are meteo-recovered / vegetation-lagging, so the stress
# effect is a per-state lookup (CDI_MODIFIER) rather than strictly monotonic.
const CDI_STATES          = ["No_drought", "Full_recovery", "Partial_recovery",
                             "Watch", "Warning", "Alert"]                       # 6
const RISK_STATES         = ["Minimal", "Low", "Moderate", "High", "Extreme"]  # 5

# ── Agri-CRMA "divorce-the-parents" layer (ASAP Option 1, Approach B) ─────────
# The 7-parent met BN above produces `risk` (== met_risk, unchanged). A separate
# crop-water-stress branch fuses wflow.jl WRSI (wrsi10) — and later FPAR /
# phenology — into `crop_stress`, then agri_risk = f(met_risk, crop_stress).
# All monotonic increasing-stress order (idx 1 = least stressed).
const WRSI10_STATES       = ["No_Stress", "Mild", "Moderate", "Severe"]        # 4
# fpar carries an explicit `Unknown` state (Option 2). "No vegetation evidence"
# and "vegetation observed healthy" are NOT the same proposition: the first must
# be a no-op, while the second is positive evidence that the crop has not (yet)
# responded to a water deficit — ASAP's level-1 "possibly evolving into poor
# growth", which should TEMPER the water signal. Collapsing them (as a 4-state
# Healthy-default would) silently turns missing data into a tempering claim.
const FPAR_STATES         = ["Unknown", "Healthy", "Mild",
                             "Moderate", "Severe_Decline"]                     # 5
# phase is a Ky *modifier*, not a stress axis (Option 3).
const PHASE_STATES        = ["Vegetative", "Flowering", "Maturation"]          # 3
const CROP_STRESS_STATES  = ["No_Stress", "Mild", "Moderate", "Severe"]        # 4 (cws)
const AGRI_RISK_STATES    = RISK_STATES                                        # 5
# FAO WRSI class cutoffs (WRSI = 100·ΣAET/ΣPET): >=80 no-stress, 65-80 mild,
# 50-65 moderate, <50 severe. Mirrors classify_wrsi() in wflow_wrsi_prep.py.
const WRSI_THRESHOLDS     = (no_stress=80.0, mild=65.0, moderate=50.0)
# fAPAR-anomaly (zFPARc) cutoffs — same −0.5/−1.0/−1.5 convention as SPI/CDI.
# Mirrors classify_fpar() in fpar_prep.py.
const FPAR_THRESHOLDS     = (healthy=-0.5, mild=-1.0, moderate=-1.5)
# CRMA risk-COGNITION ladder. All four are analytical/attention states, not
# actions: the system says how much scrutiny a unit warrants, never what to do.
# `Review` (was `Actionable_Risk`) = "escalate for senior/organisational review;
# this can no longer be handled as routine monitoring" — it is the TOP of the
# ladder. The action state (No_Action/Preparedness/Standby/Activation) belongs
# to national DRM, not to this engine; there is deliberately no action node.
const CRMA_STATES         = ["Monitor", "Evaluate", "Assess", "Review"]        # 4
const TRAFFIC_LIGHT       = Dict(
    "Monitor"  => "Green",
    "Evaluate" => "Yellow",
    "Assess"   => "Orange",
    "Review"   => "Red",
)

# Drought thresholds. SPI is unitless; cutoffs follow McKee (1993) /
# WMO Standardised Precipitation Index User Guide categories.
const CURRENT_SPI3_THRESHOLDS = (above=0.5, normal=-0.5,
                                 mild=-1.0, moderate=-1.5)
const TAIL_SPI_THRESHOLDS     = (nil=-0.5, low=-1.0, moderate=-1.5)
const DEFICIT_THRESHOLDS      = (very_low=0.2, low=0.4, medium=0.6, high=0.8)
const SPATIAL_THRESHOLDS      = (localized=0.3, moderate=0.6)
const TREND_BAND_DEFAULT      = 0.1   # SPI / month

# ── SEAS5 shared-signal (redundancy) discount ────────────────────────────────
#
# THE PROBLEM. `def`, `spa` and `tail` are NOT three independent forecasts. They
# are three summaries of ONE object: the per-member RP-exceedance field
# `crosses_rp = (SEAS5 SPI-3 <= ERA5 fitted RP threshold)`.
#   def  = fraction of members crossing
#   spa  = fraction of pixels where a majority of members cross
#   tail = p5 of the per-pixel ensemble-min SPI
# evidence_nodes.md says so outright: "RP-exceedance is the backbone of def +
# spa + tail — it drives three of the five parent nodes, not one." Yet the CPT
# multiplies them as conditionally independent parents, so ONE forecast is
# counted three times.
#
# The symptom is already in the repo's history: `tail` was DROPPED in v2_notail
# "because it was driving 84% of admin-months to Actionable_Risk" — which is
# exactly what redundant evidence does. That fix amputated the node instead of
# modelling the dependency.
#
# THE FIX (same shape as the wrsi10<->cur discount at the agri fusion). `def` is
# the primary, highest-weight summary of the exceedance field, so attenuate the
# `spa` and `tail` contributions by how much of that field `def` has already
# accounted for:
#
#     λ_seas(d) = 1 − κ·d/4        d = deficit − 1 ∈ 0..4      λ(0)=1 … λ(4)=1−κ
#
# What this buys, and why it is not merely a damping hack:
#   • def Very_Low + high tail → FULL weight. A low mean deficit probability with
#     a nasty worst member is precisely the case where the tail carries
#     information the mean does not. Nothing is double-counted, so nothing is
#     discounted. (The T1/T2/T3 expert rules encode exactly this case and are
#     guarded on d ≤ 2, i.e. where λ ≈ 1 — they keep firing at full strength.)
#   • def Very_High + high tail → DISCOUNTED. When almost every member already
#     crosses the threshold, "the worst member is bad" and "it is widespread" are
#     near-tautologies. This is where the 84% over-escalation came from.
#
# NOT discounted: `cur` and `trn` (ERA5 *observations*, a genuinely different
# source) and `cdi` (an independent observational composite).
#
# κ = 0.5 is an EXPERT first-pass value, not a measurement. Calibrate from the
# empirical correlation between def/spa/tail over the hindcast and log the
# revision like any other curatorial act.
const _SEAS_SHARED_KAPPA = 0.5

"""λ_seas(d) ∈ [1−κ, 1]: how much of a `spa`/`tail` contribution is still NEW
information once `def` (deficit index 1..5) has already fired. Decreasing in d."""
_seas_redundancy_lambda(deficit::Int; κ::Float64=_SEAS_SHARED_KAPPA)::Float64 =
    1.0 - κ * (deficit - 1) / 4.0

# ============================================================================
# CATEGORISATION
# ============================================================================

"""
Categorise current SPI-3 into 1-5 (drought-side severity, lower index = drier).

  1 Above_Normal      (SPI ≥ +0.5)
  2 Normal            (-0.5 ≤ SPI < +0.5)
  3 Mild_Drought      (-1.0 ≤ SPI < -0.5)
  4 Moderate_Drought  (-1.5 ≤ SPI < -1.0)
  5 Severe_Drought    (SPI < -1.5)

Note: index 5 is "most stressed", matching antecedent_rainfall=Saturated
in the flood model (where flood stress increases with rainfall). The
drought BN uses the same monotonic stress convention.
"""
function categorize_current_spi3(spi::Float64)::Int
    isnan(spi) && return 2  # Normal fallback
    spi <  CURRENT_SPI3_THRESHOLDS.moderate && return 5  # Severe_Drought
    spi <  CURRENT_SPI3_THRESHOLDS.mild     && return 4  # Moderate_Drought
    spi <  CURRENT_SPI3_THRESHOLDS.normal   && return 3  # Mild_Drought
    spi <  CURRENT_SPI3_THRESHOLDS.above    && return 2  # Normal
    return 1  # Above_Normal
end

"""Categorise forecast deficit probability into 1-5 (low → high)."""
function categorize_deficit(p::Float64)::Int
    isnan(p) && return 1
    p < DEFICIT_THRESHOLDS.very_low && return 1  # Very_Low
    p < DEFICIT_THRESHOLDS.low       && return 2  # Low
    p < DEFICIT_THRESHOLDS.medium    && return 3  # Medium
    p < DEFICIT_THRESHOLDS.high      && return 4  # High
    return 5  # Very_High
end

"""Categorise spatial coverage fraction into 1-3."""
function categorize_spatial(coverage::Float64)::Int
    isnan(coverage) && return 1
    coverage < SPATIAL_THRESHOLDS.localized && return 1  # Localized
    coverage < SPATIAL_THRESHOLDS.moderate  && return 2  # Moderate
    return 3  # Widespread
end

"""
Categorise SPI trend into 1-3 from slope (SPI / month). For drought,
"Deteriorating" means slope < -band (SPI dropping). The CSV from
drought_data_prep.py also writes the trend label as a string
(spi3_trend ∈ {Improving, Stable, Deteriorating}); accept either.

Index convention: 1=Improving (least stress), 3=Deteriorating (most stress).
"""
function categorize_spi3_trend(slope::Float64; band::Float64=TREND_BAND_DEFAULT)::Int
    isnan(slope) && return 2  # Stable
    slope >  band && return 1  # Improving
    slope < -band && return 3  # Deteriorating
    return 2  # Stable
end

function categorize_spi3_trend(label::AbstractString)::Int
    s = lowercase(strip(String(label)))
    s == "improving"     && return 1
    s == "deteriorating" && return 3
    return 2  # Stable / Unknown
end

"""Map agreement string to index (1-3)."""
function categorize_agreement(agreement::AbstractString)::Int
    a = lowercase(String(agreement))
    a == "low"  && return 1
    a == "high" && return 3
    return 2
end

"""
Categorise the worst-case ensemble-min SPI (p5 across leads × members) into
tail-risk index (1-4). Lower SPI → higher tail-drought risk.

  1 Nil       (SPI ≥ -0.5)
  2 Low       (-1.0 ≤ SPI < -0.5)
  3 Moderate  (-1.5 ≤ SPI < -1.0)
  4 High      (SPI < -1.5)
"""
function categorize_tail_risk(ens_min_spi::Float64)::Int
    isnan(ens_min_spi) && return 1
    ens_min_spi <  TAIL_SPI_THRESHOLDS.moderate && return 4  # High
    ens_min_spi <  TAIL_SPI_THRESHOLDS.low      && return 3  # Moderate
    ens_min_spi <  TAIL_SPI_THRESHOLDS.nil      && return 2  # Low
    return 1  # Nil
end

"""
Categorise the JRC CDI level into 1-6 (CDI_STATES order). Accepts the
`cdi_level_idx` integer written by cdi_data_prep.py (already 1..6), or a
level string ("Alert", "Watch", …). Out-of-range / missing → 1 (No_drought),
which is the CDI-absent branch (no effect on risk).
"""
function categorize_cdi(level_idx::Real)::Int
    isnan(float(level_idx)) && return 1
    i = round(Int, level_idx)
    return (i >= 1 && i <= 6) ? i : 1
end

function categorize_cdi(level::AbstractString)::Int
    s = lowercase(strip(String(level)))
    s == "no_drought"       && return 1
    s == "full_recovery"    && return 2
    s == "partial_recovery" && return 3
    s == "watch"            && return 4
    s == "warning"          && return 5
    s == "alert"            && return 6
    return 1  # unknown / "missing" → No_drought (no effect)
end

"""
Categorise a WRSI value (0..150, = 100·ΣAET/ΣPET) into a wrsi10 stress index
1..4 on FAO bands. Higher index = more crop water stress. NaN/missing → 1
(No_Stress, a no-op in the agri layer).
  1 No_Stress (WRSI ≥ 80)   2 Mild (65..80)
  3 Moderate  (50..65)      4 Severe (< 50)
"""
function categorize_wrsi10(wrsi::Real)::Int
    w = float(wrsi)
    isnan(w) && return 1
    w >= WRSI_THRESHOLDS.no_stress && return 1
    w >= WRSI_THRESHOLDS.mild      && return 2
    w >= WRSI_THRESHOLDS.moderate  && return 3
    return 4
end

function categorize_wrsi10(label::AbstractString)::Int
    s = lowercase(strip(String(label)))
    s == "no_stress" && return 1
    s == "mild"      && return 2
    s == "moderate"  && return 3
    s == "severe"    && return 4
    return 1
end

"""
Categorise an fAPAR anomaly (the ASAP `zFPARc` analogue; GDO `fpanv`) into the
`fpar` vegetation-response index 1..4. Drought-side: lower z = worse vegetation.
Cutoffs follow the SPI/CDI convention used across the engine (−0.5/−1.0/−1.5);
ASAP's critical trigger (z < −1) falls inside Moderate ∪ Severe_Decline.
NaN/missing → 1 (Healthy), a no-op in the crop branch.
  1 Healthy (z ≥ −0.5)   2 Mild (−1.0..−0.5)
  3 Moderate (−1.5..−1.0) 4 Severe_Decline (z < −1.5)
"""
function categorize_fpar(z::Real)::Int
    v = float(z)
    isnan(v) && return 1                              # Unknown — no-op
    v >= FPAR_THRESHOLDS.healthy  && return 2         # Healthy (observed)
    v >= FPAR_THRESHOLDS.mild     && return 3         # Mild
    v >= FPAR_THRESHOLDS.moderate && return 4         # Moderate      ← ASAP-critical
    return 5                                          # Severe_Decline ← ASAP-critical
end

function categorize_fpar(label::AbstractString)::Int
    s = lowercase(strip(String(label)))
    s == "healthy"        && return 2
    s == "mild"           && return 3
    s == "moderate"       && return 4
    s == "severe_decline" && return 5
    return 1  # "" / "unknown" / unrecognised → Unknown (no-op)
end

# ============================================================================
# CRMA DECISION (cost-loss-ratio rule, identical to flood)
# ============================================================================

"""
Sharpness of a posterior: 1 − H/H_max ∈ [0,1] (H_max = log k for k states).

This replaces the old `confidence = maximum(action_probs)`, which was derived
from the deleted action node. Entropy is the epistemically honest measure: a
flat posterior (we know nothing) scores 0 regardless of which state happens to
edge ahead, and only a genuinely peaked belief scores near 1. It is a statement
about the *quality of the belief*, which is exactly what CRMA is accountable
for.
"""
function posterior_confidence(probs::Vector{Float64})::Float64
    k = length(probs)
    k <= 1 && return 1.0
    s = sum(probs)
    s > 0 || return 0.0
    p = probs ./ s
    H = -sum(x * log(max(x, 1e-12)) for x in p)
    return clamp(1.0 - H / log(k), 0.0, 1.0)
end

"""
Cost-loss rule → CRMA risk state (index 1..4 = Monitor/Evaluate/Assess/Review).

The rule is retained deliberately: cost-loss here selects an **analytical
posture** (how much scrutiny/compute this unit warrants), NOT a humanitarian
action. `Review` is the top rung — escalate for organisational review.
"""
function compute_crma_state(risk_probs::Vector{Float64};
                            cost_loss_ratio::Float64=0.2)
    p_minimal  = risk_probs[1]
    p_low      = risk_probs[2]
    p_moderate = risk_probs[3]
    p_high     = risk_probs[4]
    p_extreme  = risk_probs[5]

    p_review   = p_high + p_extreme
    p_assess   = p_moderate + p_high + p_extreme
    p_evaluate = p_low + p_moderate + p_high + p_extreme

    θ_review   = cost_loss_ratio
    θ_assess   = max(2.0 * cost_loss_ratio, 0.40)
    θ_evaluate = max(3.0 * cost_loss_ratio, 0.30)

    if p_review >= θ_review
        expl = "P(High∪Extreme)=$(round(p_review, digits=2)) ≥ C/L=$(round(θ_review, digits=2))"
        return 4, expl
    elseif p_assess >= θ_assess
        expl = "P(Mod∪High∪Extreme)=$(round(p_assess, digits=2)) ≥ $(round(θ_assess, digits=2))"
        return 3, expl
    elseif p_evaluate >= θ_evaluate
        expl = "P(Low∪Mod∪High∪Extreme)=$(round(p_evaluate, digits=2)) ≥ $(round(θ_evaluate, digits=2))"
        return 2, expl
    else
        return 1, "all conditional masses below thresholds"
    end
end

# ============================================================================
# CPT — drought-side compute_risk_probs
# ============================================================================

"""
Compute risk probability vector [5] given parent state indices.

Convention: indices are 1-based with 1 = least drought-stressed,
N = most drought-stressed for each parent. The internal arithmetic
matches flood_bn_ibf_v1.jl's structure but with drought-side weights.

  current_spi3 (1..5)  1=Above_Normal …  5=Severe_Drought
  deficit      (1..5)  1=Very_Low     …  5=Very_High
  spatial      (1..3)  1=Localized    …  3=Widespread
  trend        (1..3)  1=Improving    …  3=Deteriorating
  agreement    (1..3)  1=Low          …  3=High
  tail         (1..4)  1=Nil          …  4=High
"""
function compute_risk_probs(
    current::Int,    # 1-5 (Above_Normal..Severe_Drought)
    deficit::Int,    # 1-5 (Very_Low..Very_High)
    spatial::Int,    # 1-3
    trend::Int,      # 1-3 (Improving..Deteriorating)
    agreement::Int,  # 1-3
    tail::Int=1,     # 1-4 (Nil..High)
    cdi::Int=1,      # 1-6 (No_drought..Alert); 1 = CDI-absent (no effect)
    seas_kappa::Float64=_SEAS_SHARED_KAPPA,   # shared-signal discount (0 = off)
)::Vector{Float64}
    c  = current   - 1  # 0..4 (drier ↑)
    d  = deficit   - 1  # 0..4 (more deficit ↑)
    s  = spatial   - 1  # 0..2
    t  = trend     - 1  # 0..2 (worsening ↑)
    ag = agreement - 1
    tr = tail      - 1  # 0..3

    # SEAS5 shared-signal discount: `spa` and `tail` restate the same
    # RP-exceedance field that `def` already summarises, so their marginal
    # contribution shrinks as `def` rises. See _SEAS_SHARED_KAPPA above.
    λ_seas = _seas_redundancy_lambda(deficit; κ=seas_kappa)

    # Forecast-reliability weight from ensemble agreement. `agreement` is a
    # statement about how much the SEAS5 FORECAST can be trusted, so it scales
    # the forecast-derived terms (def, spa, tail) and lets the OBSERVATIONS
    # (cur, trn, cdi) carry when the ensemble is in disarray.
    #
    # It must NOT flatten the whole posterior toward uniform, which is what the
    # old blend did. Uniform is not neutral on a monotone risk ladder — it
    # asserts P(High∪Extreme) = 0.4 — so a benign boundary was escalated to the
    # TOP rung purely because the ensemble disagreed, MANUFACTURING RISK OUT OF
    # IGNORANCE. (That bug was inert only because forecast_agreement was
    # hardcoded to a constant "Medium" in drought_data_prep.py.)
    w_fcst = ag == 0 ? 0.65 :     # Low agreement    → trust the forecast less
             ag == 1 ? 0.85 :     # Medium
                       1.00       # High             → full weight
    spa_add  = s == 2 ? 0.5 : s == 1 ? 0.25 : 0.0
    tail_add = tr == 3 ? 0.60 :   # High tail     (ens_min < -1.5)
               tr == 2 ? 0.35 :   # Moderate tail (ens_min < -1.0)
               tr == 1 ? 0.10 : 0.0

    # Base score: observation term at full weight; forecast terms scaled by
    # reliability, with spa/tail additionally discounted against def.
    base_risk = c * 0.30 +
                w_fcst * (d * 0.55 + (spa_add + tail_add) * λ_seas)

    # Trend modifier — Deteriorating SPI raises risk; Improving drops it.
    if t == 2       # Deteriorating
        base_risk += 0.35
    elseif t == 0   # Improving
        base_risk -= 0.30
    end

    # (spa + tail are folded into base_risk above, scaled by w_fcst · λ_seas.)

    # CDI modifier — the JRC convergence-of-evidence signal is an on-the-ground
    # observational anchor. Alert (precip+soil+vegetation all firing) pushes
    # risk up hard; Full_recovery (meteo recovered) de-stresses. Partial_recovery
    # and No_drought are neutral. Same additive pattern as the tail modifier.
    if cdi == 6       # Alert
        base_risk += 0.55
    elseif cdi == 5   # Warning
        base_risk += 0.30
    elseif cdi == 4   # Watch
        base_risk += 0.10
    elseif cdi == 2   # Full_recovery — partial de-stress
        base_risk -= 0.15
    end

    # Expert rules — drought analogues of the flood scenario rules.
    # CDI-anchored overrides come first: an observed Alert/Full_recovery is a
    # stronger signal than the forecast-driven base score.
    probs = if cdi == 6 && d >= 4
        # Rule C1: CDI Alert on the ground + High/Very_High forecast deficit
        # → near-certain Extreme (obs and forecast both stressed).
        [0.0, 0.0, 0.0, 0.20, 0.80]
    elseif cdi == 2 && t == 0 && c == 0
        # Rule C2: CDI Full_recovery + Improving trend + Above_Normal current
        # → confidently Minimal (forecast overcall damped by ground recovery).
        [0.85, 0.15, 0.0, 0.0, 0.0]
    elseif c == 4 && d >= 3 && t == 2
        # Rule 1: Severe_Drought + High deficit + Deteriorating
        if s >= 1
            [0.0, 0.0, 0.05, 0.20, 0.75]
        else
            [0.0, 0.0, 0.10, 0.40, 0.50]
        end
    elseif c >= 3 && d >= 3 && t == 2
        # Rule 2: Moderate/Severe drought + High deficit + Deteriorating
        [0.0, 0.0, 0.10, 0.50, 0.40]
    elseif tr >= 2 && c >= 3 && d <= 2
        # Rule T1: Low mean deficit BUT high tail risk + already dry
        if tr == 3
            [0.0, 0.10, 0.30, 0.45, 0.15]
        else
            [0.05, 0.20, 0.45, 0.25, 0.05]
        end
    elseif tr == 3 && d <= 1
        # Rule T2: Low mean deficit BUT High tail (any current state)
        [0.05, 0.20, 0.40, 0.30, 0.05]
    elseif tr >= 2 && t == 2 && d <= 2
        # Rule T3: Moderate tail + Deteriorating + low mean deficit
        [0.05, 0.15, 0.45, 0.30, 0.05]
    elseif c == 0 && d <= 2 && tr <= 1
        # Rule 3: Above_Normal current + low deficit + no tail risk
        [0.55, 0.35, 0.10, 0.0, 0.0]
    elseif t == 0 && c <= 1 && d <= 1 && tr <= 1
        # Rule 4: Improving + already-good state + low deficit + no tail
        [0.65, 0.30, 0.05, 0.0, 0.0]
    elseif c <= 1 && d >= 3
        # Rule 5: High forecast deficit but currently OK
        [0.10, 0.25, 0.45, 0.15, 0.05]
    elseif base_risk < 1
        [0.50, 0.40, 0.10, 0.0, 0.0]
    elseif base_risk < 2
        [0.10, 0.35, 0.40, 0.15, 0.0]
    elseif base_risk < 3
        [0.05, 0.15, 0.45, 0.30, 0.05]
    elseif base_risk < 4
        [0.0, 0.05, 0.25, 0.50, 0.20]
    else
        [0.0, 0.0, 0.10, 0.40, 0.50]
    end

    # Residual widening — a disagreeing ensemble should also leave us LESS
    # CONFIDENT, not just less swayed. Kept small and BOUNDED so it can never on
    # its own push a benign boundary over a CRMA threshold: at the worst
    # (Low agreement, zero risk) it contributes P(High∪Extreme) = 0.12·0.4 =
    # 0.048, well under θ_review = C/L = 0.2. The old 0.5 weight put that at
    # exactly 0.20 — dead on the threshold — which is how ignorance alone was
    # escalating benign boundaries to the top rung.
    u_w = ag == 0 ? 0.12 :     # Low
          ag == 1 ? 0.05 :     # Medium
                    0.0        # High → untouched
    if u_w > 0
        probs = (1.0 - u_w) .* probs .+ u_w .* fill(0.20, 5)
    end

    return probs ./ sum(probs)
end

# ============================================================================
# CPT BUILDERS (unchanged shape; mirrors flood)
# ============================================================================

function build_risk_cpt(; include_agreement::Bool=true, include_tail_risk::Bool=false)
    if include_tail_risk
        n_combos = include_agreement ? 5 * 5 * 3 * 3 * 3 * 4 : 5 * 5 * 3 * 3 * 4
    else
        n_combos = include_agreement ? 5 * 5 * 3 * 3 * 3 : 5 * 5 * 3 * 3
    end

    cpt = zeros(Float64, 5, n_combos)
    idx = 0

    if include_tail_risk && include_agreement
        for tl in 1:4, ag in 1:3, tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
            idx += 1; cpt[:, idx] = compute_risk_probs(cu, df, sp, tr, ag, tl)
        end
    elseif include_tail_risk
        for tl in 1:4, tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
            idx += 1; cpt[:, idx] = compute_risk_probs(cu, df, sp, tr, 3, tl)
        end
    elseif include_agreement
        for ag in 1:3, tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
            idx += 1; cpt[:, idx] = compute_risk_probs(cu, df, sp, tr, ag, 1)
        end
    else
        for tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
            idx += 1; cpt[:, idx] = compute_risk_probs(cu, df, sp, tr, 3, 1)
        end
    end

    return cpt, n_combos
end

"""Tensor form for RxInfer DiscreteTransition (and the matmul contraction).

`include_cdi` adds the JRC CDI as a 6th conditioning parent, producing a 7-D
tensor (risk, cur, def, spa, trn, tail, cdi). Six conditioning parents exceed
RxInfer's DiscreteTransition exact-rule cap, so CDI runs use the matmul path
(`infer_soft_matmul_cdi`) — mirrors how include_agreement already falls back.
"""
function build_risk_cpt_tensor(; include_tail_risk::Bool=true, include_cdi::Bool=false, agreement::Int=3)
    if include_cdi
        # Full model: tail is always present alongside CDI.
        T = zeros(Float64, 5, 5, 5, 3, 3, 4, 6)
        for cd in 1:6, tl in 1:4, tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
            T[:, cu, df, sp, tr, tl, cd] = compute_risk_probs(cu, df, sp, tr, agreement, tl, cd)
        end
        return T
    elseif include_tail_risk
        T = zeros(Float64, 5, 5, 5, 3, 3, 4)
        for tl in 1:4, tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
            T[:, cu, df, sp, tr, tl] = compute_risk_probs(cu, df, sp, tr, agreement, tl)
        end
        return T
    else
        T = zeros(Float64, 5, 5, 5, 3, 3)
        for tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
            T[:, cu, df, sp, tr] = compute_risk_probs(cu, df, sp, tr, agreement, 1)
        end
        return T
    end
end

# NOTE: the action node (build_action_cpt / ACTION_STATES) was REMOVED.
# Actions are not random variables in the same sense as rainfall or crop stress,
# and an action node inside the BN misleadingly implies the engine prescribes a
# response. The BN estimates probabilities; the cost-loss decision layer
# (compute_crma_state) maps them to an analytical posture; real-world action
# remains with national DRM. See asap/crma-epistemic-curatorial-evaluation.md.

# ============================================================================
# RxInfer MODEL
# ============================================================================

@model function drought_bn_model_5parent(T, cur_data, def_data, spa_data, trn_data, tail_data, risk_data)
    cur  ~ Categorical(fill(1/5, 5))
    def  ~ Categorical(fill(1/5, 5))
    spa  ~ Categorical(fill(1/3, 3))
    trn  ~ Categorical(fill(1/3, 3))
    tail ~ Categorical(fill(1/4, 4))
    cur_data  ~ DiscreteTransition(cur,  diageye(5))
    def_data  ~ DiscreteTransition(def,  diageye(5))
    spa_data  ~ DiscreteTransition(spa,  diageye(3))
    trn_data  ~ DiscreteTransition(trn,  diageye(3))
    tail_data ~ DiscreteTransition(tail, diageye(4))
    risk ~ DiscreteTransition(cur, T, def, spa, trn, tail)
    risk_data ~ DiscreteTransition(risk, diageye(5))
end

@model function drought_bn_model_4parent(T, cur_data, def_data, spa_data, trn_data, risk_data)
    cur  ~ Categorical(fill(1/5, 5))
    def  ~ Categorical(fill(1/5, 5))
    spa  ~ Categorical(fill(1/3, 3))
    trn  ~ Categorical(fill(1/3, 3))
    cur_data  ~ DiscreteTransition(cur,  diageye(5))
    def_data  ~ DiscreteTransition(def,  diageye(5))
    spa_data  ~ DiscreteTransition(spa,  diageye(3))
    trn_data  ~ DiscreteTransition(trn,  diageye(3))
    risk ~ DiscreteTransition(cur, T, def, spa, trn)
    risk_data ~ DiscreteTransition(risk, diageye(5))
end

_rxinfer_init_5 = @initialization begin
    q(cur)  = Categorical(fill(1/5, 5))
    q(def)  = Categorical(fill(1/5, 5))
    q(spa)  = Categorical(fill(1/3, 3))
    q(trn)  = Categorical(fill(1/3, 3))
    q(tail) = Categorical(fill(1/4, 4))
    q(risk) = Categorical(fill(1/5, 5))
end

_rxinfer_init_4 = @initialization begin
    q(cur)  = Categorical(fill(1/5, 5))
    q(def)  = Categorical(fill(1/5, 5))
    q(spa)  = Categorical(fill(1/3, 3))
    q(trn)  = Categorical(fill(1/3, 3))
    q(risk) = Categorical(fill(1/5, 5))
end

function infer_rxinfer_soft(
    cur_ev::Vector{Float64},
    def_ev::Vector{Float64},
    spa_ev::Vector{Float64},
    trn_ev::Vector{Float64};
    tail_ev::Union{Nothing,Vector{Float64}}=nothing,
    risk_cpt_tensor::AbstractArray{Float64},
    iterations::Int=10,
)::Vector{Float64}
    if tail_ev === nothing
        r = infer(
            model = drought_bn_model_4parent(T = risk_cpt_tensor),
            data  = (cur_data = cur_ev, def_data = def_ev, spa_data = spa_ev,
                     trn_data = trn_ev, risk_data = missing),
            iterations     = iterations,
            initialization = _rxinfer_init_4,
        )
    else
        r = infer(
            model = drought_bn_model_5parent(T = risk_cpt_tensor),
            data  = (cur_data = cur_ev, def_data = def_ev, spa_data = spa_ev,
                     trn_data = trn_ev, tail_data = tail_ev, risk_data = missing),
            iterations     = iterations,
            initialization = _rxinfer_init_5,
        )
    end
    return Vector{Float64}(last(r.posteriors[:risk]).p)
end

# ============================================================================
# DIRECT MATMUL FALLBACK
# ============================================================================

function encode_parents(cur::Int, def::Int, spa::Int, trn::Int, agr::Int;
                        tail::Int=1, include_tail_risk::Bool=false)::Int
    if include_tail_risk
        return ((tail - 1) * 3 * 3 * 3 * 5 * 5 +
                (agr  - 1) * 3 * 3 * 5 * 5 +
                (trn  - 1) * 3 * 5 * 5 +
                (spa  - 1) * 5 * 5 +
                (def  - 1) * 5 +
                (cur  - 1)) + 1
    else
        return ((agr  - 1) * 3 * 3 * 5 * 5 +
                (trn  - 1) * 3 * 5 * 5 +
                (spa  - 1) * 5 * 5 +
                (def  - 1) * 5 +
                (cur  - 1)) + 1
    end
end

function encode_parents_no_agreement(cur::Int, def::Int, spa::Int, trn::Int;
                                     tail::Int=1, include_tail_risk::Bool=false)::Int
    if include_tail_risk
        return ((tail - 1) * 3 * 3 * 5 * 5 +
                (trn  - 1) * 3 * 5 * 5 +
                (spa  - 1) * 5 * 5 +
                (def  - 1) * 5 +
                (cur  - 1)) + 1
    else
        return ((trn  - 1) * 3 * 5 * 5 +
                (spa  - 1) * 5 * 5 +
                (def  - 1) * 5 +
                (cur  - 1)) + 1
    end
end

function infer_direct(
    cur_idx::Int, def_idx::Int, spa_idx::Int, trn_idx::Int, agr_idx::Int,
    risk_cpt::Matrix{Float64};
    include_agreement::Bool=true,
    tail_risk_idx::Int=1, include_tail_risk::Bool=false,
)::Vector{Float64}
    parent_idx = if include_agreement
        encode_parents(cur_idx, def_idx, spa_idx, trn_idx, agr_idx;
                        tail=tail_risk_idx, include_tail_risk)
    else
        encode_parents_no_agreement(cur_idx, def_idx, spa_idx, trn_idx;
                                     tail=tail_risk_idx, include_tail_risk)
    end
    return risk_cpt[:, parent_idx]
end

"""
Tensor-contraction soft-evidence inference. Mathematically equivalent to
RxInfer message passing but ~1000× faster — used for bulk per-member runs.
"""
function infer_soft_matmul(
    cur_ev::Vector{Float64}, def_ev::Vector{Float64},
    spa_ev::Vector{Float64}, trn_ev::Vector{Float64},
    tail_ev::Vector{Float64},
    T::Array{Float64},
)::Vector{Float64}
    risk_probs = zeros(Float64, 5)
    @inbounds for tl in 1:4, tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
        w = cur_ev[cu] * def_ev[df] * spa_ev[sp] * trn_ev[tr] * tail_ev[tl]
        for r in 1:5
            risk_probs[r] += T[r, cu, df, sp, tr, tl] * w
        end
    end
    s = sum(risk_probs)
    if s > 0; risk_probs ./= s; end
    return risk_probs
end

"""
CDI-aware tensor-contraction soft-evidence inference. Same as
infer_soft_matmul but contracts the extra 6-state CDI dimension of the 7-D
tensor from build_risk_cpt_tensor(; include_cdi=true).
"""
function infer_soft_matmul_cdi(
    cur_ev::Vector{Float64}, def_ev::Vector{Float64},
    spa_ev::Vector{Float64}, trn_ev::Vector{Float64},
    tail_ev::Vector{Float64}, cdi_ev::Vector{Float64},
    T::Array{Float64},
)::Vector{Float64}
    risk_probs = zeros(Float64, 5)
    @inbounds for cd in 1:6, tl in 1:4, tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
        w = cur_ev[cu] * def_ev[df] * spa_ev[sp] * trn_ev[tr] * tail_ev[tl] * cdi_ev[cd]
        for r in 1:5
            risk_probs[r] += T[r, cu, df, sp, tr, tl, cd] * w
        end
    end
    s = sum(risk_probs)
    if s > 0; risk_probs ./= s; end
    return risk_probs
end

onehot(idx::Int, k::Int) = (v = zeros(Float64, k); v[idx] = 1.0; v)

"""
Apply the forecast-agreement blend to a risk posterior.

Every tensor builder above bakes in `agreement = 3` (High), i.e. the UNBLENDED
base — so agreement was silently dropped in the RxInfer and CDI paths (which
includes the operational `--cdi --agri` path). It only survived in the flat
`infer_direct` matmul path.

Blending after the contraction is not an approximation, it is exact. The blend
is affine, `p ↦ a·p + (1−a)·u`, and the contraction weights sum to 1, so

    blend(Σᵢ wᵢ·pᵢ) = a·Σᵢ wᵢ·pᵢ + (1−a)·u = Σᵢ wᵢ·(a·pᵢ + (1−a)·u) = Σᵢ wᵢ·blend(pᵢ)

Carrying `agreement` as an eighth tensor dimension would give the same numbers
at 3× the tensor. Low agreement spreads mass toward uniform (an honest widening
when the ensemble disagrees); High leaves the posterior untouched.
"""
function apply_agreement_blend(probs::Vector{Float64}, agr::Int)::Vector{Float64}
    agr >= 3 && return probs                 # High → unchanged (the tensor base)
    a = agr <= 1 ? 0.5 : 0.8                 # Low → 0.5 ; Medium → 0.8
    q = a .* probs .+ (1.0 - a) .* fill(0.2, 5)
    return q ./ sum(q)
end

# ============================================================================
# AGRI LAYER — crop_water_stress + agri_risk (ASAP Option 1, Approach B)
# ============================================================================
#
#   met parents (7) ─► met_risk (== `risk`, unchanged)
#   wrsi10 [, fpar] ─► crop_stress (4)          [phenology conditions this later]
#          met_risk ⊕ crop_stress ─► agri_risk (5) ─► CRMA state
#
# Kept as a post-fusion layer over the untouched met BN: the met engine still
# produces `risk`; this layer fuses it with the crop-water-stress branch. All
# functions are pure and enumerable, so the CPTs are materialised once.

# cws scoring coefficients (ASAP-faithful; see compute_cws_probs).
# β > α: vegetation is realised impact, water deficit only a precursor — which
# is why ASAP puts FPAR-only (L2) above meteo-only (L1). γ is the meteo+veg
# convergence bonus (ASAP L3). Expert first-pass values; calibrate against
# realised yield/loss and log the revision like any other curatorial act.
const _CWS_ALPHA            = 0.70   # weight on wrsi10 (water deficit)
const _CWS_BETA             = 0.80   # weight on fpar   (vegetation response)
const _CWS_GAMMA            = 0.25   # convergence bonus, scaled by the weaker axis
const _CWS_HEALTHY_TEMPER   = 0.75   # observed-healthy veg damps a water deficit (L1)
const _CWS_FLOWERING_AMP    = 1.25   # FAO-33 Ky: flowering amplifies
const _CWS_MATURATION_DAMP  = 0.75   # FAO-33 Ky: maturation damps

"""
crop_water_stress (cws) distribution [4] given the three crop-branch parents,
per bn-approach-b-crop-stress-subbranch.md §3.1:

  wrsi10 1..4  No_Stress→Severe   (wflow.jl WRSI, crop-fraction-weighted; Opt 1)
  fpar   1..4  Healthy→Severe     (ASAP zFPARc guarded by mFPARd;        Opt 2)
  phase  1..3  Vegetative/Flowering/Maturation  (Ky modifier, NOT stress; Opt 3)

  • Base: monotone in wrsi10 and fpar.
  • Convergence rule (ASAP level-3 analogue): wrsi10 AND fpar both stressed
    escalates harder than either alone.
  • Phenology (FAO-33 Ky) modifier: Flowering amplifies a given deficit
    (irreversible loss); Maturation damps it. Never creates stress on its own.

Defaults (fpar=1, phase=1) make cws track wrsi10 — the Option-1 configuration.
"""
function compute_cws_probs(w10::Int, fpar::Int=1, phase::Int=1)::Vector{Float64}
    w = w10 - 1                              # 0..3 water-deficit stress
    s = 0.0
    if fpar == 1
        # ── No vegetation evidence (Unknown) ── crop stress rests on wrsi10
        # alone. s = w reproduces the Option-1 mapping exactly, so absent FPAR
        # is a strict no-op on the Option-1 behaviour.
        s = float(w)
    else
        f = fpar - 2                         # 0..3 (Healthy .. Severe_Decline)
        # Graded, NOT max(): a single saturated axis must not swamp the other,
        # or ASAP's L1/L2/L3 rungs collapse into one.
        #   β > α — vegetation is REALISED impact; a water deficit is only a
        #   precursor ("possibly evolving into poor growth"), which is exactly
        #   why ASAP ranks FPAR-only (L2) above meteo-only (L1).
        #   γ·min(w,f) — the convergence bonus: meteo AND vegetation both firing
        #   is ASAP's L3 rung, and must exceed either alone.
        s = _CWS_ALPHA * w + _CWS_BETA * f + _CWS_GAMMA * min(w, f)
        if f == 0 && w > 0
            # Observed-healthy vegetation under a water deficit = ASAP L1. The
            # plant has not (yet) responded, so temper — but do not zero it: the
            # deficit is still real and may still evolve.
            s *= _CWS_HEALTHY_TEMPER
        end
    end
    # Phenology (FAO-33 Ky) re-weights REAL stress only — it never creates it.
    if s > 0
        phase == 2 && (s *= _CWS_FLOWERING_AMP)    # Flowering  → amplify
        phase == 3 && (s *= _CWS_MATURATION_DAMP)  # Maturation → damp
    end
    # score → cws distribution by LINEAR INTERPOLATION between the bracketing
    # states (not hard binning): a Ky re-weighting or a healthy-veg temper must
    # move the posterior even when it does not cross a state boundary. Hard
    # binning silently swallows exactly those effects.
    #
    # t = 1 + clamp(s, 0, 3) maps the score onto the 4 cws states, and makes the
    # Unknown branch (s = w) land on an exact integer ⇒ a clean one-hot ⇒ absent
    # FPAR is a strict identity on the Option-1 mapping.
    t = 1.0 + clamp(s, 0.0, 3.0)
    lo = floor(Int, t); hi = min(lo + 1, 4); frac = t - lo
    probs = zeros(Float64, 4)
    probs[lo] += (1.0 - frac); probs[hi] += frac
    return probs ./ sum(probs)
end

"""4×4×5×3 tensor CWS_CPT[cws, wrsi10, fpar, phase] — 240 entries (§3.1).
fpar has 5 states (Unknown + 4), so absent vegetation evidence is a state, not a
silent default."""
function build_cws_cpt()::Array{Float64,4}
    T = zeros(Float64, 4, 4, 5, 3)
    for ph in 1:3, fp in 1:5, w in 1:4
        T[:, w, fp, ph] = compute_cws_probs(w, fp, ph)
    end
    return T
end

"""
cws posterior [4] = Σ_{w,f,p} P(cws | w,f,p)·P(w)·P(f)·P(p) — the sum rule over
the crop branch (Jaynes §5.1), implemented as a tensor contraction exactly like
the met-side infer_soft_matmul.
"""
function infer_cws(w10_ev::Vector{Float64}, fpar_ev::Vector{Float64},
                   phase_ev::Vector{Float64}, T::Array{Float64,4})::Vector{Float64}
    cws = zeros(Float64, 4)
    @inbounds for ph in 1:3, fp in 1:5, w in 1:4
        wt = w10_ev[w] * fpar_ev[fp] * phase_ev[ph]
        wt > 0 || continue
        for k in 1:4
            cws[k] += T[k, w, fp, ph] * wt
        end
    end
    s = sum(cws); s > 0 && (cws ./= s)
    return cws
end

"""
5-vector for a continuous risk-index `target` ∈ [1,5]: linear interpolation
between the two bracketing integer states (mass-conserving, monotone). At an
integer target this is a clean one-hot — which is what makes the cws=No_Stress
column of AGRI_CPT an exact identity.
"""
function _risk_bump(target::Float64)::Vector{Float64}
    t = clamp(target, 1.0, 5.0)
    lo = floor(Int, t); hi = min(lo + 1, 5); frac = t - lo
    v = zeros(Float64, 5)
    v[lo] += (1.0 - frac); v[hi] += frac
    return v
end

# Upward shift (risk-index units) that each cws state applies to met_risk.
# cws=No_Stress ⇒ 0.0 ⇒ EXACT identity pass-through (the backward-compat no-op
# guarantee, §3.2 — mirrors the cdi=1 / tail=1 guarantees). Bounded: from a
# Minimal met state even cws=Severe reaches only ~2.5 (Low/Moderate), so the
# crop branch alone cannot manufacture Extreme without meteo corroboration.
const _CWS_SHIFT = (0.0, 0.4, 0.9, 1.5)

# ── Shared-signal (redundancy) discount — the correlation-aware fusion column ──
#
# THE PROBLEM. The two branches are NOT conditionally independent. `wrsi10` is
# wflow.jl's WRSI, forced by *observed* rainfall — so its dry signal shares an
# origin with `cur` (ERA5 SPI-3 observation) and with the precipitation term
# inside `cdi`, both of which sit on the met branch. They meet here, at
# agri_risk. With a constant upward push, ONE missing-rain signal would escalate
# the posterior TWICE (once through met_risk, again through cws).
#
# THE FIX. Discount the cws escalation by how much of that same rain signal the
# met branch has *already* counted. met_risk is a monotone proxy for "how much
# observed+forecast drought evidence has already fired", so we attenuate the
# shift as met_risk rises:
#
#     λ(m) = 1 − κ·(m−1)/4        λ(1) = 1.0 … λ(5) = 1 − κ
#     effective_shift(m, c) = _CWS_SHIFT[c] · λ(m)
#
# κ is the fraction of wrsi10's escalation power that is REDUNDANT with the met
# branch (i.e. attributable to the shared rainfall signal). The remainder is
# wflow's genuine hydrological value-add — soil-moisture storage, evaporative
# demand, routing — which the met branch cannot see and which must still
# escalate at full strength.
#
# Behaviour this buys:
#   • met Minimal + cws Severe  → FULL escalation. Nothing was double-counted:
#     rainfall looked fine, yet the water balance says the crop is failing. This
#     is exactly wflow's marginal information and it must not be discounted.
#   • met Extreme + cws Severe  → DISCOUNTED. The rain deficit already drove
#     met_risk up; counting it again is the double-count we are removing.
#   • cws No_Stress             → unchanged (shift is 0, λ irrelevant): the
#     exact-identity no-op guarantee survives.
#
# κ = 0.5 is a first-pass EXPERT value, not a measurement. Calibrate it from the
# empirical correlation between the cws state and cur/cdi over the hindcast, and
# record the revision in the CPT history like any other curatorial act.
const _SHARED_SIGNAL_KAPPA = 0.5

"""Redundancy factor λ(m) ∈ [1−κ, 1]: how much of a cws escalation is still
*new* information once met_risk=m has already fired. Decreasing in m."""
_redundancy_lambda(m::Int)::Float64 = 1.0 - _SHARED_SIGNAL_KAPPA * (m - 1) / 4.0

"""5×5×4 tensor AGRI_CPT[agri_risk, risk, cws] — 100 entries (§3.2).
Column cws=1 is the identity: AGRI_CPT[:, m, 1] == onehot(m). The cws→agri
shift is scaled by _redundancy_lambda(m) so a shared observed-rain signal is not
counted twice across the two branches."""
function build_agri_cpt()::Array{Float64,3}
    T = zeros(Float64, 5, 5, 4)
    for c in 1:4, m in 1:5
        T[:, m, c] = _risk_bump(float(m) + _CWS_SHIFT[c] * _redundancy_lambda(m))
    end
    return T
end

"""
agri_risk posterior [5] = Σ_{m,c} P(agri | risk=m, cws=c)·P(risk=m)·P(cws=c)
— the sum rule over the two branches (Jaynes §5.1). With cws hard No_Stress
this returns met_probs exactly.
"""
function compute_agri_risk_probs(met_probs::Vector{Float64},
                                 cws_probs::Vector{Float64},
                                 Ta::Array{Float64,3})::Vector{Float64}
    agri = zeros(Float64, 5)
    @inbounds for c in 1:4, m in 1:5
        wt = met_probs[m] * cws_probs[c]
        wt > 0 || continue
        for k in 1:5
            agri[k] += Ta[k, m, c] * wt
        end
    end
    s = sum(agri); s > 0 && (agri ./= s)
    return agri
end

# ============================================================================
# BOUNDARY PROCESSING
# ============================================================================

struct BoundaryInput
    id::String
    name::String
    country::String
    current_spi3::Float64
    spi3_trend::String
    forecast_deficit_prob::Float64
    spatial_coverage::Float64
    forecast_agreement::String
    ens_min_spi::Float64
    cur_probs::Union{Nothing,Vector{Float64}}
    def_probs::Union{Nothing,Vector{Float64}}
    spa_probs::Union{Nothing,Vector{Float64}}
    trn_probs::Union{Nothing,Vector{Float64}}
    tail_probs::Union{Nothing,Vector{Float64}}
    cdi_level_idx::Int                              # 1..6; 1 = No_drought / absent
    cdi_probs::Union{Nothing,Vector{Float64}}       # soft evidence over 6 CDI states
end

BoundaryInput(id, name, country, cur_spi, trend, def_p, spa_cov, agr, ens_min) =
    BoundaryInput(id, name, country, cur_spi, trend, def_p, spa_cov, agr, ens_min,
                  nothing, nothing, nothing, nothing, nothing, 1, nothing)

struct BoundaryResult
    boundary_id::String
    boundary_name::String
    country::String
    current_spi3_category::String
    spi3_trend::String
    risk_level::String
    risk_probabilities::Vector{Float64}
    confidence::Float64                # sharpness of the posterior, 1 − H/H_max
    crma_state::String
    crma_explanation::String
    traffic_light::String
end

function _assemble_result(b::BoundaryInput, cur_idx::Int, trn_idx::Int,
                          risk_probs::Vector{Float64},
                          cost_loss_ratio::Float64)::BoundaryResult
    crma_idx, crma_expl = compute_crma_state(risk_probs; cost_loss_ratio)
    crma_state = CRMA_STATES[crma_idx]
    return BoundaryResult(
        b.id, b.name, b.country,
        CURRENT_SPI3_STATES[cur_idx],
        TREND_STATES[trn_idx],
        RISK_STATES[argmax(risk_probs)],
        risk_probs,
        posterior_confidence(risk_probs),
        crma_state, crma_expl, TRAFFIC_LIGHT[crma_state],
    )
end

function process_boundary(
    b::BoundaryInput, risk_cpt::Matrix{Float64};
    include_agreement::Bool=true, include_tail_risk::Bool=false,
    cost_loss_ratio::Float64=0.2,
)::BoundaryResult
    cur_idx = categorize_current_spi3(b.current_spi3)
    def_idx = categorize_deficit(b.forecast_deficit_prob)
    spa_idx = categorize_spatial(b.spatial_coverage)
    trn_idx = categorize_spi3_trend(b.spi3_trend)
    agr_idx = categorize_agreement(b.forecast_agreement)
    tl_idx  = categorize_tail_risk(b.ens_min_spi)

    risk_probs = infer_direct(
        cur_idx, def_idx, spa_idx, trn_idx, agr_idx,
        risk_cpt;
        include_agreement, tail_risk_idx=tl_idx, include_tail_risk,
    )

    return _assemble_result(b, cur_idx, trn_idx, risk_probs, cost_loss_ratio)
end

function process_boundary_rxinfer(
    b::BoundaryInput, risk_cpt_tensor::AbstractArray{Float64};
    include_tail_risk::Bool=false,
    cost_loss_ratio::Float64=0.2, iterations::Int=10,
)::BoundaryResult
    cur_idx = categorize_current_spi3(b.current_spi3)
    def_idx = categorize_deficit(b.forecast_deficit_prob)
    spa_idx = categorize_spatial(b.spatial_coverage)
    trn_idx = categorize_spi3_trend(b.spi3_trend)
    tl_idx  = categorize_tail_risk(b.ens_min_spi)

    cur_ev = b.cur_probs === nothing ? onehot(cur_idx, 5) : b.cur_probs
    def_ev = b.def_probs === nothing ? onehot(def_idx, 5) : b.def_probs
    spa_ev = b.spa_probs === nothing ? onehot(spa_idx, 3) : b.spa_probs
    trn_ev = b.trn_probs === nothing ? onehot(trn_idx, 3) : b.trn_probs
    tail_ev = include_tail_risk ?
              (b.tail_probs === nothing ? onehot(tl_idx, 4) : b.tail_probs) :
              nothing

    risk_probs = infer_rxinfer_soft(
        cur_ev, def_ev, spa_ev, trn_ev;
        tail_ev = tail_ev,
        risk_cpt_tensor = risk_cpt_tensor,
        iterations = iterations,
    )
    return _assemble_result(b, cur_idx, trn_idx, risk_probs, cost_loss_ratio)
end

"""
CDI-enabled boundary processor. Uses the 7-D tensor + matmul contraction
(`infer_soft_matmul_cdi`) because six conditioning parents exceed RxInfer's
exact-rule cap. Tail is always included in the CDI model. Soft evidence is
used for any parent whose `*_probs` field is populated, else a one-hot from
the categorised index.
"""
function process_boundary_cdi(
    b::BoundaryInput, risk_cpt_tensors::Vector{<:AbstractArray{Float64}};
    cost_loss_ratio::Float64=0.2,
)::BoundaryResult
    # `agreement` is a forecast-RELIABILITY weight and enters compute_risk_probs
    # non-linearly (it scales the forecast terms before binning), so it cannot be
    # blended in after the contraction — it must be in the CPT. One tensor per
    # agreement state (3 × 54k floats ≈ 1.3 MB total; trivial), selected here.
    risk_cpt_tensor = risk_cpt_tensors[categorize_agreement(b.forecast_agreement)]
    cur_idx = categorize_current_spi3(b.current_spi3)
    def_idx = categorize_deficit(b.forecast_deficit_prob)
    spa_idx = categorize_spatial(b.spatial_coverage)
    trn_idx = categorize_spi3_trend(b.spi3_trend)
    tl_idx  = categorize_tail_risk(b.ens_min_spi)
    cd_idx  = categorize_cdi(b.cdi_level_idx)

    cur_ev  = b.cur_probs  === nothing ? onehot(cur_idx, 5) : b.cur_probs
    def_ev  = b.def_probs  === nothing ? onehot(def_idx, 5) : b.def_probs
    spa_ev  = b.spa_probs  === nothing ? onehot(spa_idx, 3) : b.spa_probs
    trn_ev  = b.trn_probs  === nothing ? onehot(trn_idx, 3) : b.trn_probs
    tail_ev = b.tail_probs === nothing ? onehot(tl_idx, 4)  : b.tail_probs
    cdi_ev  = b.cdi_probs  === nothing ? onehot(cd_idx, 6)  : b.cdi_probs

    risk_probs = infer_soft_matmul_cdi(
        cur_ev, def_ev, spa_ev, trn_ev, tail_ev, cdi_ev,
        risk_cpt_tensor)
    return _assemble_result(b, cur_idx, trn_idx, risk_probs, cost_loss_ratio)
end

function process_all_boundaries(
    boundaries::Vector{BoundaryInput};
    include_agreement::Bool=true, include_tail_risk::Bool=false,
    include_cdi::Bool=false,
    cost_loss_ratio::Float64=0.2, use_rxinfer::Bool=true,
)::Vector{BoundaryResult}
    results = Vector{BoundaryResult}(undef, length(boundaries))

    if include_cdi
        # CDI adds a 6th conditioning parent → matmul over the 7-D tensor.
        # One tensor per agreement state, since agreement scales the forecast
        # terms non-linearly (see process_boundary_cdi).
        T = [build_risk_cpt_tensor(; include_cdi=true, agreement=a) for a in 1:3]
        for (i, b) in enumerate(boundaries)
            results[i] = process_boundary_cdi(b, T; cost_loss_ratio)
            i % 50 == 0 && @info "Processed $i/$(length(boundaries)) boundaries (CDI matmul)"
        end
    elseif use_rxinfer && !include_agreement
        T = build_risk_cpt_tensor(; include_tail_risk)
        for (i, b) in enumerate(boundaries)
            results[i] = process_boundary_rxinfer(b, T;
                                                  include_tail_risk, cost_loss_ratio)
            i % 50 == 0 && @info "Processed $i/$(length(boundaries)) boundaries (RxInfer)"
        end
    else
        if use_rxinfer && include_agreement
            @info "include_agreement=true has 6 parents; falling back to matmul"
        end
        risk_cpt, _ = build_risk_cpt(; include_agreement, include_tail_risk)
        for (i, b) in enumerate(boundaries)
            results[i] = process_boundary(b, risk_cpt;
                                          include_agreement, include_tail_risk, cost_loss_ratio)
            i % 50 == 0 && @info "Processed $i/$(length(boundaries)) boundaries (matmul)"
        end
    end
    return results
end

# ============================================================================
# DBN — month-to-month temporal coupling
# ============================================================================

function blend_temporal_prior(yesterday::Vector{Float64}; decay::Float64=0.6)::Vector{Float64}
    v = decay .* yesterday .+ (1.0 - decay) .* fill(0.2, 5)
    return v ./ sum(v)
end

"""
Run the BN as a DBN across a sequence of monthly input CSVs. Last month's
risk posterior is blended into this month as soft virtual evidence.
After `lookback` consecutive months (default 6 = forecast horizon) the
chain resets to a uniform prior.
"""
function run_dbn_sequence(
    input_csvs::Vector{String};
    include_tail_risk::Bool=true, cost_loss_ratio::Float64=0.2,
    temporal_decay::Float64=0.6, lookback::Int=6,
)
    T = build_risk_cpt_tensor(; include_tail_risk)
    prev = Dict{String, Vector{Float64}}()
    chain_len = Dict{String, Int}()
    all_frames = DataFrames.DataFrame[]

    for (month_idx, csv_path) in enumerate(input_csvs)
        df = CSV.read(csv_path, DataFrames.DataFrame)
        colnames = names(df)
        has_min = "ens_min_spi" in colnames

        _soft(prefix, k, row) = all("$(prefix)_p$i" in colnames for i in 1:k) ?
            Float64[row["$(prefix)_p$i"] for i in 1:k] : nothing

        target_date = "target_date" in colnames ? string(df[1, :target_date]) : "month_$month_idx"
        n = DataFrames.nrow(df)
        out_rows = Vector{NamedTuple}(undef, n)

        for (i, row) in enumerate(DataFrames.eachrow(df))
            bid = String(row.id)
            cur_idx = categorize_current_spi3(Float64(row.current_spi3))
            def_idx = categorize_deficit(Float64(row.forecast_deficit_prob))
            spa_idx = categorize_spatial(Float64(row.spatial_coverage))
            trn_idx = categorize_spi3_trend(String(row.spi3_trend))
            tl_idx  = has_min ? categorize_tail_risk(Float64(row.ens_min_spi)) : 1

            cur_ev  = something(_soft("cur",  5, row), onehot(cur_idx, 5))
            def_ev  = something(_soft("def",  5, row), onehot(def_idx, 5))
            spa_ev  = something(_soft("spa",  3, row), onehot(spa_idx, 3))
            trn_ev  = something(_soft("trn",  3, row), onehot(trn_idx, 3))
            tail_ev = include_tail_risk ?
                      something(_soft("tail", 4, row), onehot(tl_idx, 4)) :
                      onehot(1, 4)

            yesterday = get(prev, bid, nothing)
            cl = get(chain_len, bid, 0)
            risk_ev = (yesterday !== nothing && cl < lookback) ?
                      blend_temporal_prior(yesterday; decay=temporal_decay) : nothing

            risk_probs = infer_soft_matmul(
                cur_ev, def_ev, spa_ev, trn_ev, tail_ev, T)

            if risk_ev !== nothing
                risk_probs .*= risk_ev
                s = sum(risk_probs)
                if s > 0; risk_probs ./= s; end
            end

            prev[bid] = copy(risk_probs)
            chain_len[bid] = (yesterday !== nothing ? cl + 1 : 1)
            crma_idx, crma_expl = compute_crma_state(risk_probs; cost_loss_ratio)

            out_rows[i] = (
                target_date     = target_date,
                dbn_month       = month_idx,
                boundary_id     = bid,
                boundary_name   = String(row.name),
                country         = String(row.country),
                risk_level      = RISK_STATES[argmax(risk_probs)],
                crma_state      = CRMA_STATES[crma_idx],
                traffic_light   = TRAFFIC_LIGHT[CRMA_STATES[crma_idx]],
                crma_explanation = crma_expl,
                risk_minimal    = risk_probs[1],
                risk_low        = risk_probs[2],
                risk_moderate   = risk_probs[3],
                risk_high       = risk_probs[4],
                risk_extreme    = risk_probs[5],
                temporal_prior  = risk_ev !== nothing,
                p_high_extreme  = risk_probs[4] + risk_probs[5],
            )
        end
        push!(all_frames, DataFrames.DataFrame(out_rows))
        @info "DBN month $month_idx ($target_date): $n boundaries"
    end
    return vcat(all_frames...)
end

# ============================================================================
# PER-MEMBER STORYLINES
# ============================================================================

function run_per_member_bn(
    member_csv::String;
    include_tail_risk::Bool=true, cost_loss_ratio::Float64=0.2,
)
    df = CSV.read(member_csv, DataFrames.DataFrame)
    T = build_risk_cpt_tensor(; include_tail_risk)
    colnames = names(df)
    _soft(prefix, k, row) = all("$(prefix)_p$i" in colnames for i in 1:k) ?
        Float64[row["$(prefix)_p$i"] for i in 1:k] : nothing

    n = DataFrames.nrow(df)
    out = Vector{NamedTuple}(undef, n)

    for (i, row) in enumerate(DataFrames.eachrow(df))
        cur_idx = categorize_current_spi3(Float64(row.current_spi3))
        def_idx = categorize_deficit(Float64(row.member_def_frac))
        spa_idx = categorize_spatial(Float64(row.member_spa_cov))
        trn_idx = categorize_spi3_trend(String(row.spi3_trend))
        tl_idx  = categorize_tail_risk(Float64(row.member_min_spi))

        cur_ev  = something(_soft("cur",  5, row), onehot(cur_idx, 5))
        def_ev  = something(_soft("def",  5, row), onehot(def_idx, 5))
        spa_ev  = something(_soft("spa",  3, row), onehot(spa_idx, 3))
        trn_ev  = something(_soft("trn",  3, row), onehot(trn_idx, 3))
        tail_ev = something(_soft("tail", 4, row), onehot(tl_idx, 4))

        risk_probs = infer_soft_matmul(
            cur_ev, def_ev, spa_ev, trn_ev, tail_ev, T)
        crma_idx, _ = compute_crma_state(risk_probs; cost_loss_ratio)

        out[i] = (
            boundary_id     = String(row.boundary_id),
            boundary_name   = String(row.boundary_name),
            country         = String(row.country),
            member          = String(row.member),
            target_date     = string(row.target_date),
            risk_level      = RISK_STATES[argmax(risk_probs)],
            crma_state      = CRMA_STATES[crma_idx],
            p_high_extreme  = risk_probs[4] + risk_probs[5],
            risk_minimal    = risk_probs[1],
            risk_low        = risk_probs[2],
            risk_moderate   = risk_probs[3],
            risk_high       = risk_probs[4],
            risk_extreme    = risk_probs[5],
            member_min_spi   = Float64(row.member_min_spi),
            member_def_frac  = Float64(row.member_def_frac),
        )
    end
    return DataFrames.DataFrame(out)
end

function select_storylines(member_results::DataFrames.DataFrame)
    groups = DataFrames.groupby(member_results, [:boundary_id, :target_date])
    rows = NamedTuple[]
    for g in groups
        sorted = sort(g, :p_high_extreme, rev=true)
        n = DataFrames.nrow(sorted)
        picks = [
            ("worst",  sorted[1, :]),
            ("median", sorted[div(n, 2) + 1, :]),
            ("best",   sorted[n, :]),
        ]
        for (stype, r) in picks
            n_ge = sum(sorted.p_high_extreme .>= r.p_high_extreme)
            push!(rows, (
                storyline       = stype,
                boundary_id     = r.boundary_id,
                boundary_name   = r.boundary_name,
                country         = r.country,
                target_date     = r.target_date,
                member          = r.member,
                risk_level      = r.risk_level,
                crma_state      = r.crma_state,
                p_high_extreme  = r.p_high_extreme,
                risk_minimal    = r.risk_minimal,
                risk_low        = r.risk_low,
                risk_moderate   = r.risk_moderate,
                risk_high       = r.risk_high,
                risk_extreme    = r.risk_extreme,
                member_min_spi   = r.member_min_spi,
                probability     = round(n_ge / n, digits=3),
                n_members       = n,
            ))
        end
    end
    return DataFrames.DataFrame(rows)
end

# ============================================================================
# CSV DRIVER
# ============================================================================

function run_csv(input_csv::String, output_csv::String;
                 include_agreement::Bool, include_tail_risk::Bool,
                 include_cdi::Bool=false, include_agri::Bool=false,
                 include_fpar::Bool=false,
                 cost_loss_ratio::Float64=0.2, use_rxinfer::Bool=true)
    df = CSV.read(input_csv, DataFrames.DataFrame)
    colnames = names(df)
    has_min = "ens_min_spi" in colnames
    if include_tail_risk && !has_min
        @warn "--tail-risk requested but ens_min_spi column missing; disabling"
        include_tail_risk = false
    end
    # Agri layer (Approach B): wrsi10 crop-water-stress node from wflow_wrsi_prep.py,
    # merged on `id`. Prefer soft w10_p1..p4, else wrsi10_value/wrsi10_class.
    has_w10_soft = all("w10_p$i" in colnames for i in 1:4)
    has_w10_val  = "wrsi10_value" in colnames
    has_w10_cls  = "wrsi10_class" in colnames
    has_w10 = has_w10_soft || has_w10_val || has_w10_cls
    if include_agri && !has_w10
        @warn "--agri requested but no w10_p*/wrsi10_value/wrsi10_class columns; disabling"
        include_agri = false
    end
    # fpar — the ASAP Option-2 vegetation-response axis (fpar_prep.py).
    has_fp_soft = all("fpar_p$i" in colnames for i in 1:5)
    has_fp_val  = "fpar_value" in colnames
    has_fp_cls  = "fpar_class" in colnames
    has_fpar = has_fp_soft || has_fp_val || has_fp_cls
    if include_fpar && !has_fpar
        @warn "--fpar requested but no fpar_p*/fpar_value/fpar_class columns; disabling"
        include_fpar = false
    end
    if include_fpar && !include_agri
        @warn "--fpar has no effect without --agri (fpar feeds the crop-stress branch)"
    end
    # VEGETATION DOUBLE-COUNT GUARD. The JRC CDI's Alert classes (7-10) already
    # require fAPAR < -1 — the same signal `fpar` carries. `cdi` sits on the met
    # branch and `fpar` on the crop branch; they meet at agri_risk, so running
    # both against a fAPAR-bearing CDI counts vegetation twice (the same class of
    # bug as the wrsi10<->cur rainfall double-count). Structural fix: build CDI
    # with `cdi_data_prep.py --fapar-source none`, which stamps fapar_source.
    if include_fpar && include_cdi
        fsrc = "fapar_source" in colnames ?
               lowercase(strip(string(first(skipmissing(df.fapar_source))))) : "unknown"
        if fsrc != "none"
            @warn """VEGETATION DOUBLE-COUNT: --fpar with a CDI built using fAPAR \
                     (fapar_source=$fsrc). CDI Alert already requires fAPAR<-1, so the \
                     vegetation signal is counted twice across the met and crop branches. \
                     Rebuild CDI with `cdi_data_prep.py --fapar-source none` so the \
                     vegetation evidence lives only in the separable fpar node."""
        else
            @info "fpar active; CDI built without fAPAR (fapar_source=none) — vegetation counted once ✓"
        end
    end
    # CDI evidence node — from the sidecar produced by cdi_data_prep.py, merged
    # onto the prep CSV on `id`. Prefer the integer level, fall back to the
    # string label, then to soft cdi_p1..cdi_p6.
    has_cdi_idx  = "cdi_level_idx" in colnames
    has_cdi_lvl  = "cdi_level" in colnames
    has_cdi_soft = all("cdi_p$i" in colnames for i in 1:6)
    has_cdi = has_cdi_idx || has_cdi_lvl || has_cdi_soft
    if include_cdi && !has_cdi
        @warn "--cdi requested but no cdi_level_idx / cdi_level / cdi_p* columns; disabling"
        include_cdi = false
    end

    # Tolerate missing/empty cells from the prep CSV (e.g. boundaries with
    # no obs pixel hits): replace with NaN / sentinels so the categorise_*
    # functions take their NaN branch.
    _f(x) = (x === missing || x === nothing) ? NaN : Float64(x)
    # string() not String(): tolerate integer id/name columns (e.g. HYBAS_ID).
    _s(x) = (x === missing || x === nothing) ? "" : string(x)
    _soft(prefix::String, k::Int, row) = all("$(prefix)_p$i" in colnames for i in 1:k) ?
        [_f(row["$(prefix)_p$i"]) for i in 1:k] : nothing

    # Read a per-row CDI level index: cdi_level_idx (1..6) if present, else map
    # the cdi_level string, else 1 (No_drought / absent).
    _cdi_idx(row) = has_cdi_idx ? categorize_cdi(_f(row.cdi_level_idx)) :
                    has_cdi_lvl ? categorize_cdi(_s(row.cdi_level)) : 1

    inputs = Vector{BoundaryInput}(undef, DataFrames.nrow(df))
    n_soft_rows = 0
    for (i, row) in enumerate(DataFrames.eachrow(df))
        cur_p  = _soft("cur",  5, row)
        def_p  = _soft("def",  5, row)
        spa_p  = _soft("spa",  3, row)
        trn_p  = _soft("trn",  3, row)
        tail_p = _soft("tail", 4, row)
        cdi_p  = _soft("cdi",  6, row)
        cdi_i  = include_cdi ? _cdi_idx(row) : 1
        if any(x -> x !== nothing, (cur_p, def_p, spa_p, trn_p, tail_p, cdi_p))
            n_soft_rows += 1
        end
        inputs[i] = BoundaryInput(
            _s(row.id),
            _s(row.name),
            _s(row.country),
            _f(row.current_spi3),
            _s(row.spi3_trend),
            _f(row.forecast_deficit_prob),
            _f(row.spatial_coverage),
            _s(row.forecast_agreement),
            has_min ? _f(row.ens_min_spi) : 0.0,
            cur_p, def_p, spa_p, trn_p, tail_p, cdi_i, cdi_p,
        )
    end

    backend = include_cdi ? "matmul+CDI" :
              (use_rxinfer && !include_agreement ? "RxInfer" : "matmul")
    @info "Processing $(length(inputs)) boundaries (backend=$backend agreement=$include_agreement tail_risk=$include_tail_risk cdi=$include_cdi C/L=$cost_loss_ratio soft_rows=$n_soft_rows)"
    results = process_all_boundaries(inputs; include_agreement, include_tail_risk,
                                      include_cdi, cost_loss_ratio, use_rxinfer)

    out = DataFrames.DataFrame(
        boundary_id           = [r.boundary_id for r in results],
        boundary_name         = [r.boundary_name for r in results],
        country               = [r.country for r in results],
        current_spi3_category = [r.current_spi3_category for r in results],
        spi3_trend            = [r.spi3_trend for r in results],
        risk_level            = [r.risk_level for r in results],
        crma_state            = [r.crma_state for r in results],
        traffic_light         = [r.traffic_light for r in results],
        crma_explanation      = [r.crma_explanation for r in results],
        confidence            = [r.confidence for r in results],
        risk_minimal          = [r.risk_probabilities[1] for r in results],
        risk_low              = [r.risk_probabilities[2] for r in results],
        risk_moderate         = [r.risk_probabilities[3] for r in results],
        risk_high             = [r.risk_probabilities[4] for r in results],
        risk_extreme          = [r.risk_probabilities[5] for r in results],
    )

    if include_cdi
        out.cdi_level = [CDI_STATES[b.cdi_level_idx] for b in inputs]
    end

    # ── Agri fusion layer: agri_risk = f(met_risk, crop_stress(wrsi10)) ──────
    # results[i] ↔ df row i (inputs built in df order; process preserves order).
    if include_agri
        Tc = build_cws_cpt(); Ta = build_agri_cpt()
        _w10_idx(row) = has_w10_val ? categorize_wrsi10(_f(row.wrsi10_value)) :
                        has_w10_cls ? categorize_wrsi10(_s(row.wrsi10_class)) : 1
        _fp_idx(row) = has_fp_val ? categorize_fpar(_f(row.fpar_value)) :
                       has_fp_cls ? categorize_fpar(_s(row.fpar_class)) : 1
        rows = collect(DataFrames.eachrow(df))
        # Preserve the met-only CRMA before overwriting the primary columns.
        out.crma_state_met    = copy(out.crma_state)
        out.traffic_light_met = copy(out.traffic_light)
        crop_lvl = Vector{String}(undef, length(results))
        fpar_lvl = Vector{String}(undef, length(results))
        agri = [zeros(Float64, 5) for _ in results]
        for (i, r) in enumerate(results)
            row = rows[i]
            w10_ev = something(_soft("w10", 4, row), onehot(_w10_idx(row), 4))
            fp_i   = include_fpar ? _fp_idx(row) : 1
            fpar_ev = include_fpar ?
                      something(_soft("fpar", 5, row), onehot(fp_i, 5)) :
                      onehot(1, 5)                       # absent → Unknown = no-op
            phase_ev = something(_soft("phase", 3, row), onehot(1, 3)) # Option 3
            fpar_lvl[i] = FPAR_STATES[fp_i]
            cws = infer_cws(w10_ev, fpar_ev, phase_ev, Tc)
            crop_lvl[i] = CROP_STRESS_STATES[argmax(cws)]
            agri[i] = compute_agri_risk_probs(r.risk_probabilities, cws, Ta)
        end
        include_fpar && (out.fpar_class = fpar_lvl)
        out.crop_stress    = crop_lvl
        out.agri_minimal   = [a[1] for a in agri]
        out.agri_low       = [a[2] for a in agri]
        out.agri_moderate  = [a[3] for a in agri]
        out.agri_high      = [a[4] for a in agri]
        out.agri_extreme   = [a[5] for a in agri]
        out.agri_risk_level = [AGRI_RISK_STATES[argmax(a)] for a in agri]
        # Primary CRMA now reflects agri_risk (met kept in *_met columns).
        crma = [compute_crma_state(a; cost_loss_ratio) for a in agri]
        out.crma_state    = [CRMA_STATES[c[1]] for c in crma]
        out.traffic_light = [TRAFFIC_LIGHT[CRMA_STATES[c[1]]] for c in crma]
        out.crma_explanation = ["agri: " * c[2] for c in crma]
        # Confidence must describe the SAME posterior the CRMA state came from.
        out.confidence_met = copy(out.confidence)
        out.confidence     = [posterior_confidence(a) for a in agri]
    end

    mkpath(dirname(abspath(output_csv)))
    CSV.write(output_csv, out)
    @info "Wrote $output_csv rows=$(DataFrames.nrow(out))"

    risk_counts = DataFrames.combine(DataFrames.groupby(out, :risk_level), DataFrames.nrow => :n)
    @info "Risk distribution (met):" risk_counts
    crma_counts = DataFrames.combine(DataFrames.groupby(out, :crma_state), DataFrames.nrow => :n)
    @info "CRMA state distribution$(include_agri ? " (agri)" : ""):" crma_counts
end

# ============================================================================
# CLI
# ============================================================================

function getarg(flag::String)
    i = findfirst(==(flag), ARGS)
    return i === nothing || i == length(ARGS) ? nothing : ARGS[i + 1]
end

function self_test()
    @info "Running drought BN self-test..."
    risk_cpt, _ = build_risk_cpt(; include_agreement=true)

    # 1. Worst case: Severe_Drought + Very_High deficit + Widespread + Deteriorating + High agreement
    #    → Extreme risk, and the CRMA ladder tops out at Review (the highest
    #    analytical posture — NOT an instruction to act).
    rp = infer_direct(5, 5, 3, 3, 3, risk_cpt)
    crma1, _ = compute_crma_state(rp)
    @info "Test 1 (worst case):" risk=RISK_STATES[argmax(rp)] crma=CRMA_STATES[crma1]
    @assert RISK_STATES[argmax(rp)] == "Extreme" "Expected Extreme risk"
    @assert CRMA_STATES[crma1] == "Review" "Worst case must reach the top rung (Review)"

    # 2. Best case: Above_Normal + Very_Low + Localized + Improving + High agreement
    rp2 = infer_direct(1, 1, 1, 1, 3, risk_cpt)
    crma2, _ = compute_crma_state(rp2)
    @info "Test 2 (best case):" risk=RISK_STATES[argmax(rp2)] crma=CRMA_STATES[crma2]
    @assert RISK_STATES[argmax(rp2)] == "Minimal" "Expected Minimal"
    @assert CRMA_STATES[crma2] == "Monitor" "Best case must stay on the bottom rung (Monitor)"

    # 3. Low agreement spreads probabilities (and therefore LOWERS confidence —
    #    posterior_confidence is the entropy-sharpness replacement for the
    #    deleted action node's maximum(action_probs)).
    rp_high = infer_direct(3, 3, 2, 2, 3, risk_cpt)
    rp_low  = infer_direct(3, 3, 2, 2, 1, risk_cpt)
    H_high = -sum(p * log(max(p, 1e-10)) for p in rp_high)
    H_low  = -sum(p * log(max(p, 1e-10)) for p in rp_low)
    @assert H_low > H_high "Low agreement should increase entropy"
    @assert posterior_confidence(rp_low) < posterior_confidence(rp_high) "Low agreement must lower confidence"
    @info "Test 3 (agreement entropy → confidence):" H_low H_high conf_low=posterior_confidence(rp_low) conf_high=posterior_confidence(rp_high)

    # 4. CDI evidence node — cdi=1 (No_drought/absent) must be a no-op relative
    #    to the CDI-free scoring (backward compatibility guarantee).
    base = compute_risk_probs(3, 3, 2, 2, 3, 2)          # tail=2, no cdi arg
    same = compute_risk_probs(3, 3, 2, 2, 3, 2, 1)       # cdi=1 explicit
    @assert maximum(abs.(base .- same)) < 1e-12 "cdi=1 must not change the posterior"
    @info "Test 4 (cdi=1 no-op): max abs diff" d=maximum(abs.(base .- same))

    # 5. CDI Alert escalates risk vs No_drought for the same parents.
    p_nodrought = compute_risk_probs(3, 3, 2, 2, 3, 1, 1)  # moderate, No_drought
    p_alert     = compute_risk_probs(3, 3, 2, 2, 3, 1, 6)  # moderate, Alert
    ph_nd = p_nodrought[4] + p_nodrought[5]
    ph_al = p_alert[4]     + p_alert[5]
    @assert ph_al > ph_nd "CDI Alert should raise P(High∪Extreme)"
    @info "Test 5 (CDI Alert escalates):" P_high_extreme_nodrought=ph_nd P_high_extreme_alert=ph_al

    # 6. CDI Full_recovery de-stresses vs No_drought.
    p_recov = compute_risk_probs(2, 2, 1, 1, 3, 1, 2)      # mild, Full_recovery
    p_base6 = compute_risk_probs(2, 2, 1, 1, 3, 1, 1)      # mild, No_drought
    @assert (p_recov[1] + p_recov[2]) >= (p_base6[1] + p_base6[2]) "Full_recovery should shift mass to Minimal/Low"
    @info "Test 6 (CDI Full_recovery de-stresses):" P_min_low_recovery=(p_recov[1]+p_recov[2]) P_min_low_base=(p_base6[1]+p_base6[2])

    # 7. Rule C1: CDI Alert + Very_High forecast deficit → Extreme.
    rp_c1 = compute_risk_probs(3, 5, 2, 2, 3, 1, 6)
    @assert RISK_STATES[argmax(rp_c1)] == "Extreme" "Rule C1 should give Extreme"
    @info "Test 7 (Rule C1 Alert+deficit→Extreme):" risk=RISK_STATES[argmax(rp_c1)]

    # 8. CDI tensor/matmul path agrees with direct compute_risk_probs.
    Tc = build_risk_cpt_tensor(; include_cdi=true)
    rp_mm = infer_soft_matmul_cdi(onehot(4,5), onehot(4,5), onehot(2,3),
                                  onehot(3,3), onehot(1,4), onehot(6,6), Tc)
    rp_dir = compute_risk_probs(4, 4, 2, 3, 3, 1, 6)
    @assert maximum(abs.(rp_mm .- rp_dir)) < 1e-10 "CDI matmul must match direct CPT"
    @info "Test 8 (CDI matmul == direct):" d=maximum(abs.(rp_mm .- rp_dir))

    # ── Agri layer (Approach B, per bn-approach-b-crop-stress-subbranch.md) ──
    Tc_cws = build_cws_cpt(); Ta_agri = build_agri_cpt()
    met = [0.05, 0.15, 0.45, 0.25, 0.10]   # a Moderate-ish met_risk posterior
    neutral_phase = onehot(1, 3)           # Vegetative (Option 3 supplies real)

    # 9. §3.2 NO-OP GUARANTEE: cws = No_Stress ⇒ agri_risk == risk EXACTLY
    #    (identity pass-through; mirrors the cdi=1 / tail=1 guarantees).
    agri_id = compute_agri_risk_probs(met, onehot(1, 4), Ta_agri)
    @assert maximum(abs.(agri_id .- met)) < 1e-12 "cws=No_Stress must be an exact identity on met_risk"
    @info "Test 9 (cws=No_Stress → identity):" max_abs_diff=maximum(abs.(agri_id .- met))

    # 10. wrsi10 Severe escalates agri_risk above met_risk.
    cws_sev = infer_cws(onehot(4, 4), onehot(1, 5), neutral_phase, Tc_cws)
    agri_sev = compute_agri_risk_probs(met, cws_sev, Ta_agri)
    @assert CROP_STRESS_STATES[argmax(cws_sev)] == "Severe" "Severe WRSI → cws Severe"
    @assert (agri_sev[4] + agri_sev[5]) > (met[4] + met[5]) "Severe WRSI must escalate P(High∪Extreme)"
    @info "Test 10 (wrsi10 Severe escalates):" agri_HE=(agri_sev[4]+agri_sev[5]) met_HE=(met[4]+met[5])

    # 11. wrsi10 No_Stress through the cws CPT ≈ met (no spurious escalation
    #     from smoothing leakage).
    cws_ok = infer_cws(onehot(1, 4), onehot(1, 5), neutral_phase, Tc_cws)
    agri_ok = compute_agri_risk_probs(met, cws_ok, Ta_agri)
    @assert CROP_STRESS_STATES[argmax(cws_ok)] == "No_Stress" "No_Stress WRSI → cws No_Stress"
    @assert abs((agri_ok[4] + agri_ok[5]) - (met[4] + met[5])) < 0.02 "healthy WRSI must not move risk materially"
    @info "Test 11 (healthy wrsi10 ≈ met):" met_HE=(met[4]+met[5]) agri_HE=(agri_ok[4]+agri_ok[5])

    # 12. §3.2 BOUNDEDNESS: cws alone cannot manufacture Extreme from a Minimal
    #     met state (no single-index basis risk).
    met_min = [0.85, 0.15, 0.0, 0.0, 0.0]
    agri_min = compute_agri_risk_probs(met_min, onehot(4, 4), Ta_agri)
    @assert argmax(agri_min) < 4 "cws=Severe alone must not push a Minimal met state to High/Extreme"
    @assert agri_min[5] < 0.05 "cws alone must not manufacture Extreme"
    @info "Test 12 (bounded — no single-index basis risk):" agri=AGRI_RISK_STATES[argmax(agri_min)] p_extreme=agri_min[5]

    # 13. Convergence (Option-2 preview): WRSI+FPAR both stressed escalates
    #     beyond WRSI alone (ASAP level-3 rung).
    cws_w  = infer_cws(onehot(2, 4), onehot(1, 5), neutral_phase, Tc_cws)  # Mild WRSI only
    cws_wf = infer_cws(onehot(2, 4), onehot(3, 5), neutral_phase, Tc_cws)  # Mild WRSI + Mild FPAR
    @assert argmax(cws_wf) > argmax(cws_w) "meteo+veg convergence must escalate"
    @info "Test 13 (WRSI+FPAR convergence):" cws_wrsi_only=CROP_STRESS_STATES[argmax(cws_w)] cws_both=CROP_STRESS_STATES[argmax(cws_wf)]

    # 14. Phenology (Option-3 preview): the same deficit at Flowering escalates
    #     vs Vegetative, and is damped at Maturation. Ky-weighted, never
    #     creating stress on its own.
    # Compare on the EXPECTED cws index: a Ky re-weighting can shift the
    # posterior without crossing a discrete state boundary, which argmax cannot
    # see.
    _cwsi(v) = sum(k * v[k] for k in 1:4)
    cws_veg  = _cwsi(infer_cws(onehot(3, 4), onehot(1, 5), onehot(1, 3), Tc_cws))
    cws_flow = _cwsi(infer_cws(onehot(3, 4), onehot(1, 5), onehot(2, 3), Tc_cws))
    cws_mat  = _cwsi(infer_cws(onehot(3, 4), onehot(1, 5), onehot(3, 3), Tc_cws))
    @assert cws_flow > cws_veg "Flowering must amplify a deficit"
    @assert cws_mat  < cws_veg "Maturation must damp a deficit"
    cws_healthy_flow = infer_cws(onehot(1, 4), onehot(1, 5), onehot(2, 3), Tc_cws)
    @assert CROP_STRESS_STATES[argmax(cws_healthy_flow)] == "No_Stress" "phase must not create stress on its own"
    @info "Test 14 (phenology Ky modifier — expected cws index):" vegetative=round(cws_veg, digits=2) flowering=round(cws_flow, digits=2) maturation=round(cws_mat, digits=2)

    # 16. SHARED-SIGNAL (redundancy) DISCOUNT — wrsi10 is wflow-forced by
    #     *observed* rain, so it shares an origin with cur/cdi on the met branch.
    #     The cws escalation must therefore shrink as met_risk (which already
    #     counted that rain signal) rises — otherwise one missing-rain signal
    #     escalates the posterior twice.
    _exp_idx(v) = sum(k * v[k] for k in 1:5)
    esc(m, c) = _exp_idx(Ta_agri[:, m, c]) - float(m)   # escalation in risk-index units
    escs = [esc(m, 4) for m in 1:4]                     # cws=Severe, met 1..4
    @assert all(escs[i] > escs[i + 1] for i in 1:3) "cws escalation must shrink as met_risk rises (redundancy discount)"
    # The divergence case must NOT be discounted: rain looked fine, the water
    # balance says otherwise — that is wflow's genuine marginal information.
    @assert escs[1] > 1.4 "met Minimal + cws Severe must keep (near-)full escalation"
    @info "Test 16 (shared-signal discount):" esc_met1=round(escs[1], digits=2) esc_met2=round(escs[2], digits=2) esc_met3=round(escs[3], digits=2) esc_met4=round(escs[4], digits=2) kappa=_SHARED_SIGNAL_KAPPA

    # 17. The discount must not break the two standing guarantees.
    @assert maximum(abs.(Ta_agri[:, 3, 1] .- onehot(3, 5))) < 1e-12 "identity no-op must survive the discount"
    agri_bound = compute_agri_risk_probs([0.85, 0.15, 0.0, 0.0, 0.0], onehot(4, 4), Ta_agri)
    @assert argmax(agri_bound) < 4 "boundedness must survive the discount"
    @info "Test 17 (guarantees survive discount): identity + bounded OK"

    # 18. ASAP Option 2 — the fpar vegetation axis.
    #     Cutoffs mirror fpar_prep.py::classify_fpar (−0.5/−1.0/−1.5), and the
    #     ASAP-critical trigger (z < −1) must land in Moderate ∪ Severe_Decline.
    @assert categorize_fpar(NaN)  == 1 "missing fpar → Unknown (no-op)"
    @assert categorize_fpar(0.3)  == 2 "z ≥ −0.5 → Healthy (observed)"
    @assert categorize_fpar(-0.7) == 3 "−1.0 ≤ z < −0.5 → Mild"
    @assert categorize_fpar(-1.2) == 4 "−1.5 ≤ z < −1.0 → Moderate"
    @assert categorize_fpar(-2.0) == 5 "z < −1.5 → Severe_Decline"
    @assert categorize_fpar("Severe_Decline") == 5 "fpar label round-trips"
    @assert categorize_fpar(-1.01) >= 4 "ASAP-critical (z < −1) must be Moderate or worse"

    # fpar=Unknown (absent evidence) must be a STRICT no-op: cws rests on wrsi10
    # alone, reproducing the Option-1 mapping exactly.
    for w in 1:4
        cws_unk = infer_cws(onehot(w, 4), onehot(1, 5), neutral_phase, Tc_cws)
        @assert argmax(cws_unk) == w "fpar=Unknown must leave cws = f(wrsi10) (w=$w)"
    end

    # ASAP LADDER — the point of Option 2. Identical met; vary the two axes.
    # L1 meteo-only  : severe water deficit, vegetation OBSERVED healthy
    # L2 fpar-only   : water fine, vegetation collapsing  (realised impact)
    # L3 both firing : convergence
    # ASAP ranks L1 < L2 < L3, and none may collapse into another.
    _cws_idx(v) = sum(k * v[k] for k in 1:4)          # expected cws index
    l1 = _cws_idx(infer_cws(onehot(4, 4), onehot(2, 5), neutral_phase, Tc_cws))
    l2 = _cws_idx(infer_cws(onehot(1, 4), onehot(5, 5), neutral_phase, Tc_cws))
    l3 = _cws_idx(infer_cws(onehot(4, 4), onehot(5, 5), neutral_phase, Tc_cws))
    @assert l1 < l2 "ASAP: FPAR-only (L2) must outrank meteo-only (L1) — vegetation is realised impact"
    @assert l2 < l3 "ASAP: convergence (L3) must outrank either axis alone"
    # Observed-healthy vegetation must TEMPER a water deficit (that is the whole
    # content of ASAP L1) — i.e. rank below the same deficit with no veg data.
    l_unknown = _cws_idx(infer_cws(onehot(4, 4), onehot(1, 5), neutral_phase, Tc_cws))
    @assert l1 < l_unknown "observed-healthy veg must temper a water deficit vs no veg data"
    @info "Test 18 (ASAP ladder L1<L2<L3):" L1_meteo_only=round(l1, digits=2) L2_fpar_only=round(l2, digits=2) L3_both=round(l3, digits=2) no_veg_data=round(l_unknown, digits=2)

    # ── 19. SEAS5 shared-signal discount ────────────────────────────────────
    # def / spa / tail are three summaries of ONE RP-exceedance field. The
    # discount must shrink spa+tail as def rises, WITHOUT touching the case the
    # tail exists for (low mean deficit, nasty worst member).
    @assert _seas_redundancy_lambda(1) ≈ 1.0 "λ_seas(def=Very_Low) must be 1 (nothing double-counted yet)"
    @assert _seas_redundancy_lambda(5) ≈ 1.0 - _SEAS_SHARED_KAPPA "λ_seas(def=Very_High) must be fully discounted"
    @assert all(_seas_redundancy_lambda(d) > _seas_redundancy_lambda(d + 1) for d in 1:4) "λ_seas must strictly decrease in def"

    # The documented symptom: `tail` was dropped in v2_notail because it drove
    # 84% of admin-months to the top rung. Enumerate the whole CPT and count the
    # combinations whose modal risk is Extreme, with the discount on vs off.
    function _n_extreme(κ)
        n = 0
        for tl in 1:4, ag in 1:3, tr in 1:3, sp in 1:3, df in 1:5, cu in 1:5
            p = compute_risk_probs(cu, df, sp, tr, ag, tl, 1, κ)
            argmax(p) == 5 && (n += 1)
        end
        return n
    end
    n_off = _n_extreme(0.0)                       # old behaviour (no discount)
    n_on  = _n_extreme(_SEAS_SHARED_KAPPA)        # with the discount
    @assert n_on < n_off "the discount must reduce top-rung inflation"
    @info "Test 19 (SEAS5 discount — top-rung inflation):" extreme_combos_before=n_off extreme_combos_after=n_on reduction="$(round(100*(n_off-n_on)/n_off, digits=1))%"

    # The tail's REASON FOR EXISTING must survive: low mean deficit + severe worst
    # member must still escalate (the T-rules are guarded on d ≤ 2, i.e. λ ≈ 1).
    p_lowdef_notail = compute_risk_probs(3, 2, 1, 2, 3, 1, 1)   # def Low, tail Nil
    p_lowdef_tail   = compute_risk_probs(3, 2, 1, 2, 3, 4, 1)   # def Low, tail High
    he(p) = p[4] + p[5]
    @assert he(p_lowdef_tail) > he(p_lowdef_notail) "a bad tail under LOW def must still escalate — that is what tail is for"
    @info "Test 19b (tail keeps its job at low def):" P_HE_no_tail=round(he(p_lowdef_notail), digits=3) P_HE_high_tail=round(he(p_lowdef_tail), digits=3)

    # ── 20. forecast_agreement must actually reach the posterior ─────────────
    # It was dead twice: hardcoded "Medium" in drought_data_prep.py, AND forced
    # to High (=unblended) inside every tensor builder, so it was silently
    # dropped on the RxInfer and CDI paths. The blend is affine and the
    # contraction weights sum to 1, so post-contraction blending is EXACT.
    H(p) = -sum(x * log(max(x, 1e-12)) for x in p)

    # (a) IGNORANCE MUST NOT MANUFACTURE RISK. A benign boundary (wet, improving,
    #     no deficit, no CDI) must stay well below θ_review = C/L = 0.2 even when
    #     the ensemble is in complete disarray. The old blend put it at exactly
    #     0.20 — dead on the threshold — escalating benign boundaries to the TOP
    #     rung purely because the forecast was uncertain.
    benign_hi  = compute_risk_probs(1, 1, 1, 1, 3, 1, 1)   # High agreement
    benign_low = compute_risk_probs(1, 1, 1, 1, 1, 1, 1)   # Low agreement
    he(p) = p[4] + p[5]
    @assert he(benign_low) < 0.2 "low agreement alone must NOT push a benign boundary to Review"
    @assert compute_crma_state(benign_low)[1] == 1 "benign + low agreement must stay Monitor"
    @info "Test 20a (ignorance ≠ risk):" P_HE_benign_high=round(he(benign_hi), digits=3) P_HE_benign_low=round(he(benign_low), digits=3) crma=CRMA_STATES[compute_crma_state(benign_low)[1]]

    # (b) Agreement is a FORECAST-RELIABILITY weight: with a stressed forecast, a
    #     disagreeing ensemble must move us LESS than a unanimous one.
    stressed_hi  = compute_risk_probs(3, 5, 3, 2, 3, 3, 1)
    stressed_low = compute_risk_probs(3, 5, 3, 2, 1, 3, 1)
    @assert he(stressed_low) < he(stressed_hi) "a forecast we cannot trust must sway us less"
    @info "Test 20b (unreliable forecast sways less):" P_HE_high_agree=round(he(stressed_hi), digits=3) P_HE_low_agree=round(he(stressed_low), digits=3)

    # (c) It must still cost CONFIDENCE — a disagreeing ensemble leaves us less
    #     sure, so the posterior widens.
    @assert H(stressed_low) > H(stressed_hi) "low agreement must widen the posterior"
    @info "Test 20c (agreement costs confidence):" H_high=round(H(stressed_hi), digits=3) H_low=round(H(stressed_low), digits=3)

    # ── Risk-cognition ladder + entropy confidence (action node deleted) ──────
    # 15. posterior_confidence: flat ⇒ 0, one-hot ⇒ 1, and it is a statement
    #     about belief sharpness, not about which action to take.
    @assert posterior_confidence(fill(0.2, 5)) < 1e-9 "flat posterior must have zero confidence"
    @assert posterior_confidence(onehot(3, 5)) > 1.0 - 1e-9 "one-hot posterior must have full confidence"
    conf_mid = posterior_confidence([0.0, 0.0, 0.1, 0.1, 0.8])
    @assert 0.0 < conf_mid < 1.0 "a peaked-but-spread posterior sits strictly between"
    # The ladder is verb-only: no state may imply a prescribed action.
    @assert CRMA_STATES == ["Monitor", "Evaluate", "Assess", "Review"] "CRMA must be the verb-only risk-cognition ladder"
    @assert !isdefined(@__MODULE__, :ACTION_STATES) "the action node must not exist"
    @info "Test 15 (entropy confidence + verb-only ladder):" flat=posterior_confidence(fill(0.2,5)) peaked=conf_mid onehot_=posterior_confidence(onehot(3,5))

    @info "All self-tests passed."
end

function main()
    if "--test" in ARGS
        self_test()
        return
    end

    input_csv  = getarg("--input-csv")
    output_csv = getarg("--output-csv")
    include_agreement = !("--no-agreement" in ARGS)
    include_tail_risk = "--tail-risk" in ARGS
    include_cdi = "--cdi" in ARGS
    include_agri = "--agri" in ARGS
    include_fpar = "--fpar" in ARGS
    cl_str = getarg("--cost-loss-ratio")
    cost_loss_ratio = cl_str === nothing ? 0.2 : parse(Float64, cl_str)
    use_rxinfer = !("--legacy-inference" in ARGS)

    if input_csv !== nothing && output_csv !== nothing
        run_csv(input_csv, output_csv; include_agreement, include_tail_risk,
                include_cdi, include_agri, include_fpar, cost_loss_ratio, use_rxinfer)
        return
    end

    @info "Drought BN IBF v1 (Julia/RxInfer)"
    @info "Usage: julia drought_bn_ibf_v1.jl --input-csv IN.csv --output-csv OUT.csv [--no-agreement] [--tail-risk] [--cdi] [--agri] [--fpar] [--legacy-inference] [--cost-loss-ratio 0.2]"
    @info "       julia drought_bn_ibf_v1.jl --test"

    # Demo: a moderately-stressed boundary
    b = BoundaryInput(
        "ETH.1", "Tigray", "Ethiopia",
        -1.4, "Deteriorating",        # current SPI-3, trend
        0.55, 0.45, "Medium", -1.7,   # deficit prob, spatial, agreement, ens-min SPI
    )
    risk_cpt, _ = build_risk_cpt()
    result = process_boundary(b, risk_cpt; include_tail_risk=true)
    @info "Demo result:" boundary=result.boundary_id risk=result.risk_level crma=result.crma_state confidence=@sprintf("%.2f", result.confidence)

    println("\nRisk probabilities:")
    for (state, prob) in zip(RISK_STATES, result.risk_probabilities)
        bar = repeat("█", round(Int, prob * 40))
        @printf("  %-10s %5.1f%% %s\n", state, prob * 100, bar)
    end
end

if abspath(PROGRAM_FILE) == @__FILE__
    main()
end
