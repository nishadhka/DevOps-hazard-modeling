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

Input is the ONE combined GRIB the ECDS front-end produces (all 8 variables,
100 perturbed members). cfgrib splits it into 5 cubes by stepType, which we
aggregate to a common daily axis:

    2t,  2d        stepType=avg     daily means        -> temp, temp_dew  (K->degC)
    mx2t6 / mn2t6  stepType=max/min 6-hourly           -> daily max/min   (K->degC)
    10u, 10v       stepType=instant 6-hourly           -> daily mean      (m/s)
    ssrd           stepType=accum   daily, cumulative  -> daily W/m2 (kin) (diff /86400)
    tp             stepType=accum   6-hourly cumulative -> daily mm/day    (diff *1000)

Pipeline:
  1. open the combined GRIB (cfgrib.open_datasets), reduce the ensemble (mean by
     default), aggregate each variable to daily, convert units, align on dates;
  2. assemble the coarse forcing `ds` with hydromt's expected names/units;
  3. hydromt reprojects ds onto the Malawi `wflow_dem` grid and runs P-M;
  4. write forcing_s2s.nc (precip / temp / pet, dims time,lat,lon) next to the
     ERA5 forcing.nc — a SEPARATE file (the forecast has its own time axis).

Run:
  uv run python mwi/compute_pet.py --self-test           # validate PET engine on synthetic input
  uv run python mwi/compute_pet.py                        # newest *.grib -> forcing_s2s.nc
  uv run python mwi/compute_pet.py --grib mwi/forcing_s2s/s2s_mwi_20260607_pf.grib
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

# GRIB shortName -> (canonical role in `ds`, daily aggregation).
# The combined S2S GRIB is split by cfgrib into cubes per stepType; we pull each
# variable by its shortName and reduce to a daily series.
SHORTNAME = {
    "2t":    ("temp",     "degC"),            # daily-averaged
    "2d":    ("temp_dew", "degC"),            # daily-averaged
    "mx2t6": ("temp_max", "degC_max"),        # 6-hourly -> daily max
    "mn2t6": ("temp_min", "degC_min"),        # 6-hourly -> daily min
    "10u":   ("wind10_u", "mean"),            # 6-hourly -> daily mean
    "10v":   ("wind10_v", "mean"),
    "ssrd":  ("kin",      "deaccum_rad"),     # daily cumulative J/m2 -> W/m2
    "tp":    ("precip",   "deaccum_precip"),  # 6-hourly cumulative m -> mm/day
}


def _dem() -> xr.DataArray:
    sm = xr.open_dataset(STATICMAPS)
    return sm["wflow_dem"].rio.set_spatial_dims(
        x_dim="lon", y_dim="lat").rio.write_crs(4326)


def _ens_time(da: xr.DataArray, ens) -> xr.DataArray:
    """Reduce the ensemble and put valid_time on a 'time' dim; rename lat/lon."""
    if "number" in da.dims:
        da = da.mean("number") if ens == "mean" else da.sel(number=int(ens))
    da = da.assign_coords(time=("step", da["valid_time"].values)).swap_dims({"step": "time"})
    ren = {d: n for d, n in (("latitude", "lat"), ("longitude", "lon")) if d in da.dims}
    da = da.rename(ren)
    # drop scalar coords (heightAboveGround, surface, step, valid_time, number, ...)
    # so vars at different reference heights (2 m temp vs 10 m wind) can combine
    keep = {"time", "lat", "lon"}
    return da.drop_vars([c for c in da.coords if c not in keep], errors="ignore")


def load_s2s(grib: Path, ens="mean") -> xr.Dataset:
    """Open the combined S2S GRIB and return a daily forcing ds on the S2S grid."""
    import cfgrib
    cubes = {}
    for ds in cfgrib.open_datasets(str(grib), backend_kwargs={"indexpath": ""}):
        for v in ds.data_vars:
            cubes[ds[v].attrs.get("GRIB_shortName", v)] = ds[v]
    missing = [s for s in SHORTNAME if s not in cubes]
    if missing:
        raise KeyError(f"{grib} missing shortNames {missing}; found {sorted(cubes)}")

    out = {}
    for sn, (role, agg) in SHORTNAME.items():
        da = _ens_time(cubes[sn], ens)
        if agg == "degC":
            da = da - 273.15
        elif agg == "degC_max":
            da = (da - 273.15).resample(time="1D").max()
        elif agg == "degC_min":
            da = (da - 273.15).resample(time="1D").min()
        elif agg == "mean":
            da = da.resample(time="1D").mean()
        elif agg == "deaccum_rad":          # cumulative J/m2 -> daily-mean W/m2
            da = (da.diff("time") / 86400.0).clip(min=0)
        elif agg == "deaccum_precip":       # cumulative m -> daily mm
            da = (da.diff("time") * 1000.0).resample(time="1D").sum().clip(min=0)
        out[role] = da.assign_coords(time=da["time"].dt.floor("D"))

    ds = xr.Dataset(out).dropna("time", how="any")   # inner-join the daily dates
    for v in ds.data_vars:
        ds[v] = ds[v].rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs(4326)
    return ds


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
    p.add_argument("--grib", type=Path, default=None,
                   help="combined S2S GRIB (default: newest *.grib in forcing_s2s/)")
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

    grib = args.grib
    if grib is None:
        cands = sorted(g for g in S2S.glob("*.grib"))
        if not cands:
            raise SystemExit(f"no *.grib in {S2S} — run download_s2s_forcing.py first")
        grib = cands[-1]
    print(f"GRIB: {grib}")
    ds = load_s2s(grib, ens=args.ens)
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
