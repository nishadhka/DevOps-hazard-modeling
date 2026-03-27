#!/usr/bin/env python3
"""
v11 — Compound Flooding: Culvert Overflow + Nile-Blocked Western Wadi.

Three inflow boundaries:
  1. Culvert 1 (25 km²) — eastern wadi through culvert opening
  2. Culvert 2 (35 km²) — central wadi through culvert opening
  3. Western Wadi (75 km²) — blocked by Nile peak, backs into settlement

The HydroATLAS level-12 sub-basin is 194.5 km². Of this:
  - 25 km² → Culvert 1 (wadi 160176763)
  - 35 km² → Culvert 2 (wadi 160245676)
  - ~60 km² → eastern Order 5 drainage (exits to Nile independently)
  - ~75 km² → western drainage (blocked during Nile peak flood)

During the Aug 28 Nile peak (31,694 m³/s from GEOGloWS), the western drainage
outlet is submerged. The western wadi system's runoff can't exit to the Nile,
so it backs up and flows eastward into the settlement — compound flooding.

See V11_RIVER_NETWORK_ANALYSIS.md for full details.

Execution:
    micromamba run -n zarrv3 python run_v11_synthetic_flood.py
"""

import json
import logging
import time
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
from pyproj import Transformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# -- Paths --------------------------------------------------------------------
WORK_DIR = Path("/data/rim2d/nile_highres")
V10_DIR = WORK_DIR / "v10"
V11_DIR = WORK_DIR / "v11"
INPUT_DIR = V10_DIR / "input"           # reuse v10 terrain inputs
V11_INPUT = V11_DIR / "input"
V11_OUTPUT = V11_DIR / "output"

# Watershed data (still used for basin polygon / IMERG download extent)
WS_DIR = V10_DIR / "input" / "watersheds"
WS_SUMMARY = WS_DIR / "watershed_summary.json"

SA_KEY = (
    "/data/08-2023/working_notes_jupyter/ignore_nka_gitrepos/"
    "cno-e4drr/devops/earth-engine-service-account/keys/"
    "earthengine-sa-20260130-key.json"
)

# -- Simulation timing --------------------------------------------------------
SIM_DUR = 3196800       # 37 days (Jul 25 — Aug 31, covers peak rain + Nile flood)
DT_INFLOW = 1800        # 30-min boundary timestep
N_RAIN = 1824           # 38 days * 48 half-hours (full IMERG period)
N_WSE = SIM_DUR // DT_INFLOW + 1  # 1777 WSE values

# IMERG config
GEE_COLLECTION = "NASA/GPM_L3/IMERG_V07"
GEE_BAND = "precipitation"
START_DATE = "2025-07-25"
END_DATE = "2025-09-01"

# -- Culvert parameters -------------------------------------------------------
# CORRECTED: catchment areas from TDX-Hydro wadi analysis
# See V11_RIVER_NETWORK_ANALYSIS.md for derivation
CULVERTS = [
    {
        "name": "Culvert1",
        "lat": 19.547450,
        "lon": 33.339139,
        "catchment_km2": 25.0,      # From wadi 160176763 (Order 2, 12 km)
        "feeding_wadi": 160176763,
    },
    {
        "name": "Culvert2",
        "lat": 19.550000,
        "lon": 33.325906,
        "catchment_km2": 35.0,      # From wadi 160245676 (Order 2, 14 km) + 160308747
        "feeding_wadi": 160245676,
    },
]

# Western wadi entry — blocked by Nile peak flood
WESTERN_ENTRY = {
    "name": "WesternWadi",
    "lat": 19.550,
    "lon": 33.300,              # Low point where western wadi meets concrete channel
    "catchment_km2": 75.0,      # Western portion of HydroATLAS basin
    "feeding_wadis": [160308747, 160333274, 160149900],
}

# GEOGloWS data for Nile blocking factor
GEOGLOWS_CSV = WORK_DIR / "visualizations" / "geoglows_rivers_jul_aug2024.csv"
NILE_REACH_ID = 160437229       # Nile at Abu Hamad

CULVERT_WIDTH = 2.0     # m (box culvert)
CULVERT_HEIGHT = 2.0    # m
N_MANNING = 0.015       # concrete
SLOPE = 0.005           # 0.5%

# CORRECTED: runoff coefficient for intense flash flood on bare desert
# Literature range: 0.50-0.80 for crusted bare soil during intense events
# (Wheater et al. 2008; Morin & Yakir 2014)
RUNOFF_COEFF = 0.65

# IMERG peak intensification factor
# IMERG 0.1-deg resolution smooths convective cells (Guilloteau et al. 2021)
# Factor of 2-5x for localized storms captured in a 0.1° pixel
# Bounded: 1.0 (no correction) to 5.0 (extreme sub-pixel concentration)
IMERG_INTENSIFICATION_BOUNDS = (1.0, 5.0)

# Target: ~0.6m mean flood depth at buildings (anecdotal observation)
TARGET_BUILDING_DEPTH_M = 0.6

# -- Helper functions ---------------------------------------------------------

def load_nc(path):
    """Load a RIM2D NetCDF file, return (data, x, y)."""
    ds = netCDF4.Dataset(str(path))
    x = ds["x"][:]
    y = ds["y"][:]
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    data[data < -9000] = np.nan
    return data, x, y


def latlon_to_grid(lat, lon, x, y):
    """Convert lat/lon to grid row/col indices."""
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    utm_x, utm_y = to_utm.transform(lon, lat)
    col = int(np.argmin(np.abs(x - utm_x)))
    row = int(np.argmin(np.abs(y - utm_y)))
    return row, col, utm_x, utm_y


# -- Watershed / basin functions (for IMERG download extent only) -------------

def load_basin_polygon(culvert_name, level):
    """Load basin GeoJSON polygon for a culvert at a given level."""
    geojson_path = WS_DIR / f"{culvert_name}_level{level:02d}.geojson"
    if not geojson_path.exists():
        return None
    with open(str(geojson_path)) as f:
        fc = json.load(f)
    return fc["features"][0]["geometry"]


def get_basin_bounding_box():
    """Get bounding box of basin polygon (for IMERG download extent)."""
    for level in [12, 10, 8]:
        geom = load_basin_polygon("Culvert1", level)
        if geom is not None:
            coords = []
            if geom["type"] == "Polygon":
                coords = geom["coordinates"][0]
            elif geom["type"] == "MultiPolygon":
                for poly in geom["coordinates"]:
                    coords.extend(poly[0])
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            return {
                "west": min(lons), "east": max(lons),
                "south": min(lats), "north": max(lats),
            }, geom, level
    return None, None, None


# -- IMERG rainfall -----------------------------------------------------------

def init_ee():
    """Initialize Earth Engine."""
    import ee
    with open(SA_KEY) as f:
        key = json.load(f)
    creds = ee.ServiceAccountCredentials(key["client_email"], SA_KEY)
    ee.Initialize(credentials=creds)
    logger.info(f"EE initialized: {key['client_email']}")
    return ee


def download_basin_rainfall(ee_module, basin_bbox, basin_geom_dict=None):
    """Download IMERG rainfall over the basin extent via GEE.

    Returns: times (datetime64), basin_mean_rain (mm/hr) per timestep
    """
    import pandas as pd

    bbox = ee_module.Geometry.Rectangle([
        basin_bbox["west"] - 0.05,
        basin_bbox["south"] - 0.05,
        basin_bbox["east"] + 0.05,
        basin_bbox["north"] + 0.05,
    ])

    if basin_geom_dict is not None:
        basin_poly = ee_module.Geometry(basin_geom_dict)
    else:
        basin_poly = bbox

    col = (
        ee_module.ImageCollection(GEE_COLLECTION)
        .filterDate(START_DATE, END_DATE)
        .filterBounds(bbox)
        .select(GEE_BAND)
    )

    n_images = col.size().getInfo()
    logger.info(f"  IMERG images over basin: {n_images}")

    if n_images == 0:
        raise RuntimeError("No IMERG images found for basin extent")

    def compute_mean(image):
        mean_val = image.reduceRegion(
            reducer=ee_module.Reducer.mean(),
            geometry=basin_poly,
            scale=11132,
            maxPixels=1e8,
        )
        return image.set("basin_mean_precip", mean_val.get(GEE_BAND))

    col_with_means = col.map(compute_mean)

    logger.info("  Fetching basin-mean rainfall time series...")
    feat_list = col_with_means.aggregate_array("basin_mean_precip").getInfo()
    time_list = col_with_means.aggregate_array("system:time_start").getInfo()

    times = np.array(time_list, dtype=np.int64)
    rain_vals = np.array(
        [v if v is not None else 0.0 for v in feat_list],
        dtype=np.float64,
    )

    sort_idx = np.argsort(times)
    times = times[sort_idx]
    rain_vals = rain_vals[sort_idx]

    times_dt = pd.to_datetime(times, unit="ms").values.astype("datetime64[ns]")

    total_mm = np.sum(rain_vals) * 0.5
    peak_rate = np.max(rain_vals)
    n_wet = int(np.sum(rain_vals > 0.1))

    logger.info(f"  Basin-mean total: {total_mm:.1f} mm")
    logger.info(f"  Peak rate: {peak_rate:.2f} mm/hr")
    logger.info(f"  Wet timesteps: {n_wet}/{len(rain_vals)}")

    return times_dt, rain_vals


# -- Hydrograph computation ---------------------------------------------------

def make_triangular_uh(tc_hours, dt_s):
    """Create a triangular unit hydrograph with time of concentration tc."""
    tc_s = tc_hours * 3600.0
    tp = tc_s
    tb = 2.0 * tc_s

    n_steps = int(np.ceil(tb / dt_s)) + 1
    t = np.arange(n_steps) * dt_s

    uh = np.zeros(n_steps)
    for i, ti in enumerate(t):
        if ti <= tp:
            uh[i] = ti / tp
        elif ti <= tb:
            uh[i] = (tb - ti) / (tb - tp)
        else:
            uh[i] = 0.0

    uh /= uh.sum()
    return uh


def compute_tc_hours(area_km2):
    """Estimate time of concentration from catchment area.

    Uses Kirpich-style empirical formula for arid basins.
    tc ~ 0.3 * A^0.4 hours (where A in km2)
    For 25 km2 -> tc ~ 1.2 hours
    For 35 km2 -> tc ~ 1.4 hours
    """
    tc = 0.3 * area_km2**0.4
    tc = max(0.5, min(tc, 12.0))
    return tc


def rational_method_hydrograph(rain_rates_mmhr, catchment_m2, runoff_coeff,
                                uh, dt_s):
    """Compute inflow hydrograph using rational method + unit hydrograph.

    Q(t) = C * I(t) * A  convolved with triangular UH.
    """
    rain_ms = rain_rates_mmhr / (1000.0 * 3600.0)
    q_instant = runoff_coeff * rain_ms * catchment_m2
    q_conv = np.convolve(q_instant, uh, mode="full")[:len(rain_rates_mmhr)]
    return q_conv


def flow_to_wse(q, dem_elev):
    """Convert flow rate to water surface elevation at culvert.

    Uses Manning's equation for rectangular box culvert.
    When Q > culvert capacity, water pressurizes and backs up.
    """
    if q <= 0:
        return dem_elev

    w = CULVERT_WIDTH
    h = CULVERT_HEIGHT
    n = N_MANNING
    s = SLOPE

    a_full = w * h
    p_full = 2 * h + w
    r_full = a_full / p_full
    q_full = (1.0 / n) * a_full * r_full**(2.0/3.0) * s**0.5

    if q <= q_full:
        d_lo, d_hi = 0.001, h
        for _ in range(50):
            d_mid = (d_lo + d_hi) / 2.0
            a = w * d_mid
            p = w + 2 * d_mid
            r = a / p
            q_test = (1.0 / n) * a * r**(2.0/3.0) * s**0.5
            if q_test < q:
                d_lo = d_mid
            else:
                d_hi = d_mid
        depth = (d_lo + d_hi) / 2.0
    else:
        q_excess = q - q_full
        cd = 0.6
        g = 9.81
        h_overflow = (q_excess / (cd * w * (2.0 * g)**0.5))**(2.0/3.0)
        depth = h + h_overflow

    depth = min(depth, 10.0)
    return dem_elev + depth


def load_nile_blocking_factor(n_rain, dt_s):
    """Load GEOGloWS Nile flow and compute blocking factor for western drainage.

    blocking(t) = (Q_nile(t) - Q_min) / (Q_max - Q_min)  clamped [0, 1]

    When Nile is at baseline (~15k m³/s): blocking ≈ 0 → western drainage exits freely
    When Nile is at peak (~31.7k m³/s): blocking = 1.0 → all western runoff enters settlement

    Returns: blocking_factor array aligned to IMERG 30-min timesteps (length n_rain)
    """
    if not GEOGLOWS_CSV.exists():
        logger.warning(f"  GEOGloWS CSV not found: {GEOGLOWS_CSV}")
        logger.warning("  Using constant blocking factor = 0.7 (assumed peak period)")
        return np.full(n_rain, 0.7)

    df = pd.read_csv(str(GEOGLOWS_CSV), parse_dates=["time"])
    nile_col = f"Q_{NILE_REACH_ID}_m3s"
    if nile_col not in df.columns:
        logger.warning(f"  Nile column {nile_col} not in CSV, using constant 0.7")
        return np.full(n_rain, 0.7)

    q_nile = df[nile_col].values
    q_min = float(np.min(q_nile))
    q_max = float(np.max(q_nile))
    logger.info(f"  Nile flow range: {q_min:.0f} — {q_max:.0f} m³/s")

    # GEOGloWS CSV is from 2024 but IMERG data is from 2025.
    # Align by day-of-year: shift CSV dates forward by 1 year.
    times_csv = df["time"].values
    csv_year = pd.Timestamp(times_csv[0]).year
    imerg_year = int(START_DATE[:4])
    year_offset = np.timedelta64(imerg_year - csv_year, "Y")
    # More precise: shift each timestamp by exactly (imerg_year - csv_year) years
    times_shifted = pd.to_datetime(times_csv).map(
        lambda t: t.replace(year=imerg_year)
    ).values

    # Create 30-min target grid aligned to IMERG (START_DATE to END_DATE)
    t0 = np.datetime64(START_DATE)
    t_target = t0 + np.arange(n_rain) * np.timedelta64(dt_s, "s")

    # Interpolate Nile flow to 30-min IMERG steps
    times_h_f = times_shifted.astype("datetime64[s]").astype(np.float64)
    t_target_f = t_target.astype("datetime64[s]").astype(np.float64)
    q_interp = np.interp(t_target_f, times_h_f, q_nile, left=q_nile[0], right=q_nile[-1])

    logger.info(f"  Date alignment: CSV {csv_year} → IMERG {imerg_year} "
                f"(shifted by {imerg_year - csv_year} year)")
    logger.info(f"  IMERG range: {START_DATE} to {END_DATE}")
    logger.info(f"  Nile flow at IMERG start: {q_interp[0]:.0f} m³/s, "
                f"end: {q_interp[-1]:.0f} m³/s")

    # Compute blocking factor
    blocking = (q_interp - q_min) / (q_max - q_min + 1e-10)
    blocking = np.clip(blocking, 0.0, 1.0)

    logger.info(f"  Blocking factor: min={blocking.min():.3f}, max={blocking.max():.3f}, "
                f"mean={blocking.mean():.3f}")
    peak_idx = int(np.argmax(blocking))
    logger.info(f"  Peak blocking at timestep {peak_idx} "
                f"(day {peak_idx * dt_s / 86400:.1f} from {START_DATE})")

    return blocking


def flow_to_wse_open(q, dem_elev, channel_width=5.0):
    """Convert flow rate to WSE for an open channel entry (western wadi).

    Uses Manning's equation for a wide rectangular channel.
    No culvert constriction — water spreads across the low point.
    """
    if q <= 0:
        return dem_elev

    n = 0.030  # natural channel (gravel/sand wadi)
    s = 0.003  # gentle slope at low point

    # Manning's for wide rectangular channel: Q = (1/n) * w * d^(5/3) * S^(1/2)
    # Solve for d: d = (Q * n / (w * S^0.5))^(3/5)
    depth = (q * n / (channel_width * s**0.5))**(3.0/5.0)
    depth = min(depth, 10.0)
    return dem_elev + depth


# -- Output writers -----------------------------------------------------------

def write_boundary_mask(culvert_cells, dem, x, y, out_path):
    """Write fluvial boundary mask raster with zone IDs at culvert cells."""
    nrows, ncols = dem.shape
    mask = np.zeros((nrows, ncols), dtype=np.float32)

    for i, (row, col, name) in enumerate(culvert_cells):
        mask[row, col] = float(i + 1)

    ds = netCDF4.Dataset(str(out_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.history = "v11: culvert inflow boundary mask (wadi-derived catchments)"
    ds.createDimension("x", ncols)
    ds.createDimension("y", nrows)
    xv = ds.createVariable("x", "f8", ("x",))
    xv[:] = x
    yv = ds.createVariable("y", "f8", ("y",))
    yv[:] = y
    band = ds.createVariable("Band1", "f4", ("y", "x"),
                             fill_value=np.float32(-9999.0))
    band[:] = mask
    ds.close()
    logger.info(f"  Written: {out_path.name} (max zone = {int(mask.max())})")


def write_inflowlocs(culvert_cells, wse_timeseries, out_path, sim_dur, dt):
    """Write inflowlocs.txt with culvert WSE timeseries."""
    n_cells = len(culvert_cells)
    n_wse = wse_timeseries[0].shape[0]

    with open(str(out_path), "w") as f:
        f.write(f"{sim_dur}\n")
        f.write(f"{dt}\n")
        f.write(f"{n_cells}\n")

        for i, (row, col, name) in enumerate(culvert_cells):
            wse = wse_timeseries[i]
            row_1 = row + 1
            col_1 = col + 1
            vals = [str(row_1), str(col_1)]
            vals.extend(f"{v:.3f}" for v in wse)
            f.write("\t".join(vals) + "\n")

    logger.info(f"  Written: {out_path.name} ({n_cells} cells, {n_wse} WSE values each)")


def write_simulation_def(out_path, rain_nr):
    """Write v11 simulation definition file (flex format)."""
    out_interval = 21600  # 6 hours
    n_out = SIM_DUR // out_interval
    out_times = " ".join(str(t) for t in range(out_interval, SIM_DUR + 1, out_interval))

    content = f"""# RIM2D model definition file (version 2.0)
# Nile high-resolution — v11 COMPOUND FLOODING
# Same domain as v10 (386 x 297, ~30m)
# 3 inflow boundaries: 2 culverts (25+35 km²) + western wadi (75 km², Nile-blocked)
# IMERG peak intensified for sub-pixel variability; C=0.65

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
input/inflowlocs_v11.txt

# RAINFALL — 2025 IMERG (same as v10)
**pluvial_raster_nr**
{rain_nr}
**pluvial_dt**
1800
**pluvial_start**
0
**pluvial_base_fn**
../v10/input/rain/imerg_v10_t

###### OUTPUT FILE SPECIFICATIONS ######
**output_base_fn**
output/nile_v11_
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
input/fluvbound_mask_v11.nc
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
    logger.info(f"  Written: {out_path.name}")


# -- Main ---------------------------------------------------------------------

def main():
    t0 = time.time()

    logger.info("=" * 70)
    logger.info("v11 — Compound Flooding: Culvert Overflow + Nile-Blocked Western Wadi")
    logger.info("=" * 70)
    logger.info("  3 inflow boundaries:")
    logger.info("    Culvert 1: 25 km² (eastern wadi)")
    logger.info("    Culvert 2: 35 km² (central wadi)")
    logger.info("    Western Wadi: 75 km² (blocked by Nile peak)")
    logger.info("")

    # Create output directories
    V11_DIR.mkdir(parents=True, exist_ok=True)
    V11_INPUT.mkdir(parents=True, exist_ok=True)
    V11_OUTPUT.mkdir(parents=True, exist_ok=True)
    (V11_DIR / "visualizations").mkdir(parents=True, exist_ok=True)

    # ---- Step 1: Catchment areas (culverts + western wadi) ----
    logger.info("--- Step 1: Catchment areas ---")
    logger.info("  (from TDX-Hydro v2 river network + HydroATLAS budget)")
    for cv in CULVERTS:
        logger.info(f"  {cv['name']}: {cv['catchment_km2']:.0f} km² "
                    f"(wadi linkno={cv['feeding_wadi']})")
    logger.info(f"  {WESTERN_ENTRY['name']}: {WESTERN_ENTRY['catchment_km2']:.0f} km² "
                f"(wadis {WESTERN_ENTRY['feeding_wadis']}, Nile-blocked)")
    total_catchment = (sum(cv["catchment_km2"] for cv in CULVERTS)
                       + WESTERN_ENTRY["catchment_km2"])
    logger.info(f"  Total contributing area: {total_catchment:.0f} km² "
                f"(of 194.5 km² HydroATLAS basin; ~60 km² drains east independently)")

    # ---- Step 2: Download IMERG over basin extent ----
    # We still use the HydroATLAS basin polygon for the IMERG download region
    # (captures upstream rainfall pattern), but apply it to the CORRECT catchment area
    logger.info("\n--- Step 2: Download basin-scale IMERG rainfall ---")

    basin_bbox, basin_geom, basin_level = get_basin_bounding_box()
    if basin_bbox is None:
        logger.error("No basin polygon found. Run delineate_watershed_v10.py first.")
        return

    logger.info(f"  Using HydroATLAS level {basin_level} polygon for IMERG extent")
    logger.info(f"  Basin bbox: W={basin_bbox['west']:.3f} E={basin_bbox['east']:.3f} "
                f"S={basin_bbox['south']:.3f} N={basin_bbox['north']:.3f}")

    ee_mod = init_ee()
    times_dt, basin_rain = download_basin_rainfall(ee_mod, basin_bbox, basin_geom)

    # Read domain-mean rain for comparison
    logger.info("\n  Reading domain-mean IMERG (v10) for comparison...")
    rain_dir = INPUT_DIR / "rain"
    domain_rain = np.zeros(N_RAIN)
    for t in range(1, N_RAIN + 1):
        path = rain_dir / f"imerg_v10_t{t}.nc"
        if not path.exists():
            continue
        ds = netCDF4.Dataset(str(path))
        data = np.array(ds["Band1"][:], dtype=np.float32)
        ds.close()
        data[data < -9000] = 0.0
        data[~np.isfinite(data)] = 0.0
        domain_rain[t - 1] = float(np.mean(data))

    domain_total = np.sum(domain_rain) * 0.5
    basin_total = np.sum(basin_rain) * 0.5
    logger.info(f"  Domain-mean total: {domain_total:.1f} mm")
    logger.info(f"  Basin-mean total:  {basin_total:.1f} mm")

    # ---- Step 2b: Load Nile blocking factor ----
    logger.info("\n--- Step 2b: Load Nile blocking factor (GEOGloWS) ---")
    nile_blocking = load_nile_blocking_factor(N_RAIN, DT_INFLOW)

    # ---- Step 3: Compute hydrographs with IMERG intensification ----
    logger.info("\n--- Step 3: Compute hydrographs (culverts + western wadi) ---")

    # Load DEM for culvert elevations
    dem, x, y = load_nc(INPUT_DIR / "dem.nc")
    nrows, ncols = dem.shape

    # Locate culvert cells
    culvert_cells = []
    culvert_elevs = []
    for cv in CULVERTS:
        row, col, utm_x, utm_y = latlon_to_grid(cv["lat"], cv["lon"], x, y)
        elev = dem[row, col]
        culvert_cells.append((row, col, cv["name"]))
        culvert_elevs.append(float(elev))
        logger.info(f"  {cv['name']}: row={row}, col={col}, elev={elev:.1f}m")

    # Locate western entry
    w_row, w_col, w_utmx, w_utmy = latlon_to_grid(
        WESTERN_ENTRY["lat"], WESTERN_ENTRY["lon"], x, y)
    w_elev = float(dem[w_row, w_col])
    logger.info(f"  {WESTERN_ENTRY['name']}: row={w_row}, col={w_col}, elev={w_elev:.1f}m")

    # Culvert full-pipe capacity
    a_full = CULVERT_WIDTH * CULVERT_HEIGHT
    p_full = 2 * CULVERT_HEIGHT + CULVERT_WIDTH
    r_full = a_full / p_full
    q_full = (1.0 / N_MANNING) * a_full * r_full**(2.0/3.0) * SLOPE**0.5
    logger.info(f"\n  Culvert full-pipe capacity: {q_full:.1f} m3/s")
    logger.info(f"  Runoff coefficient: {RUNOFF_COEFF}")

    # First pass: compute raw hydrographs (no intensification) to determine
    # what IMERG factor is needed to match target peak flow
    logger.info("\n  Computing raw hydrographs (no intensification)...")
    raw_peaks = []
    for i, cv in enumerate(CULVERTS):
        catchment_m2 = cv["catchment_km2"] * 1e6
        tc = compute_tc_hours(cv["catchment_km2"])
        uh = make_triangular_uh(tc, DT_INFLOW)
        q_raw = rational_method_hydrograph(basin_rain, catchment_m2,
                                            RUNOFF_COEFF, uh, DT_INFLOW)
        raw_peak = float(np.max(q_raw))
        raw_peaks.append(raw_peak)
        logger.info(f"    {cv['name']}: raw peak = {raw_peak:.2f} m3/s "
                    f"(tc={tc:.1f}h, A={cv['catchment_km2']:.0f}km2)")

    # Western wadi raw (without blocking, for calibration reference)
    tc_west = compute_tc_hours(WESTERN_ENTRY["catchment_km2"])
    uh_west = make_triangular_uh(tc_west, DT_INFLOW)
    q_raw_west = rational_method_hydrograph(basin_rain, WESTERN_ENTRY["catchment_km2"] * 1e6,
                                             RUNOFF_COEFF, uh_west, DT_INFLOW)
    raw_peak_west = float(np.max(q_raw_west))
    logger.info(f"    {WESTERN_ENTRY['name']}: raw peak = {raw_peak_west:.2f} m3/s "
                f"(tc={tc_west:.1f}h, A={WESTERN_ENTRY['catchment_km2']:.0f}km2, "
                f"before blocking)")

    # Determine IMERG intensification factor
    # With 3 inflow sources (total 135 km²), more water enters the domain.
    # Target: ~0.6m mean flood depth at buildings (compound event).
    # Need pressurized culvert flow + significant western inflow.
    # Target total peak Q ~ 6x culvert capacity across all sources.
    target_peak_q = q_full * 6
    # Use largest raw culvert peak as reference for factor
    max_culvert_raw = max(raw_peaks)
    if max_culvert_raw > 0:
        imerg_factor = target_peak_q / max_culvert_raw
    else:
        imerg_factor = IMERG_INTENSIFICATION_BOUNDS[1]

    # Clamp to physically reasonable range
    imerg_factor = max(IMERG_INTENSIFICATION_BOUNDS[0],
                       min(IMERG_INTENSIFICATION_BOUNDS[1], imerg_factor))

    logger.info(f"\n  IMERG peak intensification factor: {imerg_factor:.2f}x")
    logger.info(f"    Justification: IMERG 0.1-deg smooths convective cells")
    logger.info(f"    Literature range: 2-5x for storms < 20km in 0.1° pixels")
    logger.info(f"    (Guilloteau et al. 2021; Tan et al. 2016)")

    # Apply intensification to rainfall
    rain_intensified = basin_rain * imerg_factor
    rain_total_intensified = np.sum(rain_intensified) * 0.5
    logger.info(f"    Intensified basin rain total: {rain_total_intensified:.1f} mm "
                f"(from {basin_total:.1f} mm)")

    # Compute final hydrographs
    logger.info("\n  Computing final hydrographs...")
    wse_timeseries = []
    q_timeseries = []

    for i, cv in enumerate(CULVERTS):
        cv_name = cv["name"]
        catchment_m2 = cv["catchment_km2"] * 1e6
        elev = culvert_elevs[i]

        tc = compute_tc_hours(cv["catchment_km2"])
        uh = make_triangular_uh(tc, DT_INFLOW)

        q = rational_method_hydrograph(rain_intensified, catchment_m2,
                                        RUNOFF_COEFF, uh, DT_INFLOW)

        peak_q = float(np.max(q))

        logger.info(f"\n  {cv_name}:")
        logger.info(f"    Catchment: {cv['catchment_km2']:.0f} km2 "
                    f"(wadi linkno={cv['feeding_wadi']})")
        logger.info(f"    Time of concentration: {tc:.1f} hours")
        logger.info(f"    UH length: {len(uh)} steps ({len(uh)*DT_INFLOW/3600:.1f}h)")
        logger.info(f"    Peak flow: {peak_q:.1f} m3/s "
                    f"({'PRESSURIZED' if peak_q > q_full else 'free-flow'})")

        # Pad/trim to N_WSE values
        q_padded = np.zeros(N_WSE)
        n_copy = min(len(q), N_WSE - 1)
        q_padded[1:n_copy + 1] = q[:n_copy]

        q_timeseries.append(q_padded)

        # Convert flow to WSE
        wse = np.array([flow_to_wse(qi, elev) for qi in q_padded])
        wse_timeseries.append(wse)

        peak_wse = wse.max()
        peak_depth = peak_wse - elev
        n_pressurized = int(np.sum(q_padded > q_full))
        vol_m3 = np.sum(q_padded[1:]) * DT_INFLOW

        logger.info(f"    Peak WSE: {peak_wse:.2f}m (depth={peak_depth:.2f}m)")
        logger.info(f"    Pressurized timesteps: {n_pressurized}")
        logger.info(f"    Total volume: {vol_m3/1e6:.2f} M m3")
        logger.info(f"    Duration Q>1 m3/s: "
                    f"{np.sum(q_padded > 1) * DT_INFLOW / 3600:.1f}h")

    # ---- Step 3b: Western wadi hydrograph (Nile-blocked) ----
    logger.info("\n--- Step 3b: Western wadi hydrograph (Nile-blocked) ---")
    logger.info(f"  Catchment: {WESTERN_ENTRY['catchment_km2']:.0f} km²")
    logger.info(f"  Feeding wadis: {WESTERN_ENTRY['feeding_wadis']}")
    logger.info(f"  Entry point: ({WESTERN_ENTRY['lat']:.3f}, {WESTERN_ENTRY['lon']:.3f})")
    logger.info(f"  DEM elevation: {w_elev:.2f}m")

    # Compute unblocked western hydrograph
    q_west_unblocked = rational_method_hydrograph(
        rain_intensified, WESTERN_ENTRY["catchment_km2"] * 1e6,
        RUNOFF_COEFF, uh_west, DT_INFLOW)

    # Apply Nile blocking factor: Q_west(t) = Q_unblocked(t) * blocking(t)
    # When Nile is low → blocking~0 → water exits to Nile freely → no inflow
    # When Nile is high → blocking~1 → all runoff enters settlement
    q_west_blocked = q_west_unblocked[:N_RAIN] * nile_blocking[:len(q_west_unblocked[:N_RAIN])]

    # Pad to N_WSE
    q_west_padded = np.zeros(N_WSE)
    n_copy_w = min(len(q_west_blocked), N_WSE - 1)
    q_west_padded[1:n_copy_w + 1] = q_west_blocked[:n_copy_w]

    peak_q_west = float(np.max(q_west_padded))
    logger.info(f"  Peak unblocked: {float(np.max(q_west_unblocked)):.1f} m³/s")
    logger.info(f"  Peak blocked (actual inflow): {peak_q_west:.1f} m³/s")

    # Convert to WSE using open-channel formula
    wse_west = np.array([flow_to_wse_open(qi, w_elev) for qi in q_west_padded])
    peak_wse_w = wse_west.max()
    peak_depth_w = peak_wse_w - w_elev
    vol_west = np.sum(q_west_padded[1:]) * DT_INFLOW

    logger.info(f"  Peak WSE: {peak_wse_w:.2f}m (depth={peak_depth_w:.2f}m)")
    logger.info(f"  Total volume: {vol_west/1e6:.2f} M m³")
    logger.info(f"  Duration Q>1 m³/s: {np.sum(q_west_padded > 1) * DT_INFLOW / 3600:.1f}h")

    # Add western entry to boundary cells and timeseries
    culvert_cells.append((w_row, w_col, WESTERN_ENTRY["name"]))
    culvert_elevs.append(w_elev)
    q_timeseries.append(q_west_padded)
    wse_timeseries.append(wse_west)

    # ---- Step 4: Write boundary files ----
    logger.info("\n--- Step 4: Write boundary files ---")

    mask_path = V11_INPUT / "fluvbound_mask_v11.nc"
    write_boundary_mask(culvert_cells, dem, x, y, mask_path)

    inflow_path = V11_INPUT / "inflowlocs_v11.txt"
    write_inflowlocs(culvert_cells, wse_timeseries, inflow_path, SIM_DUR, DT_INFLOW)

    # Save hydrograph data for visualization
    hydro_path = V11_INPUT / "culvert_hydrographs_v11.npz"
    save_data = {
        "times_h": np.arange(N_WSE) * DT_INFLOW / 3600.0,
        "basin_rain_raw": basin_rain,
        "basin_rain_intensified": rain_intensified,
        "domain_rain": domain_rain,
        "imerg_factor": np.array([imerg_factor]),
        "nile_blocking_factor": nile_blocking,
        "q_WesternWadi": q_west_padded,
        "q_WesternWadi_unblocked": np.pad(
            q_west_unblocked[:min(len(q_west_unblocked), N_WSE-1)],
            (1, max(0, N_WSE - 1 - len(q_west_unblocked))),
        )[:N_WSE],
    }
    for i, cv in enumerate(CULVERTS):
        save_data[f"q_{cv['name']}"] = q_timeseries[i]
        # Also save raw (un-intensified) hydrograph for comparison
        tc = compute_tc_hours(cv["catchment_km2"])
        uh = make_triangular_uh(tc, DT_INFLOW)
        q_raw = rational_method_hydrograph(basin_rain, cv["catchment_km2"] * 1e6,
                                            RUNOFF_COEFF, uh, DT_INFLOW)
        q_raw_padded = np.zeros(N_WSE)
        n_copy = min(len(q_raw), N_WSE - 1)
        q_raw_padded[1:n_copy + 1] = q_raw[:n_copy]
        save_data[f"q_raw_{cv['name']}"] = q_raw_padded
    np.savez(str(hydro_path), **save_data)
    logger.info(f"  Written: {hydro_path.name}")

    # Save metadata
    meta = {
        "version": "v11_compound",
        "description": "Compound flooding: culvert overflow + Nile-blocked western wadi",
        "inflow_points": [],
        "sim_dur": SIM_DUR,
        "dt_inflow": DT_INFLOW,
        "runoff_coeff": RUNOFF_COEFF,
        "imerg_intensification_factor": imerg_factor,
        "imerg_intensification_bounds": list(IMERG_INTENSIFICATION_BOUNDS),
        "culvert_capacity_m3s": q_full,
        "basin_rain_total_mm": float(basin_total),
        "basin_rain_intensified_total_mm": float(rain_total_intensified),
        "domain_rain_total_mm": float(domain_total),
        "nile_peak_m3s": float(np.max(nile_blocking) * 1),  # placeholder
        "catchment_budget_km2": {
            "hydroatlas_total": 194.5,
            "culvert1": 25.0,
            "culvert2": 35.0,
            "eastern_independent": 60.0,
            "western_blocked": 75.0,
        },
    }
    # Culverts
    for i, cv in enumerate(CULVERTS):
        meta["inflow_points"].append({
            "name": cv["name"],
            "type": "culvert",
            "lat": cv["lat"],
            "lon": cv["lon"],
            "catchment_km2": cv["catchment_km2"],
            "feeding_wadi_linkno": cv["feeding_wadi"],
            "tc_hours": compute_tc_hours(cv["catchment_km2"]),
            "peak_flow_m3s": float(np.max(q_timeseries[i])),
            "total_volume_m3": float(np.sum(q_timeseries[i][1:]) * DT_INFLOW),
        })
    # Also put culverts under old key for backward compat with visualize_v11.py
    meta["culverts"] = [p for p in meta["inflow_points"] if p["type"] == "culvert"]
    # Western entry
    meta["inflow_points"].append({
        "name": WESTERN_ENTRY["name"],
        "type": "western_wadi",
        "lat": WESTERN_ENTRY["lat"],
        "lon": WESTERN_ENTRY["lon"],
        "catchment_km2": WESTERN_ENTRY["catchment_km2"],
        "feeding_wadi_linknos": WESTERN_ENTRY["feeding_wadis"],
        "tc_hours": tc_west,
        "peak_flow_m3s": peak_q_west,
        "total_volume_m3": float(vol_west),
        "nile_blocking": True,
    })
    # Read actual Nile peak from CSV for metadata
    if GEOGLOWS_CSV.exists():
        df_nile = pd.read_csv(str(GEOGLOWS_CSV), parse_dates=["time"])
        nile_col = f"Q_{NILE_REACH_ID}_m3s"
        if nile_col in df_nile.columns:
            meta["nile_peak_m3s"] = float(df_nile[nile_col].max())
            meta["nile_baseline_m3s"] = float(df_nile[nile_col].min())
    meta_path = V11_INPUT / "v11_metadata.json"
    with open(str(meta_path), "w") as f:
        json.dump(meta, f, indent=2)
    logger.info(f"  Written: {meta_path.name}")

    # ---- Step 5: Write simulation definition ----
    logger.info("\n--- Step 5: Write simulation definition ---")
    rain_nr = min(N_RAIN, SIM_DUR // DT_INFLOW)
    def_path = V11_DIR / "simulation_v11.def"
    write_simulation_def(def_path, rain_nr)

    # ---- Summary ----
    elapsed = time.time() - t0
    logger.info("\n" + "=" * 70)
    logger.info("v11 SETUP COMPLETE — Compound Flooding")
    logger.info("=" * 70)
    logger.info(f"  Elapsed: {elapsed:.0f}s")
    logger.info("")
    logger.info("  Inflow summary (3 boundaries):")
    logger.info(f"  {'Source':<20} {'Area (km²)':>10} {'Peak Q (m³/s)':>14} {'Volume (M m³)':>14}")
    logger.info(f"  {'-'*20} {'-'*10} {'-'*14} {'-'*14}")
    all_sources = list(CULVERTS) + [WESTERN_ENTRY]
    for i, src in enumerate(all_sources):
        peak = float(np.max(q_timeseries[i]))
        vol = float(np.sum(q_timeseries[i][1:]) * DT_INFLOW / 1e6)
        name = src["name"]
        area = src["catchment_km2"]
        logger.info(f"  {name:<20} {area:>10.0f} {peak:>14.1f} {vol:>14.2f}")
    total_peak = sum(float(np.max(q_timeseries[i])) for i in range(len(all_sources)))
    total_vol = sum(float(np.sum(q_timeseries[i][1:]) * DT_INFLOW / 1e6) for i in range(len(all_sources)))
    logger.info(f"  {'TOTAL':<20} {total_catchment:>10.0f} {total_peak:>14.1f} {total_vol:>14.2f}")
    logger.info("")
    logger.info(f"  IMERG intensification: {imerg_factor:.2f}x")
    logger.info(f"  Runoff coefficient: {RUNOFF_COEFF}")
    logger.info(f"  Nile blocking: peak factor = {float(np.max(nile_blocking)):.2f}")
    logger.info("")
    logger.info("  Next steps:")
    logger.info("  1. Visualize inputs: python visualize_v11.py --inputs")
    logger.info("  2. Run simulation:   cd v11 && ../../bin/RIM2D simulation_v11.def --def flex")
    logger.info("  3. Visualize results: python visualize_v11.py --results")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
