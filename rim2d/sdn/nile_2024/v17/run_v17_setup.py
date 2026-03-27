#!/usr/bin/env python3
"""
RIM2D v17 — Fix missing tributary channels + culvert burn.

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
    micromamba run -n zarrv3 python v17/run_v17_setup.py
    cd v17 && /data/rim2d/bin/RIM2D simulation_v17.def --def flex
"""

from pathlib import Path
import shutil, json, os
import numpy as np
import netCDF4
from pyproj import Transformer

WORK_DIR  = Path("/data/rim2d/nile_highres")
V10_INPUT = WORK_DIR / "v10" / "input"
V15_INPUT = WORK_DIR / "v15" / "input"
V13_INPUT = WORK_DIR / "v13" / "input"
V17_DIR   = WORK_DIR / "v17"
V17_INPUT = V17_DIR  / "input"
V17_INPUT.mkdir(parents=True, exist_ok=True)
(V17_DIR / "output").mkdir(exist_ok=True)

GEOJSON   = WORK_DIR / "v11" / "input" / "river_network_tdx_v2.geojson"

# ── Burn depth parameters ──────────────────────────────────────────────────
BURN_ORDER9   = 5.0   # Nile main channel
BURN_ORDER5   = 3.0   # major wadis
BURN_ORDER2   = 2.0   # minor wadis
BURN_GAP      = 3.0   # connecting gap channels (treat as Order 5 equivalent)
CULVERT_INVERT_BELOW_SURFACE = 8.0  # culvert is 8m below DEM surface

# Culvert location (confirmed from coordinate conversion)
CULVERT_ROW, CULVERT_COL = 176, 253

# Nile floodplain burn (from v15)
NILE_ELEV_THRESH = 301.0
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


# ── Step 1: Build v17 DEM ─────────────────────────────────────────────────
def build_dem_v17():
    print("\n" + "="*60)
    print("Step 1: Building v17 DEM")
    print("="*60)

    dem_orig, x, y = load_dem_v10()
    dem_v17 = dem_orig.copy()
    nrows, ncols = dem_v17.shape
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)

    # ── Fix 5a (from v15): Nile floodplain burn ────────────────────────────
    nile_mask = dem_orig < NILE_ELEV_THRESH
    dem_v17[nile_mask] = NILE_TARGET_ELEV
    n_nile = int(nile_mask.sum())
    print(f"  Fix 5a: {n_nile} Nile floodplain cells (dem<{NILE_ELEV_THRESH}m) → {NILE_TARGET_ELEV}m")

    # ── Fix 5b (from v15): Railway crossing extra burn ─────────────────────
    ds13 = netCDF4.Dataset(str(V13_INPUT / "dem_v13.nc"))
    var13 = [v for v in ds13.variables if v not in ("x", "y")][0]
    dem_v13 = np.array(ds13[var13][:]).squeeze().astype(float)
    dem_v13[dem_v13 < -9000] = np.nan
    ds13.close()
    already_burned = (dem_v13 < dem_orig - 0.5)
    railway_band = np.zeros(dem_v17.shape, dtype=bool)
    railway_band[RAILWAY_ROW_MIN:RAILWAY_ROW_MAX+1, :] = True
    railway_extra_mask = already_burned & railway_band
    dem_v17[railway_extra_mask] -= RAILWAY_BURN_EXTRA
    n_rwy = int(railway_extra_mask.sum())
    print(f"  Fix 5b: {n_rwy} railway crossing cells (rows {RAILWAY_ROW_MIN}-{RAILWAY_ROW_MAX}) lowered by {RAILWAY_BURN_EXTRA}m")

    # ── Fix 6a: Re-rasterize all stream features from GeoJSON ─────────────
    print(f"\n  Fix 6a: Re-rasterizing TDX-Hydro stream features ...")
    with open(GEOJSON) as f:
        gj = json.load(f)

    burn_depths = {9: BURN_ORDER9, 5: BURN_ORDER5, 2: BURN_ORDER2}
    total_burned_6a = 0
    for feat in gj["features"]:
        order = feat["properties"]["stream_order"]
        depth = burn_depths.get(order, BURN_ORDER2)
        geom  = feat["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = [pt for seg in coords for pt in seg]
        for lon, lat in coords:
            ex, ey = tr.transform(lon, lat)
            c = int(round((ex - x[0]) / (x[1] - x[0])))
            r = int(round((ey - y[0]) / (y[1] - y[0])))
            if 0 <= r < nrows and 0 <= c < ncols and not np.isnan(dem_orig[r, c]):
                new_elev = dem_orig[r, c] - depth
                if dem_v17[r, c] > new_elev:
                    dem_v17[r, c] = new_elev
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

    # Gap 1: F17 (east trib) → F22 (Nile east bend)
    # For each col in F17, find southernmost F17 row and northernmost F22 row
    f17_by_col = {}
    for r, c in f17_cells:
        f17_by_col.setdefault(c, []).append(r)
    f22_by_col = {}
    for r, c in f22_cells:
        f22_by_col.setdefault(c, []).append(r)

    gap1_cols = set(f17_by_col) & set(f22_by_col)
    for c in gap1_cols:
        r_f17_south = min(f17_by_col[c])   # lowest row = southernmost
        r_f22_north = max(f22_by_col[c])   # highest row = northernmost
        if r_f17_south > r_f22_north + 1:  # gap exists
            # Burn straight channel from f17 south end down to f22 north end
            for r in range(r_f22_north, r_f17_south + 1):
                if not np.isnan(dem_orig[r, c]):
                    new_elev = dem_orig[r, c] - BURN_GAP
                    if dem_v17[r, c] > new_elev:
                        dem_v17[r, c] = new_elev
                        gap_cells_burned += 1

    # Gap 2: F18 (west trib) → F19 (Nile center)
    f18_by_col = {}
    for r, c in f18_cells:
        f18_by_col.setdefault(c, []).append(r)
    f19_by_col = {}
    for r, c in f19_cells:
        f19_by_col.setdefault(c, []).append(r)

    gap2_cols = set(f18_by_col) & set(f19_by_col)
    for c in gap2_cols:
        r_f18_south = min(f18_by_col[c])
        r_f19_north = max(f19_by_col[c])
        if r_f18_south > r_f19_north + 1:
            for r in range(r_f19_north, r_f18_south + 1):
                if not np.isnan(dem_orig[r, c]):
                    new_elev = dem_orig[r, c] - BURN_GAP
                    if dem_v17[r, c] > new_elev:
                        dem_v17[r, c] = new_elev
                        gap_cells_burned += 1

    print(f"    {gap_cells_burned} gap-bridging cells burned (−{BURN_GAP}m)")

    # ── Fix 6c: Culvert at row=176, col=253 ───────────────────────────────
    print(f"\n  Fix 6c: Burning culvert cell at row={CULVERT_ROW}, col={CULVERT_COL}")
    culvert_surface = dem_orig[CULVERT_ROW, CULVERT_COL]
    culvert_invert  = culvert_surface - CULVERT_INVERT_BELOW_SURFACE
    # Burn to invert elevation (allows flow through culvert opening)
    if dem_v17[CULVERT_ROW, CULVERT_COL] > culvert_invert:
        dem_v17[CULVERT_ROW, CULVERT_COL] = culvert_invert
    print(f"    Surface: {culvert_surface:.2f}m → Invert: {culvert_invert:.2f}m")
    # Also burn the immediate neighbours for a 3-cell wide culvert passage
    for dc in [-1, 1]:
        c2 = CULVERT_COL + dc
        if 0 <= c2 < ncols and not np.isnan(dem_orig[CULVERT_ROW, c2]):
            invert2 = dem_orig[CULVERT_ROW, c2] - CULVERT_INVERT_BELOW_SURFACE
            if dem_v17[CULVERT_ROW, c2] > invert2:
                dem_v17[CULVERT_ROW, c2] = invert2

    # ── Summary ───────────────────────────────────────────────────────────
    n_total = int(np.sum(dem_v17 < dem_orig - 0.5))
    print(f"\n  Total cells modified from v10 DEM: {n_total}")

    # Write DEM
    src = V10_INPUT / "dem.nc"
    dst = V17_INPUT / "dem_v17.nc"
    shutil.copy2(src, dst)
    ds_out = netCDF4.Dataset(str(dst), "r+")
    var_out = [v for v in ds_out.variables if v not in ("x", "y")][0]
    arr = ds_out[var_out][:]
    arr_np = np.array(arr).squeeze().astype(float)
    arr_np[~np.isnan(dem_v17)] = dem_v17[~np.isnan(dem_v17)]
    ds_out[var_out][:] = arr_np
    ds_out.close()
    print(f"  Saved: {dst}")
    return x, y


# ── Step 2: Copy boundary mask ────────────────────────────────────────────
def copy_boundary_mask():
    print("\nStep 2: Copying boundary mask from v15")
    src = V15_INPUT / "fluvbound_mask_v15.nc"
    dst = V17_INPUT / "fluvbound_mask_v17.nc"
    shutil.copy2(src, dst)
    print(f"  Copied: {dst.name}")


# ── Step 3: IMERG symlinks (same as v14/v15) ──────────────────────────────
def setup_rain_symlinks():
    rain_dir = V17_INPUT / "rain"
    rain_dir.mkdir(exist_ok=True)
    existing = list(rain_dir.glob("imerg_v17_t*.nc"))
    if len(existing) == N_RAIN:
        print(f"\nStep 3: {N_RAIN} rain symlinks already exist — skipping")
        return
    print(f"\nStep 3: Creating {N_RAIN} IMERG symlinks (Aug 25-31)")
    src_dir = WORK_DIR / "v10" / "input" / "rain"
    for i in range(1, N_RAIN + 1):
        src = src_dir / f"imerg_v10_t{IMERG_START_STEP + i}.nc"
        dst = rain_dir / f"imerg_v17_t{i}.nc"
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
    print("\nStep 4: Re-generating inflowlocs_v17.txt from v12 NPZ cache")
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

    out_path = V17_INPUT / "inflowlocs_v17.txt"
    with open(out_path, "w") as f:
        f.write(f"{SIM_DUR}\n{DT_INFLOW}\n4\n")
        for (name, wse_arr) in [("Culvert1",wse_c1),("Culvert2",wse_c2),
                                  ("WesternWadi",wse_west),("HospitalWadi",wse_hw)]:
            row = d[name]["row"]; col = d[name]["col"]
            vals = " ".join(f"{v:.3f}" for v in wse_arr)
            f.write(f"{row+1}\t{col+1}\t{vals}\n")
            print(f"  {name}: peak WSE = {max(wse_arr):.2f}m")
    print(f"  Saved: {out_path}")


# ── Step 5: Write simulation_v17.def ─────────────────────────────────────
def write_def_file():
    print("\nStep 5: Writing simulation_v17.def")
    out_timing = " ".join(str(t) for t in range(21600, SIM_DUR+1, 21600))
    n_out = SIM_DUR // 21600
    content = f"""\
# RIM2D v17 — Fix missing tributary channels + culvert
# Fix 5a: Nile floodplain burn (dem<301m → 294m)
# Fix 5b: Railway crossing extra burn (rows 78-92)
# Fix 6a: Re-rasterize all TDX-Hydro stream features
# Fix 6b: Bridge tributary→Nile gap channels (F17→F22, F18→F19)
# Fix 6c: 8m culvert at row=176, col=253 (19.537547N, 33.32237E)

###### INPUT RASTERS ######
**DEM**
input/dem_v17.nc
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
input/inflowlocs_v17.txt

**pluvial_raster_nr**
{N_RAIN}
**pluvial_dt**
1800
**pluvial_start**
0
**pluvial_base_fn**
input/rain/imerg_v17_t

###### OUTPUT ######
**output_base_fn**
output/nile_v17_
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
input/fluvbound_mask_v17.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    out_path = V17_DIR / "simulation_v17.def"
    out_path.write_text(content)
    print(f"  Saved: {out_path}")


# ── Step 6: Save metadata ─────────────────────────────────────────────────
def save_metadata():
    meta = {
        "version": "v17",
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
    out_path = V17_INPUT / "v17_metadata.json"
    with open(out_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\nStep 6: Metadata saved: {out_path}")


if __name__ == "__main__":
    print("="*60)
    print("RIM2D v17 Setup — Tributary channels + culvert fix")
    print("="*60)
    build_dem_v17()
    copy_boundary_mask()
    setup_rain_symlinks()
    regenerate_inflowlocs()
    write_def_file()
    save_metadata()
    print(f"""
{'='*60}
Setup complete. To run:
  cd /data/rim2d/nile_highres/v17
  export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
  /data/rim2d/bin/RIM2D simulation_v17.def --def flex
{'='*60}
""")
