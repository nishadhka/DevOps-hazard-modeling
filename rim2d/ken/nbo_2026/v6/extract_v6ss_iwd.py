#!/usr/bin/env python3
"""
Extract final steady-state water depth as iwd.nc.

Reads the last water-depth output from v6/output/nbo_v6ss_wd_*.nc
and writes it as input/iwd_ss.nc — the equilibrated IWD for the
v6 event simulation.

Usage:
    cd /data/rim2d/nbo_2026/v6
    micromamba run -n zarrv3 python extract_v6ss_iwd.py
"""

import glob, re, shutil
from pathlib import Path
import netCDF4
import numpy as np

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
INPUT_DIR  = Path(__file__).resolve().parent / "input"

def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    var = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[var][:], dtype=np.float32)
    ds.close()
    data[data < -9000] = np.nan
    return data, x, y

def write_nc(data, x, y, path):
    fill = np.float32(-9999.0)
    arr  = np.where(np.isnan(data), fill, data).astype(np.float32)
    ds = netCDF4.Dataset(str(path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.history = "Steady-state equilibrated IWD — from v6 pre-run final timestep"
    ds.createDimension("x", arr.shape[1])
    ds.createDimension("y", arr.shape[0])
    xv = ds.createVariable("x", "f8", ("x",)); xv[:] = x
    xv.units = "m"; xv.standard_name = "projection_x_coordinate"
    yv = ds.createVariable("y", "f8", ("y",)); yv[:] = y
    yv.units = "m"; yv.standard_name = "projection_y_coordinate"
    bv = ds.createVariable("Band1", "f4", ("y", "x"), fill_value=fill)
    bv[:] = arr
    ds.close()

# Find all water depth output files
wd_files = sorted(
    [p for p in glob.glob(str(OUTPUT_DIR / "nbo_v6ss_wd_*.nc"))
     if re.search(r"nbo_v6ss_wd_\d+\.nc$", Path(p).name)],
    key=lambda p: int(re.search(r"nbo_v6ss_wd_(\d+)\.nc", Path(p).name).group(1))
)

if not wd_files:
    print("No output files found in v6/output/. Run the simulation first.")
    exit(1)

final_file = wd_files[-1]
t_sec = int(re.search(r"nbo_v6ss_wd_(\d+)\.nc", Path(final_file).name).group(1))
print(f"Found {len(wd_files)} output timesteps")
print(f"Final timestep: {Path(final_file).name}  (t={t_sec}s = {t_sec/3600:.1f}h)")

wd, x, y = load_nc(final_file)
wd = np.where(wd < 0, 0.0, wd)   # clip negatives
wd = np.where(~np.isfinite(wd), 0.0, wd)

wet = wd > 0.001
print(f"Final wet cells : {wet.sum():,}")
print(f"IWD range       : {wd[wet].min():.3f} – {wd[wet].max():.3f} m")
print(f"IWD mean (wet)  : {wd[wet].mean():.3f} m")

# Backup original geometric IWD
orig = INPUT_DIR / "iwd.nc"
backup = INPUT_DIR / "iwd_geometric.nc"
if orig.exists() and not backup.exists():
    shutil.copy2(str(orig), str(backup))
    print(f"Backed up original IWD → {backup.name}")

# Write equilibrated IWD
out_ss  = INPUT_DIR / "iwd_ss.nc"
write_nc(wd, x, y, out_ss)
print(f"Written: {out_ss}")
print()
print("To use this as IWD for the event run, update simulation_v6.def:")
print("  **IWD**")
print("  file")
print("  input/iwd_ss.nc")
