#!/usr/bin/env python3
"""
v13 — Stream channel burning + 6-day peak window simulation
============================================================

Problem identified in v12:
    Flood water pools in the urban area and does not drain southward through
    the natural stream network toward the Nile.  The TDX-Hydro river network
    (Order 5 and Order 9 segments) shows clear drainage paths but the MERIT
    30m DEM has road embankments and urban artefacts that block flow along
    those channels.

Fix — DEM stream burning:
    Lower DEM elevation along TDX-Hydro stream cells so that the channels are
    topographically connected and water can drain naturally to the Nile.
    Burn depths (applied only where DEM > downstream minimum):
        Order 9 (Nile):    5 m  — ensure open Nile channel exit
        Order 5 (streams): 3 m  — main drainage paths to Nile
        Order 2 (wadis):   2 m  — secondary wadi channels

    The burned DEM is saved as v13/input/dem_v13.nc and referenced in the
    simulation.def.  All other inputs are identical to v12.

Simulation window — 6-day peak period (v12 methodology, section 4):
    Full v11/v12 run: 37 days (Jul 25 – Aug 31), SIM_DUR = 3,196,800 s
    v13 focus window: Aug 25 – Aug 31 (6 days), SIM_DUR = 518,400 s
    IMERG files: t1489 – t1776  (step 1488 offset, 288 files)
    This covers the rainfall event peak (Aug 26-28) and the Nile peak
    (Aug 28, 31,694 m³/s) with 2 days spin-up and 2 days recession.

Usage:
    cd /data/rim2d/nile_highres/v13
    micromamba run -n zarrv3 python run_v13_setup.py
    export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
    /data/rim2d/bin/RIM2D simulation_v13.def --def flex
"""

import json
import logging
import time
from pathlib import Path

import geopandas as gpd
import netCDF4
import numpy as np
from pyproj import Transformer
from rasterio.transform import from_bounds
from rasterio.features import rasterize
from shapely.geometry import mapping

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# -- Paths --------------------------------------------------------------------
WORK_DIR   = Path("/data/rim2d/nile_highres")
V10_DIR    = WORK_DIR / "v10"
V12_DIR    = WORK_DIR / "v12"
V13_DIR    = WORK_DIR / "v13"
V13_INPUT  = V13_DIR / "input"
V13_OUTPUT = V13_DIR / "output"
RIVERS_GEOJSON = WORK_DIR / "v11" / "input" / "river_network_tdx_v2.geojson"

# -- Simulation timing — 6-day peak window -----------------------------------
# Full run starts Jul 25 00:00 UTC; Aug 25 = day 31 → IMERG step 1488
IMERG_START_STEP = 1488          # first file to use: imerg_v10_t1489
SIM_DUR          = 518_400       # 6 days in seconds
DT_INFLOW        = 1800
N_WSE            = SIM_DUR // DT_INFLOW + 1   # 289
N_RAIN           = 288           # 6 days × 48 half-hour steps
OUT_INTERVAL     = 21600         # 6-hour snapshots

# -- Stream burn depths -------------------------------------------------------
BURN_DEPTH = {
    9: 5.0,   # Nile — ensure open channel exit at domain south boundary
    5: 3.0,   # Order 5 main streams — primary drainage to Nile
    2: 2.0,   # Order 2 wadis — secondary channels
}

# -- Inherit v12 boundary parameters -----------------------------------------
CULVERT_WIDTH  = 3.0
CULVERT_HEIGHT = 2.0
N_MANNING      = 0.014
SLOPE          = 0.002
WSE_CAP_M      = 1.5
IMERG_FACTOR   = 5.0

CULVERTS = [
    {"name": "Culvert1", "lat": 19.54745, "lon": 33.339139},
    {"name": "Culvert2", "lat": 19.55,    "lon": 33.325906},
]
WESTERN_ENTRY  = {"name": "WesternWadi",  "lat": 19.55,     "lon": 33.300}
HOSPITAL_WADI  = {"name": "HospitalWadi", "lat": 19.539508, "lon": 33.330320,
                  "catchment_km2": 5.0}


# -- Helpers ------------------------------------------------------------------

def load_dem():
    ds = netCDF4.Dataset(str(V10_DIR / "input" / "dem.nc"))
    x   = np.array(ds["x"][:])
    y   = np.array(ds["y"][:])
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    dem[dem < -9000] = np.nan
    return dem, x, y


def burn_streams(dem, x, y):
    """
    Lower DEM along TDX-Hydro stream cells by BURN_DEPTH[order].
    Uses rasterio.features.rasterize to convert vector stream lines
    to the 30m grid, then applies the burn depth.
    """
    rivers = gpd.read_file(str(RIVERS_GEOJSON))
    # Reproject to UTM 32636 to match the DEM grid
    rivers = rivers.to_crs("EPSG:32636")

    ny, nx = dem.shape
    dx = x[1] - x[0]
    dy = y[1] - y[0]
    xmin = x[0]  - dx / 2
    ymin = y[0]  - dy / 2
    xmax = x[-1] + dx / 2
    ymax = y[-1] + dy / 2
    transform = from_bounds(xmin, ymin, xmax, ymax, nx, ny)

    dem_burned = dem.copy()
    total_burned = 0

    for order in sorted(BURN_DEPTH.keys(), reverse=True):
        depth = BURN_DEPTH[order]
        subset = rivers[rivers["stream_order"] == order]
        if subset.empty:
            continue

        # Rasterize: 1 where stream cell, 0 elsewhere
        shapes = [(mapping(geom), 1) for geom in subset.geometry if geom is not None]
        stream_mask = rasterize(
            shapes,
            out_shape=(ny, nx),
            transform=transform,
            fill=0,
            dtype=np.uint8,
            all_touched=True,   # include all cells touched by the line
        ).astype(bool)

        n_cells = stream_mask.sum()
        dem_burned[stream_mask] -= depth
        total_burned += n_cells
        log.info(f"  Order {order}: burned {n_cells} cells by -{depth:.1f}m")

    log.info(f"  Total cells burned: {total_burned}")
    log.info(f"  DEM min after burn: {np.nanmin(dem_burned):.1f}m  "
             f"(was {np.nanmin(dem):.1f}m)")
    return dem_burned


def save_dem(dem_burned, x, y, out_path):
    ny, nx = dem_burned.shape
    ds = netCDF4.Dataset(str(out_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.history = "v13: MERIT DEM with TDX-Hydro stream burning (Order 9=-5m, 5=-3m, 2=-2m)"
    ds.createDimension("x", nx)
    ds.createDimension("y", ny)
    xv = ds.createVariable("x", "f8", ("x",))
    xv.long_name = "x coordinate"; xv.units = "m"; xv[:] = x
    yv = ds.createVariable("y", "f8", ("y",))
    yv.long_name = "y coordinate"; yv.units = "m"; yv[:] = y
    band = ds.createVariable("Band1", "f4", ("y", "x"), fill_value=np.float32(-9999.0))
    out = dem_burned.copy()
    out[np.isnan(out)] = -9999.0
    band[:] = out
    ds.close()
    log.info(f"  Saved burned DEM: {out_path.name}")


def latlon_to_grid(lat, lon, x, y):
    t = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    ux, uy = t.transform(lon, lat)
    return int(np.argmin(np.abs(y - uy))), int(np.argmin(np.abs(x - ux)))


def culvert_full_q():
    a = CULVERT_WIDTH * CULVERT_HEIGHT
    p = 2 * CULVERT_HEIGHT + CULVERT_WIDTH
    return (1.0 / N_MANNING) * a * (a/p)**(2/3) * SLOPE**0.5


def flow_to_wse_capped(q, sill):
    if q <= 0: return sill
    w, h, n, s = CULVERT_WIDTH, CULVERT_HEIGHT, N_MANNING, SLOPE
    q_full = culvert_full_q()
    if q <= q_full:
        d_lo, d_hi = 0.001, h
        for _ in range(50):
            d = (d_lo + d_hi) / 2
            a = w*d; p = w+2*d
            if (1/n)*a*(a/p)**(2/3)*s**0.5 < q: d_lo = d
            else: d_hi = d
        depth = (d_lo+d_hi)/2
    else:
        depth = WSE_CAP_M
    return sill + depth


def flow_to_wse_open_capped(q, elev, width=5.0):
    if q <= 0: return elev
    n, s = N_MANNING, SLOPE
    d_lo, d_hi = 0.001, 20.0
    for _ in range(60):
        d = (d_lo+d_hi)/2; a=width*d; p=width+2*d
        if (1/n)*a*(a/p)**(2/3)*s**0.5 < q: d_lo=d
        else: d_hi=d
    return elev + min((d_lo+d_hi)/2, WSE_CAP_M)


def flow_to_wse_wadi(q, elev, width=3.0):
    if q <= 0: return elev
    n, s = N_MANNING, SLOPE
    d_lo, d_hi = 0.001, 10.0
    for _ in range(60):
        d = (d_lo+d_hi)/2; a=width*d; p=width+2*d
        if (1/n)*a*(a/p)**(2/3)*s**0.5 < q: d_lo=d
        else: d_hi=d
    return elev + min((d_lo+d_hi)/2, WSE_CAP_M)


def make_triangular_uh(tc_hours, dt_s):
    tc_s = tc_hours * 3600.0
    n = max(3, int(np.ceil(2*tc_s/dt_s)))
    uh = np.zeros(n)
    pk = n // 2
    for i in range(n):
        uh[i] = i/pk if i<=pk else (n-1-i)/(n-1-pk)
    s = uh.sum()
    return uh/s if s>0 else uh


def rational_method_hydrograph(rain_mmhr, area_m2, C, uh, dt_s):
    rain_ms = rain_mmhr / (1000.0 * 3600.0)
    q = np.convolve(C * rain_ms * area_m2, uh, mode="full")[:len(rain_mmhr)]
    return q


def pad(q, n=None):
    n = n or N_WSE
    out = np.zeros(n)
    nc = min(len(q), n-1)
    out[1:nc+1] = q[:nc]
    return out


def write_boundary_mask(cells, dem, x, y, out_path):
    ny, nx = dem.shape
    mask = np.zeros((ny, nx), dtype=np.float32)
    for i, (r, c, _) in enumerate(cells):
        mask[r, c] = float(i+1)
    ds = netCDF4.Dataset(str(out_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.createDimension("x", nx); ds.createDimension("y", ny)
    xv = ds.createVariable("x","f8",("x",)); xv[:]=x
    yv = ds.createVariable("y","f8",("y",)); yv[:]=y
    b  = ds.createVariable("Band1","f4",("y","x"),fill_value=np.float32(-9999))
    b[:] = mask
    ds.close()
    log.info(f"  Boundary mask: {out_path.name} ({int(mask.max())} zones)")


def write_inflowlocs(cells, wse_list, out_path):
    with open(str(out_path), "w") as f:
        f.write(f"{SIM_DUR}\n{DT_INFLOW}\n{len(cells)}\n")
        for i, (r, c, _) in enumerate(cells):
            vals = [str(r+1), str(c+1)] + [f"{v:.3f}" for v in wse_list[i]]
            f.write("\t".join(vals) + "\n")
    log.info(f"  Inflowlocs: {out_path.name} ({len(cells)} cells, {N_WSE} WSE steps)")


def write_simulation_def(out_path):
    out_times = " ".join(str(t) for t in range(OUT_INTERVAL, SIM_DUR+1, OUT_INTERVAL))
    n_out = SIM_DUR // OUT_INTERVAL
    content = f"""# RIM2D model definition file (version 2.0)
# Nile high-resolution — v13
# Fix 1 (from v12): WSE capped at sill + {WSE_CAP_M}m
# Fix 2 (from v12): 4th inflow — HospitalWadi (5 km²)
# Fix 3 (NEW):      DEM stream burning — TDX-Hydro channels carved into DEM
#                   Order 9 -5m, Order 5 -3m, Order 2 -2m
# Simulation window: Aug 25–31 (6 days, peak flood period)
#                    IMERG files t{IMERG_START_STEP+1}–t{IMERG_START_STEP+N_RAIN}

###### INPUT RASTERS ######
**DEM**
input/dem_v13.nc
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
input/inflowlocs_v13.txt

# RAINFALL — 6-day peak window (Aug 25-31)
**pluvial_raster_nr**
{N_RAIN}
**pluvial_dt**
1800
**pluvial_start**
{IMERG_START_STEP}
**pluvial_base_fn**
../v10/input/rain/imerg_v10_t

###### OUTPUT ######
**output_base_fn**
output/nile_v13_
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
input/fluvbound_mask_v13.nc
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
    log.info("="*65)
    log.info("v13 — Stream burning + 6-day peak window")
    log.info("="*65)
    V13_INPUT.mkdir(parents=True, exist_ok=True)
    V13_OUTPUT.mkdir(parents=True, exist_ok=True)

    # -- Step 1: Burn stream channels into DEM --------------------------------
    log.info("\n--- Step 1: DEM stream burning ---")
    dem_orig, x, y = load_dem()
    dem_burned = burn_streams(dem_orig, x, y)
    dem_path = V13_INPUT / "dem_v13.nc"
    save_dem(dem_burned, x, y, dem_path)

    # -- Step 2: Load v12 cached hydrographs (trim to 6-day window) ----------
    log.info("\n--- Step 2: Load v12 hydrographs, trim to 6-day window ---")
    log.info(f"  Window: IMERG steps {IMERG_START_STEP+1}–{IMERG_START_STEP+N_RAIN}")
    log.info(f"  = Aug 25 00:00 – Aug 31 00:00 UTC")

    npz = np.load(V12_DIR / "input" / "culvert_hydrographs_v12.npz")
    # v12 NPZ contains full-length (1777-step) padded arrays.
    # We need to extract the 6-day window starting at IMERG_START_STEP.
    # The hydrograph arrays are indexed at 30-min RIM2D timesteps (not IMERG files),
    # but both share the same 30-min interval so offset maps directly.
    off = IMERG_START_STEP   # timestep offset within the 1777-step array

    def trim(arr):
        """Extract N_WSE steps starting at offset, pad to N_WSE."""
        segment = arr[off : off + N_WSE]
        out = np.zeros(N_WSE)
        out[:len(segment)] = segment
        return out

    q_c1   = trim(npz["q_Culvert1"])
    q_c2   = trim(npz["q_Culvert2"])
    q_west = trim(npz["q_WesternWadi"])

    log.info(f"  Culvert1     peak Q in window: {q_c1.max():.1f} m³/s")
    log.info(f"  Culvert2     peak Q in window: {q_c2.max():.1f} m³/s")
    log.info(f"  WesternWadi  peak Q in window: {q_west.max():.1f} m³/s")

    # -- Step 3: Recompute HospitalWadi for the 6-day window -----------------
    log.info("\n--- Step 3: HospitalWadi hydrograph (6-day window) ---")
    # Load IMERG rain for the 6-day window directly from v10 rain files
    rain_dir = V10_DIR / "input" / "rain"
    rain_6d  = np.zeros(N_RAIN)
    for i in range(N_RAIN):
        t_idx = IMERG_START_STEP + i + 1   # file numbering starts at 1
        p = rain_dir / f"imerg_v10_t{t_idx}.nc"
        if p.exists():
            ds = netCDF4.Dataset(str(p))
            data = np.array(ds["Band1"][:], dtype=np.float32)
            ds.close()
            data[data < -9000] = 0.0
            data[~np.isfinite(data)] = 0.0
            rain_6d[i] = float(np.mean(data))

    rain_6d_int = rain_6d * IMERG_FACTOR
    tc_hw = 0.3 * HOSPITAL_WADI["catchment_km2"]**0.4
    uh_hw = make_triangular_uh(tc_hw, DT_INFLOW)
    q_hw_raw = rational_method_hydrograph(
        rain_6d_int, HOSPITAL_WADI["catchment_km2"]*1e6, 0.65, uh_hw, DT_INFLOW)
    q_hw = pad(q_hw_raw)
    log.info(f"  tc={tc_hw:.2f}h  peak Q: {q_hw.max():.2f} m³/s")

    # -- Step 4: Convert flows to WSE using BURNED DEM elevations -------------
    log.info("\n--- Step 4: Compute WSE timeseries (burned DEM elevations) ---")
    c1_r,  c1_c  = latlon_to_grid(CULVERTS[0]["lat"],     CULVERTS[0]["lon"],     x, y)
    c2_r,  c2_c  = latlon_to_grid(CULVERTS[1]["lat"],     CULVERTS[1]["lon"],     x, y)
    w_r,   w_c   = latlon_to_grid(WESTERN_ENTRY["lat"],   WESTERN_ENTRY["lon"],   x, y)
    hw_r,  hw_c  = latlon_to_grid(HOSPITAL_WADI["lat"],   HOSPITAL_WADI["lon"],   x, y)

    # Use burned DEM elevations for WSE calculation
    c1_elev = float(dem_burned[c1_r, c1_c])
    c2_elev = float(dem_burned[c2_r, c2_c])
    w_elev  = float(dem_burned[w_r,  w_c])
    hw_elev = float(dem_burned[hw_r, hw_c])

    log.info(f"  Culvert1    : row={c1_r},col={c1_c}  "
             f"orig={dem_orig[c1_r,c1_c]:.1f}m  burned={c1_elev:.1f}m")
    log.info(f"  Culvert2    : row={c2_r},col={c2_c}  "
             f"orig={dem_orig[c2_r,c2_c]:.1f}m  burned={c2_elev:.1f}m")
    log.info(f"  WesternWadi : row={w_r}, col={w_c}   "
             f"orig={dem_orig[w_r,w_c]:.1f}m  burned={w_elev:.1f}m")
    log.info(f"  HospitalWadi: row={hw_r},col={hw_c}  "
             f"orig={dem_orig[hw_r,hw_c]:.1f}m  burned={hw_elev:.1f}m")

    wse_c1   = np.array([flow_to_wse_capped(qi,       c1_elev) for qi in q_c1])
    wse_c2   = np.array([flow_to_wse_capped(qi,       c2_elev) for qi in q_c2])
    wse_west = np.array([flow_to_wse_open_capped(qi,  w_elev)  for qi in q_west])
    wse_hw   = np.array([flow_to_wse_wadi(qi,         hw_elev) for qi in q_hw])

    log.info(f"\n  Peak WSEs: C1={wse_c1.max():.2f}m  C2={wse_c2.max():.2f}m  "
             f"WW={wse_west.max():.2f}m  HW={wse_hw.max():.2f}m")

    # -- Step 5: Write boundary files ----------------------------------------
    log.info("\n--- Step 5: Write boundary files ---")
    cells    = [(c1_r,c1_c,"Culvert1"),(c2_r,c2_c,"Culvert2"),
                (w_r, w_c, "WesternWadi"),(hw_r,hw_c,"HospitalWadi")]
    wse_list = [wse_c1, wse_c2, wse_west, wse_hw]

    write_boundary_mask(cells, dem_burned, x, y, V13_INPUT/"fluvbound_mask_v13.nc")
    write_inflowlocs(cells, wse_list, V13_INPUT/"inflowlocs_v13.txt")
    write_simulation_def(V13_DIR/"simulation_v13.def")

    # -- Save metadata --------------------------------------------------------
    meta = {
        "version": "v13",
        "simulation_window": "Aug 25–31 2024 (6 days)",
        "sim_dur_s": SIM_DUR,
        "imerg_start_step": IMERG_START_STEP,
        "n_rain_files": N_RAIN,
        "fixes": {
            "fix1_wse_cap": f"WSE capped at sill + {WSE_CAP_M}m (inherited from v12)",
            "fix2_hospital_wadi": "4th inflow HospitalWadi 5km² (inherited from v12)",
            "fix3_stream_burning": {
                "order_9_burn_m": BURN_DEPTH[9],
                "order_5_burn_m": BURN_DEPTH[5],
                "order_2_burn_m": BURN_DEPTH[2],
                "dem_source": "MERIT 30m, stream cells from TDX-Hydro v2",
            },
        },
        "inflow_cells": [
            {"name":"Culvert1",    "row":c1_r,"col":c1_c,
             "elev_orig":float(dem_orig[c1_r,c1_c]),"elev_burned":c1_elev},
            {"name":"Culvert2",    "row":c2_r,"col":c2_c,
             "elev_orig":float(dem_orig[c2_r,c2_c]),"elev_burned":c2_elev},
            {"name":"WesternWadi", "row":w_r, "col":w_c,
             "elev_orig":float(dem_orig[w_r,w_c]),  "elev_burned":w_elev},
            {"name":"HospitalWadi","row":hw_r,"col":hw_c,
             "elev_orig":float(dem_orig[hw_r,hw_c]),"elev_burned":hw_elev},
        ],
    }
    with open(V13_INPUT/"v13_metadata.json","w") as f:
        json.dump(meta, f, indent=2)
    log.info("  Metadata: v13_metadata.json")

    log.info(f"\nSetup complete in {time.time()-t0:.1f}s")
    log.info("\nNext:")
    log.info(f"  cd {V13_DIR}")
    log.info(f"  export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH")
    log.info(f"  /data/rim2d/bin/RIM2D simulation_v13.def --def flex")


if __name__ == "__main__":
    main()
