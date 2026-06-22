"""Compute reference PET (Penman-Monteith FAO-56) from the S2S GRIBs using
hydromt, and write a wflow forcing file on the Malawi staticmaps grid.

This is step 2 after `download_s2s_forcing.py`. The PET engine is
`hydromt.workflows.forcing.pet(method="penman-monteith_tdew")` — the exact
routine `hydromt_wflow.WflowModel.setup_temp_pet_forcing` calls under the hood
(needs `pyet`). Penman-Monteith inputs map to the downloaded S2S variables:

    Tmean      <- 2t      (temp)
    Tmax/Tmin  <- mx2t/mn2t
    Tdew       <- 2d      (humidity)
    wind       <- 10u/10v
    shortwave  <- ssrd    (kin, W m-2)
    pressure   <- derived from the DEM elevation (FAO-56 standard, via pyet)
    precip     <- tp      (carried through to the forcing, mm/day)

Pipeline:
  1. load each per-variable S2S GRIB (cfgrib), reduce the ensemble (mean by
     default), deaccumulate fluxes, convert units, build a daily time axis;
  2. assemble the coarse forcing `ds` with hydromt's expected names/units;
  3. hydromt reprojects ds onto the Malawi `wflow_dem` grid and runs P-M;
  4. write forcing_s2s.nc (precip / temp / pet, dims time,lat,lon) next to the
     ERA5 forcing.nc — a SEPARATE file (the forecast has its own time axis).

NOTE: the PET computation (steps 2-4) is validated; run `--self-test` to prove
it on synthetic input + the real DEM. The GRIB reader (step 1) follows the
files written by download_s2s_forcing.py and the standard cfgrib decoding;
confirm its unit/accumulation handling against the first real download
(--accum-mode, the K->degC / J->W / m->mm conversions below).

Run:
  uv run python mwi/compute_pet.py --self-test           # validate PET engine now
  uv run python mwi/compute_pet.py                        # real S2S GRIBs -> forcing_s2s.nc
  uv run python mwi/compute_pet.py --ens 0                # use member 0 instead of ens-mean
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from hydromt.workflows import forcing as F

HERE = Path(__file__).resolve().parent
S2S = HERE / "forcing_s2s"
MODEL = Path("/mnt/wflow-secondary/v4_models/mwi")
STATICMAPS = MODEL / "staticmaps.nc"

# our file key (from download_s2s_forcing.py) -> canonical role in `ds`
# units handled in _to_units().
KEY_ROLE = {
    "2t": "temp", "mx2t": "temp_max", "mn2t": "temp_min", "2d": "temp_dew",
    "10u": "wind10_u", "10v": "wind10_v", "ssrd": "kin", "tp": "precip",
}


def _dem() -> xr.DataArray:
    sm = xr.open_dataset(STATICMAPS)
    return sm["wflow_dem"].rio.set_spatial_dims(
        x_dim="lon", y_dim="lat").rio.write_crs(4326)


def _open_grib(key: str, ens) -> xr.DataArray:
    """Open the per-variable S2S GRIB, reduce ensemble, return (time,lat,lon)."""
    matches = sorted(S2S.glob(f"{key}__*.grib"))
    if not matches:
        raise FileNotFoundError(f"no {key}__*.grib in {S2S} — run download_s2s_forcing.py")
    ds = xr.open_dataset(matches[-1], engine="cfgrib",
                         backend_kwargs={"indexpath": ""})
    da = ds[list(ds.data_vars)[0]]
    if "number" in da.dims:                       # perturbed-forecast ensemble
        da = da.mean("number") if ens == "mean" else da.sel(number=int(ens))
    # build daily time axis from the forecast step / valid_time
    if "valid_time" in da.coords:
        da = da.rename({"step": "time"}) if "step" in da.dims else da
        da = da.assign_coords(time=("time", pd.to_datetime(da["valid_time"].values)))
    elif "step" in da.dims:
        t0 = pd.to_datetime(np.atleast_1d(da["time"].values)[0])
        da = da.assign_coords(time=("step", t0 + pd.to_timedelta(da["step"].values)))
        da = da.swap_dims({"step": "time"})
    ren = {d: n for d, n in (("latitude", "lat"), ("longitude", "lon")) if d in da.dims}
    da = da.rename(ren)
    return da.rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs(4326)


def _to_units(key: str, da: xr.DataArray, accum_mode: str) -> xr.DataArray:
    """K->degC, accumulated J m-2 -> W m-2, accumulated m -> mm/day."""
    if accum_mode == "cumulative" and key in ("ssrd", "tp"):
        da = da.diff("time")                       # deaccumulate cumulative fields
    if key in ("2t", "mx2t", "mn2t", "2d"):
        return da - 273.15                         # K -> degC
    if key == "ssrd":
        return (da / 86400.0).clip(min=0)          # J m-2 per 24h -> W m-2
    if key == "tp":
        return (da * 1000.0).clip(min=0)           # m per 24h -> mm/day
    return da                                      # winds: m/s, unchanged


def load_s2s(ens="mean", accum_mode="window") -> xr.Dataset:
    ds = xr.Dataset()
    for key, role in KEY_ROLE.items():
        ds[role] = _to_units(key, _open_grib(key, ens), accum_mode)
    # align all on the common (intersected) daily time axis
    return ds.dropna("time", how="all")


def compute_pet(ds: xr.Dataset, dem: xr.DataArray) -> xr.DataArray:
    """hydromt Penman-Monteith (tdew). Pressure derived from DEM (pyet)."""
    for v in ds.data_vars:
        ds[v] = ds[v].rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs(4326)
    temp_model = ds[["temp", "temp_max", "temp_min"]].raster.reproject_like(
        dem, method="nearest_index")
    pet = F.pet(ds, temp=temp_model, dem_model=dem, method="penman-monteith_tdew",
                press_correction=False, wind_correction=True, wind_altitude=10)
    return pet.compute()


def _synthetic_ds() -> xr.Dataset:
    lat = np.arange(25, -17.5 - 0.01, -1.5)
    lon = np.arange(20, 53 + 0.01, 1.5)
    time = pd.date_range("2026-05-01", periods=10, freq="D")
    sh = (time.size, lat.size, lon.size)
    rng = np.random.default_rng(0)

    def da(v):
        return xr.DataArray(v, coords={"time": time, "lat": lat, "lon": lon},
                            dims=("time", "lat", "lon"))
    t = da(25 + rng.normal(0, 2, sh))
    return xr.Dataset(dict(
        temp=t, temp_max=t + 6, temp_min=t - 5, temp_dew=t - 8,
        wind10_u=da(rng.normal(0, 2, sh)), wind10_v=da(rng.normal(0, 2, sh)),
        kin=da(220 + rng.normal(0, 30, sh)).clip(0),
        precip=da(rng.gamma(1.0, 3.0, sh)),
    ))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--self-test", action="store_true",
                   help="run the PET engine on synthetic input + real DEM, then exit")
    p.add_argument("--ens", default="mean",
                   help="'mean' (ensemble mean, default) or a member number")
    p.add_argument("--accum-mode", default="window", choices=["window", "cumulative"],
                   help="are ssrd/tp per-window (default) or cumulative-from-start?")
    p.add_argument("--out", type=Path, default=MODEL / "forcing_s2s.nc")
    args = p.parse_args()

    dem = _dem()
    print(f"DEM grid {dict(dem.sizes)}  elev {float(dem.min()):.0f}..{float(dem.max()):.0f} m")

    if args.self_test:
        ds = _synthetic_ds()
        pet = compute_pet(ds, dem)
        print(f"[self-test] PET {dict(pet.sizes)}  "
              f"mm/day min/mean/max = {float(pet.min()):.2f} / "
              f"{float(pet.mean()):.2f} / {float(pet.max()):.2f}")
        print("[self-test] OK — hydromt penman-monteith_tdew runs on the Malawi grid.")
        return

    ds = load_s2s(ens=args.ens, accum_mode=args.accum_mode)
    print(f"S2S loaded: {ds.time.size} days  {dict(ds.sizes)}  vars {list(ds.data_vars)}")
    pet = compute_pet(ds, dem)

    # precip + temp on the model grid, to write a complete wflow forcing
    precip = ds[["precip"]].raster.reproject_like(dem, method="nearest_index")["precip"]
    temp = ds[["temp"]].raster.reproject_like(dem, method="nearest_index")["temp"]

    out = xr.Dataset({"precip": precip, "temp": temp, "pet": pet})
    for v in out.data_vars:
        out[v] = out[v].astype("float32")
    out["precip"].attrs = {"units": "mm", "long_name": "precipitation"}
    out["temp"].attrs = {"units": "degree C", "long_name": "temperature"}
    out["pet"].attrs = {"units": "mm", "long_name": "potential evaporation (Penman-Monteith FAO-56)"}
    out.attrs = {"source": "ECMWF S2S forecast (ECDS s2s-forecasts)",
                 "pet_method": "hydromt penman-monteith_tdew (pyet)",
                 "domain": "Malawi v4 staticmaps grid"}
    enc = {v: {"zlib": True, "complevel": 1} for v in out.data_vars}
    out.to_netcdf(args.out, encoding=enc)
    print(f"wrote {args.out}  ({args.out.stat().st_size/1e6:.0f} MB)  "
          f"P[{float(out.precip.mean()):.1f}mm] T[{float(out.temp.mean()):.1f}C] "
          f"PET[{float(out.pet.mean()):.1f}mm]")


if __name__ == "__main__":
    main()
