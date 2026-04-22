#!/usr/bin/env python3
"""
Step 3: Prepare Wflow Forcing File (forcing.nc) for Ethiopia

YEAR-WISE approach to avoid stalls/memory spikes:
- Build one forcing file per year (forcing_2020.nc ... forcing_2023.nc)
- Concatenate into forcing/forcing.nc

Variables:
- precip (mm/day) from CHIRPS GeoTIFFs
- temp (°C) from ERA5 t2m (hourly -> daily mean)
- pet (mm/day) from ERA5 pev (hourly -> daily sum; sign flipped; m -> mm)
"""

import gc
import json
import sys
import time
from datetime import datetime
from glob import glob
from pathlib import Path

import pandas as pd
import rioxarray as rxr
import xarray as xr


def die(msg: str, code: int = 1) -> None:
    print(f"\n✗ {msg}")
    raise SystemExit(code)


print("=" * 70)
print("PREPARE WFLOW FORCING FILE - ETHIOPIA (2020-2023) - YEAR WISE")
print("=" * 70)

# Paths
BASE_DIR = Path(__file__).parent.parent
CHIRPS_DIR = BASE_DIR / "data" / "chirps" / "daily"
ERA5_DIR = BASE_DIR / "data" / "era5"
OUTPUT_DIR = BASE_DIR / "forcing"
OUTPUT_FILE = OUTPUT_DIR / "forcing.nc"
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

ERA5_TEMP = ERA5_DIR / "temperature_2m_2020_2023.nc"
ERA5_PET = ERA5_DIR / "potential_evaporation_2020_2023.nc"

print(f"\nInput directories:")
print(f"  CHIRPS: {CHIRPS_DIR}")
print(f"  ERA5:   {ERA5_DIR}")
print(f"\nOutput file: {OUTPUT_FILE}")

if not ERA5_TEMP.exists() or not ERA5_PET.exists():
    missing = []
    if not ERA5_TEMP.exists():
        missing.append(ERA5_TEMP.name)
    if not ERA5_PET.exists():
        missing.append(ERA5_PET.name)
    die(f"ERA5 files missing: {', '.join(missing)}")

YEARS = [2020, 2021, 2022, 2023]
start_time = time.time()

print("\n[ERA5] Loading daily temperature and PET...")
temp_ds = xr.open_dataset(ERA5_TEMP)
temp = temp_ds["t2m"]
if "time" in temp.dims and "valid_time" in temp.dims:
    temp = temp.isel(time=0).drop_vars("time", errors="ignore")
if "valid_time" in temp.dims:
    temp = temp.rename({"valid_time": "time"})
temp_daily = (temp - 273.15).resample(time="1D").mean()

pet_ds = xr.open_dataset(ERA5_PET)
pet = pet_ds["pev"]
if "time" in pet.dims and "valid_time" in pet.dims:
    pet = pet.isel(time=0).drop_vars("time", errors="ignore")
if "valid_time" in pet.dims:
    pet = pet.rename({"valid_time": "time"})
pet_daily = (-pet * 1000).resample(time="1D").sum()

print(f"  ✓ ERA5 temp daily: {temp_daily.shape}")
print(f"  ✓ ERA5 pet  daily: {pet_daily.shape}")

year_files: list[str] = []

for year in YEARS:
    print("\n" + "=" * 70)
    print(f"PROCESSING YEAR {year}")
    print("=" * 70)

    year_chirps_files = sorted(glob(str(CHIRPS_DIR / f"chirps-v2.0.{year}.*.tif")))
    print(f"CHIRPS files for {year}: {len(year_chirps_files)}")
    if not year_chirps_files:
        die(f"No CHIRPS files found for year {year}")

    # Load CHIRPS for this year only (chunks of 200)
    chunk_size_files = 200
    chirps_chunks = []
    for chunk_start in range(0, len(year_chirps_files), chunk_size_files):
        chunk_end = min(chunk_start + chunk_size_files, len(year_chirps_files))
        chunk_files = year_chirps_files[chunk_start:chunk_end]

        print(
            f"  Loading CHIRPS chunk {chunk_start//chunk_size_files + 1}/"
            f"{(len(year_chirps_files)-1)//chunk_size_files + 1} "
            f"(files {chunk_start+1}-{chunk_end})...",
            flush=True,
        )

        chunk_list = []
        for chirps_file in chunk_files:
            try:
                da = rxr.open_rasterio(chirps_file)
                filename = Path(chirps_file).stem
                ymd = filename.split(".")[-3:]
                date = datetime(int(ymd[0]), int(ymd[1]), int(ymd[2]))
                chunk_list.append(da.squeeze().expand_dims(time=[date]))
            except Exception as e:
                print(f"    ✗ Error reading {Path(chirps_file).name}: {e}")

        if chunk_list:
            chirps_chunks.append(xr.concat(chunk_list, dim="time"))
        del chunk_list

    print("  Concatenating CHIRPS chunks...")
    chirps = xr.concat(chirps_chunks, dim="time")
    del chirps_chunks
    chirps.name = "precip"
    chirps.attrs["units"] = "mm/day"
    chirps.attrs["long_name"] = "Precipitation"
    print(f"  ✓ CHIRPS shape ({year}): {chirps.shape}")

    target_y = chirps.coords["y"]
    target_x = chirps.coords["x"]

    # Subset ERA5 to this year
    temp_y = temp_daily.sel(time=slice(f"{year}-01-01", f"{year}-12-31"))
    pet_y = pet_daily.sel(time=slice(f"{year}-01-01", f"{year}-12-31"))

    # Interpolate ERA5 -> CHIRPS grid in small time chunks
    print("  Interpolating ERA5 to CHIRPS grid (time-chunked)...")
    chunk_days = 31
    temp_chunks = []
    pet_chunks = []
    n_times = len(temp_y.time)
    n_chunks = (n_times - 1) // chunk_days + 1

    for i in range(0, n_times, chunk_days):
        chunk_end = min(i + chunk_days, n_times)
        chunk_idx = i // chunk_days + 1
        print(f"    ERA5 chunk {chunk_idx}/{n_chunks} (days {i+1}-{chunk_end})...", flush=True)

        temp_chunk = temp_y.isel(time=slice(i, chunk_end))
        pet_chunk = pet_y.isel(time=slice(i, chunk_end))

        t_interp = temp_chunk.interp(latitude=target_y, longitude=target_x, method="linear")
        t_interp = t_interp.drop_vars(["y", "x"], errors="ignore")
        t_interp = t_interp.rename({"latitude": "y", "longitude": "x"}).assign_coords(y=target_y, x=target_x)

        p_interp = pet_chunk.interp(latitude=target_y, longitude=target_x, method="linear")
        p_interp = p_interp.drop_vars(["y", "x"], errors="ignore")
        p_interp = p_interp.rename({"latitude": "y", "longitude": "x"}).assign_coords(y=target_y, x=target_x)

        temp_chunks.append(t_interp)
        pet_chunks.append(p_interp)
        del temp_chunk, pet_chunk, t_interp, p_interp

    temp_interp = xr.concat(temp_chunks, dim="time")
    pet_interp = xr.concat(pet_chunks, dim="time")
    del temp_chunks, pet_chunks

    # Align time dimensions for this year
    chirps_times = pd.to_datetime(chirps.time.values)
    temp_times = pd.to_datetime(temp_interp.time.values)
    pet_times = pd.to_datetime(pet_interp.time.values)
    common_start = max(chirps_times.min(), temp_times.min(), pet_times.min())
    common_end = min(chirps_times.max(), temp_times.max(), pet_times.max())

    forcing_y = xr.Dataset(
        {
            "precip": chirps.sel(time=slice(common_start, common_end)),
            "temp": temp_interp.sel(time=slice(common_start, common_end)),
            "pet": pet_interp.sel(time=slice(common_start, common_end)),
        }
    ).rename({"y": "lat", "x": "lon"})

    forcing_y.attrs["title"] = f"Wflow forcing - Ethiopia - {year}"
    forcing_y.attrs["source"] = "CHIRPS v2.0 + ERA5"
    forcing_y.attrs["period"] = f"{forcing_y.time[0].values} to {forcing_y.time[-1].values}"
    forcing_y.attrs["created"] = datetime.now().isoformat()

    out_year = OUTPUT_DIR / f"forcing_{year}.nc"
    print(f"  Saving year file: {out_year}")
    forcing_y.to_netcdf(
        out_year,
        encoding={
            "precip": {"zlib": True, "complevel": 4, "dtype": "float32"},
            "temp": {"zlib": True, "complevel": 4, "dtype": "float32"},
            "pet": {"zlib": True, "complevel": 4, "dtype": "float32"},
        },
    )
    year_files.append(str(out_year))

    # Free memory before next year
    del chirps, temp_interp, pet_interp, forcing_y
    gc.collect()

print("\n" + "=" * 70)
print("COMBINING YEAR FILES")
print("=" * 70)

forcing = xr.open_mfdataset(year_files, combine="by_coords").sortby("time")
print(f"Final combined time steps: {len(forcing.time)}")

print(f"Saving final forcing.nc to: {OUTPUT_FILE}")
forcing.to_netcdf(
    OUTPUT_FILE,
    encoding={
        "precip": {"zlib": True, "complevel": 4, "dtype": "float32"},
        "temp": {"zlib": True, "complevel": 4, "dtype": "float32"},
        "pet": {"zlib": True, "complevel": 4, "dtype": "float32"},
    },
)

elapsed = time.time() - start_time
print("\n" + "=" * 70)
print("FORCING FILE CREATED!")
print("=" * 70)
print(f"✓ Output: {OUTPUT_FILE}")
print(f"✓ Time: {elapsed/60:.1f} minutes")

info_file = OUTPUT_DIR / "forcing_info.json"
info = {
    "output_file": str(OUTPUT_FILE),
    "time_steps": int(len(forcing.time)),
    "spatial_grid": f"{len(forcing.lat)} x {len(forcing.lon)}",
    "period": f"{forcing.time[0].values} to {forcing.time[-1].values}",
    "variables": ["precip (mm/day)", "temp (°C)", "pet (mm/day)"],
    "year_files": [Path(f).name for f in year_files],
    "processing_time_minutes": round(elapsed / 60, 2),
}
with open(info_file, "w") as f:
    json.dump(info, f, indent=2, default=str)
print(f"✓ Info saved: {info_file}")

