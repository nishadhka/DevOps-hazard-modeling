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
tamsat_sm_prep.py — build the soil-moisture BN evidence node from TAMSAT,
in BOTH tenses, as an ANOMALY.

Implements step 1 of the observation/forecast realignment, with the two-archive
baseline correction applied (see TWO ARCHIVES, TWO BASELINES below).

WHY THIS EXISTS
    `wrsi10` (from wflow_wrsi_prep.py) is the only evidence node in the BN that
    is ABSOLUTE — binned on fixed FAO bands (50/65/80) — because wflow has no
    multi-decadal climatology. Every other node is an anomaly ("how unusual is
    this *for here*"). TAMSAT supplies the missing climatology, so this prep
    emits the same node on ANOMALY bands, and the last absolute node goes away.

TWO ARCHIVES, TWO BASELINES — THE LOAD-BEARING CONSTRAINT
    TAMSAT observations and TAMSAT-ALERT forecasts are NOT one product:

      obs      soil_moisture/data/v2.3.1/   sm_c4grass    1983 ->        0.9 MB/day
      forecast tamsat_alert/forecasts/      beta_c4grass  2022-08-16 ->  3.65 GB/date

    Their climatologies differ by ~25-27% (a real SMAP-recalibration difference
    between product versions). Computing an anomaly ACROSS them flips the
    drought sign: for OND 2022 Kenya, 88% (dry, P(low)=0.62) vs 130% (wet,
    P(low)=0.19). Measured against both archives, not cited.

    => EACH TENSE IS STANDARDISED AGAINST ITS OWN PRODUCT'S OWN CLIMATOLOGY,
       and the two are never differenced or cross-normalised. They meet only in
       the BN, as TENSES, comparing state probabilities. This script therefore
       runs one tense at a time (--tense) and writes one CSV per tense.

ANOMALY BANDS (the re-band that closes the absolute-node limitation)
    z = (beta - clim_mean) / clim_sd, cutoffs on the engine's SPI/CDI
    convention (the same -0.5/-1.0/-1.5 used by categorize_fpar):

        1 No_Stress  z >= -0.5      2 Mild      -1.0 <= z < -0.5
        3 Moderate   -1.5 <= z < -1.0    4 Severe    z < -1.5

    Higher index = more stress, matching the BN's monotone convention.

SOFT EVIDENCE — TWO SOURCES OF SPREAD, COMBINED
    The forecast tense has ensemble spread (15 analogue members) AND spatial
    spread (pixels in a basin). Both are real and answer different questions.
    So: per pixel, the class probability is the FRACTION OF MEMBERS in each
    class (empirical, no Normality assumed); then those per-pixel distributions
    are averaged over the basin's pixels. When members agree this degenerates
    exactly to the pixel-fraction behaviour of wflow_wrsi_prep.py. The
    observation tense has no ensemble, so it is pixel fractions directly.

OUTPUT — one row per basin polygon, keyed on `id` = HYBAS_ID, matching the
wflow_wrsi_prep.py contract so this is a DROP-IN alternative node:

    id, name, country, pfaf_id, sub_area_km2, target_date, tense,
    w10_p1..w10_p4      soft evidence over the 4 anomaly-stress states
    wrsi10_class        class label of the basin's median z (fallback path)
    sm_anom_z           basin-median z-score  (diagnostic)
    sm_beta_value       basin-median beta 0-100 (diagnostic)
    sm_stress_prob      P(z < -0.5) over the basin

    NOTE: `wrsi10_value` is deliberately NOT emitted. The engine's numeric
    fallback categorize_wrsi10(::Real) applies ABSOLUTE FAO bands (>=80 etc);
    handing it a z-score would silently misclassify (z=+0.5 would read as
    "Severe"). The engine prefers soft w10_p*, and `wrsi10_class` covers the
    label fallback, so the numeric path is left unset on purpose.

USAGE
    # observation tense (season-to-date, own 2001-2020 baseline)
    uv run tamsat_sm_prep.py --tense obs \
        --poi-start 2022-10-10 --poi-end 2022-12-31 \
        --clim-start 2001 --clim-end 2020 \
        --level 6 --out bn_inputs/tamsat_sm_obs_OND2022.csv

    # forecast tense (TAMSAT-ALERT ensemble, own 2005-2019 analogue baseline)
    uv run tamsat_sm_prep.py --tense forecast --forecast-date 20221005 \
        --poi-start 2022-10-10 --poi-end 2023-02-26 \
        --clim-start 2005 --clim-end 2019 \
        --level 6 --out bn_inputs/tamsat_sm_fc_OND2022.csv
"""
from __future__ import annotations

import argparse
import os
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd

# ── sources ──────────────────────────────────────────────────────────────────
V231_URL = ("https://gws-access.jasmin.ac.uk/public/tamsat/"
            "soil_moisture/data/v2.3.1/daily/")
ALERT_URL = ("https://gws-access.jasmin.ac.uk/public/tamsat/"
             "tamsat_alert/forecasts/")
DATA_ROOT = Path(os.environ.get("TA_DATA_ROOT", "/mnt/wflow-secondary/tamsat_alert"))

# HydroBASINS Africa (same layout as wflow_wrsi_prep.py).
DEFAULT_HYBAS_DIR = (Path(__file__).resolve().parents[2]
                     / "shared" / "hydrobasins" / "data")

# Anomaly cutoffs — the engine's SPI/CDI convention (categorize_fpar docstring).
Z_MILD, Z_MODERATE, Z_SEVERE = -0.5, -1.0, -1.5
CLASS_LABELS = {1: "No_Stress", 2: "Mild", 3: "Moderate", 4: "Severe"}
DEFAULT_COUNTRY = "East Africa"


def classify_z(z: float | np.ndarray):
    """Anomaly z -> stress state 1..4 (higher = more stress). NaN -> 1 (no-op)."""
    z = np.asarray(z, dtype="float64")
    out = np.ones(z.shape, dtype=np.int8)
    out = np.where(z < Z_MILD, 2, out)
    out = np.where(z < Z_MODERATE, 3, out)
    out = np.where(z < Z_SEVERE, 4, out)
    return np.where(np.isnan(z), 1, out)


# ── ingest: observation tense (v2.3.1) ───────────────────────────────────────
def _v231_paths(dates) -> list[str]:
    cache = DATA_ROOT / "v2.3.1_sm" / "raw_daily"
    paths = []
    for d in pd.to_datetime(dates):
        sub = d.strftime("%Y/%m")
        base = "sm" + d.strftime("%Y_%m_%d") + ".v2.3.1.nc"
        ddir = cache / sub
        ddir.mkdir(parents=True, exist_ok=True)
        fn = ddir / base
        if not fn.exists():
            try:
                urllib.request.urlretrieve(V231_URL + sub + "/" + base, fn)
            except Exception as e:                       # tolerate gaps
                print(f"[tamsat-sm] WARN missing {base}: {e}")
                continue
        paths.append(str(fn))
    if not paths:
        raise SystemExit("[tamsat-sm] no v2.3.1 files for the requested dates")
    return sorted(paths)


def load_v231(dates) -> xr.DataArray:
    """Observed sm_c4grass (0-100) for `dates`, dims (time, latitude, longitude)."""
    ds = xr.open_mfdataset(
        _v231_paths(dates), combine="nested", concat_dim="time",
        preprocess=lambda d: d[["sm_c4grass"]].rename(
            {"lon": "longitude", "lat": "latitude"}))
    b = ds["sm_c4grass"]
    b = b.assign_coords(time=pd.to_datetime(b["time"].values).normalize())
    return b.where(b != 0.0, np.nan)          # 0 = fill, as in T-A_API


# ── ingest: the forecast tense's OWN historical baseline ─────────────────────
# The ALERT ensemble is the legacy product family (beta_c4grass), NOT v2.3.1.
# Its climatology must therefore come from tamsat_alert/historical/, which is
# ~25-27% higher than v2.3.1 over the same years. Standardising ALERT beta
# against a v2.3.1 climatology makes a drought look wet -- the exact failure
# documented in the module docstring's measured example.
LEGACY_URL = ("https://gws-access.jasmin.ac.uk/public/tamsat/"
              "tamsat_alert/historical/")


def load_legacy(dates) -> xr.DataArray:
    """Observed legacy beta_c4grass (0-100) for `dates`, from the yearly files
    (~594 MB/yr, cached). Same product family as the ALERT forecast ensemble."""
    d = DATA_ROOT / "historical_legacy"
    d.mkdir(parents=True, exist_ok=True)
    dates = pd.to_datetime(dates)
    das = []
    for Y in sorted({int(x) for x in dates.year}):
        fn = d / f"sm_data.daily.{Y}.nc"
        if not fn.exists():
            print(f"[tamsat-sm] fetching legacy historical {Y} (~594 MB) ...")
            urllib.request.urlretrieve(LEGACY_URL + f"sm_data.daily.{Y}.nc", fn)
        b = xr.open_dataset(fn)["beta_c4grass"]
        # T-A_API shifts the stored 12:00 stamps back to midnight before slicing.
        b = b.assign_coords(
            time=(pd.to_datetime(b["time"].values) - pd.Timedelta(hours=12)).normalize())
        das.append(b)
    b = xr.concat(das, dim="time") if len(das) > 1 else das[0]
    b = b.sortby("time").sel(time=slice(dates.min(), dates.max()))
    return b.where(b != 0.0, np.nan)


# ── ingest: forecast tense (TAMSAT-ALERT ensemble) ───────────────────────────
def load_alert(forecast_stamp: str, poi_start, poi_end) -> xr.DataArray:
    """Forecast beta_c4grass (0-100), dims (ens_year, time, latitude, longitude).
    `ens_year` is the analogue driving year — the file states it explicitly
    (long_name = 'Year of driving data used for ensemble member')."""
    d = DATA_ROOT / "forecasts"
    d.mkdir(parents=True, exist_ok=True)
    fn = d / f"alert_{forecast_stamp}_ens.daily.nc"
    if not fn.exists():
        print(f"[tamsat-sm] fetching forecast ensemble (~3.6 GB): {fn.name}")
        urllib.request.urlretrieve(
            ALERT_URL + f"alert_{forecast_stamp}_ens.daily.nc", fn)
    b = xr.open_dataset(fn)["beta_c4grass"].sel(time=slice(poi_start, poi_end))
    if b.sizes.get("time", 0) == 0:
        raise SystemExit("[tamsat-sm] POI outside the forecast file's window "
                         "(the ALERT horizon is 150 days from the issue date)")
    return b.where(b != 0.0, np.nan)


# ── climatology (per tense, on its OWN baseline) ─────────────────────────────
def seasonal_climatology(poi_start, poi_end, clim_years, bbox, tense):
    """Per-pixel mean and sd of the POI-mean observed beta across `clim_years`,
    **from the archive belonging to `tense`**.

    This is the load-bearing correctness point of the whole prep. It is not
    enough to give each tense its own clim YEARS -- each tense must use its own
    PRODUCT:

        obs      -> v2.3.1  sm_c4grass    (matches the v2.3.1 observation)
        forecast -> legacy  beta_c4grass  (matches the ALERT ensemble)

    The two differ by ~25-27%, so crossing them flips the drought sign.
    """
    loader = load_v231 if tense == "obs" else load_legacy
    poi_start, poi_end = pd.Timestamp(poi_start), pd.Timestamp(poi_end)
    span = (poi_end - poi_start).days
    yr_off = poi_end.year - poi_start.year          # 1 if the season crosses NY
    means = []
    for Y in clim_years:
        s = pd.Timestamp(year=int(Y), month=poi_start.month, day=poi_start.day)
        dates = pd.date_range(s, s + pd.Timedelta(days=span), freq="D")
        b = crop_bbox(loader(dates), bbox)
        means.append(b.mean("time", skipna=True).expand_dims(ens_year=[int(Y)]))
        print(f"[tamsat-sm]   climatology year {Y}{'/' + str(int(Y)+yr_off) if yr_off else ''} done")
    stack = xr.concat(means, dim="ens_year")
    return stack.mean("ens_year", skipna=True), stack.std("ens_year", skipna=True)


def crop_bbox(da: xr.DataArray, bbox) -> xr.DataArray:
    """Subset to (w, s, e, n), tolerating either coordinate direction."""
    w, s, e, n = bbox
    lat, lon = da["latitude"].values, da["longitude"].values
    return da.sel(longitude=slice(w, e) if lon[0] <= lon[-1] else slice(e, w),
                  latitude=slice(s, n) if lat[0] <= lat[-1] else slice(n, s))


# ── basins / zonal machinery (mirrors wflow_wrsi_prep.py) ────────────────────
def load_basins(hybas_dir: Path, level: int, bbox, domain: Path | None):
    w, s, e, n = bbox
    shp = hybas_dir / f"hybas_af_lev{level:02d}_v1c.shp"
    src = str(shp) if shp.exists() else f"/vsizip/{hybas_dir}/hybas_af_lev{level:02d}_v1c.zip"
    gdf = gpd.read_file(src).to_crs(4326).cx[w:e, s:n]
    if len(gdf) == 0:
        raise SystemExit(f"[tamsat-sm] no level-{level} basins overlap {bbox}")
    if domain is not None and Path(domain).exists():
        dom = gpd.read_file(domain).to_crs(4326).union_all()
        keep = gdf.representative_point().within(dom)
        if keep.any():
            gdf = gdf[keep].copy()
    return gdf.reset_index(drop=True)


def rasterize_basins(gdf, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    lat, lon = np.asarray(lat), np.asarray(lon)
    res_lat, res_lon = abs(float(lat[1] - lat[0])), abs(float(lon[1] - lon[0]))
    transform = from_origin(float(lon.min()) - res_lon / 2.0,
                            float(lat.max()) + res_lat / 2.0, res_lon, res_lat)
    mask = rasterize([(g, i) for i, g in enumerate(gdf.geometry)],
                     out_shape=(len(lat), len(lon)), transform=transform,
                     fill=-1, dtype=np.int32, all_touched=False)
    if lat[0] < lat[-1]:                       # rasterize emits top-down
        mask = mask[::-1, :]
    return mask


# ── aggregation ──────────────────────────────────────────────────────────────
def aggregate(pix_probs: np.ndarray, z: np.ndarray, beta: np.ndarray,
              mask: np.ndarray, gdf, target_date: str, tense: str,
              country: str) -> pd.DataFrame:
    """pix_probs (4, ny, nx) per-pixel class probabilities -> per-basin rows."""
    rows = []
    for r in range(len(gdf)):
        sel = mask == r
        if not sel.any():
            continue
        zz = z[sel]
        finite = np.isfinite(zz)
        if not finite.any():
            continue
        pp = pix_probs[:, sel][:, finite]          # (4, npix)
        fracs = np.nanmean(pp, axis=1)             # average over basin pixels
        tot = float(fracs.sum())
        fracs = fracs / tot if tot > 0 else np.array([1.0, 0.0, 0.0, 0.0])
        z_med = float(np.nanmedian(zz[finite]))
        b = beta[sel][finite]
        cls = int(classify_z(z_med))
        bd = gdf.iloc[r]
        hid = int(bd["HYBAS_ID"]) if "HYBAS_ID" in gdf.columns else r
        rows.append({
            "id": str(hid),
            "name": f"HYBAS_{hid}",
            "country": country,
            "pfaf_id": int(bd["PFAF_ID"]) if "PFAF_ID" in gdf.columns else None,
            "sub_area_km2": round(float(bd["SUB_AREA"]), 2) if "SUB_AREA" in gdf.columns else None,
            "target_date": target_date,
            "tense": tense,
            "w10_p1": round(float(fracs[0]), 4),
            "w10_p2": round(float(fracs[1]), 4),
            "w10_p3": round(float(fracs[2]), 4),
            "w10_p4": round(float(fracs[3]), 4),
            "wrsi10_class": CLASS_LABELS[cls],
            "sm_anom_z": round(z_med, 3),
            "sm_beta_value": None if not np.isfinite(np.nanmedian(b)) else round(float(np.nanmedian(b)), 2),
            "sm_stress_prob": round(float(fracs[1] + fracs[2] + fracs[3]), 4),
            "n_pixels": int(finite.sum()),
        })
    return pd.DataFrame(rows)


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description="TAMSAT soil-moisture BN evidence node (anomaly, per tense)")
    p.add_argument("--tense", required=True, choices=["obs", "forecast"])
    p.add_argument("--poi-start", required=True, help="YYYY-MM-DD")
    p.add_argument("--poi-end", required=True, help="YYYY-MM-DD")
    p.add_argument("--forecast-date", help="YYYYMMDD (required for --tense forecast)")
    p.add_argument("--clim-start", type=int,
                   help="default 2001 (obs, TAMSAT baseline) / 2005 (forecast analogues)")
    p.add_argument("--clim-end", type=int, help="default 2020 (obs) / 2019 (forecast)")
    p.add_argument("--region", nargs=4, type=float,
                   default=[21.838949, 51.415695, -11.745695, 23.145147],
                   metavar=("LONMIN", "LONMAX", "LATMIN", "LATMAX"),
                   help="default: ICPAC East Africa domain")
    p.add_argument("--level", type=int, default=6, choices=[5, 6])
    p.add_argument("--hybas-dir", type=Path, default=DEFAULT_HYBAS_DIR)
    p.add_argument("--domain", type=Path, default=None)
    p.add_argument("--country", default=DEFAULT_COUNTRY)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()

    lon_min, lon_max, lat_min, lat_max = a.region
    bbox = (lon_min, lat_min, lon_max, lat_max)          # w, s, e, n
    poi_start, poi_end = pd.Timestamp(a.poi_start), pd.Timestamp(a.poi_end)

    # Each tense defaults to ITS OWN baseline. Never share (see module docstring).
    if a.tense == "obs":
        cs = a.clim_start or 2001
        ce = a.clim_end or 2020
    else:
        cs = a.clim_start or 2005
        ce = a.clim_end or 2019
        if not a.forecast_date:
            raise SystemExit("--forecast-date is required for --tense forecast")
    print(f"[tamsat-sm] tense={a.tense}  POI {poi_start.date()}..{poi_end.date()}"
          f"  baseline {cs}-{ce}  region {a.region}")

    # ---- the value being classified, per tense --------------------------
    if a.tense == "obs":
        dates = pd.date_range(poi_start, poi_end, freq="D")
        beta = crop_bbox(load_v231(dates), bbox).mean("time", skipna=True)
    else:
        b = crop_bbox(load_alert(a.forecast_date, poi_start, poi_end), bbox)
        members = [int(y) for y in np.atleast_1d(b["ens_year"].values)]
        print(f"[tamsat-sm] ensemble members (analogue driving years): {members}")
        beta = b.mean("time", skipna=True)                         # (ens, ny, nx)

    print(f"[tamsat-sm] building climatology {cs}-{ce} on the {a.tense} baseline ...")
    clim_mean, clim_sd = seasonal_climatology(poi_start, poi_end,
                                              range(cs, ce + 1), bbox, a.tense)

    # The value grid and the climatology are both the 0.25 deg TAMSAT grid, but
    # they come from different archives -- align all three together (guards
    # float drift and any edge-cell difference) BEFORE taking .values, so the
    # arrays below are guaranteed conformable.
    ref = beta.isel(ens_year=0, drop=True) if a.tense == "forecast" else beta
    clim_mean, clim_sd, ref = xr.align(clim_mean, clim_sd, ref, join="inner")
    beta = beta.sel(latitude=ref["latitude"], longitude=ref["longitude"])
    beta_vals = (beta.mean("ens_year", skipna=True).values
                 if a.tense == "forecast" else beta.values)

    # ---- z, per-pixel class probabilities -------------------------------
    cm, csd = clim_mean.values, clim_sd.values
    with np.errstate(invalid="ignore", divide="ignore"):
        if a.tense == "obs":
            z = (beta_vals - cm) / csd
            cls = classify_z(z)                                    # (ny, nx)
            pix = np.stack([(cls == k).astype("float64") for k in (1, 2, 3, 4)])
            pix[:, ~np.isfinite(z)] = np.nan
        else:
            zm = (beta.values - cm[None, :, :]) / csd[None, :, :]   # (ens, ny, nx)
            clsm = classify_z(zm)
            # per pixel: fraction of ENSEMBLE MEMBERS in each class
            pix = np.stack([(clsm == k).mean(axis=0) for k in (1, 2, 3, 4)])
            z = np.nanmean(zm, axis=0)
            pix[:, ~np.isfinite(z)] = np.nan

    # ---- zonal aggregation ----------------------------------------------
    lat = beta["latitude"].values
    lon = beta["longitude"].values
    gdf = load_basins(a.hybas_dir, a.level, bbox, a.domain)
    print(f"[tamsat-sm] {len(gdf)} level-{a.level} basins over the region")
    mask = rasterize_basins(gdf, lat, lon)
    df = aggregate(pix, z, beta_vals, mask, gdf,
                   target_date=str(poi_end.date()), tense=a.tense,
                   country=a.country)
    if df.empty:
        raise SystemExit("[tamsat-sm] no basin produced finite evidence")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    vc = df["wrsi10_class"].value_counts().to_dict()
    print(f"[tamsat-sm] wrote {a.out}  ({len(df)} basins)")
    print(f"[tamsat-sm] class counts: {vc}")
    print(f"[tamsat-sm] mean stress prob P(z<-0.5): {df['sm_stress_prob'].mean():.3f}")


if __name__ == "__main__":
    main()
