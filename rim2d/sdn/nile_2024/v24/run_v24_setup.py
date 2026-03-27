#!/usr/bin/env python3
"""
RIM2D v24 — v23 base + corr3.kml connectivity fix.

Root-cause analysis of v23 stagnation
--------------------------------------
The cor2.kml burn creates a channel along col~251 (rows 158–176) at ~311.70m.
Water from Culvert1/Culvert2/HospitalWadi flows into this channel and pools
at row=158, col=250 (306.44m, already burned).  In 4-directional routing
(which RIM2D uses), all 4 orthogonal neighbours of that cell are HIGHER than
306.44m, making it a pit:
  N row=159,col=250: 320.87m  S row=157,col=250: 314.30m
  E row=158,col=251: 309.11m  W row=158,col=249: 314.14m
The one usable exit (diagonal to row=157,col=249=302.79m) is only reachable
via 8-directional routing (pysheds), not 4-directional (RIM2D).  So the
depression fill passes because pysheds "sees" the diagonal exit, but RIM2D
never actually routes water there.

Fix G — corr3.kml (dem_orig − 1m)
-----------------------------------
corr3.kml traces a path from row=176 to row=158 along col~249-254.  Burned
at dem_orig − 1m it provides a shallow but real channel.  The burn lowers
blocking cells west of col=251 so that 4-directional flow becomes possible.

Fix H — 4-dir gap bridge (rows 155–158, cols 248–251)
-------------------------------------------------------
After corr3 is burned, programmatically ensure 4-directional connectivity
from the corr3 channel to the Nile zone (294 m cells at rows ≤155) by:
  1. Finding the minimum elevation along the corr3 path in the critical zone
     (rows 155–160, cols 247–255).
  2. Tracing a monotonically decreasing gradient south through any remaining
     ridge cells until reaching a Nile-zone cell (≤295 m), burning to
     max(linear_gradient, NILE_TARGET_ELEV).
This guarantees a 4-directional drainage path that RIM2D can use.

Usage:
    micromamba run -n zarrv3 python v24/run_v24_setup.py
    cd v24 && /data/rim2d/bin/RIM2D simulation_v24.def --def flex
"""

from pathlib import Path
import os, json, tempfile
import xml.etree.ElementTree as ET
import numpy as np
import netCDF4
import rasterio
from pyproj import Transformer
from pysheds.grid import Grid

WORK_DIR  = Path("/data/rim2d/nile_highres")
V10_INPUT = WORK_DIR / "v10" / "input"
V15_INPUT = WORK_DIR / "v15" / "input"
V23_DIR   = WORK_DIR / "v23"
V24_DIR   = WORK_DIR / "v24"
V24_INPUT = V24_DIR  / "input"
V24_INPUT.mkdir(parents=True, exist_ok=True)
(V24_DIR / "output").mkdir(exist_ok=True)

KML_COR1  = V23_DIR / "cor1.kml"
KML_COR2  = V23_DIR / "cor2.kml"
KML_CORR3 = V23_DIR / "corr3.kml"
KML_NS    = {"kml": "http://www.opengis.net/kml/2.2"}
GEOJSON   = WORK_DIR / "v11" / "input" / "river_network_tdx_v2.geojson"

# ── Burn parameters ──────────────────────────────────────────────────────────
NILE_ELEV_THRESH = 308.0
NILE_TARGET_ELEV = 294.0

BURN_ORDER9   = None   # Order-9: burn to NILE_TARGET_ELEV
BURN_ORDER5   = 3.0    # Order-5: dem - 3m
BURN_ORDER2   = 2.0    # Order-2: dem - 2m
SKIP_LINKNO   = 160245676

COR_BURN_DEPTH   = 8.0   # cor1/cor2: dem - 8m
CORR3_BURN_DEPTH = 1.0   # corr3:     dem - 1m (shallow channel)

# Gap bridges
MAX_GAP_ROWS  = 30       # Fix E: F18→F19 gap
# Fix H: 4-dir bridge search area (must be ABOVE the Nile zone)
BRIDGE_ROW_LO = 157      # south limit (just above Nile zone edge ~row 155)
BRIDGE_ROW_HI = 162      # north limit
BRIDGE_COL_LO = 248      # west limit
BRIDGE_COL_HI = 256      # east limit

# ── Simulation parameters ────────────────────────────────────────────────────
SIM_DUR          = 518_400
DT_INFLOW        = 1800
N_RAIN           = SIM_DUR // DT_INFLOW        # 288
IMERG_START_STEP = 1488
WSE_CAP_M        = 1.5

INFLOW_DEFS = {
    "Culvert1":    {"row": 212, "col": 312, "sill": 321.105},
    "Culvert2":    {"row": 222, "col": 266, "sill": 320.012},
    "WesternWadi": {"row": 222, "col": 175, "sill": 318.855},
    "HospitalWadi":{"row": 183, "col": 281, "sill": 316.134},
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def load_dem_v10():
    ds  = netCDF4.Dataset(str(V10_INPUT / "dem.nc"))
    x   = np.array(ds["x"][:])
    y   = np.array(ds["y"][:])
    var = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[var][:]).squeeze().astype(float)
    dem[dem < -9000] = np.nan
    ds.close()
    return dem, x, y


def bresenham(r0, c0, r1, c1):
    """All grid cells on the line (r0,c0)→(r1,c1), 4-connected.
    At diagonal steps, an intermediate orthogonal cell is inserted so that
    every consecutive pair of cells shares an edge (not just a corner).
    This is essential for RIM2D 4-directional flow routing.
    """
    pts = []
    dr = abs(r1-r0); dc = abs(c1-c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dr - dc
    r, c = r0, c0
    while True:
        pts.append((r, c))
        if r == r1 and c == c1:
            break
        e2 = 2 * err
        step_r = e2 > -dc
        step_c = e2 <  dr
        if step_r and step_c:
            # Diagonal — insert intermediate orthogonal cell for 4-connectivity
            # Move along the dominant axis first
            if dr >= dc:
                pts.append((r + sr, c))   # row step first
            else:
                pts.append((r, c + sc))   # col step first
            err -= dc; r += sr
            err += dr; c += sc
        elif step_r:
            err -= dc; r += sr
        else:
            err += dr; c += sc
    return pts


def kml_to_cells(kml_path, x, y, nrows, ncols, tr):
    """Parse KML → all grid cells along the line (Bresenham rasterized)."""
    tree = ET.parse(str(kml_path))
    root = tree.getroot()
    cells = []
    for coords_el in root.findall(".//kml:coordinates", KML_NS):
        raw_pts = []
        for pt in coords_el.text.strip().split():
            parts = pt.strip().split(",")
            if len(parts) < 2:
                continue
            lon, lat = float(parts[0]), float(parts[1])
            ex, ey = tr.transform(lon, lat)
            c = int(round((ex - x[0]) / (x[1] - x[0])))
            r = int(round((ey - y[0]) / (y[1] - y[0])))
            raw_pts.append((r, c))
        for i in range(len(raw_pts) - 1):
            for r, c in bresenham(raw_pts[i][0], raw_pts[i][1],
                                   raw_pts[i+1][0], raw_pts[i+1][1]):
                if 0 <= r < nrows and 0 <= c < ncols:
                    cells.append((r, c))
        if raw_pts:
            r, c = raw_pts[-1]
            if 0 <= r < nrows and 0 <= c < ncols:
                cells.append((r, c))
    return cells


def pysheds_fill_pass(dem_in, transform, nrows, ncols):
    """One pass of fill_depressions + resolve_flats (float64)."""
    arr = np.where(np.isnan(dem_in), -9999.0, dem_in).astype(np.float64)
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        p = tmp.name
    with rasterio.open(p, "w", driver="GTiff", height=nrows, width=ncols,
                       count=1, dtype="float64", crs="EPSG:32636",
                       transform=transform, nodata=-9999) as dst:
        dst.write(np.flipud(arr), 1)
    grid   = Grid.from_raster(p)
    dem_ps = grid.read_raster(p)
    n_pits = int(np.array(grid.detect_pits(dem_ps)).sum())
    filled = grid.fill_depressions(dem_ps)
    inflated = grid.resolve_flats(filled)
    result = np.flipud(np.array(inflated).astype(float))
    result[result <= -9000] = np.nan
    os.unlink(p)
    return result, n_pits


# ── Step 1: Build v24 DEM ─────────────────────────────────────────────────────
def build_dem_v24():
    print("\n" + "="*60)
    print("Step 1: Building v24 DEM")
    print("="*60)

    dem_orig, x, y = load_dem_v10()
    dem = dem_orig.copy()
    nrows, ncols = dem.shape
    dx = x[1]-x[0]; dy = y[1]-y[0]
    transform = rasterio.transform.from_origin(x[0]-dx/2, y[-1]+dy/2, dx, dy)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)

    print(f"  Base: v10 raw MERIT DEM ({nrows}×{ncols}, "
          f"{np.nanmin(dem_orig):.1f}–{np.nanmax(dem_orig):.1f}m)")

    # ── Fix A: Nile floodplain burn ─────────────────────────────────────────
    nile_mask = dem_orig < NILE_ELEV_THRESH
    dem[nile_mask] = NILE_TARGET_ELEV
    print(f"\n  Fix A: Nile floodplain — {int(nile_mask.sum()):,} cells → {NILE_TARGET_ELEV}m")

    # ── Fix B: GeoJSON stream burns ──────────────────────────────────────────
    print(f"\n  Fix B: GeoJSON stream burns (skip linkno={SKIP_LINKNO}) ...")
    with open(GEOJSON) as f:
        gj = json.load(f)
    n_b = 0; n_skip = 0
    for feat in gj["features"]:
        if feat["properties"]["linkno"] == SKIP_LINKNO:
            n_skip += 1
            continue
        order  = feat["properties"]["stream_order"]
        geom   = feat["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = [pt for seg in coords for pt in seg]
        for lon, lat in coords:
            ex, ey = tr.transform(lon, lat)
            c = int(round((ex - x[0]) / (x[1] - x[0])))
            r = int(round((ey - y[0]) / (y[1] - y[0])))
            if 0 <= r < nrows and 0 <= c < ncols and not np.isnan(dem_orig[r, c]):
                if order == 9:
                    new_e = NILE_TARGET_ELEV
                elif order == 5:
                    new_e = max(dem_orig[r, c] - BURN_ORDER5, NILE_TARGET_ELEV)
                else:
                    new_e = max(dem_orig[r, c] - BURN_ORDER2, NILE_TARGET_ELEV)
                if dem[r, c] > new_e:
                    dem[r, c] = new_e
                    n_b += 1
    print(f"    {n_b} cells burned ({n_skip} feature(s) skipped)")

    # ── Fix C: cor1.kml — dem - 8m ──────────────────────────────────────────
    cells_c1 = kml_to_cells(KML_COR1, x, y, nrows, ncols, tr)
    n_c1 = 0
    for r, c in cells_c1:
        if not np.isnan(dem_orig[r, c]):
            target = max(dem_orig[r, c] - COR_BURN_DEPTH, NILE_TARGET_ELEV)
            if dem[r, c] > target:
                dem[r, c] = target; n_c1 += 1
    rs1 = [r for r,c in cells_c1]; cs1 = [c for r,c in cells_c1]
    print(f"\n  Fix C: cor1.kml — {n_c1} cells burned "
          f"(rows {min(rs1)}-{max(rs1)}, cols {min(cs1)}-{max(cs1)})")

    # ── Fix D: cor2.kml — dem - 8m ──────────────────────────────────────────
    cells_c2 = kml_to_cells(KML_COR2, x, y, nrows, ncols, tr)
    n_c2 = 0
    for r, c in cells_c2:
        if not np.isnan(dem_orig[r, c]):
            target = max(dem_orig[r, c] - COR_BURN_DEPTH, NILE_TARGET_ELEV)
            if dem[r, c] > target:
                dem[r, c] = target; n_c2 += 1
    rs2 = [r for r,c in cells_c2]; cs2 = [c for r,c in cells_c2]
    print(f"\n  Fix D: cor2.kml — {n_c2} cells burned "
          f"(rows {min(rs2)}-{max(rs2)}, cols {min(cs2)}-{max(cs2)})")

    # ── Fix E: Gap bridge F18→F19 ────────────────────────────────────────────
    print(f"\n  Fix E: Gap bridge F18→F19 (gaps ≤{MAX_GAP_ROWS} rows) ...")
    def feature_cells(idx):
        feat   = gj["features"][idx]
        geom   = feat["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = [pt for seg in coords for pt in seg]
        out = set()
        for lon, lat in coords:
            ex, ey = tr.transform(lon, lat)
            c = int(round((ex - x[0]) / (x[1] - x[0])))
            r = int(round((ey - y[0]) / (y[1] - y[0])))
            if 0 <= r < nrows and 0 <= c < ncols:
                out.add((r, c))
        return out

    f18_cells = feature_cells(18); f19_cells = feature_cells(19)
    f18_by_col = {}; f19_by_col = {}
    for r, c in f18_cells: f18_by_col.setdefault(c, []).append(r)
    for r, c in f19_cells: f19_by_col.setdefault(c, []).append(r)
    gap_burned = 0
    for col in sorted(set(f18_by_col) & set(f19_by_col)):
        r_top    = min(f18_by_col[col])
        r_bottom = max(f19_by_col[col])
        gap = r_top - r_bottom
        if 1 < gap <= MAX_GAP_ROWS:
            for r in range(r_bottom, r_top):
                if not np.isnan(dem_orig[r, col]):
                    if dem[r, col] > NILE_TARGET_ELEV:
                        dem[r, col] = NILE_TARGET_ELEV
                        gap_burned += 1
    print(f"    {gap_burned} cells burned (→ {NILE_TARGET_ELEV}m)")

    # ── Fix G: corr3.kml — dem_orig - 1m (shallow channel) ─────────────────
    print(f"\n  Fix G: corr3.kml — dem_orig - {CORR3_BURN_DEPTH}m ...")
    cells_g = kml_to_cells(KML_CORR3, x, y, nrows, ncols, tr)
    n_g = 0; corr3_rows = []
    for r, c in cells_g:
        if not np.isnan(dem_orig[r, c]):
            target = max(dem_orig[r, c] - CORR3_BURN_DEPTH, NILE_TARGET_ELEV)
            if dem[r, c] > target:
                dem[r, c] = target; n_g += 1
            corr3_rows.append(r)
    rsg = [r for r,c in cells_g]; csg = [c for r,c in cells_g]
    print(f"    {n_g} cells burned "
          f"(rows {min(rsg)}-{max(rsg)}, cols {min(csg)}-{max(csg)})")

    # ── Fix H: 4-directional gap bridge to Nile ──────────────────────────────
    # After all KML burns, find the lowest point in the corr3 area (the channel
    # floor from which water tries to drain) and trace a monotonically decreasing
    # 4-directional path southward until hitting a Nile zone cell (≤295m).
    # This ensures RIM2D 4-directional routing can actually carry water to Nile.
    print(f"\n  Fix H: 4-directional bridge from corr3 to Nile zone ...")

    # Find the minimum elevation in the corr3 search band (the actual channel floor)
    sub = dem[BRIDGE_ROW_LO:BRIDGE_ROW_HI+1, BRIDGE_COL_LO:BRIDGE_COL_HI+1]
    min_idx = np.unravel_index(np.nanargmin(sub), sub.shape)
    start_row = BRIDGE_ROW_LO + min_idx[0]
    start_col = BRIDGE_COL_LO + min_idx[1]
    start_elev = float(dem[start_row, start_col])
    print(f"    Channel floor: row={start_row}, col={start_col}, elev={start_elev:.2f}m")

    # Search south from start_row for the nearest Nile cell in the same column
    # (or within ±2 cols if not found in same col)
    nile_row = None; nile_col = start_col
    for dc in [0, -1, 1, -2, 2]:
        tc = start_col + dc
        if tc < 0 or tc >= ncols:
            continue
        for r in range(start_row - 1, -1, -1):
            if dem[r, tc] <= NILE_TARGET_ELEV + 1.0:
                nile_row = r; nile_col = tc
                break
        if nile_row is not None:
            break

    if nile_row is None:
        print("    WARNING: no Nile cell found — skipping bridge")
    else:
        nile_elev = float(dem[nile_row, nile_col])
        gap_cells = abs(start_row - nile_row) - 1  # interior cells to burn
        print(f"    Nile target: row={nile_row}, col={nile_col}, elev={nile_elev:.2f}m")
        print(f"    Gap: {gap_cells} interior cells (rows {nile_row+1}–{start_row-1})")

        bridge_burned = 0
        total_steps = start_row - nile_row  # total rows to traverse
        # Burn each cell between start and Nile on a linear gradient
        # stepping south (decreasing row index) from start_row-1 to nile_row+1
        for step, r in enumerate(range(start_row - 1, nile_row, -1), start=1):
            target_elev = start_elev - (start_elev - nile_elev) * step / total_steps
            target_elev = max(target_elev, NILE_TARGET_ELEV)
            if dem[r, nile_col] > target_elev:
                print(f"      row={r}, col={nile_col}: "
                      f"{dem[r,nile_col]:.2f}m → {target_elev:.2f}m")
                dem[r, nile_col] = target_elev
                bridge_burned += 1
        print(f"    Bridge cells burned: {bridge_burned}")

    # ── Fix F: Pysheds 2-pass depression fill ───────────────────────────────
    # (Applied AFTER all explicit burns so fill has the full picture)
    dem_preburn = dem.copy()  # snapshot of all deliberate burns
    print(f"\n  Fix F: Pysheds 2-pass depression fill ...")

    dem_f1, pits1 = pysheds_fill_pass(dem, transform, nrows, ncols)
    dem_f1 = np.where(np.isnan(dem_orig), np.nan, dem_f1)

    burn_mask = (~np.isnan(dem_preburn)) & (dem_preburn < dem_orig - 0.1)
    dem_ab = dem_f1.copy()
    dem_ab[burn_mask] = dem_preburn[burn_mask]
    dem_ab = np.where(np.isnan(dem_orig), np.nan, dem_ab)

    dem_f2, pits2 = pysheds_fill_pass(dem_ab, transform, nrows, ncols)
    dem_final = np.where(np.isnan(dem_orig), np.nan, dem_f2)

    raised = (~np.isnan(dem_final)) & (dem_final > dem_preburn + 0.01)
    print(f"    Pass 1 — pits before: {pits1}")
    print(f"    Pass 2 — pits before: {pits2}")
    print(f"    Cells raised by fill: {int(raised.sum()):,} "
          f"(avg +{float(np.nanmean((dem_final - dem_preburn)[raised])):.2f}m)")

    n_total = int(np.sum(dem_final < dem_orig - 0.1))
    print(f"    Total cells modified from v10: {n_total:,}")

    # ── Write outputs ─────────────────────────────────────────────────────────
    tif_out = V24_INPUT / "dem_v24.tif"
    arr_out = np.where(np.isnan(dem_final), -9999.0, dem_final).astype(np.float64)
    with rasterio.open(str(tif_out), "w", driver="GTiff", height=nrows,
                       width=ncols, count=1, dtype="float64", crs="EPSG:32636",
                       transform=transform, nodata=-9999) as dst:
        dst.write(np.flipud(arr_out), 1)
    print(f"\n    Saved GeoTIFF: {tif_out.name}")

    nc_out = V24_INPUT / "dem_v24.nc"
    src_ds = netCDF4.Dataset(str(V10_INPUT / "dem.nc"))
    ds_out = netCDF4.Dataset(str(nc_out), "w", format="NETCDF4")
    ds_out.createDimension("x", len(x))
    ds_out.createDimension("y", len(y))
    vx = ds_out.createVariable("x", "f8", ("x",)); vx[:] = x
    vy = ds_out.createVariable("y", "f8", ("y",)); vy[:] = y
    for a in src_ds["x"].ncattrs(): vx.setncattr(a, src_ds["x"].getncattr(a))
    for a in src_ds["y"].ncattrs(): vy.setncattr(a, src_ds["y"].getncattr(a))
    src_var = [v for v in src_ds.variables if v not in ("x","y")][0]
    vb = ds_out.createVariable("Band1", "f8", ("y","x"), fill_value=-9999.0)
    for a in src_ds[src_var].ncattrs():
        try: vb.setncattr(a, src_ds[src_var].getncattr(a))
        except: pass
    vb[:] = np.where(np.isnan(dem_final), -9999.0, dem_final)
    src_ds.close(); ds_out.close()
    print(f"    Saved NetCDF:   {nc_out.name}")

    return x, y


# ── Step 2: DEM diagnostic ───────────────────────────────────────────────────
def dem_diagnostic():
    """Trace steepest-descent path from each inflow to verify Nile reach (4-dir)."""
    print("\n" + "="*60)
    print("Step 2: DEM diagnostic (4-directional steepest descent)")
    print("="*60)
    ds = netCDF4.Dataset(str(V24_INPUT / "dem_v24.nc"))
    var = [v for v in ds.variables if v not in ("x","y")][0]
    dem = np.array(ds[var][:]).squeeze()
    ds.close()
    nrows, ncols = dem.shape

    for name, d in INFLOW_DEFS.items():
        r, c = d["row"], d["col"]
        visited = set(); path = [(r, c)]
        visited.add((r, c))
        for _ in range(5000):
            neighbors = []
            for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
                nr, nc = r+dr, c+dc
                if 0 <= nr < nrows and 0 <= nc < ncols and (nr,nc) not in visited:
                    if not np.isnan(dem[nr, nc]):
                        neighbors.append((dem[nr,nc], nr, nc))
            if not neighbors:
                break
            _, nr, nc = min(neighbors)
            if dem[nr, nc] >= dem[r, c]:
                break
            r, c = nr, nc
            visited.add((r, c))
            path.append((r, c))
        end_elev = dem[path[-1][0], path[-1][1]]
        reached  = end_elev <= NILE_TARGET_ELEV + 2.0
        status   = "REACHES NILE ✓" if reached else f"STALLS at row={path[-1][0]}, col={path[-1][1]}, elev={end_elev:.2f}m"
        print(f"  {name:<18} path_len={len(path):4d}  end_elev={end_elev:.2f}m  {status}")


# ── Step 3: Inflowlocs ───────────────────────────────────────────────────────
def build_inflowlocs():
    print("\nStep 3: Inflowlocs — copying from v15")
    src = V15_INPUT / "inflowlocs_v15.txt"
    dst = V24_INPUT / "inflowlocs_v24.txt"
    dst.write_text(src.read_text().replace("v15", "v24"))
    print(f"  Saved: {dst.name}")


# ── Step 4: Rain symlinks ────────────────────────────────────────────────────
def build_rain():
    print("\nStep 4: Rain symlinks → v23/input/rain")
    rain_dir = V24_INPUT / "rain"
    rain_dir.mkdir(exist_ok=True)
    src_dir  = V23_DIR / "input" / "rain"
    n = 0
    for i in range(1, N_RAIN + 1):
        dst = rain_dir / f"imerg_v24_t{i}.nc"
        src = src_dir  / f"imerg_v23_t{i}.nc"
        if not dst.exists():
            dst.symlink_to(src)
            n += 1
    print(f"  {n} symlinks created → {src_dir}")


# ── Step 5: Simulation def ───────────────────────────────────────────────────
def write_def():
    print("\nStep 5: Writing simulation_v24.def")
    out_timing = " ".join(str(t) for t in range(21600, SIM_DUR+1, 21600))
    content = f"""\
# RIM2D v24 — v23 base + corr3.kml connectivity fix
# Fix A: Nile floodplain burn (dem<308m → 294m)
# Fix B: GeoJSON stream burns (skip linkno=160245676)
# Fix C: cor1.kml corrected channel (dem-8m)
# Fix D: cor2.kml corrected channel (dem-8m)
# Fix E: Gap bridge F18→F19 narrow gaps
# Fix G: corr3.kml shallow channel (dem-1m) — railway stagnation to Nile
# Fix H: 4-directional gap bridge to Nile (linear gradient)
# Fix F: Pysheds 2-pass depression fill + resolve_flats (float64)

###### INPUT RASTERS ######
**DEM**
input/dem_v24.nc
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
input/inflowlocs_v24.txt

**pluvial_raster_nr**
288
**pluvial_dt**
1800
**pluvial_start**
0
**pluvial_base_fn**
input/rain/imerg_v24_t

###### OUTPUT ######
**output_base_fn**
output/nile_v24_
**out_cells**
../v10/input/outflowlocs.txt
**out_timing_nr**
24
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
input/fluvbound_mask_v24.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    out = V24_DIR / "simulation_v24.def"
    out.write_text(content)
    print(f"  Saved: {out.name}")


# ── Step 6: fluvbound mask ───────────────────────────────────────────────────
def build_fluvbound():
    """Copy fluvbound mask from v23 (same inflow locations)."""
    print("\nStep 6: Fluvbound mask — copying from v23")
    import shutil
    src = V23_DIR / "input" / "fluvbound_mask_v23.nc"
    dst = V24_INPUT / "fluvbound_mask_v24.nc"
    shutil.copy(str(src), str(dst))
    print(f"  Saved: {dst.name}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("RIM2D v24 Setup — v23 base + corr3.kml connectivity fix")
    print("=" * 60)

    build_dem_v24()
    dem_diagnostic()
    build_inflowlocs()
    build_rain()
    build_fluvbound()
    write_def()

    print(f"""
{'='*60}
Setup complete.  To run simulation:
  cd /data/rim2d/nile_highres/v24
  export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
  /data/rim2d/bin/RIM2D simulation_v24.def --def flex
{'='*60}
""")
