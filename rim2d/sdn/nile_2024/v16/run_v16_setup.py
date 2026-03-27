#!/usr/bin/env python3
"""
RIM2D v16 — Steady-state drainage connectivity test.

Purpose:
  No rainfall. Extreme constant WSE at all 4 inflow cells (sill + 5m).
  Run for 6 days to reach near-steady state.
  Goal: verify that all channels drain through the Nile floodplain to the
  western domain exit.  If water pools instead of draining, the DEM still
  has connectivity gaps.

Usage:
    micromamba run -n zarrv3 python v16/run_v16_setup.py
    cd v16 && /data/rim2d/bin/RIM2D simulation_v16.def --def flex
"""

from pathlib import Path
import shutil, json
import numpy as np
import netCDF4

WORK_DIR   = Path("/data/rim2d/nile_highres")
V15_INPUT  = WORK_DIR / "v15" / "input"
V16_DIR    = WORK_DIR / "v16"
V16_INPUT  = V16_DIR  / "input"
V16_INPUT.mkdir(parents=True, exist_ok=True)
(V16_DIR / "output").mkdir(exist_ok=True)

# ── Simulation parameters ──────────────────────────────────────────────────
SIM_DUR   = 518_400    # 6 days (same window as v15)
DT_INFLOW = 1800       # 30 min
N_WSE     = SIM_DUR // DT_INFLOW + 1   # 289 timesteps (inclusive)

# Extreme constant WSE: sill + EXTREME_DEPTH above sill for every timestep
EXTREME_DEPTH = 5.0   # metres above sill — forces maximum hydraulic gradient

# Inflow cell definitions (row/col 0-indexed; sill = DEM elevation at cell in v15)
INFLOW_DEFS = {
    "Culvert1":    {"row": 212, "col": 312, "sill": 321.105},
    "Culvert2":    {"row": 222, "col": 266, "sill": 320.012},
    "WesternWadi": {"row": 222, "col": 175, "sill": 318.855},
    "HospitalWadi":{"row": 183, "col": 281, "sill": 316.134},
}


# ── Step 1: Copy v15 DEM (already has Nile + railway burns) ──────────────
def copy_dem():
    print("\nStep 1: Copying v15 DEM (Nile + railway burns already applied)")
    src = V15_INPUT / "dem_v15.nc"
    dst = V16_INPUT / "dem_v16.nc"
    shutil.copy2(src, dst)
    # Verify burn stats
    ds = netCDF4.Dataset(str(dst))
    var = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[var][:]).squeeze().astype(float)
    dem[dem < -9000] = np.nan
    ds.close()
    n_nile = int(np.sum(dem < 296))
    print(f"  Nile cells (dem<296m): {n_nile}")
    print(f"  DEM min: {np.nanmin(dem):.1f}m, max: {np.nanmax(dem):.1f}m")
    print(f"  Saved: {dst}")


# ── Step 2: Copy boundary mask from v15 ──────────────────────────────────
def copy_boundary_mask():
    print("\nStep 2: Copying boundary mask from v15")
    src = V15_INPUT / "fluvbound_mask_v15.nc"
    dst = V16_INPUT / "fluvbound_mask_v16.nc"
    shutil.copy2(src, dst)
    print(f"  Copied: {dst.name}")


# ── Step 3: Write extreme constant inflowlocs_v16.txt ────────────────────
def write_inflowlocs():
    print("\nStep 3: Writing inflowlocs_v16.txt (extreme constant WSE, no storm)")
    out_path = V16_INPUT / "inflowlocs_v16.txt"
    with open(out_path, "w") as f:
        f.write(f"{SIM_DUR}\n{DT_INFLOW}\n{len(INFLOW_DEFS)}\n")
        for name, d in INFLOW_DEFS.items():
            wse = d["sill"] + EXTREME_DEPTH
            vals = " ".join(f"{wse:.3f}" for _ in range(N_WSE))
            f.write(f"{d['row'] + 1}\t{d['col'] + 1}\t{vals}\n")
            print(f"  {name}: constant WSE = {wse:.3f}m (sill={d['sill']}m + {EXTREME_DEPTH}m)")
    print(f"  Saved: {out_path}")


# ── Step 4: Write simulation_v16.def ─────────────────────────────────────
def write_def_file():
    print("\nStep 4: Writing simulation_v16.def")
    out_timing = " ".join(str(t) for t in range(21600, SIM_DUR + 1, 21600))
    n_out = SIM_DUR // 21600

    content = f"""\
# RIM2D model definition file
# Nile high-resolution — v16
# STEADY-STATE DRAINAGE CONNECTIVITY TEST
# No rainfall; extreme constant inflow (sill+{EXTREME_DEPTH}m) at all 4 boundaries
# Purpose: verify Nile floodplain burns create end-to-end drainage connectivity

###### INPUT RASTERS ######
**DEM**
input/dem_v16.nc
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
input/inflowlocs_v16.txt

# NO RAINFALL — steady-state drainage test
**pluvial_raster_nr**
0

###### OUTPUT ######
**output_base_fn**
output/nile_v16_
**out_cells**
../v10/input/outflowlocs.txt
**out_timing_nr**
{n_out}
**out_timing**
{out_timing}

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
input/fluvbound_mask_v16.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    out_path = V16_DIR / "simulation_v16.def"
    out_path.write_text(content)
    print(f"  Saved: {out_path}")


# ── Step 5: Save metadata ─────────────────────────────────────────────────
def save_metadata():
    print("\nStep 5: Saving metadata")
    meta = {
        "version": "v16",
        "purpose": "Steady-state drainage connectivity test — no rainfall",
        "dem_source": "v15 (Nile floodplain + railway burns applied)",
        "rainfall": "none",
        "sim_dur_s": SIM_DUR,
        "dt_inflow_s": DT_INFLOW,
        "inflow_wse_above_sill_m": EXTREME_DEPTH,
        "inflow_points": [
            {"name": k, "row": v["row"], "col": v["col"],
             "sill_m": v["sill"], "constant_wse_m": v["sill"] + EXTREME_DEPTH}
            for k, v in INFLOW_DEFS.items()
        ],
    }
    out_path = V16_INPUT / "v16_metadata.json"
    with open(out_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Saved: {out_path}")


if __name__ == "__main__":
    print("=" * 60)
    print("RIM2D v16 Setup — Steady-state drainage connectivity test")
    print("=" * 60)
    copy_dem()
    copy_boundary_mask()
    write_inflowlocs()
    write_def_file()
    save_metadata()
    print(f"""
{'=' * 60}
Setup complete. To run simulation:
  cd /data/rim2d/nile_highres/v16
  export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
  /data/rim2d/bin/RIM2D simulation_v16.def --def flex
{'=' * 60}
""")
