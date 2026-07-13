#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "icechunk==2.0.3",
#   "xarray",
#   "netcdf4",
#   "zarr>=3",
#   "numpy",
#   "pandas",
#   "geopandas",
#   "pyogrio",
#   "rasterio",
#   "shapely",
#   "s3fs",
#   "fsspec",
# ]
# ///
"""
fpar_prep.py — build the `fpar` vegetation-response BN node (ASAP Option 2).

ASAP mechanism #2 (the `zFPARc` rung): the escalation from "water deficit
possibly evolving into poor growth" (meteo only) to "evidence of poor growth"
requires an **independent plant-response** signal. This prep produces that axis
per HydroBASINS polygon, crop-fraction-weighted with the same ASAP crop AFI used
by `wflow_wrsi_prep.py`, so `fpar` lines up row-for-row with `wrsi10`.

Evidence consumed (NOT produced — we compute no new EO product):
  GDO fAPAR anomaly icechunk  e4drr-project/observations/gdo_fpar_icechunk
      var `fpanv` — "fAPAR anomaly (VIIRS)", dekadal, 2012-01 → now.
      This is the **zFPARc analogue** (standardised vegetation anomaly).

States (5) — cutoffs follow the SPI/CDI convention already used across the
engine (−0.5 / −1.0 / −1.5), with ASAP's critical trigger at z < −1 falling
inside Moderate ∪ Severe_Decline:

  1 Unknown         (no data)            ← strict BN no-op
  2 Healthy         (z ≥ −0.5)           ← observed-healthy: TEMPERS a water deficit
  3 Mild            (−1.0 ≤ z < −0.5)
  4 Moderate        (−1.5 ≤ z < −1.0)    ← ASAP-critical
  5 Severe_Decline  (z < −1.5)           ← ASAP-critical

`Unknown` is a state, not a default. "No vegetation evidence" and "vegetation
observed healthy" are different propositions: the first must change nothing,
the second is positive evidence that the crop has not (yet) responded to a
water deficit — ASAP's level-1 "water deficit possibly evolving into poor
growth" — and should temper it. Collapsing the two would silently turn missing
data into a tempering claim.

────────────────────────────────────────────────────────────────────────────
TWO HONEST CAVEATS — read before trusting this node
────────────────────────────────────────────────────────────────────────────

1. **The ASAP `mFPARd` guard is NOT active by default.** ASAP flags a pixel
   critical only when
       zFPARc < −1  AND  mFPARd < −(10/100)·AVG(mFPAR)
   The second condition suppresses false positives where inter-annual FPAR
   variability is tiny, so a large z-score reflects a trivial absolute change.
   `mFPARd` needs **raw** FPAR + its historical mean; the GDO store carries only
   the anomaly, so the guard cannot be computed from it. Pass a raw-FPAR source
   via `--mfpard-nc` (a grid of the mean-FPAR difference) plus `--mfpar-avg-nc`
   to switch the exact ASAP guard on. Without it the guard is skipped and the
   run says so loudly.
   Partial mitigation that IS active: the crop-fraction weighting confines the
   signal to cropland, which removes most of the arid/bare low-variability
   pixels the guard exists to suppress — it reduces, but does not eliminate,
   that failure mode.

2. **Vegetation double-counting with `cdi`.** The JRC CDI's Alert classes
   (7–10) *already require* `fAPAR < −1` — the same vegetation signal. `cdi` is
   on the met branch and `fpar` on the crop branch; they meet at `agri_risk`,
   so running both on a fAPAR-bearing CDI counts vegetation twice (the same
   class of bug as the wrsi10↔cur rainfall double-count).
   **Structural fix (do this):** when the `fpar` node is active, build CDI
   *without* fAPAR —
       uv run cdi_data_prep.py --fapar-source none ...
   CDI then carries only precipitation + soil moisture (max level = Warning),
   and the vegetation evidence lives exclusively in this separable, auditable
   node. That is exactly the rationale for Option 2 in
   `../asap/asap-crma-gap-and-bn-role.md`: an independent axis so convergence is
   *explicit*, not hidden inside a composite. `drought_bn_ibf_v1.jl` warns if it
   sees `--fpar` alongside a CDI whose `fapar_source` is not `none`.

Output CSV — one row per basin, keyed `id` = HYBAS_ID, merge onto the BN input:

    id, name, country, target_date,
    crop_active_frac,       (crop fraction, as in wflow_wrsi_prep)
    fpar_value,             crop-weighted median fAPAR anomaly (z)
    fpar_class,             Healthy / Mild / Moderate / Severe_Decline
    fpar_min,               worst pixel carrying real crop cover
    fpar_critical_share,    crop-weighted share with z < -1 (+ guard) — ASAP's
                            ">25% of active area" quantity
    fpar_asap_warn,         bool: fpar_critical_share > 0.25 (ASAP trigger)
    fpar_guard,             "mfpard" | "none" — was the ASAP guard applied?
    fpar_p1..fpar_p5        soft evidence (crop-weighted class shares; p1 =
                            Unknown absorbs no-data and the CAF<25% shortfall)

Usage:
    uv run fpar_prep.py --date 2026-03 \
        --wrsi-nc /mnt/wflow-secondary/v4_models/mwi/output/output_grid_wrsi.nc \
        --level 6 --out bn_inputs/fpar_mwi_2026-03.csv
    # (--wrsi-nc is used only to define the grid/domain so fpar rows align
    #  exactly with the wrsi10 rows; --bbox works too if you have no WRSI run.)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import icechunk as ic
import numpy as np
import pandas as pd
import xarray as xr

# Reuse the Option-1 machinery so `fpar` and `wrsi10` share boundaries, the
# crop AFI, the CAF gate and the weighted reduction — row-for-row alignment.
from wflow_wrsi_prep import (
    CAF_GATE,
    DEFAULT_CROP_AFI,
    DEFAULT_HYBAS_DIR,
    _weighted_median,
    load_basins,
    load_crop_fraction,
    rasterize_basins,
)

S3_BUCKET = "us-west-2.opendata.source.coop"
S3_REGION = "us-west-2"
GDO_FPAR_PREFIX = "e4drr-project/observations/gdo_fpar_icechunk"   # var: fpanv

# 5 states — `Unknown` is explicit. "No vegetation evidence" and "vegetation
# observed healthy" are different propositions: the first must be a BN no-op,
# the second is positive evidence that the crop has not (yet) responded to a
# water deficit (ASAP L1) and should TEMPER it. Mirrors FPAR_STATES in
# drought_bn_ibf_v1.jl.
FPAR_STATES = ["Unknown", "Healthy", "Mild", "Moderate", "Severe_Decline"]  # 1..5
# Drought-side cutoffs on the standardised anomaly (lower = worse vegetation).
FPAR_THRESHOLDS = (-0.5, -1.0, -1.5)      # healthy / mild / moderate boundaries
ASAP_CRITICAL_Z = -1.0                    # ASAP: zFPARc < -1
ASAP_MFPARD_FRAC = 0.10                   # ASAP: mFPARd < -10% * AVG(mFPAR)
ASAP_AREA_TRIGGER = 0.25                  # ASAP: >25% of active area


def classify_fpar(z: float) -> int:
    """fAPAR anomaly → state 1..5 (1 = Unknown, 2 = Healthy … 5 = Severe_Decline)."""
    if not np.isfinite(z):
        return 1                          # Unknown — no-op
    if z >= FPAR_THRESHOLDS[0]:
        return 2                          # Healthy (observed)
    if z >= FPAR_THRESHOLDS[1]:
        return 3                          # Mild
    if z >= FPAR_THRESHOLDS[2]:
        return 4                          # Moderate       ← ASAP-critical
    return 5                              # Severe_Decline ← ASAP-critical


def open_icechunk_anon(prefix: str) -> xr.Dataset:
    st = ic.s3_storage(bucket=S3_BUCKET, prefix=prefix, region=S3_REGION,
                       anonymous=True)
    repo = ic.Repository.open(st, config=ic.RepositoryConfig.default())
    return xr.open_zarr(repo.readonly_session("main").store, consolidated=False)


def regrid_nearest(da: xr.DataArray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Nearest-neighbour regrid of a (lat, lon) field onto the target grid."""
    src_lat = np.asarray(da["lat"].values)
    src_lon = np.asarray(da["lon"].values)
    ii = np.abs(src_lat[None, :] - lat[:, None]).argmin(axis=1)
    jj = np.abs(src_lon[None, :] - lon[:, None]).argmin(axis=1)
    return np.asarray(da.values, dtype="float64")[np.ix_(ii, jj)]


def aggregate_fpar(z: np.ndarray, critical: np.ndarray, mask: np.ndarray,
                   gdf: gpd.GeoDataFrame, lat: np.ndarray, lon: np.ndarray,
                   crop_frac: np.ndarray | None, guard: str) -> pd.DataFrame:
    """Crop-fraction-weighted per-basin reduction (mirrors wflow_wrsi_prep)."""
    weighted = crop_frac is not None
    rows = []
    for r in range(len(gdf)):
        sel = (mask == r) & np.isfinite(z)
        if sel.sum() < 1:
            vals = np.array([], dtype="float64")
            wts = np.array([], dtype="float64")
            crit = np.array([], dtype=bool)
            crop_active = float(crop_frac[mask == r].mean()) if weighted and (mask == r).any() else np.nan
        else:
            vals = z[sel].astype("float64")
            wts = crop_frac[sel].astype("float64") if weighted else np.ones(vals.size)
            crit = critical[sel]
            crop_active = float(crop_frac[mask == r].mean()) if weighted else np.nan

        # Soft evidence is 5-wide; index 0 is `Unknown`. Mass that we have NO
        # basis for asserting goes to Unknown — which the BN treats as a strict
        # no-op. (Spreading it uniformly over the stress states would instead put
        # 4/5 of the mass on "some vegetation stress", inventing evidence.)
        if vals.size == 0 or (weighted and wts.sum() <= 0):
            med = vmin = np.nan
            fracs = np.zeros(5); fracs[0] = 1.0        # no (crop) data → Unknown
            crit_share = np.nan
        else:
            med = _weighted_median(vals, wts) if weighted else float(np.median(vals))
            tail_sel = (wts >= 0.10) if weighted else np.ones(vals.size, bool)
            vmin = float(np.min(vals[tail_sel])) if tail_sel.any() else float(np.min(vals))
            cls = np.array([classify_fpar(v) for v in vals])
            W = wts.sum()
            fracs = np.array([wts[cls == k].sum() / W for k in (1, 2, 3, 4, 5)])
            crit_share = float(wts[crit].sum() / W)
            # ASAP CAF>25% gate: with little crop area we have little basis for a
            # *crop* vegetation claim, so the shortfall goes to Unknown.
            if weighted and np.isfinite(crop_active):
                strength = min(1.0, crop_active / CAF_GATE)
                fracs = strength * fracs
                fracs[0] += 1.0 - strength

        b = gdf.iloc[r]
        hid = int(b["HYBAS_ID"]) if "HYBAS_ID" in gdf.columns else r
        rows.append({
            "id": str(hid),
            "name": f"HYBAS_{hid}",
            "crop_active_frac": None if not np.isfinite(crop_active) else round(crop_active, 4),
            "fpar_value": None if not np.isfinite(med) else round(med, 3),
            "fpar_class": FPAR_STATES[classify_fpar(med) - 1],
            "fpar_min": None if not np.isfinite(vmin) else round(vmin, 3),
            "fpar_critical_share": None if not np.isfinite(crit_share) else round(crit_share, 4),
            "fpar_asap_warn": bool(np.isfinite(crit_share) and crit_share > ASAP_AREA_TRIGGER),
            "fpar_guard": guard,
            "fpar_p1": round(float(fracs[0]), 4),   # Unknown
            "fpar_p2": round(float(fracs[1]), 4),   # Healthy
            "fpar_p3": round(float(fracs[2]), 4),   # Mild
            "fpar_p4": round(float(fracs[3]), 4),   # Moderate
            "fpar_p5": round(float(fracs[4]), 4),   # Severe_Decline
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="target month/dekad (YYYY-MM or YYYY-MM-DD)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--wrsi-nc", default=None,
                    help="wflow output_grid_wrsi.nc — defines the grid/domain so "
                         "fpar rows align with wrsi10. Alternative: --bbox")
    ap.add_argument("--bbox", default=None, help="W,S,E,N if no --wrsi-nc")
    ap.add_argument("--level", type=int, default=6, choices=[5, 6])
    ap.add_argument("--hydrobasins-dir", default=str(DEFAULT_HYBAS_DIR))
    ap.add_argument("--domain", default=None)
    ap.add_argument("--country", default="Malawi")
    ap.add_argument("--crop-afi", default=DEFAULT_CROP_AFI)
    ap.add_argument("--no-crop-weight", action="store_true")
    ap.add_argument("--mfpard-nc", default=None,
                    help="grid of mean-FPAR difference (mFPARd). Supply WITH "
                         "--mfpar-avg-nc to activate the exact ASAP guard.")
    ap.add_argument("--mfpar-avg-nc", default=None,
                    help="grid of AVG(mFPAR) (historical mean FPAR)")
    args = ap.parse_args()

    D = pd.Timestamp(args.date)

    # ── target grid: the WRSI grid (so rows align) or a bbox ────────────────
    if args.wrsi_nc:
        ds = xr.open_dataset(args.wrsi_nc)
        lat = np.asarray(ds["lat"].values); lon = np.asarray(ds["lon"].values)
        domain = Path(args.domain) if args.domain else None
        if domain is None:
            nc = Path(args.wrsi_nc)
            sibs = list(nc.parent.parent.glob("*_v4_basin.geojson")) + \
                   list(nc.parent.glob("*_v4_basin.geojson"))
            domain = sibs[0] if sibs else None
    elif args.bbox:
        w, s, e, n = (float(x) for x in args.bbox.split(","))
        # 0.01° working grid over the bbox
        lat = np.arange(s, n, 0.01); lon = np.arange(w, e, 0.01)
        domain = Path(args.domain) if args.domain else None
    else:
        raise SystemExit("[fpar-prep] need --wrsi-nc or --bbox")
    bbox = (float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()))

    # ── fAPAR anomaly (zFPARc analogue) ────────────────────────────────────
    print("[fpar-prep] opening GDO fAPAR anomaly icechunk ...", flush=True)
    fp = open_icechunk_anon(GDO_FPAR_PREFIX)
    times = pd.to_datetime(fp.time.values)
    ok = times <= D
    if not ok.any():
        raise SystemExit(f"[fpar-prep] no fAPAR dekad ≤ {D.date()}")
    idx = int(np.where(ok)[0].max())
    t = pd.Timestamp(fp.time.values[idx])
    print(f"[fpar-prep] fAPAR dekad: {t.date()}")
    z = regrid_nearest(fp["fpanv"].isel(time=idx).load(), lat, lon)

    # ── ASAP mFPARd guard (optional — needs raw FPAR, absent from GDO) ──────
    critical = np.isfinite(z) & (z < ASAP_CRITICAL_Z)
    guard = "none"
    if args.mfpard_nc and args.mfpar_avg_nc:
        md = regrid_nearest(xr.open_dataarray(args.mfpard_nc), lat, lon)
        av = regrid_nearest(xr.open_dataarray(args.mfpar_avg_nc), lat, lon)
        guard_ok = np.isfinite(md) & np.isfinite(av) & (md < -ASAP_MFPARD_FRAC * av)
        critical &= guard_ok
        guard = "mfpard"
        print(f"[fpar-prep] ASAP mFPARd guard ACTIVE "
              f"(zFPARc < {ASAP_CRITICAL_Z} AND mFPARd < -{ASAP_MFPARD_FRAC:.0%}·AVG(mFPAR))")
    else:
        print("[fpar-prep] WARNING: ASAP mFPARd guard NOT applied — the GDO store "
              "carries only the anomaly, not raw FPAR. Low-variability pixels can "
              "yield large z-scores from trivial absolute change. Crop weighting "
              "mitigates but does not eliminate this. Pass --mfpard-nc + "
              "--mfpar-avg-nc to activate the exact ASAP guard.")

    # ── boundaries + crop weighting (shared with wrsi10) ────────────────────
    gdf = load_basins(Path(args.hydrobasins_dir), args.level, bbox, domain)
    print(f"[fpar-prep] {len(gdf)} level-{args.level} basins over {tuple(round(x,2) for x in bbox)}")
    crop_frac = None
    if not args.no_crop_weight:
        crop_frac = load_crop_fraction(Path(args.crop_afi), lat, lon)
        if crop_frac is not None:
            print(f"[fpar-prep] crop weighting ON (ASAP AFI); grid crop mean="
                  f"{100*np.nanmean(crop_frac):.1f}%")

    mask = rasterize_basins(gdf, lat, lon)
    df = aggregate_fpar(z, critical, mask, gdf, lat, lon, crop_frac, guard)
    df.insert(2, "country", args.country)
    df.insert(3, "target_date", str(t.date()))

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    have = df["fpar_value"].dropna()
    print(f"[fpar-prep] wrote {out}  rows={len(df)}  with-data={len(have)}")
    if len(have):
        print(f"[fpar-prep] fpar_class: "
              f"{df.loc[df.fpar_value.notna(),'fpar_class'].value_counts().to_dict()}")
        print(f"[fpar-prep] ASAP warn (>25% of crop area critical): "
              f"{int(df.fpar_asap_warn.sum())}/{len(df)} basins")
    print("[fpar-prep] REMINDER: build CDI with --fapar-source none when using "
          "this node, or vegetation is counted twice (cdi Alert also needs fAPAR<-1).")


if __name__ == "__main__":
    main()
