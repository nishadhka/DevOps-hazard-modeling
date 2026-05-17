"""Build Wflow forcing.nc per v4 case from the single EDH ERA5 zarr.

Single source: EarthDataHub ERA5 reanalysis-single-levels (hourly, 0.25°,
auth via ~/.netrc + the de_personal token — HTTP Basic, exactly the EDH
documented method). No CHIRPS.

Per case in SELECTED (small bbox first):
  1. read v4 bbox (<iso>_v4.geojson) + event period (region_configs)
  2. subset ERA5 tp/t2m/pev to bbox+period (hourly, lazy/dask)
  3. hourly → daily:
        precip = Σ tp  · 1000           (m  → mm/day)
        temp   = mean(t2m) − 273.15      (K  → °C)
        pet    = −Σ pev · 1000, ≥0       (m  → mm/day, ERA5 pev is negative)
  4. regrid (linear) onto that case's staticmaps lat/lon grid
  5. write /mnt/wflow-secondary/v4_models/<iso>/forcing.nc with the wflow
     names precip / temp / pet, dims (time, lat, lon) == staticmaps grid.

Token lives only in .env / ~/.netrc (both outside git).
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import xarray as xr

REPO = Path(__file__).resolve().parents[2]
V4 = REPO / "shared" / "hydrobasins" / "outputs_v4"
MODELS = Path("/mnt/wflow-secondary/v4_models")
ERA5_URL = ("https://data.earthdatahub.destine.eu/era5/"
            "reanalysis-era5-single-levels-v0.zarr")
PAD = 0.3  # deg, ≥ one ERA5 cell so the bbox is fully covered before interp

sys.path.insert(0, str(REPO))
from region_configs import REGIONS  # noqa: E402

ISO_STEM = {
    "BDI": "01_burundi_bdi_v4",   "DJI": "02_djibouti_dji_v4",
    "ERI": "03_eritrea_eri_v4",   "ETH": "04_ethiopia_eth_v4",
    "KEN": "05_kenya_ken_v4",     "RWA": "06_rwanda_rwa_v4",
    "SOM": "07_somalia_som_v4",   "SSD": "08_south_sudan_ssd_v4",
    "SDN": "09_sudan_sdn_v4",     "TZA": "10_tanzania_tza_v4",
    "UGA": "11_uganda_uga_v4",
}
PERIOD = {c["country_iso"]: (c["start"], c["end"]) for c in REGIONS.values()}
SELECTED = ["BDI", "ERI", "DJI", "RWA", "TZA", "UGA",
            "KEN", "SDN", "ETH", "SSD", "SOM"]


def open_era5() -> xr.Dataset:
    ds = xr.open_dataset(
        ERA5_URL, storage_options={"client_kwargs": {"trust_env": True}},
        chunks={}, engine="zarr")
    return ds.rename({"valid_time": "time"})


def build_case(iso: str, era5: xr.Dataset) -> None:
    stem = ISO_STEM[iso]
    w, s, e, n = gpd.read_file(V4 / f"{stem}.geojson").total_bounds
    start, end = PERIOD[iso]
    out_dir = MODELS / iso.lower()
    sm = xr.open_dataset(out_dir / "staticmaps.nc")
    sm_lat, sm_lon = sm["lat"], sm["lon"]

    # ERA5: latitude 90→-90 (desc), longitude 0→359.75
    sub = era5[["tp", "t2m", "pev"]].sel(
        time=slice(start, f"{end}T23:59"),
        latitude=slice(n + PAD, s - PAD),
        longitude=slice(w - PAD, e + PAD),
    )
    if sub["time"].size == 0:
        print(f"  [{iso}] no ERA5 in {start}..{end}, skip"); return

    daily = xr.Dataset()
    daily["precip"] = sub["tp"].resample(time="1D").sum() * 1000.0
    daily["temp"] = sub["t2m"].resample(time="1D").mean() - 273.15
    daily["pet"] = (-sub["pev"].resample(time="1D").sum() * 1000.0).clip(min=0)
    # ascending coords for interp
    daily = daily.sortby("latitude").sortby("longitude").load()

    forcing = daily.interp(
        latitude=sm_lat.values, longitude=sm_lon.values, method="linear"
    ).rename({"latitude": "lat", "longitude": "lon"})
    forcing = forcing.assign_coords(lat=sm_lat.values, lon=sm_lon.values)
    for v in ("precip", "temp", "pet"):
        forcing[v] = forcing[v].astype("float32")
    forcing["precip"].attrs = {"units": "mm", "long_name": "precipitation"}
    forcing["temp"].attrs = {"units": "degree C", "long_name": "temperature"}
    forcing["pet"].attrs = {"units": "mm",
                            "long_name": "potential evaporation"}
    forcing.attrs = {"source": "EarthDataHub ERA5 single-levels v0",
                     "case": iso, "period": f"{start}/{end}"}

    fp = out_dir / "forcing.nc"
    enc = {v: {"zlib": True, "complevel": 1} for v in
           ("precip", "temp", "pet")}
    forcing.to_netcdf(fp, encoding=enc)
    nt = forcing["time"].size
    print(f"  [{iso}] forcing.nc  {nt} days  "
          f"{forcing.sizes['lat']}×{forcing.sizes['lon']}  "
          f"{fp.stat().st_size/1e6:.0f} MB  "
          f"P[{float(forcing.precip.mean()):.1f}mm] "
          f"T[{float(forcing.temp.mean()):.1f}°C] "
          f"PET[{float(forcing.pet.mean()):.1f}mm]")


if __name__ == "__main__":
    print("Opening EDH ERA5 ...")
    era5 = open_era5()
    print(f"ERA5 {era5.time.values[0]} .. {era5.time.values[-1]} | "
          f"Selected: {SELECTED}")
    for iso in SELECTED:
        sm = MODELS / iso.lower() / "staticmaps.nc"
        if not sm.exists():
            print(f"  [{iso}] no staticmaps.nc — skip"); continue
        if (MODELS / iso.lower() / "forcing.nc").exists():
            print(f"  [{iso}] forcing.nc exists — skip"); continue
        try:
            build_case(iso, era5)
        except Exception as ex:
            print(f"  [{iso}] FAILED: {type(ex).__name__}: {str(ex)[:160]}")
    print("Done.")
