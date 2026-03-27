#!/usr/bin/env python3
"""
RIM2D v23 — Fresh start from v10 DEM with corrected KML river burns.

Strategy:
  - Base DEM: v10 (raw MERIT DEM, no prior modifications)
  - Fix A: Nile floodplain burn (dem < 308m → 294m)
  - Fix B: GeoJSON stream burns — ALL features EXCEPT linkno=160245676
           (that feature is wrongly positioned vs Google Earth satellite)
  - Fix C: cor1.kml — ground-truth corrected channel line (8m burn)
  - Fix D: cor2.kml — ground-truth corrected channel line (8m burn)
           Both KMLs trace the actual wadi + culvert positions, so no
           separate hardcoded culvert fix is needed.
  - Fix E: Gap bridge F18→F19 narrow gaps (≤30 rows) from GeoJSON
  - Fix F: Pysheds 2-pass depression fill + resolve_flats (float64)

DEM diagnostic is run first to confirm all 4 inflows reach Nile before sim.

Usage:
    micromamba run -n zarrv3 python v23/run_v23_setup.py
    micromamba run -n zarrv3 python v23/analysis/dem_diagnostic.py
    cd v23 && /data/rim2d/bin/RIM2D simulation_v23.def --def flex
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
V23_INPUT = V23_DIR  / "input"
V23_INPUT.mkdir(parents=True, exist_ok=True)
(V23_DIR / "output").mkdir(exist_ok=True)

KML_COR1 = V23_DIR / "cor1.kml"
KML_COR2 = V23_DIR / "cor2.kml"
KML_NS   = {"kml": "http://www.opengis.net/kml/2.2"}
GEOJSON  = WORK_DIR / "v11" / "input" / "river_network_tdx_v2.geojson"

# ── Burn parameters ─────────────────────────────────────────────────────────
NILE_ELEV_THRESH = 308.0    # Nile floodplain threshold
NILE_TARGET_ELEV = 294.0    # Nile channel floor

BURN_ORDER9      = None     # Order-9: burn to exact NILE_TARGET_ELEV
BURN_ORDER5      = 3.0      # Order-5: dem - 3m, capped at NILE_TARGET_ELEV
BURN_ORDER2      = 2.0      # Order-2: dem - 2m, capped at NILE_TARGET_ELEV
SKIP_LINKNO      = 160245676  # wrong GeoJSON feature — replaced by cor KMLs

COR_BURN_DEPTH   = 8.0      # cor1/cor2: dem - 8m (deep enough to route through ridge)

# Gap bridge (F18→F19 only)
MAX_GAP_ROWS = 30

# ── Simulation parameters ────────────────────────────────────────────────────
SIM_DUR   = 518_400
DT_INFLOW = 1800
N_RAIN    = SIM_DUR // DT_INFLOW        # 288
N_WSE     = SIM_DUR // DT_INFLOW + 1   # 289
IMERG_START_STEP = 1488
WSE_CAP_M = 1.5

INFLOW_DEFS = {
    "Culvert1":    {"row": 212, "col": 312, "sill": 321.105},
    "Culvert2":    {"row": 222, "col": 266, "sill": 320.012},
    "WesternWadi": {"row": 222, "col": 175, "sill": 318.855},
    "HospitalWadi":{"row": 183, "col": 281, "sill": 316.134},
}


# ── Helpers ──────────────────────────────────────────────────────────────────
def load_dem_v10():
    ds = netCDF4.Dataset(str(V10_INPUT / "dem.nc"))
    x   = np.array(ds["x"][:])
    y   = np.array(ds["y"][:])
    var = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[var][:]).squeeze().astype(float)
    dem[dem < -9000] = np.nan
    ds.close()
    return dem, x, y


def kml_to_cells(kml_path, x, y, nrows, ncols, tr):
    """Parse KML coordinates → all grid cells along the line (Bresenham rasterize).
    Fills every cell between consecutive KML points so the channel is continuous."""
    tree = ET.parse(str(kml_path))
    root = tree.getroot()

    def bresenham(r0, c0, r1, c1):
        """All grid cells on the line from (r0,c0) to (r1,c1)."""
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
            if e2 > -dc:
                err -= dc; r += sr
            if e2 <  dr:
                err += dr; c += sc
        return pts

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
        # Rasterize every segment between consecutive KML points
        for i in range(len(raw_pts) - 1):
            r0, c0 = raw_pts[i]
            r1, c1 = raw_pts[i+1]
            for r, c in bresenham(r0, c0, r1, c1):
                if 0 <= r < nrows and 0 <= c < ncols:
                    cells.append((r, c))
        # Include the last point
        if raw_pts:
            r, c = raw_pts[-1]
            if 0 <= r < nrows and 0 <= c < ncols:
                cells.append((r, c))
    return cells


def pysheds_fill_pass(dem_in, transform, nrows, ncols):
    """One pass of fill_depressions + resolve_flats (float64 GeoTIFF I/O).
    Returns conditioned array (south-up) and pits_before count."""
    arr = np.where(np.isnan(dem_in), -9999.0, dem_in).astype(np.float64)
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        p = tmp.name
    with rasterio.open(p, "w", driver="GTiff", height=nrows, width=ncols,
                       count=1, dtype="float64", crs="EPSG:32636",
                       transform=transform, nodata=-9999) as dst:
        dst.write(np.flipud(arr), 1)
    grid    = Grid.from_raster(p)
    dem_ps  = grid.read_raster(p)
    n_pits  = int(np.array(grid.detect_pits(dem_ps)).sum())
    filled  = grid.fill_depressions(dem_ps)
    inflated = grid.resolve_flats(filled)
    result  = np.flipud(np.array(inflated).astype(float))
    result[result <= -9000] = np.nan
    os.unlink(p)
    return result, n_pits


# ── Step 1: Build v23 DEM ────────────────────────────────────────────────────
def build_dem_v23():
    print("\n" + "="*60)
    print("Step 1: Building v23 DEM")
    print("="*60)

    dem_orig, x, y = load_dem_v10()
    dem_v23 = dem_orig.copy()
    nrows, ncols = dem_v23.shape
    dx = x[1]-x[0]; dy = y[1]-y[0]
    transform = rasterio.transform.from_origin(x[0]-dx/2, y[-1]+dy/2, dx, dy)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)

    print(f"  Base: v10 raw MERIT DEM ({nrows}×{ncols}, "
          f"{np.nanmin(dem_orig):.1f}–{np.nanmax(dem_orig):.1f}m)")

    # ── Fix A: Nile floodplain burn ─────────────────────────────────────────
    nile_mask = dem_orig < NILE_ELEV_THRESH
    dem_v23[nile_mask] = NILE_TARGET_ELEV
    print(f"\n  Fix A: Nile floodplain — {int(nile_mask.sum()):,} cells "
          f"(dem<{NILE_ELEV_THRESH}m) → {NILE_TARGET_ELEV}m")

    # ── Fix B: GeoJSON stream burns (skip linkno=SKIP_LINKNO) ───────────────
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
                if dem_v23[r, c] > new_e:
                    dem_v23[r, c] = new_e
                    n_b += 1
    print(f"    {n_b} cells burned ({n_skip} feature(s) skipped)")

    # ── Fix C: cor1.kml — ground-truth corrected channel ────────────────────
    cells_c1 = kml_to_cells(KML_COR1, x, y, nrows, ncols, tr)
    n_c1 = 0
    for r, c in cells_c1:
        if not np.isnan(dem_orig[r, c]):
            target = max(dem_orig[r, c] - COR_BURN_DEPTH, NILE_TARGET_ELEV)
            if dem_v23[r, c] > target:
                dem_v23[r, c] = target
                n_c1 += 1
    rs1 = [r for r,c in cells_c1]; cs1 = [c for r,c in cells_c1]
    print(f"\n  Fix C: cor1.kml — {n_c1} cells burned "
          f"(rows {min(rs1)}-{max(rs1)}, cols {min(cs1)}-{max(cs1)})")

    # ── Fix D: cor2.kml — ground-truth corrected channel ────────────────────
    cells_c2 = kml_to_cells(KML_COR2, x, y, nrows, ncols, tr)
    n_c2 = 0
    for r, c in cells_c2:
        if not np.isnan(dem_orig[r, c]):
            target = max(dem_orig[r, c] - COR_BURN_DEPTH, NILE_TARGET_ELEV)
            if dem_v23[r, c] > target:
                dem_v23[r, c] = target
                n_c2 += 1
    rs2 = [r for r,c in cells_c2]; cs2 = [c for r,c in cells_c2]
    print(f"\n  Fix D: cor2.kml — {n_c2} cells burned "
          f"(rows {min(rs2)}-{max(rs2)}, cols {min(cs2)}-{max(cs2)})")

    # ── Fix E: Gap bridge F18→F19 (narrow gaps ≤ MAX_GAP_ROWS) ─────────────
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

    f18_cells = feature_cells(18)
    f19_cells = feature_cells(19)
    f18_by_col = {}
    for r, c in f18_cells: f18_by_col.setdefault(c, []).append(r)
    f19_by_col = {}
    for r, c in f19_cells: f19_by_col.setdefault(c, []).append(r)
    gap_burned = 0
    for c in sorted(set(f18_by_col) & set(f19_by_col)):
        r_top    = min(f18_by_col[c])
        r_bottom = max(f19_by_col[c])
        gap = r_top - r_bottom
        if 1 < gap <= MAX_GAP_ROWS:
            for r in range(r_bottom, r_top):
                if not np.isnan(dem_orig[r, c]):
                    if dem_v23[r, c] > NILE_TARGET_ELEV:
                        dem_v23[r, c] = NILE_TARGET_ELEV
                        gap_burned += 1
    print(f"    {gap_burned} cells burned (→ {NILE_TARGET_ELEV}m)")

    n_burns = int(np.sum(dem_v23 < dem_orig - 0.1))
    print(f"\n  Total cells burned from v10 base: {n_burns:,}")

    # ── Fix F: Pysheds 2-pass depression fill ───────────────────────────────
    print(f"\n  Fix F: Pysheds 2-pass depression fill ...")

    # Pass 1 — fill the burned DEM
    dem_f1, pits1 = pysheds_fill_pass(dem_v23, transform, nrows, ncols)
    dem_f1 = np.where(np.isnan(dem_orig), np.nan, dem_f1)

    # Re-apply deliberate burns (fill may have raised channel cells back up)
    burn_mask = (~np.isnan(dem_v23)) & (dem_v23 < dem_orig - 0.1)
    dem_ab = dem_f1.copy()
    dem_ab[burn_mask] = dem_v23[burn_mask]
    dem_ab = np.where(np.isnan(dem_orig), np.nan, dem_ab)

    # Pass 2 — clear pits re-introduced by re-applied burns
    dem_f2, pits2 = pysheds_fill_pass(dem_ab, transform, nrows, ncols)
    dem_final = np.where(np.isnan(dem_orig), np.nan, dem_f2)

    raised = (~np.isnan(dem_final)) & (dem_final > dem_v23 + 0.01)
    print(f"    Pass 1 — pits before: {pits1}")
    print(f"    Pass 2 — pits before: {pits2}")
    print(f"    Cells raised by fill: {int(raised.sum()):,} "
          f"(avg +{float(np.nanmean((dem_final - dem_v23)[raised])):.2f}m)")

    n_final = int(np.sum(dem_final < dem_orig - 0.1))
    print(f"    Total cells modified from v10: {n_final:,}")

    # ── Write GeoTIFF (float64, for diagnostic / QGIS) ──────────────────────
    tif_out = V23_INPUT / "dem_v23.tif"
    arr_out = np.where(np.isnan(dem_final), -9999.0, dem_final).astype(np.float64)
    with rasterio.open(str(tif_out), "w", driver="GTiff", height=nrows,
                       width=ncols, count=1, dtype="float64", crs="EPSG:32636",
                       transform=transform, nodata=-9999) as dst:
        dst.write(np.flipud(arr_out), 1)
    print(f"\n    Saved GeoTIFF: {tif_out.name}")

    # ── Write NetCDF (float64 — preserves resolve_flats micro-gradients) ────
    nc_out  = V23_INPUT / "dem_v23.nc"
    src_ds  = netCDF4.Dataset(str(V10_INPUT / "dem.nc"))
    ds_out  = netCDF4.Dataset(str(nc_out), "w", format="NETCDF4")
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


# ── Step 2: Inflowlocs (copy + rename from v15) ──────────────────────────────
def build_inflowlocs():
    print("\nStep 2: Inflowlocs — copying from v15")
    src = V15_INPUT / "inflowlocs_v15.txt"
    dst = V23_INPUT / "inflowlocs_v23.txt"
    dst.write_text(src.read_text().replace("v15", "v23"))
    print(f"  Saved: {dst.name}")


# ── Step 3: Simulation def ───────────────────────────────────────────────────
def write_def():
    print("\nStep 3: Writing simulation_v23.def")
    out_timing = " ".join(str(t) for t in range(21600, SIM_DUR+1, 21600))
    content = f"""\
# RIM2D v23 — Fresh v10 base + corrected KML river burns
# Fix A: Nile floodplain burn (dem<308m → 294m)
# Fix B: GeoJSON stream burns (skip linkno=160245676 — wrong position)
# Fix C: cor1.kml corrected channel (dem-8m)
# Fix D: cor2.kml corrected channel (dem-8m, includes culvert path)
# Fix E: Gap bridge F18→F19 narrow gaps
# Fix F: Pysheds 2-pass depression fill + resolve_flats (float64)

###### INPUT RASTERS ######
**DEM**
input/dem_v23.nc
**buildings**
../v10/input/buildings.nc
**fluvbound**
input/fluvbound_mask_v23.nc
**infiltration**
../v10/input/infiltration.nc
**manning**
../v10/input/manning.nc

###### RAINFALL ######
**rainfall_nc**
{N_RAIN}
""" + "\n".join(f"input/rain/imerg_v23_t{i}.nc" for i in range(1, N_RAIN+1)) + f"""

###### BOUNDARY CONDITIONS ######
**inflowlocs**
input/inflowlocs_v23.txt

###### OUTPUT ######
**results_name**
output/nile_v23_
**results_frequency**
{out_timing}
**vel_out**
.TRUE.
**wd_max**
.TRUE.
**wd_max_t**
.TRUE.
**vel_max**
.TRUE.

###### SIMULATION ######
**sim_duration**
{SIM_DUR}
**initial_wd**
0.0
**acceleration_coef**
0.7
**SGC_channel**
.FALSE.
**sheetflow_roughness**
.TRUE.
"""
    out = V23_DIR / "simulation_v23.def"
    out.write_text(content)
    print(f"  Saved: {out.name}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("RIM2D v23 Setup — v10 base + corrected KML burns")
    print("=" * 60)

    x, y = build_dem_v23()
    build_inflowlocs()
    write_def()

    print(f"""
{'='*60}
Setup complete.  Run DEM diagnostic FIRST:
  micromamba run -n zarrv3 python v23/analysis/dem_diagnostic.py

If all 4 inflows show REACHES NILE ✓, then simulate:
  cd /data/rim2d/nile_highres/v23
  export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
  /data/rim2d/bin/RIM2D simulation_v23.def --def flex
{'='*60}
""")
