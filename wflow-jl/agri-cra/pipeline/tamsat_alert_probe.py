#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "xarray",
#   "numpy",
#   "netcdf4",
#   "requests",
# ]
# ///
"""
TAMSAT-ALERT API probe — pin the *actual* response schema before we freeze
the BN node states for the seasonal soil-moisture / WRSI evidence node.

Why this exists
---------------
"The TAMSAT-ALERT API" is not a REST/JSON endpoint. It is two layers:

  A. INPUT data — a public file server on JASMIN serving TAMSAT **soil
     moisture** and **rainfall** estimates + forecasts as NetCDF, refreshed
     on the dekadal 1/6/11/16/21/26 schedule:
        soil moisture v2.3.1 : https://gws-access.jasmin.ac.uk/public/tamsat/soil_moisture/data/v2.3.1/
        rainfall     v3.1    : https://gws-access.jasmin.ac.uk/public/tamsat/rfe/data/v3.1/
     The soil-moisture field TAMSAT-ALERT builds WRSI from is `sm_c4grass`
     (a 0-100 availability factor / beta) — confirmed in the API source
     (TAMSAT-ALERT_API.py line ~608: sm_poi = ...["sm_c4grass"]).

  B. The WRSI PRODUCT — `TAMSAT/TAMSAT-ALERT_API_V2` (the tool that actually
     *creates* the seasonal WRSI). It ingests the layer-A files + a tercile
     precipitation forecast and writes the node-ready evidence. Confirmed CLI:
        python TAMSAT-ALERT_API.py -poi_start=YYYY-MM-DD -poi_end=YYYY-MM-DD \
            -current_date=LATEST -clim_years=1991,2020 -coords=N,S,W,E \
            -weights=ECMWF_S2S        # <-- the S2S/SEAS tercile hook
     Confirmed outputs (from output_forecasts() / terciles_text() in source):
        wrsi-forecast_{poi}_{fcast}.nc   vars (dims lon,lat):
            wrsi_forecast_ens_mean       tercile-weighted end-of-season WRSI
            wrsi_forecast_ens_sd
            wrsi_clim                    climatological-mean WRSI (clim_years)
            wrsi_sd
            wrsi_forecast_anom           = ens_mean - clim_mean
            wrsi_forecast_percent_anom   = ens_mean / clim_mean * 100
        ensemble-wrsi-forecast_{poi}_{fcast}.nc   full per-member WRSI (storylines)
        <tercile>.csv                    P(lower / mid / upper tercile WRSI),
            lower = P(below-normal end-of-season WRSI) via
            norm(clim_mean,clim_sd).ppf(0.33) → norm(ens_mean,ens_sd).cdf(·)

The BN's `wrsi_seas` node consumes layer B, NOT the raw layer-A files:
  * wrsi_seas_prob_below  <- lower-tercile probability   (mirrors the SEAS5
                             `forecast_deficit_prob`/`def` node; already a
                             probability in [0,1], no binning guess needed)
  * wrsi_seas_pct_normal  <- wrsi_forecast_percent_anom   (percent-of-normal,
                             maps to FAO-style stress classes)
  * wrsi_seas_ens_min     <- min over ensemble-wrsi-forecast members (tail)

This probe pins BOTH layers: the layer-A input schema (so a local
TAMSAT-ALERT run / our own WRSI reproduction reads the right variable), and
the layer-B output schema (documented from source, since running the full
tool needs the JASMIN forecast archive). Guessing either and hard-coding a
bin table is exactly the mistake this prevents.

What it does
------------
  * Discovers the soil-moisture store layout (aggregations present).
  * Downloads one sample file at each aggregation of interest
    (dekadal, dekadal-anomalies, seasonal-anomalies) into a cache dir.
  * Opens each with xarray and dumps a machine-readable schema:
    dims, coords (name/dtype/size/min/max), data_vars (name/dtype/dims/
    units/long_name/valid range/_FillValue), global attrs, and — for the
    main field — a NaN-aware value histogram so we can see the empirical
    distribution the bin cutoffs must sit on.
  * Writes:  tamsat_alert_schema.json   (the frozen schema, machine-readable)
             prints a human summary + a *proposed* node-state mapping that a
             human must confirm before it is copied into the BN.

Usage
-----
    uv run tamsat_alert_probe.py --year 2026 --month 01
    uv run tamsat_alert_probe.py --year 2026 --month 01 \
        --out-json tamsat_alert_schema.json --cache-dir /tmp/tamsat_probe

Nothing here is frozen into the BN automatically. The whole point is to look
at the printed schema + proposed mapping and *then* hand-edit the node bins
in drought_data_prep.py / drought_bn_ibf_v1.jl.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import requests
import xarray as xr

# ─── endpoints (pinned by directory probe, 2026-07) ──────────────────────────
SM_BASE  = "https://gws-access.jasmin.ac.uk/public/tamsat/soil_moisture/data/v2.3.1"
RFE_BASE = "https://gws-access.jasmin.ac.uk/public/tamsat/rfe/data/v3.1"

# Aggregations we care about for the BN, with their leaf filename templates.
# Verified live: dekadal files come as dk1/dk2/dk3 per month; seasonal is one
# file per (year, anchor-month). Absolute vs. *_anom variants share a grid.
#   sm{YYYY}_{MM}-dk{1..3}.v2.3.1.nc           (dekadal absolute)
#   sm{YYYY}_{MM}-dk{1..3}_anom.v2.3.1.nc      (dekadal anomaly)
#   sm{YYYY}_{MM}_seas_anom.v2.3.1.nc          (seasonal anomaly)
PROBE_TARGETS = [
    ("dekadal",           "{base}/dekadal/{yyyy}/{mm}/sm{yyyy}_{mm}-dk1.v2.3.1.nc"),
    ("dekadal-anomalies", "{base}/dekadal-anomalies/{yyyy}/{mm}/sm{yyyy}_{mm}-dk1_anom.v2.3.1.nc"),
    ("seasonal",          "{base}/seasonal/{yyyy}/{mm}/sm{yyyy}_{mm}_seas.v2.3.1.nc"),
    ("seasonal-anomalies","{base}/seasonal-anomalies/{yyyy}/{mm}/sm{yyyy}_{mm}_seas_anom.v2.3.1.nc"),
]

# ─── layer B: authoritative WRSI-product schema (from TAMSAT-ALERT_API_V2 src) ─
# Documented, not probed live (running the full tool needs the JASMIN forecast
# archive). Sourced from output_forecasts() + terciles_text() in
# github.com/TAMSAT/TAMSAT-ALERT_API_V2 / TAMSAT-ALERT_API.py.
TAMSAT_ALERT_V2_OUTPUT_SCHEMA = {
    "repo": "https://github.com/TAMSAT/TAMSAT-ALERT_API_V2",
    "cli_example": ("python TAMSAT-ALERT_API.py -poi_start=2024-03-01 "
                    "-poi_end=2024-05-31 -current_date=LATEST "
                    "-clim_years=1991,2020 -coords=6,-5,32,43 -weights=ECMWF_S2S"),
    "wrsi_built_from": "sm_c4grass (0-100 soil-moisture availability factor / beta)",
    "s2s_seas_hook": "-weights=ECMWF_S2S uses ECMWF-S2S tercile precip forecast",
    "files": {
        "wrsi-forecast_{poi}_{fcast}.nc": {
            "dims": ["lon", "lat"],
            "vars": {
                "wrsi_forecast_ens_mean": "tercile-weighted end-of-season WRSI",
                "wrsi_forecast_ens_sd":   "ensemble SD of end-of-season WRSI",
                "wrsi_clim":              "climatological-mean WRSI over clim_years",
                "wrsi_sd":                "climatological SD",
                "wrsi_forecast_anom":     "ens_mean - clim_mean (absolute WRSI anom)",
                "wrsi_forecast_percent_anom": "ens_mean / clim_mean * 100 (% of normal)",
            },
        },
        "ensemble-wrsi-forecast_{poi}_{fcast}.nc": {
            "content": "full per-member end-of-season WRSI ensemble (storylines / tail)",
        },
        "<terciles>.csv": {
            "content": "P(lower), P(mid), P(upper) tercile end-of-season WRSI; "
                       "lower = P(below-normal) via norm(clim).ppf(0.33) → "
                       "norm(ens).cdf(·)",
        },
    },
    "bn_node_mapping": {
        "wrsi_seas_prob_below": "lower-tercile probability [0,1] — mirrors the "
                                "SEAS5 `def` node; NO bin guess required",
        "wrsi_seas_pct_normal": "wrsi_forecast_percent_anom — FAO-style stress "
                                "classes on percent-of-normal",
        "wrsi_seas_ens_min":    "min over ensemble-wrsi-forecast members (tail)",
    },
}


def discover_aggregations() -> list[str]:
    """List the aggregation subdirs under the soil-moisture store root."""
    import re
    r = requests.get(f"{SM_BASE}/", timeout=60)
    r.raise_for_status()
    subs = sorted(set(re.findall(r'href="([^"/?]+)/"', r.text)))
    return [s for s in subs if not s.startswith("..") and s not in (".",)]


def download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[probe]   cached {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
        return dest
    print(f"[probe]   GET {url}")
    r = requests.get(url, timeout=180, stream=True)
    r.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        for chunk in r.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
    print(f"[probe]   saved  {dest.name} ({dest.stat().st_size/1e6:.1f} MB)")
    return dest


def _jsonable(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.ndarray, list, tuple)):
        return [_jsonable(x) for x in np.asarray(v).ravel()[:8].tolist()]
    return str(v)


def schema_of(ds: xr.Dataset) -> dict:
    coords = {}
    for name, c in ds.coords.items():
        vals = c.values
        entry = {"dtype": str(c.dtype), "size": int(c.size),
                 "attrs": {k: _jsonable(v) for k, v in c.attrs.items()}}
        try:
            if np.issubdtype(c.dtype, np.datetime64):
                entry["min"] = str(np.min(vals)); entry["max"] = str(np.max(vals))
            else:
                fv = np.asarray(vals, dtype="float64")
                entry["min"] = float(np.nanmin(fv)); entry["max"] = float(np.nanmax(fv))
        except Exception as e:  # noqa: BLE001
            entry["range_error"] = str(e)
        coords[name] = entry

    data_vars = {}
    for name, da in ds.data_vars.items():
        a = da.attrs
        entry = {
            "dtype": str(da.dtype),
            "dims": list(da.dims),
            "shape": [int(s) for s in da.shape],
            "units": a.get("units"),
            "long_name": a.get("long_name") or a.get("standard_name"),
            "_FillValue": _jsonable(a.get("_FillValue")),
            "valid_min": _jsonable(a.get("valid_min")),
            "valid_max": _jsonable(a.get("valid_max")),
            "attrs": {k: _jsonable(v) for k, v in a.items()},
        }
        data_vars[name] = entry
    return {
        "dims": {k: int(v) for k, v in ds.sizes.items()},
        "coords": coords,
        "data_vars": data_vars,
        "global_attrs": {k: _jsonable(v) for k, v in ds.attrs.items()},
    }


def value_histogram(ds: xr.Dataset, var: str) -> dict | None:
    """NaN-aware empirical distribution of the main field — the axis the BN
    bin cutoffs must sit on."""
    if var not in ds.data_vars:
        return None
    a = np.asarray(ds[var].values, dtype="float64").ravel()
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return {"n_finite": 0}
    qs = [0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100]
    return {
        "n_total": int(a.size),
        "n_finite": int(finite.size),
        "n_nan": int(a.size - finite.size),
        "percentiles": {str(q): float(np.percentile(finite, q)) for q in qs},
        "mean": float(finite.mean()),
        "std": float(finite.std()),
    }


def pick_main_var(sch: dict) -> str | None:
    """Heuristic: the largest-rank data var whose name looks like the field
    (sm / anom / wrsi), else the first data var."""
    dv = sch["data_vars"]
    if not dv:
        return None
    prefer = [n for n in dv if any(t in n.lower()
              for t in ("sm", "soil", "anom", "wrsi", "moist"))]
    cands = prefer or list(dv)
    return max(cands, key=lambda n: len(dv[n]["dims"]))


def pick_wrsi_analogue_var(sch: dict, hist_by_var: dict) -> str | None:
    """The BN's WRSI-like node wants a *bounded stress index*, not a raw store.
    Prefer a data var whose empirical range sits in [0,100] (the TAMSAT
    availability factor `sm_c4grass` beta), else fall back to the main var.
    Discovered live: `sm_c4grass` = 'Soil moisture availability factor (beta)
    for C4 grasses (range 0-100, unitless)' — a WRSI-analogue we can bin with
    FAO-style stress classes directly, unlike the kg/m2 stores."""
    for name, h in hist_by_var.items():
        if not h or not h.get("n_finite"):
            continue
        p = h["percentiles"]
        if p["0"] >= -0.5 and p["100"] <= 101 and (p["100"] - p["0"]) > 20:
            return name
    return pick_main_var(sch)


def propose_node_mapping(abs_schema: dict | None, abs_hist_by_var: dict) -> dict:
    """Emit the CONFIRMED wrsi_seas node mapping.

    The node consumes TAMSAT-ALERT_API_V2's WRSI *product* (layer B, schema
    documented in TAMSAT_ALERT_V2_OUTPUT_SCHEMA), which is already probabilistic
    — so, unlike a raw field, there is no bin-cutoff guess to freeze for the
    primary axis:

      * wrsi_seas_prob_below  = lower-tercile probability  ∈ [0,1]
            → feed as the `def`-style deficit node directly.
      * wrsi_seas_pct_normal  = wrsi_forecast_percent_anom  (% of normal WRSI)
            → FAO-style stress classes on percent-of-normal (below).
      * wrsi_seas_ens_min     = min over ensemble-wrsi-forecast members (tail).

    The layer-A `sm_c4grass` beta (0-100) — probed live from the absolute
    `seasonal/` file — is what the tool integrates to WRSI, so its empirical
    range is reported here to VALIDATE any local WRSI reproduction.
    """
    beta_var = pick_wrsi_analogue_var(abs_schema, abs_hist_by_var) if abs_schema else None
    beta_hist = abs_hist_by_var.get(beta_var) if beta_var else None
    beta_ok = False
    if beta_hist and beta_hist.get("n_finite"):
        p = beta_hist["percentiles"]
        beta_ok = p["0"] >= -0.5 and p["100"] <= 101

    return {
        "node": "wrsi_seas",
        "source": "TAMSAT-ALERT_API_V2 WRSI product (layer B)",
        "primary_axis": {
            "column": "wrsi_seas_prob_below",
            "from": "lower-tercile probability CSV",
            "type": "probability in [0,1] — NO bin guess; reuse categorize_deficit()",
        },
        "stress_class_axis": {
            "column": "wrsi_seas_pct_normal",
            "from": "wrsi_forecast_percent_anom (ens_mean / clim_mean * 100)",
            "states": ["No_Stress", "Mild", "Moderate", "Severe"],
            "cutoffs_percent_of_normal": {
                "No_Stress (idx1, least stress)": ">= 90",
                "Mild      (idx2)":               "75 .. 90",
                "Moderate  (idx3)":               "50 .. 75",
                "Severe    (idx4, most stress)":  "< 50",
            },
            "caveat": "calibrate percent-of-normal cutoffs against maize/pasture "
                      "yield in a held-out season before operational use.",
        },
        "tail_axis": {
            "column": "wrsi_seas_ens_min",
            "from": "min over ensemble-wrsi-forecast_*.nc members",
        },
        "layer_a_beta_validation": {
            "field": beta_var,
            "is_bounded_0_100_in_absolute_seasonal_file": beta_ok,
            "empirical": (f"p1={beta_hist['percentiles']['1']:.1f} "
                          f"p50={beta_hist['percentiles']['50']:.1f} "
                          f"p99={beta_hist['percentiles']['99']:.1f}"
                          if beta_hist else "seasonal absolute file not probed"),
            "note": "sm_c4grass is the field TAMSAT-ALERT integrates into WRSI; "
                    "use to validate a local WRSI reproduction, not as the node "
                    "directly.",
        },
        "ACTION": "Layer-B axes are probabilistic/percent-of-normal → freeze "
                  "wrsi_seas_prob_below via the existing categorize_deficit(); "
                  "confirm the percent-of-normal cutoffs, then wire "
                  "categorize_wrsi_seasonal(...) in drought_bn_ibf_v1.jl.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year",  default="2026")
    ap.add_argument("--month", default="01", help="zero-padded month, e.g. 01")
    ap.add_argument("--cache-dir", default="/tmp/tamsat_probe")
    ap.add_argument("--out-json",  default="tamsat_alert_schema.json")
    args = ap.parse_args()

    cache = Path(args.cache_dir)
    yyyy, mm = args.year, args.month

    print("=" * 72)
    print("TAMSAT-ALERT probe — soil-moisture store v2.3.1")
    print("=" * 72)
    try:
        aggs = discover_aggregations()
        print(f"[probe] aggregations present: {aggs}")
    except Exception as e:  # noqa: BLE001
        print(f"[probe] WARNING: could not list store root ({e}); "
              f"continuing with known targets")
        aggs = []

    report: dict = {
        "sm_base": SM_BASE, "rfe_base": RFE_BASE,
        "sample": {"year": yyyy, "month": mm},
        "aggregations_present": aggs,
        "issue_schedule_days": [1, 6, 11, 16, 21, 26],
        "tamsat_alert_v2_output_schema": TAMSAT_ALERT_V2_OUTPUT_SCHEMA,
        "targets": {},
    }

    abs_seasonal_schema = None
    abs_seasonal_hist = None
    for label, tmpl in PROBE_TARGETS:
        url = tmpl.format(base=SM_BASE, yyyy=yyyy, mm=mm)
        print(f"\n[probe] --- {label} ---")
        try:
            f = download(url, cache / Path(url).name)
            ds = xr.open_dataset(f)
        except Exception as e:  # noqa: BLE001
            print(f"[probe]   FAILED: {e}")
            report["targets"][label] = {"url": url, "error": str(e)}
            continue

        sch = schema_of(ds)
        main = pick_main_var(sch)
        hist_by_var = {vn: value_histogram(ds, vn) for vn in sch["data_vars"]}
        hist = hist_by_var.get(main)
        report["targets"][label] = {"url": url, "filename": Path(url).name,
                                     "schema": sch, "main_var": main,
                                     "histogram": hist,
                                     "histogram_by_var": hist_by_var}
        # Human summary
        print(f"[probe]   dims        : {sch['dims']}")
        print(f"[probe]   coords      : "
              + ", ".join(f"{k}[{v['size']}]" for k, v in sch["coords"].items()))
        for cn, cv in sch["coords"].items():
            if "min" in cv:
                print(f"[probe]     {cn:>6}: {cv['min']} .. {cv['max']} ({cv['dtype']})")
        print(f"[probe]   data_vars   : {list(sch['data_vars'])}")
        for vn, vv in sch["data_vars"].items():
            print(f"[probe]     {vn}: dims={vv['dims']} units={vv['units']!r} "
                  f"long_name={vv['long_name']!r} fill={vv['_FillValue']}")
        print(f"[probe]   main field  : {main}")
        if hist and hist.get("n_finite"):
            p = hist["percentiles"]
            print(f"[probe]   distribution: n_finite={hist['n_finite']} "
                  f"nan={hist['n_nan']} mean={hist['mean']:.3f} std={hist['std']:.3f}")
            print(f"[probe]     pct  p1={p['1']:.3f} p5={p['5']:.3f} "
                  f"p25={p['25']:.3f} p50={p['50']:.3f} p75={p['75']:.3f} "
                  f"p95={p['95']:.3f} p99={p['99']:.3f}")
        ds.close()
        if label == "seasonal":
            abs_seasonal_schema, abs_seasonal_hist = sch, hist_by_var

    proposal = propose_node_mapping(abs_seasonal_schema, abs_seasonal_hist or {})
    report["confirmed_wrsi_seas_node"] = proposal
    print("\n" + "=" * 72)
    print("CONFIRMED wrsi_seas node mapping (TAMSAT-ALERT_API_V2 WRSI product):")
    print("=" * 72)
    print(json.dumps(proposal, indent=2))

    out = Path(args.out_json)
    out.write_text(json.dumps(report, indent=2))
    print(f"\n[probe] wrote machine-readable schema → {out}")
    print("[probe] Next: eyeball the schema above, confirm the field + units, "
          "then hand-edit the node bins. Nothing was frozen automatically.")


if __name__ == "__main__":
    main()
