#!/usr/bin/env python3
"""
NBO v2 — 2026-03-06 Flash Flood Event
Compound pluvial + fluvial simulation, 24 h from 16:00 on 2026-03-06.

Event description
-----------------
  2026-03-05: Intermittent rainfall throughout the day → fully saturated soil
  2026-03-06 16:00: Simulation start (t=0)
  2026-03-06 17:30: Heavy rainfall onset (t=5400 s)
  2026-03-06 17:30–21:30: Intense 4-hour burst → river overflow
  Observed damage: cars washed at -1.311°N/36.821°E and Kirinyaga Road -1.280°N/36.827°E

Rainfall data (24h totals from 5 gauges):
  Dagoretti       112.2 mm
  Moi Airbase     145.4 mm
  Wilson Airport  160.0 mm
  Kabete          117.4 mm
  Thika            59.6 mm
  Domain mean ≈ 119 mm (IDW)

Methodology
-----------
  • Spatial field : IDW (power=2) from 5 rain gauges → 30 m grid
  • Temporal shape: modified Huff Type-II curve; 65% of total in 4-h burst
                    centred at 19:30 (t=3.5 h after burst onset)
  • Antecedent    : fully saturated → inf_rate = 0, IWD = channel seed
  • Hydrograph    : rational method Q = C × i × A, C_eff = 0.85 (saturated)
                    90 entry points from river_entries_v1.csv
                    UP_AREA from HydroATLAS (order-5: 400–3000 km²;
                    lower orders scaled by Hack's law: A = 10 × 4^(order-2))
  • WSE BC        : Manning wide-rectangular channel

Outputs (in v2/)
----------------
  input/rain/rain_v2_t{NNN}.nc    48 half-hourly rainfall rasters
  input/fluvbound_mask_v2.nc      boundary cell mask
  input/inflowlocs_v2.txt         WSE timeseries (90 entry points)
  input/v2_metadata.json          run metadata
  simulation_v2.def               RIM2D flex definition file
  visualizations/v2_inputs.png    input summary

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python run_v2_event_flood.py
    cd v2 && ../../bin/RIM2D simulation_v2.def --def flex
"""

import json
import csv
from pathlib import Path

import numpy as np
import netCDF4
from pyproj import Transformer

WORK_DIR  = Path("/data/rim2d/nbo_2026")
V1_DIR    = WORK_DIR / "v1"
V2_DIR    = WORK_DIR / "v2"
INPUT_DIR = V2_DIR / "input"
RAIN_DIR  = INPUT_DIR / "rain"
VIS_DIR   = V2_DIR / "visualizations"

# ── Grid reference (same 30 m UTM-37S grid as v1) ──────────────────────────
DEM_PATH      = V1_DIR / "input" / "dem.nc"
IWD_PATH      = V1_DIR / "input" / "iwd.nc"
ENTRIES_CSV   = V1_DIR / "input" / "river_entries_v1.csv"
WS_SUMMARY    = V1_DIR / "input" / "watersheds" / "watershed_summary.json"

# ── Event parameters ────────────────────────────────────────────────────────
SIM_START_UTC = "2026-03-06T16:00:00Z"
SIM_DUR_S     = 86400          # 24 h
DT_RAIN_S     = 1800           # 30-min timesteps
N_RAIN        = SIM_DUR_S // DT_RAIN_S   # 48 steps

# Burst window in simulation seconds
BURST_START_S = 5400           # t = 1h30 → 17:30
BURST_END_S   = 19800          # t = 5h30 → 21:30

# Runoff coefficient — elevated for saturated antecedent conditions
C_EFF = 0.85

# Manning channel params (wide rectangular)
MANNINGS_N  = 0.035
CHANNEL_W   = 15.0             # assumed channel width (m)
CHANNEL_S   = 0.005            # assumed bed slope (m/m)

# ── Rain gauges (24h total from 16:00) ──────────────────────────────────────
GAUGES = [
    {"name": "Dagoretti",      "lat": -1.30203, "lon": 36.75980, "rain_24h_mm": 112.2},
    {"name": "Moi Airbase",    "lat": -1.27727, "lon": 36.86230, "rain_24h_mm": 145.4},
    {"name": "Wilson Airport", "lat": -1.32170, "lon": 36.81480, "rain_24h_mm": 160.0},
    {"name": "Kabete",         "lat": -1.20667, "lon": 36.76889, "rain_24h_mm": 117.4},
    {"name": "Thika",          "lat": -1.22275, "lon": 36.88859, "rain_24h_mm":  59.6},
]

# ── Damage locations for output cells ───────────────────────────────────────
DAMAGE_LOCS = [
    {"name": "Cars washed (Ngong Rd area)", "lat": -1.31125, "lon": 36.82077},
    {"name": "Kirinyaga Road flood",         "lat": -1.27954, "lon": 36.82727},
]

# ── HydroATLAS UP_AREA for the 8 legacy entry points (km²) ─────────────────
# Used to anchor stream-order scaling for the 90 new entry points
HYDROATLAS_UP_AREA = {
    # entry1 order5=1070, entry2 order5=3026, entry3 order4=796,
    # entry4 order4=388, entry5 order4=495, entry7 order3=118
}

# Empirical UP_AREA by stream order (km²) anchored to HydroATLAS medians
# Hack's law calibrated: A(order) = A5_med / 4^(5-order)
# A5 median from HydroATLAS = ~1500 km²
UP_AREA_BY_ORDER = {
    5: 1500.0,
    4:  375.0,
    3:   95.0,
    2:   24.0,
}

# ── Coordinate transformer ──────────────────────────────────────────────────
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32737", always_xy=True)
TO_LL  = Transformer.from_crs("EPSG:32737", "EPSG:4326", always_xy=True)


# ===========================================================================
# 1. Load grid
# ===========================================================================

def load_grid():
    ds = netCDF4.Dataset(str(DEM_PATH))
    x  = np.array(ds["x"][:])
    y  = np.array(ds["y"][:])
    vn = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[vn][:], dtype=np.float64)
    ds.close()
    dem[dem < -9000] = np.nan
    print(f"  Grid: {dem.shape}, dx={x[1]-x[0]:.0f} m")
    return x, y, dem


# ===========================================================================
# 2. Build temporal rainfall distribution (48 steps)
# ===========================================================================

def build_temporal_fractions():
    """
    Modified Huff Type-II curve for a saturated tropical event.

    Distribution of 24h total across 48 half-hourly steps (step 0 = 16:00):
      Steps  0– 2  (16:00–17:30)  pre-burst:  5% of total
      Steps  3–10  (17:30–21:30)  burst peak: 65% of total
                                  triangular, peak at step 6 (19:30–20:00)
      Steps 11–15  (21:30–00:00)  declining:  15% of total
      Steps 16–47  (00:00–16:00)  overnight:  15% of total
    """
    fracs = np.zeros(N_RAIN)

    # Pre-burst (steps 0-2): uniform 5%
    fracs[0:3] = 0.05 / 3

    # Burst (steps 3-10): triangular peak at step 6
    burst_weights = np.array([0.04, 0.08, 0.14, 0.20, 0.20, 0.16, 0.11, 0.07])
    fracs[3:11] = burst_weights * 0.65

    # Post-burst decline (steps 11-15): linear decay 15%
    decay = np.linspace(0.05, 0.01, 5)
    fracs[11:16] = decay / decay.sum() * 0.15

    # Overnight (steps 16-47): residual 15%
    fracs[16:48] = 0.15 / 32

    # Normalise to exactly 1.0
    fracs /= fracs.sum()
    return fracs


# ===========================================================================
# 3. IDW interpolation of gauge totals → 30 m rainfall grid
# ===========================================================================

def idw_rainfall(x_utm, y_utm, gauges, power=2):
    """
    IDW interpolation from gauge lat/lon totals onto the UTM 30m grid.
    Returns a 2D array of 24h totals (mm) in RIM2D row-major (y-first).
    """
    print("  IDW interpolating from 5 gauges...")
    ny, nx = len(y_utm), len(x_utm)
    XX, YY = np.meshgrid(x_utm, y_utm)   # shape (ny, nx)

    weights = np.zeros((len(gauges), ny, nx))
    values  = np.array([g["rain_24h_mm"] for g in gauges])

    for i, g in enumerate(gauges):
        gx, gy = TO_UTM.transform(g["lon"], g["lat"])
        d2 = (XX - gx)**2 + (YY - gy)**2
        d2 = np.maximum(d2, 1e6)   # min distance 1 km to avoid singularity
        weights[i] = 1.0 / d2**power

    w_sum = weights.sum(axis=0)
    rain_24h = np.zeros((ny, nx))
    for i in range(len(gauges)):
        rain_24h += (weights[i] / w_sum) * values[i]

    mn, mx, mean = rain_24h.min(), rain_24h.max(), rain_24h.mean()
    print(f"  Spatial rainfall: min={mn:.1f}  mean={mean:.1f}  max={mx:.1f} mm")
    return rain_24h


def build_rainfall_steps(rain_24h_grid, temporal_fracs):
    """
    For each timestep, compute rainfall intensity (mm/s = m³/m²/s × 1000).
    Returns list of 48 intensity grids (m/s).
    """
    steps = []
    for frac in temporal_fracs:
        depth_m = rain_24h_grid * frac / 1000.0   # m per timestep
        intensity_ms = depth_m / DT_RAIN_S          # m/s
        steps.append(intensity_ms)
    return steps


# ===========================================================================
# 4. Write NetCDF rainfall files
# ===========================================================================

def write_nc(data, x, y, path, varname="rainfall", units="m s-1"):
    ds = netCDF4.Dataset(str(path), "w")
    ds.createDimension("x", len(x))
    ds.createDimension("y", len(y))
    vx = ds.createVariable("x", "f8", ("x",)); vx[:] = x
    vy = ds.createVariable("y", "f8", ("y",)); vy[:] = y
    vd = ds.createVariable(varname, "f4", ("y", "x"),
                            fill_value=-9999.0)
    vd.units = units
    arr = data.astype(np.float32)
    arr[~np.isfinite(arr)] = -9999.0
    vd[:] = arr
    ds.close()


def write_rainfall_nc(steps, x, y):
    RAIN_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  Writing {len(steps)} rainfall NetCDF files...")
    for i, grid in enumerate(steps):
        path = RAIN_DIR / f"rain_v2_t{i+1:04d}.nc"
        write_nc(grid, x, y, path, varname="rain")
    peak_i = int(np.argmax([g.max() for g in steps]))
    print(f"  Peak step: t={peak_i+1:04d}  "
          f"({peak_i*30//60:02d}:{(peak_i*30)%60:02d} after 16:00)  "
          f"max intensity = {max(g.max() for g in steps)*1000*1800:.1f} mm/30min")


# ===========================================================================
# 5. Load entry points and assign catchment areas
# ===========================================================================

def load_entries():
    """
    Load all 90 entry points, but assign areas differently by category:

    CROSSING entries — rivers entering from outside the domain.
      Use full UP_AREA (HydroATLAS where available, else order-based).
      These are real upstream catchment inflows.

    INTERIOR / HEADWATER entries — segments entirely inside the domain.
      These receive rainfall directly from the pluvial component.
      Assign a small INCREMENTAL lateral area only (local sub-basin
      contributing to that reach between this and the next upstream node).
      Use SUB_AREA_BY_ORDER — much smaller than UP_AREA.
    """
    # Incremental lateral area per node for interior segments (km²)
    SUB_AREA_BY_ORDER = {5: 15.0, 4: 8.0, 3: 4.0, 2: 2.0}

    entries = []
    with open(str(ENTRIES_CSV)) as f:
        for row in csv.DictReader(f):
            so  = int(row["stream_order"])
            cat = row["category"]
            area = (UP_AREA_BY_ORDER[so] if cat == "crossing"
                    else SUB_AREA_BY_ORDER[so])
            entries.append({
                "entry_id":     int(row["entry_id"]),
                "lon":          float(row["lon"]),
                "lat":          float(row["lat"]),
                "stream_order": so,
                "category":     cat,
                "linkno":       int(row["linkno"]),
                "up_area_km2":  area,
            })

    # Override crossing entries with HydroATLAS UP_AREA where available
    try:
        with open(str(WS_SUMMARY)) as f:
            ws = json.load(f)
        hydroatlas_pts = []
        for name, d in ws.items():
            lv = d.get("levels", {})
            area = (lv.get("12", {}) or lv.get("10", {}) or {}).get("up_area_km2")
            if area:
                hydroatlas_pts.append({
                    "lon": d["lon"], "lat": d["lat"], "up_area_km2": area
                })
        for ha in hydroatlas_pts:
            dists = [((e["lon"]-ha["lon"])**2+(e["lat"]-ha["lat"])**2)**0.5
                     for e in entries]
            nearest = entries[int(np.argmin(dists))]
            if min(dists) < 0.02 and nearest["category"] == "crossing":
                nearest["up_area_km2"] = ha["up_area_km2"]
    except Exception:
        pass

    n_cross = sum(1 for e in entries if e["category"] == "crossing")
    n_int   = len(entries) - n_cross
    print(f"  Loaded {len(entries)} entry points  "
          f"({n_cross} crossing with full UP_AREA, {n_int} interior with lateral area)")
    return entries


# ===========================================================================
# 6. Compute synthetic hydrographs
# ===========================================================================

def time_of_concentration(area_km2):
    """Empirical tc (hours) from basin area — Kirpich-type."""
    return 0.3 * area_km2**0.4


def triangular_uh(tc_h, dt_h, n_steps):
    """Unit hydrograph: triangular, base = 2*tc, peak at tc."""
    t = np.arange(n_steps) * dt_h
    uh = np.zeros(n_steps)
    for i, ti in enumerate(t):
        if ti <= tc_h:
            uh[i] = ti / tc_h
        elif ti <= 2 * tc_h:
            uh[i] = (2 * tc_h - ti) / tc_h
    s = uh.sum()
    if s > 0:
        uh /= s
    return uh


def compute_hydrographs(entries, rain_24h_grid, x_utm, y_utm, temporal_fracs):
    """
    For each entry compute Q(t) = C × i(t) × A using basin-mean IDW rainfall
    convolved with a triangular unit hydrograph.
    """
    dt_h = DT_RAIN_S / 3600.0
    # Basin-mean rainfall: use the IDW value nearest the entry point
    for e in entries:
        ex, ey = TO_UTM.transform(e["lon"], e["lat"])
        ix = int(np.argmin(np.abs(x_utm - ex)))
        iy = int(np.argmin(np.abs(y_utm - ey)))
        ix = np.clip(ix, 0, rain_24h_grid.shape[1] - 1)
        iy = np.clip(iy, 0, rain_24h_grid.shape[0] - 1)
        e["rain_24h_mm"] = float(rain_24h_grid[iy, ix])

    hydrographs = []
    for e in entries:
        area_m2 = e["up_area_km2"] * 1e6
        tc_h    = time_of_concentration(e["up_area_km2"])
        uh      = triangular_uh(tc_h, dt_h, N_RAIN)

        # Instantaneous runoff (m³/s) per step = C × i × A
        rain_per_step_m = e["rain_24h_mm"] / 1000.0 * temporal_fracs
        i_ms = rain_per_step_m / DT_RAIN_S
        q_instant = C_EFF * i_ms * area_m2

        # Convolve with UH
        q_conv = np.convolve(q_instant, uh)[:N_RAIN]
        hydrographs.append(q_conv)

    return np.array(hydrographs)   # shape (n_entries, N_RAIN)


# ===========================================================================
# 7. Convert discharge to WSE and write RIM2D boundary files
# ===========================================================================

def q_to_wse(q, dem_elev):
    """
    Manning wide rectangular channel:  depth = (Q*n / (W*S^0.5))^(3/5)
    WSE = bed elevation + depth
    """
    depth = (np.maximum(q, 0) * MANNINGS_N / (CHANNEL_W * CHANNEL_S**0.5))**(3/5)
    return dem_elev + depth


def grid_index(lon, lat, x_utm, y_utm):
    ex, ey = TO_UTM.transform(lon, lat)
    ix = int(np.argmin(np.abs(x_utm - ex)))
    iy = int(np.argmin(np.abs(y_utm - ey)))
    return np.clip(ix, 0, len(x_utm)-1), np.clip(iy, 0, len(y_utm)-1)


def write_fluvbound_mask(entries, x_utm, y_utm, dem):
    """
    Each entry cell must have its 1-based entry index as the mask value.
    RIM2D counts flbounds = maxval(mask) and checks it equals ninflow.
    """
    mask = np.zeros_like(dem, dtype=np.float32)
    for i, e in enumerate(entries):
        ix, iy = grid_index(e["lon"], e["lat"], x_utm, y_utm)
        mask[iy, ix] = float(i + 1)   # 1-based index per entry
    path = INPUT_DIR / "fluvbound_mask_v2.nc"
    write_nc(mask, x_utm, y_utm, path, varname="Band1", units="-")
    n = int((mask > 0).sum())
    print(f"  Written: fluvbound_mask_v2.nc  ({n} boundary cells, max={int(mask.max())})")
    return mask


def write_inflowlocs(entries, hydrographs, x_utm, y_utm, dem):
    """
    RIM2D inflowlocs format (confirmed from v11/input/inflowlocs_v11.txt):
      Line 1: sim_dur (seconds)
      Line 2: dt between WSE values (seconds)
      Line 3: n_cells
      Each cell: ix  iy  wse_1  wse_2  ...  wse_N   (all on one line)
    """
    path = INPUT_DIR / "inflowlocs_v2.txt"
    n_entries = len(entries)

    lines = [
        str(SIM_DUR_S),
        str(DT_RAIN_S),
        str(n_entries),
    ]

    for i, e in enumerate(entries):
        ix, iy = grid_index(e["lon"], e["lat"], x_utm, y_utm)
        iy1 = iy + 1   # 1-based row (y) index  — col 1 in infl array
        ix1 = ix + 1   # 1-based col (x) index  — col 2 in infl array
        bed_elev = float(dem[iy, ix]) if np.isfinite(dem[iy, ix]) else 1600.0
        wse_series = q_to_wse(hydrographs[i], bed_elev)
        # RIM2D needs N+1 WSE values: t=0, t=dt, ..., t=boundlength
        # Prepend t=0 value (bed elevation = no inflow yet at sim start)
        wse_full = np.concatenate([[bed_elev], wse_series])
        wse_str = "\t".join(f"{w:.4f}" for w in wse_full)
        lines.append(f"{iy1}\t{ix1}\t{wse_str}")

    with open(str(path), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  Written: inflowlocs_v2.txt  ({n_entries} entries × {N_RAIN} steps)")

    # Report peak flows
    print("\n  Peak flows (top 10 by stream order):")
    peak_q = [(entries[i]["entry_id"], entries[i]["stream_order"],
               entries[i]["lat"], entries[i]["lon"],
               hydrographs[i].max()) for i in range(len(entries))]
    peak_q.sort(key=lambda x: -x[4])
    for eid, so, lat, lon, q in peak_q[:10]:
        print(f"    Entry {eid:3d} order={so} ({lat:.4f},{lon:.4f})  "
              f"Q_peak = {q:.1f} m³/s")


# ===========================================================================
# 8. Write simulation definition file
# ===========================================================================

def write_simdef(n_rain):
    # Compute output timing: every 30 min for 24h
    out_times = list(range(DT_RAIN_S, SIM_DUR_S + DT_RAIN_S, DT_RAIN_S))
    out_str   = " ".join(str(t) for t in out_times)

    content = f"""# RIM2D model definition file (version 2.0)
# NBO v2 — 2026-03-06 Flash Flood Event (Compound Pluvial + Fluvial)
# Gauge-interpolated rainfall | 90 river entry points | C={C_EFF} saturated
# Simulation: {SIM_START_UTC} + 24h

###### INPUT RASTERS ######
**DEM**
../v1/input/dem.nc
**buildings**
../v1/input/buildings.nc
**IWD**
file
../v1/input/iwd.nc
**roughness**
file
../v1/input/roughness.nc
**pervious_surface**
../v1/input/pervious_surface.nc
**sealed_surface**
../v1/input/sealed_surface.nc
**sewershed**
../v1/input/sewershed_v1_full.nc

###### BOUNDARIES ######
**fluvial_boundary**
input/inflowlocs_v2.txt

###### RAINFALL (gauge-interpolated, 30-min timesteps) ######
**pluvial_raster_nr**
{n_rain}
**pluvial_dt**
{DT_RAIN_S}
**pluvial_start**
0
**pluvial_base_fn**
input/rain/rain_v2_t

###### OUTPUT FILE SPECIFICATIONS ######
**output_base_fn**
output/nbo_v2_
**out_cells**
input/outflowlocs_v2.txt
**out_timing_nr**
{len(out_times)}
**out_timing**
{out_str}

###### MODEL PARAMETERS ######
**dt**
1
**sim_dur**
{SIM_DUR_S}
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
input/fluvbound_mask_v2.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    path = V2_DIR / "simulation_v2.def"
    with open(str(path), "w") as f:
        f.write(content)
    print(f"  Written: simulation_v2.def")


# ===========================================================================
# 9. Save metadata
# ===========================================================================

def save_metadata(entries, rain_24h_grid, temporal_fracs):
    meta = {
        "event":           "2026-03-06 Nairobi Flash Flood",
        "sim_start":       SIM_START_UTC,
        "sim_duration_h":  SIM_DUR_S / 3600,
        "burst_start_h":   BURST_START_S / 3600,
        "burst_end_h":     BURST_END_S / 3600,
        "C_eff":           C_EFF,
        "inf_rate":        0,
        "antecedent":      "fully saturated",
        "n_rain_steps":    N_RAIN,
        "rain_dt_s":       DT_RAIN_S,
        "n_entry_points":  len(entries),
        "gauges":          GAUGES,
        "damage_locations": DAMAGE_LOCS,
        "domain_mean_rain_mm": float(rain_24h_grid.mean()),
        "temporal_fracs":  temporal_fracs.tolist(),
        "entry_areas": {
            str(e["entry_id"]): {
                "up_area_km2":  e["up_area_km2"],
                "stream_order": e["stream_order"],
                "rain_24h_mm":  e.get("rain_24h_mm", None),
            }
            for e in entries
        },
    }
    path = INPUT_DIR / "v2_metadata.json"
    with open(str(path), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"  Written: v2_metadata.json")


# ===========================================================================
# 10. Visualization
# ===========================================================================

def visualize(rain_24h_grid, x_utm, y_utm, temporal_fracs, hydrographs,
              entries, dem):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    VIS_DIR.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 3, figsize=(22, 14))

    # Convert UTM corners to lat/lon for imshow extent
    lon0, lat0 = TO_LL.transform(float(x_utm[0]),  float(y_utm[0]))
    lon1, lat1 = TO_LL.transform(float(x_utm[-1]), float(y_utm[-1]))
    extent_ll = [lon0, lon1, lat0, lat1]

    # ── Panel 1: 24h rainfall spatial ──
    ax = axes[0, 0]
    im = ax.imshow(rain_24h_grid, origin="lower", extent=extent_ll,
                   cmap="Blues", vmin=50, vmax=180)
    plt.colorbar(im, ax=ax, label="24h rainfall (mm)")
    # Gauge markers
    cmap_g = plt.cm.RdYlGn
    for g in GAUGES:
        c = cmap_g((g["rain_24h_mm"] - 50) / 130)
        ax.plot(g["lon"], g["lat"], "o", color=c, markersize=12,
                markeredgecolor="black", markeredgewidth=1, zorder=5)
        ax.annotate(f"{g['name']}\n{g['rain_24h_mm']} mm",
                    (g["lon"], g["lat"]), textcoords="offset points",
                    xytext=(6, 4), fontsize=8, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="gray", alpha=0.85))
    # Damage locations
    for d in DAMAGE_LOCS:
        ax.plot(d["lon"], d["lat"], "x", color="red", markersize=14,
                markeredgewidth=2.5, zorder=10)
        ax.annotate(d["name"], (d["lon"], d["lat"]),
                    textcoords="offset points", xytext=(6, -12),
                    fontsize=7.5, color="red")
    ax.set_title("24h Rainfall — IDW from 5 Gauges", fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.grid(alpha=0.2)

    # ── Panel 2: Temporal distribution ──
    ax = axes[0, 1]
    times_h = np.arange(N_RAIN) * DT_RAIN_S / 3600
    intensity_mm30 = temporal_fracs * 160.0  # Wilson Airport max as example
    bar_colors = ["#e06600" if (BURST_START_S/3600 <= t < BURST_END_S/3600)
                  else "#4d8cff" for t in times_h]
    ax.bar(times_h, intensity_mm30, width=0.45, color=bar_colors, alpha=0.85)
    ax.axvline(BURST_START_S/3600, color="red", linestyle="--", lw=1.5,
               label="Burst onset 17:30")
    ax.axvline(BURST_END_S/3600,   color="red", linestyle=":",  lw=1.5,
               label="Burst end 21:30")
    ax.set_xlabel("Hours after 16:00")
    ax.set_ylabel("Rainfall intensity (mm/30 min)\n[Wilson Airport scale]")
    ax.set_title("Temporal Distribution — Huff Type-II", fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.2)
    # Add clock labels
    clock = ["16:00","17:00","18:00","19:00","20:00","21:00",
             "22:00","23:00","00:00"]
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(range(9))
    ax2.set_xticklabels(clock, fontsize=8)

    # ── Panel 3: Entry points coloured by stream order ──
    ax = axes[0, 2]
    order_c = {2: "#80b3ff", 3: "#4d8cff", 4: "#1a66ff", 5: "#0033aa"}
    for so in [2, 3, 4, 5]:
        pts = [e for e in entries if e["stream_order"] == so]
        if pts:
            ax.scatter([p["lon"] for p in pts], [p["lat"] for p in pts],
                       c=order_c[so], s=18*(so-1), edgecolors="white",
                       linewidths=0.4, zorder=5, label=f"Order {so} ({len(pts)})")
    # Domain box
    bx_lons = [36.6, 37.1, 37.1, 36.6, 36.6]
    bx_lats = [-1.402, -1.402, -1.098, -1.098, -1.402]
    ax.plot(bx_lons, bx_lats, "k--", lw=1.8)
    for d in DAMAGE_LOCS:
        ax.plot(d["lon"], d["lat"], "rx", markersize=12, markeredgewidth=2, zorder=10)
    ax.set_title(f"90 River Entry Points by Stream Order", fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.legend(fontsize=9, loc="upper left"); ax.grid(alpha=0.2)
    ax.set_aspect("equal")

    # ── Panel 4: Peak discharge map ──
    ax = axes[1, 0]
    peak_q = np.array([hydrographs[i].max() for i in range(len(entries))])
    sc = ax.scatter([e["lon"] for e in entries], [e["lat"] for e in entries],
                    c=np.log10(np.maximum(peak_q, 1)), cmap="hot_r",
                    s=[20 + 3*q**0.5 for q in peak_q],
                    edgecolors="black", linewidths=0.4, zorder=5)
    plt.colorbar(sc, ax=ax, label="log₁₀(Q_peak m³/s)")
    ax.plot(bx_lons, bx_lats, "k--", lw=1.8, label="Domain")
    for g in GAUGES:
        ax.plot(g["lon"], g["lat"], "b^", markersize=7, zorder=6)
    for d in DAMAGE_LOCS:
        ax.plot(d["lon"], d["lat"], "rx", markersize=12, markeredgewidth=2, zorder=10)
    ax.set_title("Peak Discharge at Entry Points", fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.grid(alpha=0.2); ax.set_aspect("equal")

    # ── Panel 5: Hydrographs — order-5 + damage-adjacent entries ──
    ax = axes[1, 1]
    t_clock = times_h  # hours after 16:00
    order5 = [i for i, e in enumerate(entries) if e["stream_order"] == 5]
    # Find entries nearest to damage locations
    damage_idxs = []
    for d in DAMAGE_LOCS:
        dists = [((e["lon"]-d["lon"])**2 + (e["lat"]-d["lat"])**2)**0.5
                 for e in entries]
        damage_idxs.append(int(np.argmin(dists)))

    plot_idxs = list(dict.fromkeys(order5 + damage_idxs))[:8]
    colors_h = plt.cm.tab10(np.linspace(0, 0.9, len(plot_idxs)))
    for ci, idx in enumerate(plot_idxs):
        e = entries[idx]
        lbl = (f"Entry {e['entry_id']} ord={e['stream_order']} "
               f"({e['up_area_km2']:.0f}km²)")
        ax.plot(t_clock, hydrographs[idx], color=colors_h[ci],
                linewidth=1.8, label=lbl)
    ax.axvspan(BURST_START_S/3600, BURST_END_S/3600, alpha=0.08, color="red",
               label="Burst window")
    ax.set_xlabel("Hours after 16:00")
    ax.set_ylabel("Discharge (m³/s)")
    ax.set_title("Synthetic Hydrographs — Order-5 + Damage-Adjacent", fontweight="bold")
    ax.legend(fontsize=7.5, loc="upper right"); ax.grid(alpha=0.2)
    # Clock axis
    ax3 = ax.twiny(); ax3.set_xlim(ax.get_xlim())
    ax3.set_xticks(range(9)); ax3.set_xticklabels(clock, fontsize=8)

    # ── Panel 6: Damage locations on DEM ──
    ax = axes[1, 2]
    dem_plot = np.ma.masked_invalid(dem)
    ax.imshow(dem_plot, origin="lower", extent=extent_ll,
              cmap="terrain", alpha=0.7)
    # Gauge stations
    for g in GAUGES:
        ax.plot(g["lon"], g["lat"], "b^", markersize=9,
                markeredgecolor="black", markeredgewidth=0.8, zorder=5)
        ax.annotate(f"{g['rain_24h_mm']:.0f}mm", (g["lon"], g["lat"]),
                    textcoords="offset points", xytext=(4, 4), fontsize=7.5,
                    color="navy",
                    bbox=dict(boxstyle="round,pad=0.1", fc="white",
                              ec="navy", alpha=0.7))
    # Damage markers — large red X
    for d in DAMAGE_LOCS:
        ax.plot(d["lon"], d["lat"], "X", color="red", markersize=16,
                markeredgecolor="white", markeredgewidth=1.5, zorder=10)
        ax.annotate(d["name"], (d["lon"], d["lat"]),
                    textcoords="offset points", xytext=(8, -14),
                    fontsize=8, color="red", fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="red", alpha=0.85))
    ax.plot(bx_lons, bx_lats, "k--", lw=1.8)
    ax.set_title("Damage Locations + Rainfall Gauges on DEM", fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.grid(alpha=0.2)
    # River distance annotation
    ax.annotate("← Nairobi River corridor", xy=(36.82, -1.29),
                fontsize=9, color="navy", style="italic",
                bbox=dict(boxstyle="round,pad=0.2", fc="lightyellow",
                          ec="navy", alpha=0.8))

    fig.suptitle(
        "NBO v2 — 2026-03-06 Flash Flood Event\n"
        "Compound Pluvial + Fluvial | 24h from 16:00 | "
        f"C_eff={C_EFF} (saturated) | 90 river entry points",
        fontsize=14, fontweight="bold",
    )
    fig.tight_layout()
    out = VIS_DIR / "v2_inputs.png"
    fig.savefig(str(out), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 65)
    print("NBO v2 — 2026-03-06 Flash Flood Event Setup")
    print(f"  Start: {SIM_START_UTC}  |  Duration: 24 h")
    print(f"  Burst: 17:30–21:30 (4 h)  |  C_eff = {C_EFF} (saturated)")
    print("=" * 65)

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    V2_DIR.mkdir(parents=True, exist_ok=True)
    (V2_DIR / "output").mkdir(exist_ok=True)

    print("\n[1] Loading grid...")
    x_utm, y_utm, dem = load_grid()

    print("\n[2] Building temporal distribution (48 × 30-min steps)...")
    temporal_fracs = build_temporal_fractions()
    burst_frac = temporal_fracs[3:11].sum()
    print(f"  Burst fraction (steps 3-10): {burst_frac:.1%}")
    print(f"  Peak step intensity: {temporal_fracs.max()*100:.2f}% of 24h total")

    print("\n[3] IDW spatial interpolation from 5 gauges...")
    rain_24h = idw_rainfall(x_utm, y_utm, GAUGES)

    print("\n[4] Building 48 rainfall intensity grids...")
    rain_steps = build_rainfall_steps(rain_24h, temporal_fracs)

    print("\n[5] Writing rainfall NetCDF files...")
    write_rainfall_nc(rain_steps, x_utm, y_utm)

    print("\n[6] Loading 90 river entry points...")
    entries = load_entries()

    print("\n[7] Computing synthetic hydrographs...")
    hydrographs = compute_hydrographs(entries, rain_24h, x_utm, y_utm,
                                      temporal_fracs)
    total_peak = hydrographs.sum(axis=0).max()
    print(f"  Total combined peak inflow: {total_peak:.0f} m³/s")

    print("\n[8] Writing boundary condition files...")
    write_fluvbound_mask(entries, x_utm, y_utm, dem)
    write_inflowlocs(entries, hydrographs, x_utm, y_utm, dem)

    print("\n[9] Writing simulation definition file...")
    write_simdef(N_RAIN)

    print("\n[10] Saving metadata...")
    save_metadata(entries, rain_24h, temporal_fracs)

    print("\n[11] Generating input visualization...")
    visualize(rain_24h, x_utm, y_utm, temporal_fracs, hydrographs,
              entries, dem)

    # Summary
    print("\n" + "=" * 65)
    print("SETUP COMPLETE")
    print("=" * 65)
    domain_mean = rain_24h.mean()
    print(f"  Domain-mean 24h rainfall:     {domain_mean:.1f} mm")
    print(f"  Peak 24h rainfall (grid max): {rain_24h.max():.1f} mm")
    print(f"  Burst period intensity:       "
          f"~{domain_mean*burst_frac/(BURST_END_S-BURST_START_S)*3600:.1f} mm/hr peak")
    print(f"  Entry points:                 {len(entries)}")
    print(f"  Rainfall files:               {N_RAIN}")
    print(f"\nRun simulation:")
    print(f"  cd {V2_DIR}")
    print(f"  ../../bin/RIM2D simulation_v2.def --def flex")
    print("=" * 65)


if __name__ == "__main__":
    main()
