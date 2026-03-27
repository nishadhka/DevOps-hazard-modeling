#!/usr/bin/env python3
"""
run_v15_setup.py — RIM2D v15 boundary and DEM preparation
===========================================================
Changes from v14:
  Fix 5a: DEM-based Nile channel burn
           All cells with MERIT dem < NILE_THRESH (301m) → burned to NILE_TARGET (294m)
           Closes the TDX-Hydro coverage gap across cols ~130-306 (Nile meander bend)
  Fix 5b: Railway crossing burn
           At the ~302m ridge (rows 78-92) where drainage crosses the railway embankment,
           apply an extra -RAILWAY_BURN_M burn on top of the v13 TDX-Hydro burns

All other settings inherited from v14:
  - WSE cap sill+1.5m (v12)
  - 4th inflow HospitalWadi (v12)
  - TDX-Hydro Order-2/5/9 stream burns (v13)
  - IMERG symlinks for Aug 25-31 window (v14)

Usage:
    cd /data/rim2d/nile_highres/v15
    micromamba run -n zarrv3 python run_v15_setup.py
"""

import json
import os
import shutil
from pathlib import Path

import netCDF4
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────
WORK_DIR  = Path("/data/rim2d/nile_highres")
V10_DIR   = WORK_DIR / "v10"
V13_DIR   = WORK_DIR / "v13"     # source of TDX-Hydro burned DEM
V14_DIR   = WORK_DIR / "v14"
V15_DIR   = WORK_DIR / "v15"
V15_INPUT = V15_DIR / "input"

# ── DEM burn parameters ────────────────────────────────────────────────────
NILE_THRESH      = 301.0    # cells below this = Nile floodplain
NILE_TARGET_ELEV = 294.0    # burn target (Nile low-water elevation estimate)

RAILWAY_ROW_MIN  = 78       # row band where railway embankment sits
RAILWAY_ROW_MAX  = 92       # (between settlement and Nile floodplain)
RAILWAY_BURN_M   = 5.0      # extra burn at stream crossing points within railway band

# ── Inflow / simulation parameters (unchanged from v14) ───────────────────
SIM_DUR    = 518_400    # 6 days (Aug 25-31)
DT_INFLOW  = 1800       # 30 min
N_RAIN     = SIM_DUR // DT_INFLOW       # 288 IMERG files
N_WSE      = SIM_DUR // DT_INFLOW + 1  # 289 WSE timesteps (inclusive of t=0 and t=SIM_DUR)
IMERG_START_STEP = 1488              # offset into full IMERG (t1489 = Aug 25 00:00 UTC)
WSE_CAP_M  = 1.5        # max depth above sill at any inflow cell


# ── Manning bisection for culvert WSE ─────────────────────────────────────
def culvert_full_flow(w, h, n, s):
    """Full-pipe Manning discharge (m³/s)."""
    A = w * h
    P = 2 * (w + h)
    R = A / P
    return (1 / n) * A * R ** (2 / 3) * s ** 0.5


def manning_depth(q, w, n, s, tol=1e-4, max_iter=50):
    """Bisection: normal depth for open-channel Manning."""
    lo, hi = 1e-4, 20.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        A = w * mid
        P = w + 2 * mid
        R = A / P
        q_mid = (1 / n) * A * R ** (2 / 3) * s ** 0.5
        if q_mid < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


def flow_to_wse_capped(q, sill_elev, w, h, n, s):
    """WSE from flow, capped at sill + WSE_CAP_M."""
    q_full = culvert_full_flow(w, h, n, s)
    if q <= 1e-9:
        return sill_elev
    if q <= q_full:
        depth = manning_depth(q, w, n, s)
    else:
        depth = WSE_CAP_M
    return sill_elev + min(depth, WSE_CAP_M)


def flow_to_wse_wadi(q, bed_elev, w=20.0, n=0.035, s=0.005):
    """Open-channel wadi WSE, capped at bed + WSE_CAP_M."""
    if q <= 1e-9:
        return bed_elev
    depth = manning_depth(q, w, n, s)
    return bed_elev + min(depth, WSE_CAP_M)


# ── Rational method / unit hydrograph (same as v12-v14) ───────────────────
def compute_tc_hours(area_km2):
    """Kirpich time of concentration (hours)."""
    return 0.0195 * (area_km2 * 1e6 / 1e4) ** 0.385 / 60

def triangular_uh(tc_hours, dt_hours=0.5):
    """Triangular unit hydrograph, normalised to unit area."""
    tp = tc_hours
    tb = 2.67 * tp
    steps = int(np.ceil(tb / dt_hours)) + 1
    t = np.arange(steps) * dt_hours
    uh = np.where(
        t <= tp,
        t / tp,
        np.where(t <= tb, (tb - t) / (tb - tp), 0.0),
    )
    uh_sum = np.sum(uh) * dt_hours
    return uh / uh_sum if uh_sum > 0 else uh

def rational_method_hydrograph(rain_mm_per_hr, catchment_m2, runoff_coeff, uh, dt_s=1800):
    """Convolve rainfall with UH to get discharge (m³/s)."""
    dt_hr = dt_s / 3600.0
    q_eff = rain_mm_per_hr / 1000.0 / 3600.0 * runoff_coeff * catchment_m2  # m³/s per step
    n = len(rain_mm_per_hr)
    q = np.convolve(q_eff, uh)[:n]
    return np.maximum(q, 0.0)


# ── Step 1: Build v15 DEM (Nile floodplain burn + railway burn) ────────────
def build_dem_v15():
    print("=" * 60)
    print("Step 1: Building v15 DEM")
    print("=" * 60)

    # Start from v13 stream-burned DEM (has TDX-Hydro burns already)
    src_dem = V13_DIR / "input" / "dem_v13.nc"
    print(f"  Base DEM: {src_dem}")

    ds_in  = netCDF4.Dataset(str(src_dem))
    x_arr  = np.array(ds_in["x"][:], dtype=np.float64)
    y_arr  = np.array(ds_in["y"][:], dtype=np.float64)
    dem    = np.array(ds_in["Band1"][:], dtype=np.float32).squeeze()
    ds_in.close()

    dem_v10_path = V10_DIR / "input" / "dem.nc"
    ds_v10 = netCDF4.Dataset(str(dem_v10_path))
    dem_orig = np.array(ds_v10["Band1"][:], dtype=np.float32).squeeze()
    ds_v10.close()

    dem_v15 = dem.copy()

    # Fix 5a: burn all Nile floodplain cells (orig dem < NILE_THRESH) to NILE_TARGET
    nile_mask = dem_orig < NILE_THRESH
    n_nile = int(nile_mask.sum())
    dem_v15[nile_mask] = NILE_TARGET_ELEV
    print(f"  Fix 5a: {n_nile} Nile floodplain cells (dem<{NILE_THRESH}m) → {NILE_TARGET_ELEV}m")

    # Fix 5b: railway crossing burn — extra -RAILWAY_BURN_M in the embankment row band
    # only where v13 already has TDX-Hydro stream burns (dem_v13 < dem_orig)
    railway_band = np.zeros_like(nile_mask, dtype=bool)
    railway_band[RAILWAY_ROW_MIN:RAILWAY_ROW_MAX + 1, :] = True
    stream_burned = dem < dem_orig   # cells v13 already burned
    railway_crossing = railway_band & stream_burned & ~nile_mask
    n_rail = int(railway_crossing.sum())
    dem_v15[railway_crossing] -= RAILWAY_BURN_M
    print(f"  Fix 5b: {n_rail} railway crossing cells (rows {RAILWAY_ROW_MIN}-{RAILWAY_ROW_MAX}, "
          f"already burned) lowered by extra {RAILWAY_BURN_M}m")

    total_burned = int(np.sum(dem_v15 < dem_orig))
    print(f"  Total cells modified from original v10 DEM: {total_burned}")

    # Save
    out_path = V15_INPUT / "dem_v15.nc"
    ds_out = netCDF4.Dataset(str(out_path), "w", format="NETCDF4")
    ds_out.createDimension("x", len(x_arr))
    ds_out.createDimension("y", len(y_arr))
    xv = ds_out.createVariable("x", "f8", ("x",))
    yv = ds_out.createVariable("y", "f8", ("y",))
    bv = ds_out.createVariable("Band1", "f4", ("y", "x"))
    xv[:] = x_arr;  xv.long_name = "x coordinate";  xv.units = "m"
    yv[:] = y_arr;  yv.long_name = "y coordinate";  yv.units = "m"
    bv[:] = dem_v15
    bv.long_name = "elevation";  bv.units = "m"
    ds_out.Conventions = "CF-1.5"
    ds_out.description = (
        f"v15 DEM: v13 TDX-Hydro burns + "
        f"Nile floodplain burn (dem<{NILE_THRESH}m→{NILE_TARGET_ELEV}m) + "
        f"railway crossing burn rows {RAILWAY_ROW_MIN}-{RAILWAY_ROW_MAX} extra -{RAILWAY_BURN_M}m"
    )
    ds_out.close()
    print(f"  Saved: {out_path}")
    return dem_v15, x_arr, y_arr


# ── Step 2: Copy boundary mask and inflow locs from v14 ───────────────────
def copy_boundary_files():
    print("\nStep 2: Copying boundary files from v14")
    for fname in ["fluvbound_mask_v14.nc", "inflowlocs_v14.txt"]:
        src = V14_DIR / "input" / fname
        dst_name = fname.replace("v14", "v15")
        dst = V15_INPUT / dst_name
        shutil.copy2(src, dst)
        print(f"  Copied {fname} → {dst_name}")


# ── Step 3: Symlink IMERG rain files (identical to v14) ───────────────────
def setup_rain_symlinks():
    rain_dir = V15_INPUT / "rain"
    existing = list(rain_dir.glob("imerg_v15_t*.nc"))
    if len(existing) == N_RAIN:
        print(f"\nStep 3: {N_RAIN} rain symlinks already exist — skipping")
        return

    print(f"\nStep 3: Creating {N_RAIN} IMERG symlinks (Aug 25-31)")
    src_rain = V10_DIR / "input" / "rain"
    for i in range(1, N_RAIN + 1):
        src_t = IMERG_START_STEP + i
        src   = src_rain / f"imerg_v10_t{src_t}.nc"
        dst   = rain_dir / f"imerg_v15_t{i}.nc"
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
    # Verify first and last
    t1   = rain_dir / "imerg_v15_t1.nc"
    t288 = rain_dir / f"imerg_v15_t{N_RAIN}.nc"
    print(f"  t1   → {os.readlink(t1)}")
    print(f"  t{N_RAIN} → {os.readlink(t288)}")


# ── Step 4: Load cached hydrographs and regenerate inflowlocs_v15.txt ──────
def regenerate_inflowlocs():
    """
    Re-generate inflowlocs_v15.txt from the v12 NPZ cache using the 6-day
    IMERG window.  The WSE values are identical to v14; only the filename
    suffix changes (v14 → v15).
    """
    print("\nStep 4: Re-generating inflowlocs_v15.txt from v12 NPZ cache")

    npz_path = WORK_DIR / "v12" / "input" / "culvert_hydrographs_v12.npz"
    data = np.load(str(npz_path))

    # Hardcoded inflow definitions (row/col 0-indexed; sill = DEM elev at cell)
    # Sill values read from first WSE entry in inflowlocs_v14.txt (Q=0 baseline)
    INFLOW_DEFS = {
        "Culvert1":    {"row": 212, "col": 312, "sill": 321.105},
        "Culvert2":    {"row": 222, "col": 266, "sill": 320.012},
        "WesternWadi": {"row": 222, "col": 175, "sill": 318.855},
        "HospitalWadi":{"row": 183, "col": 281, "sill": 316.134},
    }

    # Culvert parameters (same as v12-v14)
    CULVERT_W = 4.0; CULVERT_H = 2.5; CULVERT_N = 0.013; CULVERT_S = 0.005

    # Hydrograph arrays (trim to 6-day window starting at IMERG_START_STEP)
    def trim(arr):
        # Take N_WSE=289 steps starting at IMERG_START_STEP
        return arr[IMERG_START_STEP: IMERG_START_STEP + N_WSE]

    q_c1   = trim(data["q_Culvert1"])
    q_c2   = trim(data["q_Culvert2"])
    q_west = trim(data["q_WesternWadi"])
    q_hw   = trim(data["q_HospitalWadi"])

    def pad(arr):
        if len(arr) < N_WSE:
            arr = np.concatenate([arr, np.full(N_WSE - len(arr), arr[-1])])
        return arr[:N_WSE]

    q_c1   = pad(q_c1);   q_c2 = pad(q_c2)
    q_west = pad(q_west); q_hw = pad(q_hw)

    sill_c1   = INFLOW_DEFS["Culvert1"]["sill"]
    sill_c2   = INFLOW_DEFS["Culvert2"]["sill"]
    sill_west = INFLOW_DEFS["WesternWadi"]["sill"]
    sill_hw   = INFLOW_DEFS["HospitalWadi"]["sill"]

    row_c1, col_c1     = INFLOW_DEFS["Culvert1"]["row"],     INFLOW_DEFS["Culvert1"]["col"]
    row_c2, col_c2     = INFLOW_DEFS["Culvert2"]["row"],     INFLOW_DEFS["Culvert2"]["col"]
    row_west, col_west = INFLOW_DEFS["WesternWadi"]["row"],  INFLOW_DEFS["WesternWadi"]["col"]
    row_hw, col_hw     = INFLOW_DEFS["HospitalWadi"]["row"], INFLOW_DEFS["HospitalWadi"]["col"]

    wse_c1   = [flow_to_wse_capped(q, sill_c1, CULVERT_W, CULVERT_H, CULVERT_N, CULVERT_S)
                for q in q_c1]
    wse_c2   = [flow_to_wse_capped(q, sill_c2, CULVERT_W, CULVERT_H, CULVERT_N, CULVERT_S)
                for q in q_c2]
    wse_west = [flow_to_wse_wadi(q, sill_west) for q in q_west]
    wse_hw   = [flow_to_wse_wadi(q, sill_hw)   for q in q_hw]

    # Write inflowlocs_v15.txt
    out_path = V15_INPUT / "inflowlocs_v15.txt"
    with open(out_path, "w") as f:
        f.write(f"{SIM_DUR}\n{DT_INFLOW}\n4\n")
        for (row, col), wse_arr, name in [
            ((row_c1,   col_c1),   wse_c1,   "Culvert1"),
            ((row_c2,   col_c2),   wse_c2,   "Culvert2"),
            ((row_west, col_west), wse_west, "WesternWadi"),
            ((row_hw,   col_hw),   wse_hw,   "HospitalWadi"),
        ]:
            vals = " ".join(f"{v:.3f}" for v in wse_arr)
            # RIM2D uses 1-based row/col
            f.write(f"{row + 1}\t{col + 1}\t{vals}\n")
            peak = max(wse_arr)
            print(f"  {name}: peak WSE = {peak:.2f}m")

    print(f"  Saved: {out_path}")


# ── Step 5: Write simulation_v15.def ──────────────────────────────────────
def write_def_file():
    print("\nStep 5: Writing simulation_v15.def")

    out_times = " ".join(str(t) for t in range(21600, SIM_DUR + 1, 21600))
    n_out = len(out_times.split())

    content = f"""# RIM2D model definition file (version 2.0)
# Nile high-resolution — v15
# Fix 1 (v12): WSE capped at sill + 1.5m
# Fix 2 (v12): 4th inflow — HospitalWadi (5 km²)
# Fix 3 (v13): DEM stream burning — TDX-Hydro channels carved into DEM
# Fix 4 (v14): Correct IMERG window — Aug 25-31 symlinked as t1-t288
# Fix 5a (v15): DEM-based Nile floodplain burn (all dem<301m → 294m)
# Fix 5b (v15): Railway crossing burn (rows {RAILWAY_ROW_MIN}-{RAILWAY_ROW_MAX}, extra -{RAILWAY_BURN_M}m)

###### INPUT RASTERS ######
**DEM**
input/dem_v15.nc
**buildings**
../v10/input/buildings.nc
**IWD**
file
../v10/input/iwd.nc
**roughness**
file
../v10/input/roughness.nc
**pervious_surface**
../v10/input/pervious_surface.nc
**sealed_surface**
../v10/input/sealed_surface.nc
**sewershed**
../v10/input/sewershed_v10_full.nc

###### BOUNDARIES ######
**fluvial_boundary**
input/inflowlocs_v15.txt

# RAINFALL — 6-day peak window (Aug 25-31)
# Symlinks: imerg_v15_t1 = original t{IMERG_START_STEP + 1}, t{N_RAIN} = original t{IMERG_START_STEP + N_RAIN}
**pluvial_raster_nr**
{N_RAIN}
**pluvial_dt**
{DT_INFLOW}
**pluvial_start**
0
**pluvial_base_fn**
input/rain/imerg_v15_t

###### OUTPUT ######
**output_base_fn**
output/nile_v15_
**out_cells**
../v10/input/outflowlocs.txt
**out_timing_nr**
{n_out}
**out_timing**
{out_times}

###### MODEL PARAMETERS ######
**dt**
1
**sim_dur**
{SIM_DUR}
**inf_rate**
0
**sewer_cap**
0
**sewer_threshold**
0.002
**alpha**
0.4
**theta**
0.8

###### FLAGS ######
**verbose**
.TRUE.
**routing**
.TRUE.
**superverbose**
.FALSE.
**neg_wd_corr**
.TRUE.
**sew_sub**
.FALSE.
none
**fluv_bound**
.TRUE.
input/fluvbound_mask_v15.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    out_path = V15_DIR / "simulation_v15.def"
    out_path.write_text(content)
    print(f"  Saved: {out_path}")


# ── Step 6: Save metadata ──────────────────────────────────────────────────
def save_metadata(dem_v15, x_arr, y_arr):
    print("\nStep 6: Saving metadata")
    dem_orig = np.array(
        netCDF4.Dataset(str(V10_DIR / "input" / "dem.nc"))["Band1"][:],
        dtype=np.float32
    ).squeeze()
    nile_mask = dem_orig < NILE_THRESH

    meta = {
        "version": "v15",
        "sim_dur_s": SIM_DUR,
        "dt_inflow_s": DT_INFLOW,
        "n_rain_steps": N_RAIN,
        "imerg_start_step": IMERG_START_STEP,
        "wse_cap_m": WSE_CAP_M,
        "dem_fixes": {
            "base": "v13 TDX-Hydro burned DEM",
            "fix_5a_nile_thresh_m": NILE_THRESH,
            "fix_5a_nile_target_m": NILE_TARGET_ELEV,
            "fix_5a_cells_burned": int(nile_mask.sum()),
            "fix_5b_railway_row_min": RAILWAY_ROW_MIN,
            "fix_5b_railway_row_max": RAILWAY_ROW_MAX,
            "fix_5b_extra_burn_m": RAILWAY_BURN_M,
        },
        "inflow_cells": [
            {"name": "Culvert1",     "row": 212, "col": 312},
            {"name": "Culvert2",     "row": 222, "col": 266},
            {"name": "WesternWadi",  "row": 222, "col": 175},
            {"name": "HospitalWadi", "row": 183, "col": 281},
        ],
    }
    out_path = V15_INPUT / "v15_metadata.json"
    with open(out_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Saved: {out_path}")


# ── Main ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("RIM2D v15 Setup")
    print("=" * 60)

    dem_v15, x_arr, y_arr = build_dem_v15()
    copy_boundary_files()
    setup_rain_symlinks()
    regenerate_inflowlocs()
    write_def_file()
    save_metadata(dem_v15, x_arr, y_arr)

    print("\n" + "=" * 60)
    print("Setup complete. To run simulation:")
    print("  cd /data/rim2d/nile_highres/v15")
    print("  export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH")
    print("  /data/rim2d/bin/RIM2D simulation_v15.def --def flex")
    print("=" * 60)
