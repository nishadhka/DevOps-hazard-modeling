#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pandas"]
# ///
"""
cdi_crosscheck.py — use the JRC/ICPAC CDI as a CROSS-CHECK, not as BN evidence.

Design decision (observation-forecast-realignment.md §5, atom-led config):
the BN consumes the *atoms* — SPI (precip), fAPAR (vegetation), soil moisture —
as separate observation nodes. The CDI is a COMPOSITE of those same atoms, so
feeding it as an evidence node double-counts them (the whole reason the ad-hoc
--fapar-source none / discounts were needed). Instead CDI is retained as an
independent **cross-check layer**: computed, reported, and compared against
ICPAC's East Africa Drought Watch (EADW), but NEVER fused into the posterior.

This tool therefore does TWO comparisons and changes NOTHING:

  1. CDI vs EADW  — "does our recomputed CDI agree with what ICPAC publishes?"
     Uses the wide CSV from `cdi_data_prep.py --cdi-source both`
     (cdi_level_recomp vs cdi_level_eadw). This is the "verify against the East
     Africa Drought Watch" check: CDI stays trustworthy as an operational layer
     because it is reconciled with the authoritative published product.

  2. CDI vs BN    — the observation-vs-forecast co-occurrence (cdi_bn_integration
     .md §7). CDI is an OBSERVED convergence state ("what the ground shows now");
     the BN CRMA state here is FORECAST-driven ("what we expect"). Their 2x2 tells
     an analyst whether observation and outlook agree, and which is leading:

        CDI (obs)            BN CRMA (forecast)    reading
        ------------------   -------------------   -----------------------------
        Alert/Warning        Review/Assess         CONVERGENT — obs & outlook agree
        No_drought/recovery  Review/Assess         FORECAST-LEADING — coming, not yet on ground
        Alert/Warning        Monitor/Evaluate      OBS-LEADING — here now, model expects easing
        No_drought/recovery  Monitor/Evaluate      CONVERGENT-BENIGN

     This is a decision aid, printed and written to a column. It does not move
     the posterior — the BN was already run WITHOUT --cdi.

Because CDI is no longer BN evidence, the cross-check CDI should be the FULL CDI
(built WITH fAPAR, i.e. the default `cdi_data_prep.py`), so it matches EADW.
The old `--fapar-source none` double-count guard is now unnecessary.

Usage:
    # 1. BN run WITHOUT cdi as evidence (atom-led):
    #    julia drought_bn_ibf_v1.jl --input-csv IN.csv --output-csv bn.csv --tail-risk --agri --fpar
    # 2. full CDI for the cross-check:
    #    uv run cdi_data_prep.py --cdi-source both --date 2026-03 --adm1 adm1.geojson --out cdi.csv
    # 3. cross-check (no posterior change):
    uv run cdi_crosscheck.py --bn-csv bn.csv --cdi-csv cdi.csv --out bn_with_crosscheck.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

# CDI level (observed convergence) → "observed drought pressure" tier.
CDI_STRESS = {
    "No_drought": "benign", "Full_recovery": "benign", "Partial_recovery": "benign",
    "Watch": "watch", "Warning": "stress", "Alert": "stress",
}
# BN CRMA state (forecast) → "forecast concern" tier.
BN_CONCERN = {
    "Monitor": "low", "Evaluate": "low", "Assess": "high", "Review": "high",
}


def cooccur(cdi_level: str, crma_state: str) -> str:
    obs = CDI_STRESS.get(str(cdi_level), "unknown")
    fc = BN_CONCERN.get(str(crma_state), "unknown")
    if obs == "unknown" or fc == "unknown":
        return "unknown"
    obs_hot = obs in ("watch", "stress")
    if obs_hot and fc == "high":
        return "convergent"          # observation and outlook both concerned
    if not obs_hot and fc == "high":
        return "forecast-leading"    # coming, not yet on the ground
    if obs_hot and fc == "low":
        return "obs-leading"         # here now, model expects easing → investigate
    return "convergent-benign"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bn-csv", required=True, help="BN output run WITHOUT --cdi")
    ap.add_argument("--cdi-csv", required=True,
                    help="CDI CSV (cdi_data_prep.py; --cdi-source both enables the EADW check)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    bn = pd.read_csv(args.bn_csv, keep_default_na=False)
    cdi = pd.read_csv(args.cdi_csv, keep_default_na=False).set_index("id")
    cols = set(cdi.columns)

    # Guard: refuse to silently "cross-check" if CDI was actually fused as
    # evidence (that would defeat the atom-led decision).
    if "crma_state_pre_cdi" in bn.columns:
        print("[cdi-xcheck] WARNING: the BN CSV has crma_state_pre_cdi — CDI looks "
              "like it was applied as EVIDENCE. Under the atom-led config CDI must "
              "be cross-check ONLY; re-run the BN without CDI as evidence.")

    # ── 1. CDI vs EADW (only with --cdi-source both) ────────────────────────
    both = "cdi_level_recomp" in cols and "cdi_level_eadw" in cols
    if both:
        agree = (cdi["cdi_level_recomp"] == cdi["cdi_level_eadw"])
        n = len(cdi); k = int(agree.sum())
        print(f"[cdi-xcheck] CDI vs EADW: {k}/{n} boundaries agree "
              f"({k/max(n,1):.0%}) — recomputed CDI reconciled with the East "
              f"Africa Drought Watch.")
        single_level = None
    else:
        single_level = ("cdi_level" if "cdi_level" in cols else None)
        if single_level is None:
            raise SystemExit("[cdi-xcheck] CDI CSV needs cdi_level, OR "
                             "cdi_level_recomp+cdi_level_eadw (--cdi-source both).")
        print("[cdi-xcheck] single-source CDI (no EADW column) — skipping the "
              "CDI-vs-EADW reconciliation; run cdi_data_prep.py --cdi-source both "
              "to enable it.")

    def cdi_level_for(bid):
        if bid not in cdi.index:
            return ""
        row = cdi.loc[bid]
        if both:
            # prefer EADW (the authoritative published product) for the co-occurrence
            return str(row["cdi_level_eadw"])
        return str(row[single_level])

    # ── 2. CDI (obs) vs BN (forecast) co-occurrence ─────────────────────────
    bn = bn.copy()
    bn["cdi_level_xcheck"] = [cdi_level_for(b) for b in bn["boundary_id"]]
    bn["obs_forecast_cooccur"] = [
        cooccur(lvl, st) for lvl, st in zip(bn["cdi_level_xcheck"], bn["crma_state"])
    ]

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    bn.to_csv(out, index=False)
    tally = bn["obs_forecast_cooccur"].value_counts().to_dict()
    print(f"[cdi-xcheck] wrote {out}  rows={len(bn)}")
    print(f"[cdi-xcheck] observation↔forecast co-occurrence: {tally}")
    lead = bn[bn["obs_forecast_cooccur"].isin(["obs-leading", "forecast-leading"])]
    if len(lead):
        print(f"[cdi-xcheck] {len(lead)} boundaries where observation and forecast "
              f"DISAGREE — the ones worth an analyst's eye (posterior unchanged).")
    print("[cdi-xcheck] NOTE: the BN posterior was NOT modified. CDI is a "
          "cross-check layer, not an evidence node.")


if __name__ == "__main__":
    main()
