"""Download ECMWF S2S forecast forcing for the Malawi / enlarged East-Africa
domain, with ALL the variables needed to compute reference PET by the
Penman(-Monteith) FAO-56 method.

Dataset : s2s-forecasts  (ECMWF Climate Data Store, https://ecds.ecmwf.int)
            https://ecds.ecmwf.int/datasets/s2s-forecasts?tab=download
Domain  : enlarged East-Africa extent that covers Malawi
            lat -17.5 .. 25 , lon 20 .. 53
            CDS area = [North, West, South, East] = [25, 20, -17.5, 53]
Output  : one GRIB per variable in mwi/forcing_s2s/  (resumable; existing
            files are skipped). Per-variable files keep each retrieval small
            and let a single bad variable name fail in isolation.

This script ONLY downloads. PET (Penman) + regrid onto the wflow staticmaps
grid + write forcing.nc are the next step (see build_v4_forcing.py for the
target forcing.nc contract: precip / temp / pet, mm & degree C, daily).

--------------------------------------------------------------------------
Credentials (cdsapi, pending — user will share):
  cdsapi.Client() reads ~/.cdsapirc. For ECDS that file is:

      url: https://ecds.ecmwf.int/api
      key: <YOUR-ECDS-TOKEN>

  (Confirm the exact `url` from the dataset page's "Show API request" box.)
  You can also override via env CDSAPI_URL / CDSAPI_KEY without writing the
  file. Nothing secret is stored in this script or the repo.

Run:
  uv run python mwi/download_s2s_forcing.py --dry-run          # print requests
  uv run python mwi/download_s2s_forcing.py                    # download all
  uv run python mwi/download_s2s_forcing.py --only 2t tp       # subset
  uv run python mwi/download_s2s_forcing.py --date 2026-05-01  # other init date
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

OUT = Path(__file__).resolve().parent / "forcing_s2s"

DATASET = "s2s-forecasts"

# CDS area convention: [North, West, South, East]
# enlarged East-Africa extent covering Malawi (lat -17.5..25, lon 20..53)
AREA = [25, 20, -17.5, 53]

# S2S leadtime windows: 24-hour buckets out to 1104 h (= 46 days).
# "0_24", "24_48", ... "1080_1104"  (46 entries) — matches the ECDS example.
LEADTIME_HOURS = [f"{i*24}_{(i+1)*24}" for i in range(46)]

# --------------------------------------------------------------------------
# Variables for the Penman(-Monteith) FAO-56 match (+ the two wflow forcing
# fields). Each entry: short-key -> (cds_variable_name, Penman/forcing role).
#
# NAMING: the ECDS request strings use the underscored long form, e.g. the
# example used "2_m_temperature". The strings below follow that convention,
# but VERIFY each against the dataset page's "Show API request" tool — the
# canonical names live there. A wrong name only fails that one file.
#
# FAO-56 Penman-Monteith needs: Tmean, Tmax, Tmin, wind (u,v), net radiation
# (or the downward short/long pair), humidity (dewpoint), pressure.
# De Bruin / Makkink (simpler fallback) needs only: ssrd (+ strd), Tmean, sp.
# --------------------------------------------------------------------------
VARIABLES: dict[str, tuple[str, str]] = {
    # --- wflow forcing fields ---
    "tp":   ("total_precipitation",                         "forcing: precipitation"),
    "2t":   ("2_m_temperature",                             "forcing: temperature; PET Tmean"),
    # --- Penman-Monteith temperature extremes ---
    "mx2t": ("maximum_2_m_temperature_in_the_last_6_hours", "PET Tmax"),
    "mn2t": ("minimum_2_m_temperature_in_the_last_6_hours", "PET Tmin"),
    # --- wind ---
    "10u":  ("10_m_u_component_of_wind",                    "PET wind (u)"),
    "10v":  ("10_m_v_component_of_wind",                    "PET wind (v)"),
    # --- radiation (downward pair preferred; net as alternative) ---
    "ssrd": ("surface_solar_radiation_downwards",           "PET shortwave down (also De Bruin/Makkink)"),
    "strd": ("surface_thermal_radiation_downwards",         "PET longwave down (also De Bruin)"),
    "ssr":  ("surface_net_solar_radiation",                 "PET net shortwave (alt)"),
    "str":  ("surface_net_thermal_radiation",               "PET net longwave (alt)"),
    # --- humidity + pressure ---
    "2d":   ("2_m_dewpoint_temperature",                    "PET humidity (-> actual vapour pressure)"),
    "sp":   ("surface_pressure",                            "PET psychrometric constant"),
}

# Minimal sets, for reference / --only convenience:
#   FAO-56 PM : 2t mx2t mn2t 10u 10v ssrd strd 2d sp  (+ tp for forcing)
#   De Bruin  : ssrd strd 2t sp                        (+ tp for forcing)


def build_request(cds_variable: str, args) -> dict:
    """One ECDS s2s-forecasts retrieve() request for a single variable."""
    return {
        "origin": args.origin,
        "year": args.year,
        "month": args.month,
        "day": args.day,
        "time": args.time,
        "level_type": "single_level",
        "variable": [cds_variable],
        "forecast_type": args.forecast_type,
        "leadtime_hour": LEADTIME_HOURS,
        "area": args.area,
        "data_format": args.data_format,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", default="2026-05-01",
                   help="forecast initialisation date YYYY-MM-DD (default 2026-05-01)")
    p.add_argument("--time", default="00:00", help="init time (default 00:00)")
    p.add_argument("--origin", default="ecmwf", help="model origin (default ecmwf)")
    p.add_argument("--forecast-type", default="perturbed_forecast",
                   help="perturbed_forecast (ensemble) | control_forecast")
    p.add_argument("--data-format", default="grib", choices=["grib", "netcdf"])
    p.add_argument("--area", nargs=4, type=float, default=AREA,
                   metavar=("N", "W", "S", "E"),
                   help="CDS area N W S E (default 25 20 -17.5 53)")
    p.add_argument("--only", nargs="+", default=None,
                   help=f"subset of variable keys to fetch (default all: {list(VARIABLES)})")
    p.add_argument("--outdir", type=Path, default=OUT)
    p.add_argument("--dry-run", action="store_true",
                   help="print the requests, do not download")
    args = p.parse_args()

    y, m, d = args.date.split("-")
    args.year, args.month, args.day = y, m, d

    keys = args.only or list(VARIABLES)
    bad = [k for k in keys if k not in VARIABLES]
    if bad:
        raise SystemExit(f"unknown variable keys {bad}; choose from {list(VARIABLES)}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    ext = "grib" if args.data_format == "grib" else "nc"
    stem = f"{args.origin}_{args.year}{args.month}{args.day}_{args.forecast_type}"

    print(f"Dataset : {DATASET}")
    print(f"Area    : N {args.area[0]}  W {args.area[1]}  S {args.area[2]}  E {args.area[3]}")
    print(f"Init    : {args.date} {args.time}  origin={args.origin}  type={args.forecast_type}")
    print(f"Leadtime: {LEADTIME_HOURS[0]} .. {LEADTIME_HOURS[-1]}  ({len(LEADTIME_HOURS)} windows)")
    print(f"Out     : {args.outdir}")
    print(f"Vars    : {keys}\n")

    client = None
    if not args.dry_run:
        import cdsapi
        url = os.environ.get("CDSAPI_URL")
        key = os.environ.get("CDSAPI_KEY")
        client = cdsapi.Client(url=url, key=key) if (url and key) else cdsapi.Client()

    for k in keys:
        cds_name, role = VARIABLES[k]
        target = args.outdir / f"{k}__{stem}.{ext}"
        req = build_request(cds_name, args)
        if args.dry_run:
            print(f"[{k:5}] {cds_name:42} # {role}")
            print(f"        -> {target.name}")
            print(f"        {req}\n")
            continue
        if target.exists() and target.stat().st_size > 0:
            print(f"[{k:5}] exists, skip -> {target.name}")
            continue
        print(f"[{k:5}] {cds_name}  -> {target.name}")
        client.retrieve(DATASET, req).download(str(target))

    if args.dry_run:
        print("DRY RUN — no data downloaded. Populate ~/.cdsapirc (or "
              "CDSAPI_URL/CDSAPI_KEY) and drop --dry-run to fetch.")


if __name__ == "__main__":
    main()
