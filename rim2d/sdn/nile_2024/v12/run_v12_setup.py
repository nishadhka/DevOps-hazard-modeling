#!/usr/bin/env python3
"""
v12 — Two targeted fixes to v11 compound flood model
======================================================

Fix 1 — WSE cap at culvert/wadi inflow cells
    v11 used a pressurized overflow formula that forced WSE 5–8m above the
    culvert sill at a single cell, creating unrealistic pooling. v12 caps the
    WSE increment at each boundary cell to sill_elevation + WSE_CAP_M (1.5m).
    Excess flow above that head is treated as sheet flow that RIM2D propagates
    naturally once water enters the domain.

Fix 2 — 4th inflow: hospital-side urban drainage wadi
    Ground observations confirm that a small N-S drainage wadi at
    (19.539508, 33.330320) — between the main settlement and the hospital —
    flooded during the Aug 2024 event, cutting road access to the hospital.
    This wadi has its own small catchment (~5 km²) draining the low-lying
    area between the settlement and the Nile bank. v12 adds it as a 4th
    inflow boundary using the same IMERG rainfall + rational method, but
    with a shorter time of concentration (small urban catchment).

Usage:
    cd /data/rim2d/nile_highres/v12
    micromamba run -n zarrv3 python run_v12_setup.py
    export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
    ../bin/RIM2D simulation_v12.def --def flex
"""

import json
import logging
import time
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
from pyproj import Transformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# -- Paths --------------------------------------------------------------------
WORK_DIR  = Path("/data/rim2d/nile_highres")
V10_DIR   = WORK_DIR / "v10"
V11_DIR   = WORK_DIR / "v11"
V12_DIR   = WORK_DIR / "v12"
V12_INPUT = V12_DIR / "input"
V12_OUTPUT= V12_DIR / "output"
V11_NPZ   = V11_DIR / "input" / "culvert_hydrographs_v11.npz"

# -- Simulation timing (same as v11) -----------------------------------------
SIM_DUR   = 3196800   # 37 days
DT_INFLOW = 1800      # 30-min boundary timestep
N_WSE     = SIM_DUR // DT_INFLOW + 1   # 1777
N_RAIN    = 1824
OUT_INTERVAL = 21600  # 6-hour snapshots

# -- Culvert geometry (same as v11) ------------------------------------------
CULVERT_WIDTH  = 3.0
CULVERT_HEIGHT = 2.0
N_MANNING      = 0.014
SLOPE          = 0.002

# -- FIX 1: WSE cap -----------------------------------------------------------
# Maximum water depth above culvert sill elevation at any single boundary cell.
# Physically: head needed to pass ~2-3x culvert capacity via free overflow weir.
# Values: 1.5m = moderate overtopping; replaces the 5-8m pressurized formula.
WSE_CAP_M = 1.5

# -- Inflow configurations ---------------------------------------------------
CULVERTS = [
    {"name": "Culvert1", "lat": 19.54745, "lon": 33.339139, "catchment_km2": 25.0},
    {"name": "Culvert2", "lat": 19.55,    "lon": 33.325906, "catchment_km2": 35.0},
]
WESTERN_ENTRY = {
    "name": "WesternWadi", "lat": 19.55, "lon": 33.300,
    "catchment_km2": 75.0, "nile_blocked": True,
}
# FIX 2: 4th inflow — hospital-side drainage wadi
HOSPITAL_WADI = {
    "name": "HospitalWadi",
    "lat": 19.539508, "lon": 33.330320,
    # Small catchment: urban drainage strip between settlement and Nile bank
    # Estimated ~5 km² from DEM topo — narrow strip ~2km long x ~2.5km wide
    "catchment_km2": 5.0,
    "note": (
        "N-S drainage wadi 500m west of hospital. Floods road crossing during "
        "Aug 2024 event, cutting access between settlement and hospital. "
        "Catchment: low-lying strip between settlement and Nile bank."
    ),
}

# IMERG intensification (same as v11 — already at physical upper bound)
IMERG_FACTOR = 5.0

# -- Helpers ------------------------------------------------------------------

def load_dem():
    ds = netCDF4.Dataset(str(V10_DIR / "input" / "dem.nc"))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    dem[dem < -9000] = np.nan
    return dem, x, y


def latlon_to_grid(lat, lon, x, y):
    t = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    ux, uy = t.transform(lon, lat)
    col = int(np.argmin(np.abs(x - ux)))
    row = int(np.argmin(np.abs(y - uy)))
    return row, col


def culvert_full_capacity():
    a = CULVERT_WIDTH * CULVERT_HEIGHT
    p = 2 * CULVERT_HEIGHT + CULVERT_WIDTH
    r = a / p
    return (1.0 / N_MANNING) * a * r ** (2.0 / 3.0) * SLOPE ** 0.5


def flow_to_wse_capped(q, sill_elev):
    """
    FIX 1: Convert flow to WSE with a hard cap of sill_elev + WSE_CAP_M.

    Below culvert capacity: Manning depth (same as v11).
    Above culvert capacity: WSE capped at sill + WSE_CAP_M.
    This prevents the pressurized formula from creating unrealistic 5-8m head
    at a single boundary cell.
    """
    if q <= 0:
        return sill_elev

    w, h, n, s = CULVERT_WIDTH, CULVERT_HEIGHT, N_MANNING, SLOPE
    a_full = w * h
    p_full = 2 * h + w
    q_full = (1.0 / n) * a_full * (a_full / p_full) ** (2.0 / 3.0) * s ** 0.5

    if q <= q_full:
        # Free-flow: solve for normal depth via bisection
        d_lo, d_hi = 0.001, h
        for _ in range(50):
            d = (d_lo + d_hi) / 2.0
            a = w * d
            p = w + 2 * d
            q_t = (1.0 / n) * a * (a / p) ** (2.0 / 3.0) * s ** 0.5
            if q_t < q:
                d_lo = d
            else:
                d_hi = d
        depth = (d_lo + d_hi) / 2.0
    else:
        # Pressurized / overtopping: CAP depth at WSE_CAP_M (Fix 1)
        depth = WSE_CAP_M

    return sill_elev + depth


def flow_to_wse_open_capped(q, dem_elev, width=5.0):
    """
    Open channel WSE for WesternWadi, also capped at dem_elev + WSE_CAP_M.
    """
    if q <= 0:
        return dem_elev
    n, s = N_MANNING, SLOPE
    d_lo, d_hi = 0.001, 20.0
    for _ in range(60):
        d = (d_lo + d_hi) / 2.0
        a = width * d
        p = width + 2 * d
        q_t = (1.0 / n) * a * (a / p) ** (2.0 / 3.0) * s ** 0.5
        if q_t < q:
            d_lo = d
        else:
            d_hi = d
    depth = min((d_lo + d_hi) / 2.0, WSE_CAP_M)
    return dem_elev + depth


def flow_to_wse_wadi(q, dem_elev, width=3.0):
    """
    FIX 2: WSE for hospital wadi — small natural channel, no culvert structure.
    Uses open-channel Manning's depth, capped at WSE_CAP_M.
    """
    if q <= 0:
        return dem_elev
    n, s = N_MANNING, SLOPE
    d_lo, d_hi = 0.001, 10.0
    for _ in range(60):
        d = (d_lo + d_hi) / 2.0
        a = width * d
        p = width + 2 * d
        q_t = (1.0 / n) * a * (a / p) ** (2.0 / 3.0) * s ** 0.5
        if q_t < q:
            d_lo = d
        else:
            d_hi = d
    depth = min((d_lo + d_hi) / 2.0, WSE_CAP_M)
    return dem_elev + depth


def make_triangular_uh(tc_hours, dt_s):
    """Triangular unit hydrograph."""
    tc_s = tc_hours * 3600.0
    n_steps = max(3, int(np.ceil(2 * tc_s / dt_s)))
    uh = np.zeros(n_steps)
    peak_step = int(n_steps // 2)
    for i in range(n_steps):
        if i <= peak_step:
            uh[i] = i / peak_step if peak_step > 0 else 1.0
        else:
            uh[i] = (n_steps - 1 - i) / (n_steps - 1 - peak_step)
    s = uh.sum()
    return uh / s if s > 0 else uh


def compute_tc_hours(area_km2):
    """Kirpich formula adapted for arid wadi catchments."""
    return 0.3 * area_km2 ** 0.4


def rational_method_hydrograph(rain_rates_mmhr, catchment_m2, runoff_coeff, uh, dt_s):
    rain_ms = rain_rates_mmhr / (1000.0 * 3600.0)
    q_instant = runoff_coeff * rain_ms * catchment_m2
    q_conv = np.convolve(q_instant, uh, mode="full")[: len(rain_rates_mmhr)]
    return q_conv


def pad_to_nwse(q):
    """Pad flow array to N_WSE length (prepend zero at t=0)."""
    out = np.zeros(N_WSE)
    n = min(len(q), N_WSE - 1)
    out[1 : n + 1] = q[:n]
    return out


def write_boundary_mask(cells, dem, x, y, out_path):
    nrows, ncols = dem.shape
    mask = np.zeros((nrows, ncols), dtype=np.float32)
    for i, (row, col, _) in enumerate(cells):
        mask[row, col] = float(i + 1)
    ds = netCDF4.Dataset(str(out_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.history = "v12: 4-zone boundary mask"
    ds.createDimension("x", ncols)
    ds.createDimension("y", nrows)
    xv = ds.createVariable("x", "f8", ("x",))
    xv[:] = x
    yv = ds.createVariable("y", "f8", ("y",))
    yv[:] = y
    band = ds.createVariable("Band1", "f4", ("y", "x"), fill_value=np.float32(-9999.0))
    band[:] = mask
    ds.close()
    log.info(f"  Boundary mask: {out_path.name} ({int(mask.max())} zones)")


def write_inflowlocs(cells, wse_list, out_path):
    with open(str(out_path), "w") as f:
        f.write(f"{SIM_DUR}\n{DT_INFLOW}\n{len(cells)}\n")
        for i, (row, col, _) in enumerate(cells):
            vals = [str(row + 1), str(col + 1)]
            vals.extend(f"{v:.3f}" for v in wse_list[i])
            f.write("\t".join(vals) + "\n")
    log.info(f"  Inflowlocs: {out_path.name} ({len(cells)} cells)")


def write_simulation_def(out_path):
    out_times = " ".join(
        str(t) for t in range(OUT_INTERVAL, SIM_DUR + 1, OUT_INTERVAL)
    )
    n_out = SIM_DUR // OUT_INTERVAL
    content = f"""# RIM2D model definition file (version 2.0)
# Nile high-resolution — v12
# Fix 1: WSE capped at sill + {WSE_CAP_M}m (no pressurized 5-8m head)
# Fix 2: 4th inflow — hospital-side drainage wadi (HospitalWadi, 5 km²)
# 4 inflow boundaries: Culvert1 (25km²) + Culvert2 (35km²)
#                    + WesternWadi (75km², Nile-blocked)
#                    + HospitalWadi (5km², hospital access wadi)

###### INPUT RASTERS ######
**DEM**
../v10/input/dem.nc
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
input/inflowlocs_v12.txt

# RAINFALL — same IMERG as v10/v11
**pluvial_raster_nr**
{N_RAIN}
**pluvial_dt**
1800
**pluvial_start**
0
**pluvial_base_fn**
../v10/input/rain/imerg_v10_t

###### OUTPUT ######
**output_base_fn**
output/nile_v12_
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
input/fluvbound_mask_v12.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    with open(str(out_path), "w") as f:
        f.write(content)
    log.info(f"  Simulation def: {out_path.name}")


# -- Main ---------------------------------------------------------------------

def main():
    t0 = time.time()
    log.info("=" * 65)
    log.info("v12 — Compound Flood: 4 inflows, WSE cap fix")
    log.info("=" * 65)

    V12_INPUT.mkdir(parents=True, exist_ok=True)
    V12_OUTPUT.mkdir(parents=True, exist_ok=True)

    # -- Load cached v11 hydrographs (IMERG already downloaded) --------------
    log.info("\nLoading v11 cached hydrographs ...")
    npz = np.load(V11_NPZ)
    # These are unintensified (factor=1) raw hydrographs
    q_raw_c1           = npz["q_raw_Culvert1"]
    q_raw_c2           = npz["q_raw_Culvert2"]
    q_raw_west_unblocked = npz["q_WesternWadi_unblocked"]
    nile_blocking      = npz["nile_blocking_factor"]
    basin_rain_raw     = npz["basin_rain_raw"]          # mm/hr, 30-min steps
    basin_rain_int     = npz["basin_rain_intensified"]  # at 5x

    log.info(f"  IMERG factor: {IMERG_FACTOR:.1f}x")
    log.info(f"  Nile blocking: min={nile_blocking.min():.3f}, max={nile_blocking.max():.3f}")

    # -- Load DEM -------------------------------------------------------------
    log.info("\nLoading DEM ...")
    dem, x, y = load_dem()

    # Locate all boundary cells
    c1_r, c1_c = latlon_to_grid(CULVERTS[0]["lat"], CULVERTS[0]["lon"], x, y)
    c2_r, c2_c = latlon_to_grid(CULVERTS[1]["lat"], CULVERTS[1]["lon"], x, y)
    w_r,  w_c  = latlon_to_grid(WESTERN_ENTRY["lat"], WESTERN_ENTRY["lon"], x, y)
    hw_r, hw_c = latlon_to_grid(HOSPITAL_WADI["lat"], HOSPITAL_WADI["lon"], x, y)

    c1_elev = float(dem[c1_r, c1_c])
    c2_elev = float(dem[c2_r, c2_c])
    w_elev  = float(dem[w_r,  w_c])
    hw_elev = float(dem[hw_r, hw_c])

    log.info(f"  Culvert1:     row={c1_r}, col={c1_c}, elev={c1_elev:.1f}m")
    log.info(f"  Culvert2:     row={c2_r}, col={c2_c}, elev={c2_elev:.1f}m")
    log.info(f"  WesternWadi:  row={w_r},  col={w_c},  elev={w_elev:.1f}m")
    log.info(f"  HospitalWadi: row={hw_r}, col={hw_c}, elev={hw_elev:.1f}m")

    q_cap = culvert_full_capacity()
    log.info(f"\n  Culvert full-pipe capacity: {q_cap:.1f} m³/s")
    log.info(f"  WSE cap above sill: {WSE_CAP_M:.1f}m  [FIX 1]")

    # -- Culvert 1 hydrograph -------------------------------------------------
    log.info("\n--- Culvert1 (25 km²) ---")
    q_c1 = q_raw_c1[:N_RAIN] * IMERG_FACTOR
    q_c1_p = pad_to_nwse(q_c1)
    wse_c1 = np.array([flow_to_wse_capped(qi, c1_elev) for qi in q_c1_p])
    log.info(f"  Peak Q: {q_c1_p.max():.1f} m³/s  |  Peak WSE: {wse_c1.max():.2f}m  "
             f"(max depth above sill: {wse_c1.max()-c1_elev:.2f}m)")

    # -- Culvert 2 hydrograph -------------------------------------------------
    log.info("\n--- Culvert2 (35 km²) ---")
    q_c2 = q_raw_c2[:N_RAIN] * IMERG_FACTOR
    q_c2_p = pad_to_nwse(q_c2)
    wse_c2 = np.array([flow_to_wse_capped(qi, c2_elev) for qi in q_c2_p])
    log.info(f"  Peak Q: {q_c2_p.max():.1f} m³/s  |  Peak WSE: {wse_c2.max():.2f}m  "
             f"(max depth above sill: {wse_c2.max()-c2_elev:.2f}m)")

    # -- Western wadi (Nile-blocked) ------------------------------------------
    log.info("\n--- WesternWadi (75 km², Nile-blocked) ---")
    n_west = min(len(q_raw_west_unblocked), N_RAIN)
    q_west_unblocked = q_raw_west_unblocked[:n_west] * IMERG_FACTOR
    q_west_blocked   = q_west_unblocked * nile_blocking[:n_west]
    q_west_p         = pad_to_nwse(q_west_blocked)
    wse_west = np.array([flow_to_wse_open_capped(qi, w_elev) for qi in q_west_p])
    log.info(f"  Peak Q (blocked): {q_west_p.max():.1f} m³/s  |  "
             f"Peak WSE: {wse_west.max():.2f}m  "
             f"(max depth: {wse_west.max()-w_elev:.2f}m)")

    # -- Hospital wadi (FIX 2) ------------------------------------------------
    log.info("\n--- HospitalWadi (5 km², Fix 2) ---")
    log.info(f"  {HOSPITAL_WADI['note']}")
    tc_hw = compute_tc_hours(HOSPITAL_WADI["catchment_km2"])
    uh_hw = make_triangular_uh(tc_hw, DT_INFLOW)
    # Use intensified basin rainfall (same IMERG event)
    # Runoff coefficient = 0.65 (same as culverts — semi-arid urban)
    q_hw = rational_method_hydrograph(
        basin_rain_int[:N_RAIN],
        HOSPITAL_WADI["catchment_km2"] * 1e6,
        0.65, uh_hw, DT_INFLOW,
    )
    q_hw_p  = pad_to_nwse(q_hw)
    wse_hw  = np.array([flow_to_wse_wadi(qi, hw_elev) for qi in q_hw_p])
    log.info(f"  Tc: {tc_hw:.2f}h  |  Peak Q: {q_hw_p.max():.2f} m³/s  |  "
             f"Peak WSE: {wse_hw.max():.2f}m  "
             f"(max depth: {wse_hw.max()-hw_elev:.2f}m)")

    # -- Write boundary files -------------------------------------------------
    log.info("\n--- Writing boundary files ---")
    cells = [
        (c1_r, c1_c, "Culvert1"),
        (c2_r, c2_c, "Culvert2"),
        (w_r,  w_c,  "WesternWadi"),
        (hw_r, hw_c, "HospitalWadi"),
    ]
    wse_list = [wse_c1, wse_c2, wse_west, wse_hw]

    write_boundary_mask(cells, dem, x, y, V12_INPUT / "fluvbound_mask_v12.nc")
    write_inflowlocs(cells, wse_list, V12_INPUT / "inflowlocs_v12.txt")
    write_simulation_def(V12_DIR / "simulation_v12.def")

    # -- Save NPZ for visualisation ------------------------------------------
    np.savez(
        V12_INPUT / "culvert_hydrographs_v12.npz",
        q_Culvert1=q_c1_p,
        q_Culvert2=q_c2_p,
        q_WesternWadi=q_west_p,
        q_WesternWadi_unblocked=q_west_unblocked,
        q_HospitalWadi=q_hw_p,
        nile_blocking_factor=nile_blocking,
        imerg_factor=np.array([IMERG_FACTOR]),
        wse_cap_m=np.array([WSE_CAP_M]),
    )
    log.info(f"  Hydrographs NPZ: culvert_hydrographs_v12.npz")

    # -- Save metadata --------------------------------------------------------
    meta = {
        "version": "v12",
        "fixes": {
            "fix1_wse_cap": f"WSE capped at sill + {WSE_CAP_M}m (was 5-8m in v11)",
            "fix2_hospital_wadi": "4th inflow at hospital access wadi (5 km²)",
        },
        "inflow_points": [
            {"name": "Culvert1",     "lat": CULVERTS[0]["lat"],     "lon": CULVERTS[0]["lon"],
             "catchment_km2": 25.0, "peak_q_m3s": float(q_c1_p.max()),
             "peak_wse_m": float(wse_c1.max()), "max_depth_above_sill_m": float(wse_c1.max()-c1_elev)},
            {"name": "Culvert2",     "lat": CULVERTS[1]["lat"],     "lon": CULVERTS[1]["lon"],
             "catchment_km2": 35.0, "peak_q_m3s": float(q_c2_p.max()),
             "peak_wse_m": float(wse_c2.max()), "max_depth_above_sill_m": float(wse_c2.max()-c2_elev)},
            {"name": "WesternWadi",  "lat": WESTERN_ENTRY["lat"],  "lon": WESTERN_ENTRY["lon"],
             "catchment_km2": 75.0, "peak_q_m3s": float(q_west_p.max()),
             "peak_wse_m": float(wse_west.max()), "max_depth_above_sill_m": float(wse_west.max()-w_elev),
             "nile_blocking": True},
            {"name": "HospitalWadi", "lat": HOSPITAL_WADI["lat"],  "lon": HOSPITAL_WADI["lon"],
             "catchment_km2": 5.0,  "peak_q_m3s": float(q_hw_p.max()),
             "peak_wse_m": float(wse_hw.max()), "max_depth_above_sill_m": float(wse_hw.max()-hw_elev),
             "note": HOSPITAL_WADI["note"]},
        ],
        "imerg_factor": IMERG_FACTOR,
        "wse_cap_m": WSE_CAP_M,
    }
    with open(V12_INPUT / "v12_metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    log.info(f"  Metadata: v12_metadata.json")

    log.info(f"\nSetup complete in {time.time()-t0:.1f}s")
    log.info("\nNext:")
    log.info(f"  cd {V12_DIR}")
    log.info(f"  export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH")
    log.info(f"  ../bin/RIM2D simulation_v12.def --def flex")


if __name__ == "__main__":
    main()
