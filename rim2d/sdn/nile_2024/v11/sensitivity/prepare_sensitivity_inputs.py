#!/usr/bin/env python3
"""
Prepare boundary condition inputs for sensitivity ensemble (Steps 2 & 3).
=========================================================================
Uses the cached hydrographs from v11 (culvert_hydrographs_v11.npz) to generate
boundary files for each scenario without re-downloading IMERG or re-running EE.

Scenarios
---------
Step 2 — Compound flooding decomposition:
  culverts_only  : Culvert1 + Culvert2 only (no western wadi)  — imerg 5x
  halfblock      : All 3 inflows, western wadi at 50% max blocking — imerg 5x

Step 3 — Rainfall uncertainty:
  intens2x       : All 3 inflows, IMERG intensification factor = 2x
  intens3p5x     : All 3 inflows, IMERG intensification factor = 3.5x
  intens7x       : All 3 inflows, IMERG intensification factor = 7x

(The baseline v11_compound at 5x is already complete in v11/input + v11/output.)

Outputs (per scenario, under sensitivity/<name>/):
  input/fluvbound_mask_<name>.nc
  input/inflowlocs_<name>.txt
  simulation_<name>.def
  input -> symlinks to shared v10 terrain + rain inputs

Usage:
    cd /data/rim2d/nile_highres/v11/sensitivity
    micromamba run -n zarrv3 python prepare_sensitivity_inputs.py
"""

import json
import logging
import shutil
from pathlib import Path

import netCDF4
import numpy as np
from pyproj import Transformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# -- Paths --------------------------------------------------------------------
WORK_DIR = Path("/data/rim2d/nile_highres")
V10_INPUT = WORK_DIR / "v10" / "input"
V11_DIR = WORK_DIR / "v11"
V11_INPUT = V11_DIR / "input"
SENS_DIR = V11_DIR / "sensitivity"
NPZ = V11_INPUT / "culvert_hydrographs_v11.npz"
V11_META = V11_INPUT / "v11_metadata.json"
RIM2D_BIN = WORK_DIR.parent / "bin" / "RIM2D"

# -- Shared simulation parameters (same as v11) -------------------------------
SIM_DUR = 3196800      # 37 days in seconds
DT_INFLOW = 1800       # 30-min boundary timestep
N_WSE = SIM_DUR // DT_INFLOW + 1
N_RAIN = 1824          # IMERG timesteps
OUT_INTERVAL = 21600   # 6-hour output snapshots

# Culvert geometry (from v11)
CULVERT_WIDTH = 3.0
CULVERT_HEIGHT = 2.0
N_MANNING = 0.014
SLOPE = 0.002

# Culvert + western entry locations
CULVERTS = [
    {"name": "Culvert1", "lat": 19.54745, "lon": 33.339139, "catchment_km2": 25.0},
    {"name": "Culvert2", "lat": 19.55,    "lon": 33.325906, "catchment_km2": 35.0},
]
WESTERN_ENTRY = {"name": "WesternWadi", "lat": 19.55, "lon": 33.300, "catchment_km2": 75.0}

# Base IMERG intensification (v11 baseline)
BASE_IMERG_FACTOR = 5.0

# -- Scenarios ----------------------------------------------------------------
SCENARIOS = {
    "culverts_only": {
        "description": "Culvert1 + Culvert2 only (no western wadi / no compound flooding)",
        "imerg_factor": BASE_IMERG_FACTOR,
        "include_western": False,
        "western_block_scale": 0.0,
    },
    "halfblock": {
        "description": "All 3 inflows; western wadi at 50% of full Nile-blocking",
        "imerg_factor": BASE_IMERG_FACTOR,
        "include_western": True,
        "western_block_scale": 0.5,
    },
    "intens2x": {
        "description": "All 3 inflows; IMERG intensification factor = 2x",
        "imerg_factor": 2.0,
        "include_western": True,
        "western_block_scale": 1.0,
    },
    "intens3p5x": {
        "description": "All 3 inflows; IMERG intensification factor = 3.5x",
        "imerg_factor": 3.5,
        "include_western": True,
        "western_block_scale": 1.0,
    },
    "intens7x": {
        "description": "All 3 inflows; IMERG intensification factor = 7x",
        "imerg_factor": 7.0,
        "include_western": True,
        "western_block_scale": 1.0,
    },
}


# -- Helpers ------------------------------------------------------------------

def load_dem():
    """Load DEM grid (x, y arrays + elevation array)."""
    import netCDF4
    ds = netCDF4.Dataset(str(V10_INPUT / "dem.nc"))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    dem[dem < -9000] = np.nan
    return dem, x, y


def latlon_to_grid(lat, lon, x, y):
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    utm_x, utm_y = to_utm.transform(lon, lat)
    col = int(np.argmin(np.abs(x - utm_x)))
    row = int(np.argmin(np.abs(y - utm_y)))
    return row, col


def culvert_capacity():
    a = CULVERT_WIDTH * CULVERT_HEIGHT
    p = 2 * CULVERT_HEIGHT + CULVERT_WIDTH
    r = a / p
    return (1.0 / N_MANNING) * a * r ** (2.0 / 3.0) * SLOPE ** 0.5


def flow_to_wse(q, dem_elev):
    """Manning / pressurized WSE at culvert (same logic as run_v11)."""
    if q <= 0:
        return dem_elev
    w, h, n, s = CULVERT_WIDTH, CULVERT_HEIGHT, N_MANNING, SLOPE
    a_full = w * h
    p_full = 2 * h + w
    q_full = (1.0 / n) * a_full * (a_full / p_full) ** (2.0 / 3.0) * s ** 0.5
    if q <= q_full:
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
        q_excess = q - q_full
        h_overflow = (q_excess / (0.6 * w * (2 * 9.81) ** 0.5)) ** (2.0 / 3.0)
        depth = h + h_overflow
    return dem_elev + min(depth, 10.0)


def flow_to_wse_open(q, dem_elev, width=5.0):
    """Normal-depth WSE for open channel (western wadi entry)."""
    if q <= 0:
        return dem_elev
    n, s = N_MANNING, SLOPE
    # Iterate depth for rectangular section
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
    return dem_elev + (d_lo + d_hi) / 2.0


def scale_hydrograph(q_base_raw, new_factor, base_factor):
    """Rescale a hydrograph to a different IMERG intensification factor."""
    # q_base_raw is the unintensified hydrograph; scale linearly
    return q_base_raw * (new_factor / base_factor)


def write_boundary_mask(cells, dem, x, y, out_path):
    nrows, ncols = dem.shape
    mask = np.zeros((nrows, ncols), dtype=np.float32)
    for i, (row, col, _) in enumerate(cells):
        mask[row, col] = float(i + 1)
    ds = netCDF4.Dataset(str(out_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.createDimension("x", ncols)
    ds.createDimension("y", nrows)
    xv = ds.createVariable("x", "f8", ("x",))
    xv[:] = x
    yv = ds.createVariable("y", "f8", ("y",))
    yv[:] = y
    band = ds.createVariable("Band1", "f4", ("y", "x"), fill_value=np.float32(-9999.0))
    band[:] = mask
    ds.close()


def write_inflowlocs(cells, wse_list, out_path):
    n_wse = wse_list[0].shape[0]
    with open(str(out_path), "w") as f:
        f.write(f"{SIM_DUR}\n{DT_INFLOW}\n{len(cells)}\n")
        for i, (row, col, _) in enumerate(cells):
            vals = [str(row + 1), str(col + 1)]
            vals.extend(f"{v:.3f}" for v in wse_list[i])
            f.write("\t".join(vals) + "\n")


def write_def(out_path, scenario_name, rain_nr):
    out_times = " ".join(
        str(t) for t in range(OUT_INTERVAL, SIM_DUR + 1, OUT_INTERVAL)
    )
    n_out = SIM_DUR // OUT_INTERVAL
    tag = scenario_name
    content = f"""# RIM2D model definition file (version 2.0)
# Nile high-resolution — sensitivity scenario: {tag}

###### INPUT RASTERS ######
**DEM**
../../../v10/input/dem.nc
**buildings**
../../../v10/input/buildings.nc
**IWD**
file
../../../v10/input/iwd.nc
**roughness**
file
../../../v10/input/roughness.nc
**pervious_surface**
../../../v10/input/pervious_surface.nc
**sealed_surface**
../../../v10/input/sealed_surface.nc
**sewershed**
../../../v10/input/sewershed_v10_full.nc

###### BOUNDARIES ######
**fluvial_boundary**
input/inflowlocs_{tag}.txt

# RAINFALL — IMERG (shared with v10/v11)
**pluvial_raster_nr**
{rain_nr}
**pluvial_dt**
1800
**pluvial_start**
0
**pluvial_base_fn**
../../../v10/input/rain/imerg_v10_t

###### OUTPUT ######
**output_base_fn**
output/nile_{tag}_
**out_cells**
../../../v10/input/outflowlocs.txt
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
input/fluvbound_mask_{tag}.nc
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


# -- Main ---------------------------------------------------------------------

def main():
    log.info("Loading cached v11 hydrographs from NPZ ...")
    npz = np.load(NPZ)
    q_raw_c1 = npz["q_raw_Culvert1"]          # unintensified
    q_raw_c2 = npz["q_raw_Culvert2"]
    q_raw_west_unblocked = npz["q_WesternWadi_unblocked"]  # unintensified, unblocked
    nile_blocking = npz["nile_blocking_factor"]
    rain_nr = N_RAIN   # number of IMERG files

    log.info("Loading DEM ...")
    dem, x, y = load_dem()

    # Grid locations
    c1_row, c1_col = latlon_to_grid(CULVERTS[0]["lat"], CULVERTS[0]["lon"], x, y)
    c2_row, c2_col = latlon_to_grid(CULVERTS[1]["lat"], CULVERTS[1]["lon"], x, y)
    w_row,  w_col  = latlon_to_grid(WESTERN_ENTRY["lat"], WESTERN_ENTRY["lon"], x, y)
    c1_elev = float(dem[c1_row, c1_col])
    c2_elev = float(dem[c2_row, c2_col])
    w_elev  = float(dem[w_row,  w_col])

    log.info(f"  Culvert1: row={c1_row}, col={c1_col}, elev={c1_elev:.1f} m")
    log.info(f"  Culvert2: row={c2_row}, col={c2_col}, elev={c2_elev:.1f} m")
    log.info(f"  WesternWadi: row={w_row}, col={w_col}, elev={w_elev:.1f} m")

    metadata_all = {}

    for name, cfg in SCENARIOS.items():
        log.info(f"\n{'='*60}")
        log.info(f"Scenario: {name}")
        log.info(f"  {cfg['description']}")

        scen_dir = SENS_DIR / name
        inp_dir  = scen_dir / "input"
        out_dir  = scen_dir / "output"
        inp_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        factor = cfg["imerg_factor"]
        scale = factor / BASE_IMERG_FACTOR   # relative to cached raw

        # -- Culvert hydrographs (rescaled to new intensification) ------------
        q_c1 = scale_hydrograph(q_raw_c1, factor, 1.0)   # raw is already at factor=1
        q_c2 = scale_hydrograph(q_raw_c2, factor, 1.0)

        # Pad to N_WSE (prepend zero at t=0)
        def pad(q):
            out = np.zeros(N_WSE)
            n = min(len(q), N_WSE - 1)
            out[1:n+1] = q[:n]
            return out

        q_c1_p = pad(q_c1)
        q_c2_p = pad(q_c2)

        wse_c1 = np.array([flow_to_wse(qi, c1_elev) for qi in q_c1_p])
        wse_c2 = np.array([flow_to_wse(qi, c2_elev) for qi in q_c2_p])

        cells   = [(c1_row, c1_col, "Culvert1"), (c2_row, c2_col, "Culvert2")]
        wse_list = [wse_c1, wse_c2]

        log.info(f"  Culvert1 peak Q: {q_c1_p.max():.1f} m³/s")
        log.info(f"  Culvert2 peak Q: {q_c2_p.max():.1f} m³/s")

        meta = {
            "scenario": name,
            "description": cfg["description"],
            "imerg_factor": factor,
            "include_western": cfg["include_western"],
            "western_block_scale": cfg["western_block_scale"],
            "culvert1_peak_m3s": float(q_c1_p.max()),
            "culvert2_peak_m3s": float(q_c2_p.max()),
        }

        # -- Western wadi (optional) -----------------------------------------
        if cfg["include_western"]:
            q_west_raw = scale_hydrograph(q_raw_west_unblocked, factor, 1.0)
            block_scale = cfg["western_block_scale"]
            # Apply (potentially scaled) Nile blocking
            blocking = nile_blocking[:len(q_west_raw)] * block_scale
            blocking = np.clip(blocking, 0.0, 1.0)
            q_west_blocked = q_west_raw[:N_RAIN] * blocking[:N_RAIN]
            q_west_p = pad(q_west_blocked)
            wse_west = np.array([flow_to_wse_open(qi, w_elev) for qi in q_west_p])

            cells.append((w_row, w_col, "WesternWadi"))
            wse_list.append(wse_west)

            log.info(f"  WesternWadi peak Q (blocked): {q_west_p.max():.1f} m³/s  "
                     f"[block_scale={block_scale:.1f}]")
            meta["western_peak_m3s"] = float(q_west_p.max())
            meta["western_block_scale"] = block_scale
        else:
            log.info("  WesternWadi: disabled")
            meta["western_peak_m3s"] = 0.0

        # -- Write boundary files --------------------------------------------
        mask_path = inp_dir / f"fluvbound_mask_{name}.nc"
        inflow_path = inp_dir / f"inflowlocs_{name}.txt"
        def_path = scen_dir / f"simulation_{name}.def"

        write_boundary_mask(cells, dem, x, y, mask_path)
        write_inflowlocs(cells, wse_list, inflow_path)
        write_def(def_path, name, rain_nr)
        log.info(f"  Written: {mask_path.name}, {inflow_path.name}, {def_path.name}")

        metadata_all[name] = meta

    # -- Write ensemble metadata JSON ----------------------------------------
    meta_path = SENS_DIR / "ensemble_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata_all, f, indent=2)
    log.info(f"\nEnsemble metadata: {meta_path}")

    # -- Print run commands --------------------------------------------------
    print("\n" + "=" * 60)
    print("Next: run RIM2D for each scenario (or use run_sensitivity_ensemble.sh)")
    print("=" * 60)
    for name in SCENARIOS:
        print(f"  cd {SENS_DIR / name} && {RIM2D_BIN} simulation_{name}.def --def flex")


if __name__ == "__main__":
    main()
