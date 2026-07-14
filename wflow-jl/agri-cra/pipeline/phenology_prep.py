#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "xarray",
#   "netcdf4",
#   "numpy",
#   "pandas",
#   "geopandas",
#   "pyogrio",
#   "rasterio",
#   "shapely",
# ]
# ///
"""
phenology_prep.py — build the `phase` growth-stage conditioner (ASAP Option 3).

ASAP mechanism #3: the same anomaly means a different thing at a different
phenological phase, and water stress is *irreversible at flowering* (highest
FAO-33 Ky). `phase` is therefore a MODIFIER on the crop branch, not a stress
axis: it re-weights `wrsi10` and `fpar`, and never creates stress on its own.

  1 Vegetative   — baseline (neutral)
  2 Flowering    — amplifies a given deficit (highest Ky, irreversible loss)
  3 Maturation   — damps it (the crop is past the point of intervention)

This is a *tracker*, not a crop model — a light lookup over data we already
have, exactly as the plan requires. It is built from the wflow forcing
(`precip`, `temp`), so it needs no new download:

  1. **Onset** (agronomic planting date), FAO-style: the first dekad inside the
     onset window with ≥ `--onset-mm` of rain whose following two dekads also
     total ≥ `--onset-followup-mm` — i.e. rains that actually established,
     rather than a false start a farmer would lose a planting to.
  2. **Thermal time** from onset: GDD = Σ max(0, Tmean − Tbase), Tbase 10 °C
     for maize. Thermal time — not the calendar — is what the crop's
     development actually tracks.
  3. **Stage fraction** = GDD / GDD_maturity, mapped to the three phases with
     SOFT boundaries, so a basin sitting near flowering does not flip
     discontinuously between phases.

Outputs (one row per basin, keyed `id` = HYBAS_ID — aligns with wrsi10/fpar):

    id, name, country, target_date,
    onset_date, gdd, stage_frac, phase, season_active,
    phase_p1..phase_p3        soft evidence over Vegetative/Flowering/Maturation

`season_active` is False when no onset was found in the window, or the crop is
past maturity (stage_frac > 1). **This matters**: with no crop in the field,
"crop water stress" is not a meaningful proposition, and `wrsi10`/`fpar` should
not escalate the posterior. `drought_bn_ibf_v1.jl` reads `season_active` and
neutralises the crop branch when it is False (see --agri).

Usage:
    uv run phenology_prep.py --date 2021-02-15 \
        --forcing /mnt/wflow-secondary/v4_models/rwa/forcing.nc \
        --level 6 --out bn_inputs/phase_2021-02.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

from wflow_wrsi_prep import (
    DEFAULT_CROP_AFI,
    DEFAULT_HYBAS_DIR,
    load_basins,
    load_crop_fraction,
    rasterize_basins,
)

PHASE_STATES = ["Vegetative", "Flowering", "Maturation"]   # 1..3

# Maize defaults (FAO-33 / standard agronomy). Tunable per crop.
TBASE_C = 10.0          # base temperature for GDD
GDD_MATURITY = 1500.0   # thermal time from emergence to maturity
FLOWER_START = 0.55     # stage fraction at which flowering begins
FLOWER_END = 0.70       # ... and ends (grain fill / maturation follows)
SOFT_RAMP = 0.07        # soft-boundary half-width, in stage-fraction units


def phase_soft(frac: float) -> np.ndarray:
    """Stage fraction → soft evidence over the 3 phases, with soft boundaries.

    Hard binning would flip a basin discontinuously across flowering — the very
    window the node exists to resolve — so the boundaries are ramped.
    """
    if not np.isfinite(frac):
        return np.array([1.0, 0.0, 0.0])          # unknown → Vegetative (neutral)

    def ramp(x: float, edge: float) -> float:
        """0 below edge-SOFT_RAMP, 1 above edge+SOFT_RAMP, linear between."""
        if x <= edge - SOFT_RAMP:
            return 0.0
        if x >= edge + SOFT_RAMP:
            return 1.0
        return (x - (edge - SOFT_RAMP)) / (2 * SOFT_RAMP)

    past_flower_start = ramp(frac, FLOWER_START)
    past_flower_end = ramp(frac, FLOWER_END)
    p_veg = 1.0 - past_flower_start
    p_flow = past_flower_start - past_flower_end
    p_mat = past_flower_end
    p = np.array([p_veg, p_flow, p_mat], dtype="float64")
    p = np.clip(p, 0.0, 1.0)
    return p / p.sum()


def basin_series(da: xr.DataArray, mask: np.ndarray, r: int,
                 crop_frac: np.ndarray | None) -> np.ndarray:
    """Crop-weighted basin-mean daily series for basin r."""
    sel = mask == r
    if not sel.any():
        return np.array([])
    arr = np.asarray(da.values, dtype="float64")          # (time, lat, lon)
    vals = arr[:, sel]                                    # (time, npix)
    if crop_frac is not None:
        w = crop_frac[sel]
        if w.sum() <= 0:
            w = np.ones_like(w)
    else:
        w = np.ones(vals.shape[1])
    with np.errstate(invalid="ignore"):
        num = np.nansum(vals * w[None, :], axis=1)
        den = np.nansum(np.isfinite(vals) * w[None, :], axis=1)
    out = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
    return out


def detect_onset(dates: pd.DatetimeIndex, precip: np.ndarray,
                 win_start: pd.Timestamp, win_end: pd.Timestamp,
                 onset_mm: float, followup_mm: float) -> pd.Timestamp | None:
    """FAO-style agronomic onset: first dekad in the window with >= onset_mm,
    whose following two dekads total >= followup_mm (so a false start that the
    farmer would lose a planting to does not count as onset)."""
    s = pd.Series(precip, index=dates).fillna(0.0)
    dek = s.resample("10D").sum()
    idx = dek.index
    for i, t in enumerate(idx):
        if t < win_start or t > win_end:
            continue
        if dek.iloc[i] < onset_mm:
            continue
        follow = dek.iloc[i + 1:i + 3].sum() if i + 1 < len(dek) else 0.0
        if follow >= followup_mm:
            return pd.Timestamp(t)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="target date (YYYY-MM-DD)")
    ap.add_argument("--forcing", required=True,
                    help="wflow forcing.nc with daily precip + temp")
    ap.add_argument("--out", required=True)
    ap.add_argument("--level", type=int, default=6, choices=[5, 6])
    ap.add_argument("--hydrobasins-dir", default=str(DEFAULT_HYBAS_DIR))
    ap.add_argument("--domain", default=None)
    ap.add_argument("--country", default="Malawi")
    ap.add_argument("--crop-afi", default=DEFAULT_CROP_AFI)
    ap.add_argument("--no-crop-weight", action="store_true")
    ap.add_argument("--onset-window-days", type=int, default=150,
                    help="search this many days back from --date for onset")
    ap.add_argument("--onset-mm", type=float, default=25.0)
    ap.add_argument("--onset-followup-mm", type=float, default=20.0)
    ap.add_argument("--tbase", type=float, default=TBASE_C)
    ap.add_argument("--gdd-maturity", type=float, default=GDD_MATURITY)
    args = ap.parse_args()

    D = pd.Timestamp(args.date)
    ds = xr.open_dataset(args.forcing)
    for v in ("precip", "temp"):
        if v not in ds.data_vars:
            raise SystemExit(f"[phen-prep] forcing lacks '{v}' (has {list(ds.data_vars)})")

    dates = pd.to_datetime(ds.time.values)
    if D < dates.min() or D > dates.max():
        raise SystemExit(f"[phen-prep] --date {D.date()} outside forcing "
                         f"{dates.min().date()}..{dates.max().date()}")
    win_start = D - pd.Timedelta(days=args.onset_window_days)
    keep = (dates >= win_start) & (dates <= D)
    if keep.sum() < 30:
        raise SystemExit("[phen-prep] not enough forcing days in the onset window")
    sub = ds.isel(time=np.where(keep)[0])
    sdates = pd.to_datetime(sub.time.values)

    # Guard the all-NaN forcing failure mode (MWI's forcing.nc is entirely NaN).
    probe = np.asarray(sub["precip"].isel(time=0).values, dtype="float64")
    if not np.isfinite(probe).any():
        raise SystemExit(
            "[phen-prep] forcing precip is ALL-NaN — the forcing build failed. "
            "Rebuild it before running phenology (this is the MWI case's state).")

    lat = np.asarray(ds["lat"].values); lon = np.asarray(ds["lon"].values)
    bbox = (float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()))
    domain = Path(args.domain) if args.domain else None
    if domain is None:
        f = Path(args.forcing)
        sibs = list(f.parent.glob("*_v4_basin.geojson"))
        domain = sibs[0] if sibs else None

    gdf = load_basins(Path(args.hydrobasins_dir), args.level, bbox, domain)
    print(f"[phen-prep] {len(gdf)} level-{args.level} basins; target {D.date()}; "
          f"onset window from {win_start.date()}")
    crop_frac = None
    if not args.no_crop_weight:
        crop_frac = load_crop_fraction(Path(args.crop_afi), lat, lon)
    mask = rasterize_basins(gdf, lat, lon)

    pr = sub["precip"]; tp = sub["temp"]
    rows = []
    for r in range(len(gdf)):
        p_ser = basin_series(pr, mask, r, crop_frac)
        t_ser = basin_series(tp, mask, r, crop_frac)
        onset = None
        gdd = np.nan
        frac = np.nan
        if p_ser.size and np.isfinite(p_ser).any():
            onset = detect_onset(sdates, p_ser, win_start, D,
                                 args.onset_mm, args.onset_followup_mm)
        if onset is not None and t_ser.size:
            m = (sdates >= onset) & (sdates <= D)
            tt = t_ser[m]
            gdd = float(np.nansum(np.clip(tt - args.tbase, 0, None)))
            frac = gdd / args.gdd_maturity

        season_active = bool(onset is not None and np.isfinite(frac) and frac <= 1.0)
        p = phase_soft(frac if season_active else np.nan)
        b = gdf.iloc[r]
        hid = int(b["HYBAS_ID"]) if "HYBAS_ID" in gdf.columns else r
        rows.append({
            "id": str(hid),
            "name": f"HYBAS_{hid}",
            "country": args.country,
            "target_date": str(D.date()),
            "onset_date": "" if onset is None else str(onset.date()),
            "gdd": None if not np.isfinite(gdd) else round(gdd, 1),
            "stage_frac": None if not np.isfinite(frac) else round(frac, 3),
            "phase": PHASE_STATES[int(np.argmax(p))],
            "season_active": season_active,
            "phase_p1": round(float(p[0]), 4),
            "phase_p2": round(float(p[1]), 4),
            "phase_p3": round(float(p[2]), 4),
        })

    df = pd.DataFrame(rows)
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    n_act = int(df.season_active.sum())
    print(f"[phen-prep] wrote {out}  rows={len(df)}  season_active={n_act}/{len(df)}")
    print(f"[phen-prep] phase: {df.loc[df.season_active,'phase'].value_counts().to_dict()}")
    if n_act:
        print(f"[phen-prep] stage_frac: "
              f"{df.loc[df.season_active,'stage_frac'].min():.2f}.."
              f"{df.loc[df.season_active,'stage_frac'].max():.2f}")
    if n_act < len(df):
        print(f"[phen-prep] NOTE: {len(df)-n_act} basins have no active season "
              f"(no onset, or past maturity). The BN neutralises the crop branch "
              f"there — no crop in the field means crop-water-stress is not a "
              f"meaningful proposition.")


if __name__ == "__main__":
    main()
