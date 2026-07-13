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
wflow_wrsi_prep.py — build the `wrsi10` BN evidence node from a wflow.jl run.

This is the post-wflow step of the agri-CRMA chain: it turns a wflow.jl
`output_grid_wrsi.nc` (daily `aet`, `pet`) into per-HydroBASINS-polygon WRSI
evidence that the drought BN consumes as the 10-day crop-water-stress node.

WRSI definition (the project's canonical form, from
shared/hydrobasins/wrsi_analysis.py):

    WRSI = 100 * Σ AET / Σ PET      (Kc=1 water-balance form, masked where ΣPET≈0)

FAO interpretation bands: <50 crop-failure likely, 50-79 water stress,
>=80 no/minimal stress. The node splits the stress band at 65 to give a
4-state axis matching the BN's monotonic convention:

    1 No_Stress (WRSI >= 80)   2 Mild (65..80)
    3 Moderate  (50..65)       4 Severe (< 50)      (higher index = more stress)

Two temporal modes:
  --mode dekadal  (default) season-to-date cumulative WRSI at the latest
                  dekad — the operational "10-day" node (resample 10D, cumsum
                  within the season, take the last dekad's cumulative grid).
  --mode period   WRSI over the whole run period (season-total diagnostic).

Boundaries: HydroBASINS Africa level 5 or 6. For Malawi the level-5 anchor
(HYBAS_ID 1051472390, Lake Malawi / Shire / Upper Zambezi) contains 9 level-6
sub-basins; --level 6 gives per-sub-basin rows, --level 5 gives one country-
scale row. Basins are auto-subset to the WRSI grid's bbox, and optionally
clipped to a --domain polygon (default: the run's own basin geojson).

Output CSV — one row per basin polygon, keyed on `id` = HYBAS_ID, ready to
merge into the drought BN input CSV as the wrsi10 node:

    id, name, country, pfaf_id, sub_area_km2, target_date,
    wrsi10_value,        zonal-median WRSI over the basin
    wrsi10_class,        FAO/stress class of the median
    wrsi10_min,          worst-pixel WRSI (sub-area tail)
    wrsi10_stress_prob,  fraction of basin pixels with WRSI < 80
    w10_p1..w10_p4       soft evidence over the 4 stress states (pixel fractions)

Usage:
    # Malawi, once the wflow run has produced output/output_grid_wrsi.nc:
    uv run wflow_wrsi_prep.py \
        --wrsi-nc /mnt/wflow-secondary/v4_models/mwi/output/output_grid_wrsi.nc \
        --level 6 --out bn_inputs/wrsi10_mwi_2026-07.csv

    # verify the machinery on an existing case (auto-selects that case's basins):
    uv run wflow_wrsi_prep.py \
        --wrsi-nc ../../runs/rwa_wrsi/output/output_grid_wrsi.nc \
        --level 6 --out /tmp/wrsi10_rwa.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

# ─── WRSI / stress-state constants ───────────────────────────────────────────
# 4 stress states in increasing-stress order (matches the BN convention where
# a higher index is more stressed, e.g. TAIL_RISK / CDI). Cutoffs are on WRSI
# (0..150): FAO bands at 50 and 80, stress band split at 65.
WRSI10_STATES = ["No_Stress", "Mild", "Moderate", "Severe"]  # idx 1..4
# edges for np.digitize on WRSI value → class index 1..4 (drier = higher idx)
#   WRSI >= 80 -> 1 (No_Stress); 65..80 -> 2; 50..65 -> 3; <50 -> 4
WRSI_CLASS_EDGES = [50.0, 65.0, 80.0]  # ascending; see classify_wrsi()
STRESS_THRESHOLD = 80.0                # WRSI < 80 counts as "under stress"

# HydroBASINS Africa zip layout (repo default).
# .../wflow-jl/agri-cra/pipeline/wflow_wrsi_prep.py → parents[2] == wflow-jl
DEFAULT_HYBAS_DIR = (Path(__file__).resolve().parents[2]
                     / "shared" / "hydrobasins" / "data")

# ASAP crop Area-Fraction Image (mechanism #1 in asap-crma-gap-and-bn-role.md):
# JRC ASAP v04 global crop AFI, EPSG:4326, ~500 m, pixel value = crop cover %
# (0-100, verified against Iowa/Punjab crop-dense regions). Consumed, not
# produced. Download: https://mars.jrc.ec.europa.eu/asap/files/asap_mask_crop_v04.tif
DEFAULT_CROP_AFI = "/mnt/wflow-data/asap/asap_mask_crop_v04.tif"
# ASAP active-area gate: warn only where the anomalous share exceeds this
# fraction of the *active* (crop) area (note.txt L123). Used here as a soft
# evidence-strength gate, not a hard cutoff.
CAF_GATE = 0.25

# Rough country label for the domain (metadata only; wrsi10 is basin-keyed).
DEFAULT_COUNTRY = "Malawi"


def classify_wrsi(v: float) -> int:
    """WRSI value → stress-state index 1..4 (1=No_Stress .. 4=Severe)."""
    if not np.isfinite(v):
        return 1
    if v >= 80.0:
        return 1  # No_Stress
    if v >= 65.0:
        return 2  # Mild
    if v >= 50.0:
        return 3  # Moderate
    return 4      # Severe


# ─── WRSI grids (canonical wrsi_analysis.py logic) ───────────────────────────


def wrsi_period_grid(aet: xr.DataArray, pet: xr.DataArray) -> xr.DataArray:
    """100 * ΣAET/ΣPET over the whole time axis, masked where ΣPET≈0."""
    sa = aet.sum("time", skipna=True)
    sp = pet.sum("time", skipna=True)
    return (100.0 * sa / sp.where(sp > 1e-6)).clip(0, 150)


def wrsi_dekadal_latest_grid(aet: xr.DataArray, pet: xr.DataArray
                             ) -> tuple[xr.DataArray, pd.Timestamp]:
    """Per-pixel season-to-date cumulative WRSI at the latest dekad.

    Resample to 10-day sums, cumulative-sum within each calendar year (the
    growing-season accumulation), and return the last dekad's cumulative
    100*ΣAET/ΣPET grid — the operational 10-day WRSI field.
    """
    aet10 = aet.resample(time="10D").sum(skipna=True)
    pet10 = pet.resample(time="10D").sum(skipna=True)
    yr = aet10["time"].dt.year
    ca = aet10.groupby(yr).cumsum("time")
    cp = pet10.groupby(yr).cumsum("time")
    wrsi = (100.0 * ca / cp.where(cp > 1e-6)).clip(0, 150)
    last = wrsi.isel(time=-1)
    return last, pd.Timestamp(aet10["time"].values[-1])


# ─── basin loading + rasterisation ───────────────────────────────────────────


def load_basins(hybas_dir: Path, level: int, bbox: tuple[float, float, float, float],
                domain: Path | None) -> gpd.GeoDataFrame:
    """Load HydroBASINS Africa polygons at `level`, restricted to the WRSI grid
    bbox and (optionally) clipped to a `domain` polygon whose basins we keep
    when their representative point falls inside it."""
    w, s, e, n = bbox
    # Prefer the unzipped .shp; fall back to the zip. Avoid the bbox= spatial
    # filter — the shipped .sbn index is corrupt ("Invalid node descriptor
    # size") for some queries — and instead filter in-memory with .cx.
    shp = hybas_dir / f"hybas_af_lev{level:02d}_v1c.shp"
    src = str(shp) if shp.exists() else f"/vsizip/{hybas_dir}/hybas_af_lev{level:02d}_v1c.zip"
    gdf = gpd.read_file(src).to_crs(4326)
    gdf = gdf.cx[w:e, s:n]                     # bounding-box slice, no .sbn
    if len(gdf) == 0:
        raise SystemExit(f"[wrsi-prep] no level-{level} basins overlap the WRSI "
                         f"grid bbox {tuple(round(x, 2) for x in bbox)}")
    if domain is not None and domain.exists():
        dom = gpd.read_file(domain).to_crs(4326).union_all()
        keep = gdf.representative_point().within(dom)
        if keep.any():
            gdf = gdf[keep].copy()
            print(f"[wrsi-prep] clipped to domain {domain.name}: "
                  f"{len(gdf)} level-{level} basins")
    return gdf.reset_index(drop=True)


def rasterize_basins(gdf: gpd.GeoDataFrame, lat: np.ndarray, lon: np.ndarray
                     ) -> np.ndarray:
    """Per-pixel region index (int32, -1 = no basin). rasterio directly, to
    avoid regionmask's large intermediate alloc (same approach as
    cdi_data_prep.py::build_mask)."""
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    lat = np.asarray(lat); lon = np.asarray(lon)
    n_lat, n_lon = len(lat), len(lon)
    res_lat = abs(float(lat[1] - lat[0])); res_lon = abs(float(lon[1] - lon[0]))
    west = float(lon.min()) - res_lon / 2.0
    north = float(lat.max()) + res_lat / 2.0
    transform = from_origin(west, north, res_lon, res_lat)
    shapes = [(geom, idx) for idx, geom in enumerate(gdf.geometry)]
    mask = rasterize(shapes, out_shape=(n_lat, n_lon), transform=transform,
                     fill=-1, dtype=np.int32, all_touched=False)
    if lat[0] < lat[-1]:               # rasterize emits top-down (max-lat first)
        mask = mask[::-1, :]
    return mask


def load_crop_fraction(afi_path: Path, lat: np.ndarray, lon: np.ndarray
                       ) -> np.ndarray | None:
    """Windowed-read the ASAP crop AFI over the WRSI grid bbox and regrid
    (nearest) to the WRSI (lat, lon) grid. Returns crop fraction in [0,1], or
    None if the AFI is unavailable (→ caller falls back to unweighted)."""
    if not Path(afi_path).exists():
        print(f"[wrsi-prep] crop AFI not found ({afi_path}); "
              f"falling back to UNWEIGHTED (flat) reduction")
        return None
    import rasterio
    from rasterio.windows import from_bounds
    res_lat = abs(float(lat[1] - lat[0])); res_lon = abs(float(lon[1] - lon[0]))
    w = float(lon.min()) - res_lon; e = float(lon.max()) + res_lon
    s = float(lat.min()) - res_lat; n = float(lat.max()) + res_lat
    with rasterio.open(afi_path) as ds:
        win = from_bounds(w, s, e, n, ds.transform)
        a = ds.read(1, window=win).astype("float64")            # crop % 0-100
        wt = ds.window_transform(win)
        nrow, ncol = a.shape
        src_lon = wt.c + (np.arange(ncol) + 0.5) * wt.a
        src_lat = wt.f + (np.arange(nrow) + 0.5) * wt.e          # wt.e < 0
    # nearest-neighbour regrid to the WRSI grid
    ji = np.abs(src_lon[None, :] - lon[:, None]).argmin(axis=1)
    ii = np.abs(src_lat[None, :] - lat[:, None]).argmin(axis=1)
    frac = a[np.ix_(ii, ji)] / 100.0
    return np.clip(frac, 0.0, 1.0)


def _weighted_median(vals: np.ndarray, wts: np.ndarray) -> float:
    """Weighted median (50th weighted percentile)."""
    order = np.argsort(vals)
    v = vals[order]; w = wts[order]
    cw = np.cumsum(w)
    if cw[-1] <= 0:
        return float(np.median(vals))
    cutoff = 0.5 * cw[-1]
    return float(v[np.searchsorted(cw, cutoff)])


# ─── per-basin zonal reduction → wrsi10 node ─────────────────────────────────


def aggregate(wrsi: np.ndarray, mask: np.ndarray, gdf: gpd.GeoDataFrame,
              lat: np.ndarray, lon: np.ndarray,
              crop_frac: np.ndarray | None = None) -> pd.DataFrame:
    """Per-basin WRSI reduction → wrsi10 node rows.

    If `crop_frac` (0..1 grid) is given, the reduction is **crop-fraction-
    weighted** (ASAP mechanism #1): each pixel's WRSI is weighted by its crop
    cover, so a rangeland/bare basin neither dilutes nor fabricates the crop
    signal. The soft-evidence bins `w10_p*` become crop-weighted class shares,
    and `wrsi10_stress_prob` is the crop-weighted stressed share. `crop_active_
    frac` (mean crop fraction) drives the ASAP CAF>25% soft gate: below the
    gate the soft evidence is shrunk toward uniform (weak evidence = BN no-op),
    the Bayesian analogue of "no warning unless >25% of active area is hit".
    """
    weighted = crop_frac is not None
    rows = []
    for r in range(len(gdf)):
        sel = (mask == r) & np.isfinite(wrsi)
        if sel.sum() < 1:
            pt = gdf.iloc[r].geometry.representative_point()
            i = int(np.argmin(np.abs(lat - pt.y)))
            j = int(np.argmin(np.abs(lon - pt.x)))
            vals = np.array([wrsi[i, j]], dtype="float64")
            wts = np.array([crop_frac[i, j] if weighted else 1.0], dtype="float64")
            ok = np.isfinite(vals)
            vals, wts = vals[ok], wts[ok]
            crop_active = float(wts[0]) if weighted and wts.size else np.nan
        else:
            vals = wrsi[sel].astype("float64")
            wts = (crop_frac[sel].astype("float64") if weighted
                   else np.ones(vals.size))
            crop_active = float(crop_frac[mask == r].mean()) if weighted else np.nan

        if vals.size == 0 or (weighted and wts.sum() <= 0):
            med = np.nan; vmin = np.nan
            # No (crop) data → put the mass on No_Stress, the BN's identity
            # state for this node. A UNIFORM vector is NOT a no-op here: it
            # would place 3/4 of the mass on stressed states and escalate the
            # posterior purely because we lack data.
            fracs = np.zeros(4); fracs[0] = 1.0
            stress_prob = np.nan
        else:
            med = _weighted_median(vals, wts) if weighted else float(np.median(vals))
            # tail = worst pixel that carries meaningful crop cover
            tail_sel = (wts >= 0.10) if weighted else np.ones(vals.size, bool)
            vmin = float(np.min(vals[tail_sel])) if tail_sel.any() else float(np.min(vals))
            cls = np.array([classify_wrsi(v) for v in vals])
            W = wts.sum()
            fracs = np.array([wts[cls == k].sum() / W for k in (1, 2, 3, 4)],
                             dtype="float64")
            stress_prob = float(wts[vals < STRESS_THRESHOLD].sum() / W)
            # ASAP CAF>25% gate: with little crop area we have little basis for a
            # *crop* water-stress claim, so the shortfall goes to No_Stress (the
            # identity state), NOT to a uniform vector — uniform would escalate
            # the posterior purely because the basin is barely cropped.
            if weighted and np.isfinite(crop_active):
                strength = min(1.0, crop_active / CAF_GATE)
                fracs = strength * fracs
                fracs[0] += 1.0 - strength
        b = gdf.iloc[r]
        hid = int(b["HYBAS_ID"]) if "HYBAS_ID" in gdf.columns else r
        pfaf = int(b["PFAF_ID"]) if "PFAF_ID" in gdf.columns else -1
        area = float(b["SUB_AREA"]) if "SUB_AREA" in gdf.columns else np.nan
        rows.append({
            "id":                 str(hid),
            "name":               f"HYBAS_{hid}",
            "pfaf_id":            pfaf,
            "sub_area_km2":       area,
            "crop_active_frac":   None if not np.isfinite(crop_active) else round(crop_active, 4),
            "wrsi10_value":       None if not np.isfinite(med) else round(med, 2),
            "wrsi10_class":       WRSI10_STATES[classify_wrsi(med) - 1],
            "wrsi10_min":         None if not np.isfinite(vmin) else round(vmin, 2),
            "wrsi10_stress_prob": None if stress_prob is None or not np.isfinite(stress_prob)
                                  else round(stress_prob, 4),
            "w10_p1": round(float(fracs[0]), 4),
            "w10_p2": round(float(fracs[1]), 4),
            "w10_p3": round(float(fracs[2]), 4),
            "w10_p4": round(float(fracs[3]), 4),
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wrsi-nc", required=True,
                    help="wflow output_grid_wrsi.nc with daily aet/pet")
    ap.add_argument("--out", required=True, help="output wrsi10 node CSV")
    ap.add_argument("--level", type=int, default=6, choices=[5, 6],
                    help="HydroBASINS level (5=country-scale anchor, 6=sub-basins)")
    ap.add_argument("--hydrobasins-dir", default=str(DEFAULT_HYBAS_DIR),
                    help="dir holding hybas_af_lev0X_v1c.zip")
    ap.add_argument("--domain", default=None,
                    help="optional geojson to clip basins to (keep basins whose "
                         "rep-point is inside). Default: the run's sibling "
                         "*_v4_basin.geojson if present.")
    ap.add_argument("--mode", default="dekadal", choices=["dekadal", "period"],
                    help="dekadal = season-to-date cumulative WRSI at the latest "
                         "dekad (10-day node); period = whole-run WRSI")
    ap.add_argument("--country", default=DEFAULT_COUNTRY,
                    help="country label written to the CSV (metadata only)")
    ap.add_argument("--crop-afi", default=DEFAULT_CROP_AFI,
                    help="ASAP crop Area-Fraction Image (crop %% 0-100) for "
                         "CAF>25%% crop weighting. Consumed, not produced.")
    ap.add_argument("--no-crop-weight", action="store_true",
                    help="disable crop weighting (flat reduction over all pixels)")
    args = ap.parse_args()

    wrsi_nc = Path(args.wrsi_nc)
    print(f"[wrsi-prep] opening {wrsi_nc}", flush=True)
    ds = xr.open_dataset(wrsi_nc)
    if not {"aet", "pet"} <= set(ds.data_vars):
        raise SystemExit(f"[wrsi-prep] expected aet+pet in {wrsi_nc}, "
                         f"got {list(ds.data_vars)}")
    aet, pet = ds["aet"], ds["pet"]
    lat = np.asarray(ds["lat"].values); lon = np.asarray(ds["lon"].values)

    if args.mode == "dekadal":
        wrsi_da, target = wrsi_dekadal_latest_grid(aet, pet)
        print(f"[wrsi-prep] mode=dekadal  latest dekad = {target.date()}")
    else:
        wrsi_da = wrsi_period_grid(aet, pet)
        target = pd.Timestamp(ds["time"].values[-1])
        print(f"[wrsi-prep] mode=period   through {target.date()}")
    wrsi = np.asarray(wrsi_da.values, dtype="float64")

    # Default domain: the run's own basin geojson sitting beside the nc.
    domain = Path(args.domain) if args.domain else None
    if domain is None:
        sibs = list(wrsi_nc.parent.parent.glob("*_v4_basin.geojson")) \
             + list(wrsi_nc.parent.glob("*_v4_basin.geojson"))
        if sibs:
            domain = sibs[0]
            print(f"[wrsi-prep] default domain = {domain}")

    bbox = (float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()))
    gdf = load_basins(Path(args.hydrobasins_dir), args.level, bbox, domain)
    print(f"[wrsi-prep] {len(gdf)} level-{args.level} basins over grid "
          f"{tuple(round(x, 2) for x in bbox)}")

    crop_frac = None
    if not args.no_crop_weight:
        crop_frac = load_crop_fraction(Path(args.crop_afi), lat, lon)
        if crop_frac is not None:
            print(f"[wrsi-prep] crop weighting ON (ASAP AFI); grid crop-cover "
                  f"mean={100*np.nanmean(crop_frac):.1f}%  "
                  f">25%%={100*np.mean(crop_frac > CAF_GATE):.0f}% of pixels")
    else:
        print("[wrsi-prep] crop weighting OFF (--no-crop-weight)")

    mask = rasterize_basins(gdf, lat, lon)
    df = aggregate(wrsi, mask, gdf, lat, lon, crop_frac=crop_frac)
    df.insert(2, "country", args.country)
    df.insert(7, "target_date", str(target.date()))

    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    finite = df["wrsi10_value"].dropna()
    n_missing = len(df) - len(finite)
    print(f"[wrsi-prep] wrote {out}  rows={len(df)}  "
          f"(with-data={len(finite)}, no-grid-overlap={n_missing} → uniform "
          f"soft evidence = BN no-op)")
    if len(finite):
        vc = df.loc[df["wrsi10_value"].notna(), "wrsi10_class"].value_counts().to_dict()
        print(f"[wrsi-prep] wrsi10_class (with-data): {vc}")
        print(f"[wrsi-prep] WRSI median across basins = {finite.median():.1f} "
              f"(min {finite.min():.1f}, max {finite.max():.1f})")


if __name__ == "__main__":
    main()
