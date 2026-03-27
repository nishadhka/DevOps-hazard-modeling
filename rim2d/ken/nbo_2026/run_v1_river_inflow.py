#!/usr/bin/env python3
"""
v1 River Inflow — Auto-detect river entry points and generate boundary conditions.

Detects where rivers enter the Nairobi domain by finding domain-edge cells with
high flow accumulation, then generates hydrographs using the rational method
(Q = C * I * A) convolved with a triangular unit hydrograph from IMERG rainfall.

This script is designed to be run AFTER visualize_v1.py --inputs is reviewed.
Entry point locations and catchment areas can be adjusted manually before
running the simulation.

Steps:
  1. Load flwacc_30m.nc, identify top river entry points at domain edges
  2. Estimate upstream catchment area from flow accumulation count
  3. Compute hydrograph per entry using rational method + UH convolution
  4. Convert flow to WSE via Manning's equation
  5. Write fluvbound_mask_v1.nc and inflowlocs_v1.txt

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python run_v1_river_inflow.py
"""

from pathlib import Path

import netCDF4
import numpy as np
from pyproj import Transformer

WORK_DIR  = Path(__file__).parent   # /data/rim2d/nbo_2026
V1_DIR    = WORK_DIR / "v1"
INPUT_DIR = V1_DIR / "input"
RAIN_DIR  = INPUT_DIR / "rain"
RAIN_PREFIX = "imerg_v1_t"

CRS_UTM = "EPSG:32737"

# -- Simulation timing --------------------------------------------------------
SIM_DUR   = 2592000   # 30 days
DT_INFLOW = 1800      # 30-min boundary timestep
N_RAIN    = 1440      # 30 days × 48
N_WSE     = SIM_DUR // DT_INFLOW + 1  # 1441 WSE values (t=0 included)

# -- River entry detection ----------------------------------------------------
# Minimum flow accumulation at domain edge to be classed as a river entry.
# Increase if too many small wadis are captured; decrease if main rivers missed.
ACC_THRESH = 500      # upstream cells (≈ ~500 × (30m)² ≈ 0.45 km²)
TOP_N      = 8        # maximum number of entry points to use

# Cell size (used to estimate catchment area from flow accumulation count)
CELL_AREA_M2 = 30.0 * 30.0   # 900 m² per cell

# -- Channel hydraulics (tropical natural channels) ---------------------------
CHANNEL_WIDTH  = 20.0    # m  — typical Nairobi river width
CHANNEL_SLOPE  = 0.003   # m/m — moderate gradient toward Athi
N_MANNING      = 0.040   # natural channel

# -- Rational method parameters -----------------------------------------------
RUNOFF_COEFF   = 0.60    # urban/mixed catchment (Nairobi is highly urbanised)
TC_HOURS       = 4.0     # time of concentration (hours)

# -- Flow cap per entry (m3/s) -------------------------------------------------
# Prevents unrealistically large flows from large upstream accumulation areas.
MAX_Q_PER_ENTRY = 300.0   # m3/s


# -- Helper functions ---------------------------------------------------------

def load_nc(path):
    ds      = netCDF4.Dataset(str(path))
    x       = ds["x"][:]
    y       = ds["y"][:]
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    data    = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    data[data < -9000] = np.nan
    return data, x, y


def detect_river_entries(flwacc, acc_thresh=ACC_THRESH, top_n=TOP_N):
    """
    Find domain-edge cells with flow accumulation >= acc_thresh.

    Returns list of (row, col, acc) sorted by descending accumulation,
    limited to top_n entries.  Entries are deduplicated so that adjacent
    high-acc cells on the same river count only once (keep the local max).
    """
    nrows, ncols = flwacc.shape
    entries = []

    # Scan all four edges
    for row in range(nrows):
        for col in [0, ncols - 1]:
            acc = flwacc[row, col]
            if np.isfinite(acc) and acc >= acc_thresh:
                entries.append((row, col, acc))

    for col in range(ncols):
        for row in [0, nrows - 1]:
            acc = flwacc[row, col]
            if np.isfinite(acc) and acc >= acc_thresh:
                entries.append((row, col, acc))

    if not entries:
        raise RuntimeError(
            f"No river entries found with acc >= {acc_thresh}. "
            "Lower ACC_THRESH or check flwacc_30m.nc."
        )

    # Sort by descending accumulation
    entries.sort(key=lambda e: e[2], reverse=True)

    # Deduplicate: suppress entries within 5 cells of a higher-acc entry
    kept = []
    for row, col, acc in entries:
        too_close = False
        for kr, kc, _ in kept:
            if abs(row - kr) <= 5 and abs(col - kc) <= 5:
                too_close = True
                break
        if not too_close:
            kept.append((row, col, acc))
        if len(kept) >= top_n:
            break

    return kept


def read_rain_rates():
    """Load domain-mean precipitation rate (mm/hr) for each half-hourly step."""
    print(f"\nReading {N_RAIN} rain files from {RAIN_DIR}...")
    rain_rates = np.zeros(N_RAIN)
    for t in range(1, N_RAIN + 1):
        path = RAIN_DIR / f"{RAIN_PREFIX}{t}.nc"
        if not path.exists():
            continue
        ds   = netCDF4.Dataset(str(path))
        data = np.array(ds["Band1"][:], dtype=np.float32)
        ds.close()
        data[data < -9000] = 0.0
        data[~np.isfinite(data)] = 0.0
        rain_rates[t - 1] = float(np.mean(data))

    total_mm = np.sum(rain_rates) * 0.5
    n_wet    = int(np.sum(rain_rates > 0.1))
    print(f"  Total domain-mean rainfall: {total_mm:.1f} mm")
    print(f"  Wet timesteps (>0.1 mm/hr): {n_wet}/{N_RAIN}")
    print(f"  Peak domain-mean rate:      {rain_rates.max():.2f} mm/hr")
    return rain_rates


def make_triangular_uh(tc_hours, dt_s):
    tc_s   = tc_hours * 3600.0
    tb     = 2.0 * tc_s
    n_steps = int(np.ceil(tb / dt_s)) + 1
    t      = np.arange(n_steps) * dt_s
    uh     = np.zeros(n_steps)
    for i, ti in enumerate(t):
        if   ti <= tc_s: uh[i] = ti / tc_s
        elif ti <= tb:   uh[i] = (tb - ti) / tc_s
    uh /= uh.sum()
    return uh


def rational_hydrograph(rain_rates_mmhr, catchment_m2, uh):
    rain_ms    = rain_rates_mmhr / (1000.0 * 3600.0)
    q_instant  = RUNOFF_COEFF * rain_ms * catchment_m2
    q_conv     = np.convolve(q_instant, uh, mode="full")[:len(rain_rates_mmhr)]
    return np.clip(q_conv, 0.0, MAX_Q_PER_ENTRY)


def flow_to_wse(q, dem_elev):
    """Manning's wide rectangular channel: depth = (Q*n / (w*S^0.5))^0.6."""
    if q <= 0:
        return dem_elev
    w   = CHANNEL_WIDTH
    n   = N_MANNING
    s   = CHANNEL_SLOPE
    # Simplified wide-channel approximation
    depth = (q * n / (w * s**0.5))**(3.0/5.0)
    depth = min(depth, 15.0)   # cap at 15 m
    return dem_elev + depth


def write_boundary_mask(entries, dem, x, y, out_path):
    nrows, ncols = dem.shape
    mask = np.zeros((nrows, ncols), dtype=np.float32)
    for i, (row, col, _) in enumerate(entries):
        mask[row, col] = float(i + 1)

    ds = netCDF4.Dataset(str(out_path), "w", format="NETCDF3_CLASSIC")
    ds.Conventions = "CF-1.5"
    ds.history     = "v1: river inflow boundary mask"
    ds.createDimension("x", ncols)
    ds.createDimension("y", nrows)
    xv = ds.createVariable("x", "f8", ("x",)); xv[:] = x
    yv = ds.createVariable("y", "f8", ("y",)); yv[:] = y
    band = ds.createVariable("Band1", "f4", ("y", "x"),
                             fill_value=np.float32(-9999.0))
    band[:] = mask
    ds.close()
    print(f"  Written: {out_path.name} ({int(mask.max())} zones)")


def write_inflowlocs(entries, wse_timeseries, out_path):
    n_cells = len(entries)
    with open(str(out_path), "w") as f:
        f.write(f"{SIM_DUR}\n")
        f.write(f"{DT_INFLOW}\n")
        f.write(f"{n_cells}\n")
        for i, (row, col, _) in enumerate(entries):
            wse  = wse_timeseries[i]
            vals = [str(row + 1), str(col + 1)]   # 1-indexed for Fortran
            vals.extend(f"{v:.3f}" for v in wse)
            f.write("\t".join(vals) + "\n")
    print(f"  Written: {out_path.name} ({n_cells} cells, {N_WSE} WSE values each)")


# -- Main ---------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Nairobi v1 — River Inflow Boundary Conditions")
    print(f"  ACC_THRESH:  {ACC_THRESH} cells")
    print(f"  TOP_N:       {TOP_N} entries")
    print(f"  Runoff coeff: {RUNOFF_COEFF}")
    print(f"  Manning n:   {N_MANNING}")
    print(f"  Duration:    {SIM_DUR/86400:.0f} days ({SIM_DUR}s)")
    print("=" * 60)

    print("\nLoading v1 DEM and flow accumulation...")
    dem,    x, y = load_nc(INPUT_DIR / "dem.nc")
    flwacc, _, _ = load_nc(INPUT_DIR / "flwacc_30m.nc")
    nrows, ncols = dem.shape
    print(f"  Grid: {ncols} x {nrows}")
    print(f"  Flow acc range: {np.nanmin(flwacc):.0f} – {np.nanmax(flwacc):.0f}")

    print(f"\nDetecting river entry points (acc >= {ACC_THRESH})...")
    entries = detect_river_entries(flwacc, ACC_THRESH, TOP_N)
    print(f"  Found {len(entries)} entry points")

    # Convert to lat/lon for reporting
    to_wgs84 = Transformer.from_crs(CRS_UTM, "EPSG:4326", always_xy=True)

    print("\n  Entry points (sorted by flow accumulation):")
    print(f"  {'#':<3} {'row':>5} {'col':>5} {'acc':>8}  {'catch_km2':>10}  "
          f"{'lat':>10}  {'lon':>10}  {'elev':>8}")
    print("  " + "-" * 75)

    for i, (row, col, acc) in enumerate(entries):
        catchment_m2  = acc * CELL_AREA_M2
        catchment_km2 = catchment_m2 / 1e6
        utm_x  = float(x[col])
        utm_y  = float(y[row])
        lon, lat = to_wgs84.transform(utm_x, utm_y)
        elev = float(dem[row, col]) if np.isfinite(dem[row, col]) else float("nan")
        print(f"  {i+1:<3} {row:>5} {col:>5} {acc:>8.0f}  "
              f"{catchment_km2:>10.1f}  {lat:>10.5f}  {lon:>10.5f}  {elev:>8.1f}m")

    # Read rainfall
    rain_rates = read_rain_rates()

    # Unit hydrograph
    print(f"\nCreating triangular unit hydrograph (tc={TC_HOURS:.0f}h)...")
    uh = make_triangular_uh(TC_HOURS, DT_INFLOW)
    print(f"  UH length: {len(uh)} steps ({len(uh)*DT_INFLOW/3600:.1f}h)")

    # Compute hydrographs
    print("\nComputing river hydrographs...")
    wse_timeseries = []
    q_arrays       = {}

    for i, (row, col, acc) in enumerate(entries):
        catchment_m2 = acc * CELL_AREA_M2
        elev         = float(dem[row, col]) if np.isfinite(dem[row, col]) else 0.0

        q     = rational_hydrograph(rain_rates, catchment_m2, uh)
        q_wse = np.zeros(N_WSE)
        q_wse[0] = 0.0
        n_copy   = min(len(q), N_WSE - 1)
        q_wse[1:n_copy + 1] = q[:n_copy]

        wse = np.array([flow_to_wse(qi, elev) for qi in q_wse])
        wse_timeseries.append(wse)
        q_arrays[f"q_entry{i+1}"] = q_wse

        peak_q     = q_wse.max()
        peak_depth = wse.max() - elev
        vol_m3     = np.sum(q_wse[1:]) * DT_INFLOW
        print(f"  Entry {i+1} (row={row},col={col}): "
              f"peak={peak_q:.1f} m3/s, depth={peak_depth:.2f}m, "
              f"vol={vol_m3/1e6:.2f} Mm3")

    # Write files
    print("\nWriting boundary mask...")
    write_boundary_mask(entries, dem, x, y, INPUT_DIR / "fluvbound_mask_v1.nc")

    print("Writing inflowlocs...")
    write_inflowlocs(entries, wse_timeseries, INPUT_DIR / "inflowlocs_v1.txt")

    # Save hydrograph data for visualization
    q_arrays["rain_rates"] = rain_rates
    q_arrays["times_h"]    = np.arange(N_WSE) * DT_INFLOW / 3600.0
    hydro_path = INPUT_DIR / "river_hydrographs.npz"
    np.savez(str(hydro_path), **q_arrays)
    print(f"  Written: {hydro_path.name}")

    # Save entry metadata as CSV for manual review / adjustment
    csv_path = INPUT_DIR / "river_entry_points.csv"
    with open(str(csv_path), "w") as f:
        f.write("entry_id,row,col,flow_acc,catchment_km2,lat,lon,elevation_m\n")
        for i, (row, col, acc) in enumerate(entries):
            catchment_km2 = acc * CELL_AREA_M2 / 1e6
            utm_x = float(x[col]);  utm_y = float(y[row])
            lon, lat = to_wgs84.transform(utm_x, utm_y)
            elev = float(dem[row, col]) if np.isfinite(dem[row, col]) else float("nan")
            f.write(f"{i+1},{row},{col},{acc:.0f},{catchment_km2:.2f},"
                    f"{lat:.6f},{lon:.6f},{elev:.1f}\n")
    print(f"  Written: {csv_path.name}")

    print("\n" + "=" * 60)
    print("Verification:")
    print(f"  Boundary zones: {len(entries)}")
    print(f"  WSE values per cell: {N_WSE} "
          f"(expected {SIM_DUR // DT_INFLOW + 1})")
    print(f"  Catchment areas: {[f'{e[2]*CELL_AREA_M2/1e6:.1f}km2' for e in entries]}")
    print("\nTo adjust entries: edit ACC_THRESH or TOP_N at the top of this script,")
    print("or edit river_entry_points.csv and re-run.")
    print("\nNext: python visualize_v1.py --inputs")
    print("=" * 60)


if __name__ == "__main__":
    main()
