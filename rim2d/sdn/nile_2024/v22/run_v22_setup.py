#!/usr/bin/env python3
"""
RIM2D v22 — Fix HospitalWadi → Nile connectivity (Fix 8).

Root cause diagnosed from v21 output:
  F17 GeoJSON rasterises only rows 178-183 at col~281. A 29-row (870m)
  unburned ridge at 315-320m blocks HospitalWadi (row=183, col=281)
  from draining to the Nile 294m zone (which starts at row~153).
  In v21, HospitalWadi water pools at WSE ~316-317m and never reaches
  the Nile — the depression-filling path traced a 7km route but the
  hydraulic head was insufficient to overtop the ridge.

Fix 8: Burn a 3-cell-wide channel (cols 278-280) from row=153 to row=183
  at dem-8m (same depth as the culvert), capped at 294m. This creates a
  ~307m invert connecting HospitalWadi directly to the Nile 294m zone.

Root cause diagnosed from v16 steady-state run:
  Two Order-2 tributary streams visible in TDX-Hydro GeoJSON were never
  rasterized into the DEM — leaving unburned gaps between the wadi channels
  and the Nile floodplain zone:

  Gap 1 (eastern): F17 tributary (cols 240-298) ends at row ~144-200.
                   F22 Nile east bend starts at row ~128-146.
                   Gap = 29-72 unburned rows at cols 255-298.

  Gap 2 (western): F18 tributary (cols 147-183) ends at row ~133-193.
                   F19 Nile center starts at row ~106-117.
                   Gap = 27-76 unburned rows at cols 147-183.

  Culvert: 8m culvert under railway/road at 19.537547°N, 33.32237°E
           → row=176, col=253, DEM=315.85m → burn to invert ~307.85m.

Fixes applied on top of v15 DEM:
  Fix 6a: Re-rasterize ALL stream features from TDX-Hydro GeoJSON (Order 2/5/9)
  Fix 6b: Burn connecting channels through Gap 1 and Gap 2
  Fix 6c: Burn 8m culvert cell at row=176, col=253

Usage:
    micromamba run -n zarrv3 python v22/run_v22_setup.py
    cd v22 && /data/rim2d/bin/RIM2D simulation_v22.def --def flex
"""

from pathlib import Path
import shutil, json, os, tempfile
import numpy as np
import netCDF4
import rasterio
from pyproj import Transformer
from pysheds.grid import Grid

WORK_DIR  = Path("/data/rim2d/nile_highres")
V10_INPUT = WORK_DIR / "v10" / "input"
V15_INPUT = WORK_DIR / "v15" / "input"
V13_INPUT = WORK_DIR / "v13" / "input"
V22_DIR   = WORK_DIR / "v22"
V22_INPUT = V22_DIR  / "input"
V22_INPUT.mkdir(parents=True, exist_ok=True)
(V22_DIR / "output").mkdir(exist_ok=True)

GEOJSON   = WORK_DIR / "v11" / "input" / "river_network_tdx_v2.geojson"

# ── Burn depth parameters ──────────────────────────────────────────────────
# v22 changes vs v18:
#   - Order-9 Nile cells burned to exactly NILE_TARGET_ELEV (not dem-5m)
#     → fixes fragmented Nile channel at cols 209-241 (302-312m ridges)
#   - Gap bridge cells burned to exactly NILE_TARGET_ELEV (not dem-3m)
#     → fixes shallow channel floors (312m) that block flow to Nile (294m)
#   - Nile threshold raised 301m → 308m to capture 302-307m ridge cells
BURN_ORDER5   = 3.0   # major wadis (relative burn, capped at Nile level)
BURN_ORDER2   = 2.0   # minor wadis (relative burn, capped at Nile level)
CULVERT_INVERT_BELOW_SURFACE = 8.0  # culvert is 8m below DEM surface

# Culvert location (confirmed from coordinate conversion)
CULVERT_ROW, CULVERT_COL = 176, 253

# Nile floodplain burn — raised threshold captures 302-307m ridge cells
NILE_ELEV_THRESH = 308.0   # was 301m — now captures 302-307m Nile ridges
NILE_TARGET_ELEV = 294.0

# Railway zone extra burn (from v15)
RAILWAY_ROW_MIN, RAILWAY_ROW_MAX = 78, 92
RAILWAY_BURN_EXTRA = 5.0

# ── Simulation parameters (same as v15) ───────────────────────────────────
SIM_DUR      = 518_400
DT_INFLOW    = 1800
N_RAIN       = SIM_DUR // DT_INFLOW        # 288 IMERG files
N_WSE        = SIM_DUR // DT_INFLOW + 1   # 289 WSE timesteps
IMERG_START_STEP = 1488
WSE_CAP_M    = 1.5
INFLOW_DEFS  = {
    "Culvert1":    {"row": 212, "col": 312, "sill": 321.105},
    "Culvert2":    {"row": 222, "col": 266, "sill": 320.012},
    "WesternWadi": {"row": 222, "col": 175, "sill": 318.855},
    "HospitalWadi":{"row": 183, "col": 281, "sill": 316.134},
}


def load_dem_v10():
    ds = netCDF4.Dataset(str(V10_INPUT / "dem.nc"))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    var = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[var][:]).squeeze().astype(float)
    dem[dem < -9000] = np.nan
    ds.close()
    return dem, x, y


def lonlat_to_rowcol(lon, lat, x, y):
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    ex, ey = tr.transform(lon, lat)
    col = int(round((ex - x[0]) / (x[1] - x[0])))
    row = int(round((ey - y[0]) / (y[1] - y[0])))
    return row, col


# ── Step 1: Build v22 DEM ─────────────────────────────────────────────────
def build_dem_v22():
    print("\n" + "="*60)
    print("Step 1: Building v22 DEM")
    print("="*60)

    dem_orig, x, y = load_dem_v10()
    dem_v22 = dem_orig.copy()
    nrows, ncols = dem_v22.shape
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)

    # ── Fix 5a (from v15): Nile floodplain burn ────────────────────────────
    nile_mask = dem_orig < NILE_ELEV_THRESH
    dem_v22[nile_mask] = NILE_TARGET_ELEV
    n_nile = int(nile_mask.sum())
    print(f"  Fix 5a: {n_nile} Nile floodplain cells (dem<{NILE_ELEV_THRESH}m) → {NILE_TARGET_ELEV}m")

    # Fix 5b REMOVED: railway extra burn created a 289m hydraulic sink
    # that pooled water instead of routing it. Gap bridge (Fix 6b) handles
    # channel continuity through the railway zone instead.
    print(f"  Fix 5b: SKIPPED (railway extra burn removed — was creating sink)")

    # ── Fix 6a: Re-rasterize all stream features from GeoJSON ─────────────
    print(f"\n  Fix 6a: Re-rasterizing TDX-Hydro stream features ...")
    with open(GEOJSON) as f:
        gj = json.load(f)

    # Order 9 (Nile): burn to exactly NILE_TARGET_ELEV — ensures continuous channel
    # Order 5/2: burn relative (dem - depth), capped at NILE_TARGET_ELEV
    total_burned_6a = 0
    for feat in gj["features"]:
        order = feat["properties"]["stream_order"]
        geom  = feat["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = [pt for seg in coords for pt in seg]
        for lon, lat in coords:
            ex, ey = tr.transform(lon, lat)
            c = int(round((ex - x[0]) / (x[1] - x[0])))
            r = int(round((ey - y[0]) / (y[1] - y[0])))
            if 0 <= r < nrows and 0 <= c < ncols and not np.isnan(dem_orig[r, c]):
                if order == 9:
                    new_elev = NILE_TARGET_ELEV   # exact 294m for Nile channel
                elif order == 5:
                    new_elev = max(dem_orig[r, c] - BURN_ORDER5, NILE_TARGET_ELEV)
                else:
                    new_elev = max(dem_orig[r, c] - BURN_ORDER2, NILE_TARGET_ELEV)
                if dem_v22[r, c] > new_elev:
                    dem_v22[r, c] = new_elev
                    total_burned_6a += 1
    print(f"    {total_burned_6a} cells burned from GeoJSON stream features")

    # ── Fix 6b: Bridge the two tributary→Nile gaps ────────────────────────
    print(f"\n  Fix 6b: Burning tributary→Nile connecting channels ...")

    # Load GeoJSON features to get endpoint rows
    with open(GEOJSON) as f:
        gj = json.load(f)

    def get_feature_cells(idx):
        feat = gj["features"][idx]
        geom = feat["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = [pt for seg in coords for pt in seg]
        cells = set()
        for lon, lat in coords:
            ex, ey = tr.transform(lon, lat)
            c = int(round((ex - x[0]) / (x[1] - x[0])))
            r = int(round((ey - y[0]) / (y[1] - y[0])))
            if 0 <= r < nrows and 0 <= c < ncols:
                cells.add((r, c))
        return cells

    f17_cells = get_feature_cells(17)   # east tributary (Order 2)
    f18_cells = get_feature_cells(18)   # west tributary (Order 2)
    f19_cells = get_feature_cells(19)   # Nile center (Order 9)
    f22_cells = get_feature_cells(22)   # Nile east bend (Order 9)

    gap_cells_burned = 0

    # Gap 1 (F17 east trib → F22 Nile): F17 already connects to F22 at col=253
    # (gap=0 rows there). No bridge needed — water routes via col=253 junction.
    # Bridging all cols 255-298 burned too many cells creating a 294m pit that
    # flooded with Culvert1 water (322m WSE).
    print("    Gap 1 (F17→F22): SKIPPED — natural connection exists at col=253")

    # Gap 2: F18 (west trib) → F19 (Nile center)
    # Bridge ONLY the narrowest gap columns (≤ 30 rows gap, cols 147-152)
    # to avoid creating large 294m pit areas
    MAX_GAP_ROWS = 30   # only bridge short gaps
    f18_by_col = {}
    for r, c in f18_cells:
        f18_by_col.setdefault(c, []).append(r)
    f19_by_col = {}
    for r, c in f19_cells:
        f19_by_col.setdefault(c, []).append(r)

    gap2_cols = set(f18_by_col) & set(f19_by_col)
    for c in sorted(gap2_cols):
        r_f18_south = min(f18_by_col[c])
        r_f19_north = max(f19_by_col[c])
        gap_rows = r_f18_south - r_f19_north
        if 1 < gap_rows <= MAX_GAP_ROWS:   # only bridge short gaps
            for r in range(r_f19_north, r_f18_south):
                if not np.isnan(dem_orig[r, c]):
                    if dem_v22[r, c] > NILE_TARGET_ELEV:
                        dem_v22[r, c] = NILE_TARGET_ELEV
                        gap_cells_burned += 1

    print(f"    {gap_cells_burned} gap-bridging cells burned (→ {NILE_TARGET_ELEV}m)")

    # ── Fix 6c: Culvert at row=176, col=253 ───────────────────────────────
    print(f"\n  Fix 6c: Burning culvert cell at row={CULVERT_ROW}, col={CULVERT_COL}")
    culvert_surface = dem_orig[CULVERT_ROW, CULVERT_COL]
    culvert_invert  = max(culvert_surface - CULVERT_INVERT_BELOW_SURFACE, NILE_TARGET_ELEV)
    # Burn to invert elevation (allows flow through culvert opening)
    if dem_v22[CULVERT_ROW, CULVERT_COL] > culvert_invert:
        dem_v22[CULVERT_ROW, CULVERT_COL] = culvert_invert
    print(f"    Surface: {culvert_surface:.2f}m → Invert: {culvert_invert:.2f}m (capped at {NILE_TARGET_ELEV}m)")
    # Also burn the immediate neighbours for a 3-cell wide culvert passage
    for dc in [-1, 1]:
        c2 = CULVERT_COL + dc
        if 0 <= c2 < ncols and not np.isnan(dem_orig[CULVERT_ROW, c2]):
            invert2 = max(dem_orig[CULVERT_ROW, c2] - CULVERT_INVERT_BELOW_SURFACE, NILE_TARGET_ELEV)
            if dem_v22[CULVERT_ROW, c2] > invert2:
                dem_v22[CULVERT_ROW, c2] = invert2

    # ── Fix 8: HospitalWadi → Nile connecting channel ─────────────────────
    # Diagnosed from v21 output: F17 GeoJSON only rasterises rows 178-183
    # at col~281. A 29-row (870m) unburned ridge at 315-320m blocks flow
    # between HospitalWadi inflow (row=183) and the Nile 294m zone (row~153).
    # Burn a 3-cell-wide channel (cols 278-280) from row=183 to row=153
    # at dem-8m (same depth logic as the culvert), capped at NILE_TARGET_ELEV.
    print(f"\n  Fix 8: HospitalWadi→Nile connecting channel ...")
    HOSP_BURN_DEPTH   = 8.0    # same as culvert
    HOSP_COL_CENTER   = 279    # lowest-elevation path (cols 278-280)
    HOSP_ROW_TOP      = 183    # HospitalWadi inflow row
    HOSP_ROW_BOTTOM   = 153    # row where Nile 294m zone begins at this col
    hosp_chan_burned   = 0
    for r in range(HOSP_ROW_BOTTOM, HOSP_ROW_TOP + 1):
        for dc in [-1, 0, 1]:   # 3-cell wide channel
            c = HOSP_COL_CENTER + dc
            if 0 <= c < ncols and not np.isnan(dem_orig[r, c]):
                target = max(dem_orig[r, c] - HOSP_BURN_DEPTH, NILE_TARGET_ELEV)
                if dem_v22[r, c] > target:
                    dem_v22[r, c] = target
                    hosp_chan_burned += 1
    print(f"    {hosp_chan_burned} cells burned (cols {HOSP_COL_CENTER-1}–{HOSP_COL_CENTER+1}, "
          f"rows {HOSP_ROW_BOTTOM}–{HOSP_ROW_TOP})")

    n_total = int(np.sum(dem_v22 < dem_orig - 0.5))
    print(f"\n  Total cells modified from burns: {n_total}")

    # ── Fix 7: Pysheds depression filling (hydrologic conditioning) ────────
    print(f"\n  Fix 7: Pysheds depression filling ...")

    # Write burned DEM to temp GeoTIFF for pysheds
    dx_g = x[1]-x[0]; dy_g = y[1]-y[0]
    transform = rasterio.transform.from_origin(x[0]-dx_g/2, y[-1]+dy_g/2, dx_g, dy_g)
    # Use float64 throughout pysheds pipeline — resolve_flats adds sub-millimeter
    # increments that are lost if stored as float32 at ~320m values.
    dem_for_pysheds = np.where(np.isnan(dem_v22), -9999, dem_v22).astype(np.float64)

    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp_tif = tmp.name
    with rasterio.open(tmp_tif, "w", driver="GTiff",
                       height=nrows, width=ncols, count=1, dtype="float64",
                       crs="EPSG:32636", transform=transform, nodata=-9999) as dst_r:
        dst_r.write(np.flipud(dem_for_pysheds), 1)

    # Run depression filling + resolve flats (standard hydrologic conditioning)
    # fill_depressions raises pits to spill point but creates flat areas
    # resolve_flats adds tiny gradients (< 0.01m) through flats to force flow routing
    grid   = Grid.from_raster(tmp_tif)
    dem_ps = grid.read_raster(tmp_tif)
    pits_before = int(np.array(grid.detect_pits(dem_ps)).sum())
    dem_filled   = grid.fill_depressions(dem_ps)
    dem_inflated = grid.resolve_flats(dem_filled)   # adds tiny gradients
    dem_filled_np = np.flipud(np.array(dem_inflated).astype(float))
    dem_filled_np[dem_filled_np <= -9000] = np.nan

    pits_after_check = Grid.from_raster(tmp_tif)
    import tempfile as tf2
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp2:
        tmp2_tif = tmp2.name
    with rasterio.open(tmp2_tif, "w", driver="GTiff",
                       height=nrows, width=ncols, count=1, dtype="float64",
                       crs="EPSG:32636", transform=transform, nodata=-9999) as dst_r2:
        dst_r2.write(np.flipud(np.where(np.isnan(dem_filled_np), -9999, dem_filled_np).astype(np.float64)), 1)
    grid2   = Grid.from_raster(tmp2_tif)
    dem_ps2 = grid2.read_raster(tmp2_tif)
    pits_after = int(np.array(grid2.detect_pits(dem_ps2)).sum())

    # Count raised cells (where filling increased elevation)
    raised_mask = (~np.isnan(dem_filled_np)) & (dem_filled_np > dem_v22 + 0.01)
    n_raised = int(raised_mask.sum())
    max_raise = float(np.nanmax(dem_filled_np[raised_mask])) if n_raised else 0
    print(f"    Pits before filling: {pits_before}")
    print(f"    Pits after filling:  {pits_after}")
    print(f"    Cells raised by fill: {n_raised} (max elevation after fill: {max_raise:.1f}m)")

    # Use filled DEM as the base (all pits resolved to spill points).
    # Then re-apply deliberate channel burns so the burned stream cells
    # remain lowered (override the filled value with the burned value).
    dem_after_burns = dem_filled_np.copy()
    burn_mask = (~np.isnan(dem_v22)) & (dem_v22 < dem_orig - 0.1)
    dem_after_burns[burn_mask] = dem_v22[burn_mask]
    dem_after_burns = np.where(np.isnan(dem_v22), np.nan, dem_after_burns)

    # Second fill pass: re-applying burns may re-introduce pits at channel cells.
    # Run fill+resolve_flats again on dem_after_burns to clear them.
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp3:
        tmp3_tif = tmp3.name
    dem_ab_for_ps = np.where(np.isnan(dem_after_burns), -9999, dem_after_burns).astype(np.float64)
    with rasterio.open(tmp3_tif, "w", driver="GTiff",
                       height=nrows, width=ncols, count=1, dtype="float64",
                       crs="EPSG:32636", transform=transform, nodata=-9999) as dst_r3:
        dst_r3.write(np.flipud(dem_ab_for_ps), 1)
    grid3  = Grid.from_raster(tmp3_tif)
    dem_p3 = grid3.read_raster(tmp3_tif)
    pits3_before = int(np.array(grid3.detect_pits(dem_p3)).sum())
    dem_f3  = grid3.fill_depressions(dem_p3)
    dem_inf3 = grid3.resolve_flats(dem_f3)
    dem_final = np.flipud(np.array(dem_inf3).astype(float))
    dem_final[dem_final <= -9000] = np.nan
    dem_final = np.where(np.isnan(dem_v22), np.nan, dem_final)
    pits3_after = int(np.array(grid3.detect_pits(dem_inf3)).sum())
    print(f"    2nd fill pass: {pits3_before} pits → {pits3_after} pits")
    os.unlink(tmp3_tif)

    os.unlink(tmp_tif); os.unlink(tmp2_tif)

    n_total_final = int(np.sum(dem_final < dem_orig - 0.5))
    print(f"    Total cells modified from v10 DEM (after fill): {n_total_final}")

    # Write final DEM to GeoTIFF (for diagnostic) — float64 to preserve gradients
    tif_out = V22_INPUT / "dem_v22.tif"
    with rasterio.open(str(tif_out), "w", driver="GTiff",
                       height=nrows, width=ncols, count=1, dtype="float64",
                       crs="EPSG:32636", transform=transform, nodata=-9999) as dst_r:
        dst_r.write(np.flipud(np.where(np.isnan(dem_final), -9999, dem_final).astype(np.float64)), 1)
    print(f"    Saved GeoTIFF: {tif_out.name}")

    # Write NetCDF — recreate as float64 to preserve resolve_flats gradients
    # (v10 original is float32 which would truncate sub-millimeter increments)
    src_ds = netCDF4.Dataset(str(V10_INPUT / "dem.nc"))
    dst = V22_INPUT / "dem_v22.nc"
    ds_out = netCDF4.Dataset(str(dst), "w", format="NETCDF4")
    ds_out.createDimension("x", len(x))
    ds_out.createDimension("y", len(y))
    vx = ds_out.createVariable("x", "f8", ("x",)); vx[:] = x
    vy = ds_out.createVariable("y", "f8", ("y",)); vy[:] = y
    # Copy attributes from source x/y
    for attr in src_ds["x"].ncattrs(): vx.setncattr(attr, src_ds["x"].getncattr(attr))
    for attr in src_ds["y"].ncattrs(): vy.setncattr(attr, src_ds["y"].getncattr(attr))
    vband = ds_out.createVariable("Band1", "f8", ("y", "x"), fill_value=-9999.0)
    src_var = [v for v in src_ds.variables if v not in ("x","y")][0]
    for attr in src_ds[src_var].ncattrs():
        try: vband.setncattr(attr, src_ds[src_var].getncattr(attr))
        except: pass
    arr_out = np.where(np.isnan(dem_final), -9999.0, dem_final)
    vband[:] = arr_out
    src_ds.close(); ds_out.close()
    print(f"  Saved NetCDF (float64): {dst}")
    return x, y


# ── Step 2: Copy boundary mask ────────────────────────────────────────────
def copy_boundary_mask():
    print("\nStep 2: Copying boundary mask from v15")
    src = V15_INPUT / "fluvbound_mask_v15.nc"
    dst = V22_INPUT / "fluvbound_mask_v22.nc"
    shutil.copy2(src, dst)
    print(f"  Copied: {dst.name}")


# ── Step 3: IMERG symlinks (same as v14/v15) ──────────────────────────────
def setup_rain_symlinks():
    rain_dir = V22_INPUT / "rain"
    rain_dir.mkdir(exist_ok=True)
    existing = list(rain_dir.glob("imerg_v22_t*.nc"))
    if len(existing) == N_RAIN:
        print(f"\nStep 3: {N_RAIN} rain symlinks already exist — skipping")
        return
    print(f"\nStep 3: Creating {N_RAIN} IMERG symlinks (Aug 25-31)")
    src_dir = WORK_DIR / "v10" / "input" / "rain"
    for i in range(1, N_RAIN + 1):
        src = src_dir / f"imerg_v10_t{IMERG_START_STEP + i}.nc"
        dst = rain_dir / f"imerg_v22_t{i}.nc"
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(str(src), str(dst))
    print(f"  t1 → imerg_v10_t{IMERG_START_STEP+1}.nc")
    print(f"  t{N_RAIN} → imerg_v10_t{IMERG_START_STEP+N_RAIN}.nc")


# ── Step 4: Regenerate inflowlocs ─────────────────────────────────────────
def flow_to_wse_capped(q, sill, w, h, n, s):
    """Manning culvert WSE, capped at sill + WSE_CAP_M."""
    import math
    A = w * h; P = 2*h + w; R = A/P
    q_full = (1/n) * A * R**(2/3) * s**0.5
    if q <= 0:    return sill
    if q >= q_full: return sill + WSE_CAP_M
    depth = (q * n / (w * s**0.5))**(3/5)
    depth = min(depth, WSE_CAP_M)
    return sill + depth

def flow_to_wse_wadi(q, sill):
    """Simple rectangular channel WSE for open wadi."""
    if q <= 0: return sill
    W = 10.0; n = 0.030; S = 0.005
    depth = (q * n / (W * S**0.5))**(3/5)
    depth = min(depth, WSE_CAP_M)
    return sill + depth

def regenerate_inflowlocs():
    print("\nStep 4: Re-generating inflowlocs_v22.txt from v12 NPZ cache")
    npz_path = WORK_DIR / "v12" / "input" / "culvert_hydrographs_v12.npz"
    data = np.load(str(npz_path))

    CULVERT_W=4.0; CULVERT_H=2.5; CULVERT_N=0.013; CULVERT_S=0.005

    def trim(arr):
        return arr[IMERG_START_STEP: IMERG_START_STEP + N_WSE]
    def pad(arr):
        if len(arr) < N_WSE:
            arr = np.concatenate([arr, np.full(N_WSE - len(arr), arr[-1])])
        return arr[:N_WSE]

    q_c1   = pad(trim(data["q_Culvert1"]))
    q_c2   = pad(trim(data["q_Culvert2"]))
    q_west = pad(trim(data["q_WesternWadi"]))
    q_hw   = pad(trim(data["q_HospitalWadi"]))

    d = INFLOW_DEFS
    wse_c1   = [flow_to_wse_capped(q, d["Culvert1"]["sill"],    CULVERT_W,CULVERT_H,CULVERT_N,CULVERT_S) for q in q_c1]
    wse_c2   = [flow_to_wse_capped(q, d["Culvert2"]["sill"],    CULVERT_W,CULVERT_H,CULVERT_N,CULVERT_S) for q in q_c2]
    wse_west = [flow_to_wse_wadi(q, d["WesternWadi"]["sill"])   for q in q_west]
    wse_hw   = [flow_to_wse_wadi(q, d["HospitalWadi"]["sill"])  for q in q_hw]

    out_path = V22_INPUT / "inflowlocs_v22.txt"
    with open(out_path, "w") as f:
        f.write(f"{SIM_DUR}\n{DT_INFLOW}\n4\n")
        for (name, wse_arr) in [("Culvert1",wse_c1),("Culvert2",wse_c2),
                                  ("WesternWadi",wse_west),("HospitalWadi",wse_hw)]:
            row = d[name]["row"]; col = d[name]["col"]
            vals = " ".join(f"{v:.3f}" for v in wse_arr)
            f.write(f"{row+1}\t{col+1}\t{vals}\n")
            print(f"  {name}: peak WSE = {max(wse_arr):.2f}m")
    print(f"  Saved: {out_path}")


# ── Step 5: Write simulation_v22.def ─────────────────────────────────────
def write_def_file():
    print("\nStep 5: Writing simulation_v22.def")
    out_timing = " ".join(str(t) for t in range(21600, SIM_DUR+1, 21600))
    n_out = SIM_DUR // 21600
    content = f"""\
# RIM2D v22 — HospitalWadi→Nile channel fix
# Fix 5a: Nile floodplain burn (dem<308m → 294m)
# Fix 6a: Re-rasterize all TDX-Hydro stream features
# Fix 6b: Bridge F18→F19 narrow gap (≤30 rows)
# Fix 6c: 8m culvert at row=176, col=253 (19.537547N, 33.32237E)
# Fix 7:  Pysheds depression filling + resolve_flats (2 passes)
# Fix 8:  HospitalWadi→Nile channel: cols 278-280, rows 153-183, dem-8m

###### INPUT RASTERS ######
**DEM**
input/dem_v22.nc
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
input/inflowlocs_v22.txt

**pluvial_raster_nr**
{N_RAIN}
**pluvial_dt**
1800
**pluvial_start**
0
**pluvial_base_fn**
input/rain/imerg_v22_t

###### OUTPUT ######
**output_base_fn**
output/nile_v22_
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
input/fluvbound_mask_v22.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    out_path = V22_DIR / "simulation_v22.def"
    out_path.write_text(content)
    print(f"  Saved: {out_path}")


# ── Step 6: Save metadata ─────────────────────────────────────────────────
def save_metadata():
    meta = {
        "version": "v22",
        "fixes": {
            "5a": "Nile floodplain burn dem<301m → 294m",
            "5b": f"Railway crossing extra burn rows {RAILWAY_ROW_MIN}-{RAILWAY_ROW_MAX}",
            "6a": "Re-rasterize all TDX-Hydro GeoJSON stream features",
            "6b": "Bridge tributary→Nile gaps: F17→F22 (east) and F18→F19 (west)",
            "6c": f"8m culvert at row={CULVERT_ROW}, col={CULVERT_COL} (19.537547N, 33.32237E)",
        },
        "culvert": {"row": CULVERT_ROW, "col": CULVERT_COL,
                    "lat": 19.537547, "lon": 33.32237,
                    "depth_m": CULVERT_INVERT_BELOW_SURFACE},
    }
    out_path = V22_INPUT / "v22_metadata.json"
    with open(out_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\nStep 6: Metadata saved: {out_path}")


if __name__ == "__main__":
    print("="*60)
    print("RIM2D v22 Setup — Tributary channels + culvert fix")
    print("="*60)
    build_dem_v22()
    copy_boundary_mask()
    setup_rain_symlinks()
    regenerate_inflowlocs()
    write_def_file()
    save_metadata()
    print(f"""
{'='*60}
Setup complete. To run:
  cd /data/rim2d/nile_highres/v22
  export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
  /data/rim2d/bin/RIM2D simulation_v22.def --def flex
{'='*60}
""")
