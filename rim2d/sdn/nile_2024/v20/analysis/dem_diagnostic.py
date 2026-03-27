#!/usr/bin/env python3
"""
DEM Diagnostic — v20 terrain analysis before simulation.

Panels:
  1. DEM hillshade + river network overlay
  2. Slope (degrees) — reveals ridges and flat zones
  3. Log flow accumulation — shows drainage paths and concentrations
  4. Depressions / sinks — where water will stagnate
  5. Inflow → Nile connectivity check — trace each inflow path south
  6. DEM profile along each tributary path

Usage:
    micromamba run -n zarrv3 python v20/analysis/dem_diagnostic.py
"""

from pathlib import Path
import json
import numpy as np
import netCDF4
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe
import rasterio
from pysheds.grid import Grid
from pyproj import Transformer

WORK_DIR  = Path("/data/rim2d/nile_highres")
V20_INPUT = WORK_DIR / "v20" / "input"
DEM_TIF   = V20_INPUT / "dem_v20.tif"
DEM_NC    = V20_INPUT / "dem_v20.nc"
GEOJSON   = WORK_DIR / "v11" / "input" / "river_network_tdx_v2.geojson"
VIZ_DIR   = WORK_DIR / "v20" / "analysis" / "visualizations"
VIZ_DIR.mkdir(parents=True, exist_ok=True)
DPI = 130

INFLOW_DEFS = {
    "Culvert1":    {"row": 212, "col": 312, "sill": 321.105, "color": "#e41a1c"},
    "Culvert2":    {"row": 222, "col": 266, "sill": 320.012, "color": "#377eb8"},
    "WesternWadi": {"row": 222, "col": 175, "sill": 318.855, "color": "#2ca02c"},
    "HospitalWadi":{"row": 183, "col": 281, "sill": 316.134, "color": "#ff7f00"},
}


def load_dem_nc():
    ds = netCDF4.Dataset(str(DEM_NC))
    x  = np.array(ds["x"][:])
    y  = np.array(ds["y"][:])
    var = [v for v in ds.variables if v not in ("x", "y")][0]
    dem = np.array(ds[var][:]).squeeze().astype(float)
    dem[dem < -9000] = np.nan
    ds.close()
    return dem, x, y


def make_hillshade(dem, az=315, alt=45):
    dy, dx = np.gradient(np.nan_to_num(dem))
    slope  = np.pi/2 - np.arctan(np.sqrt(dx**2 + dy**2))
    aspect = np.arctan2(-dy, dx)
    az_r, alt_r = np.radians(az), np.radians(alt)
    return np.sin(alt_r)*np.sin(slope) + np.cos(alt_r)*np.cos(slope)*np.cos(az_r-aspect)


def load_river_cells(dem, x, y):
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    with open(GEOJSON) as f:
        gj = json.load(f)
    dx = x[1]-x[0]; dy = y[1]-y[0]
    nrows, ncols = dem.shape
    rivers = {}  # order → list of (row, col)
    for feat in gj["features"]:
        order = feat["properties"]["stream_order"]
        geom  = feat["geometry"]
        coords = geom["coordinates"]
        if geom["type"] == "MultiLineString":
            coords = [pt for seg in coords for pt in seg]
        for lon, lat in coords:
            ex, ey = tr.transform(lon, lat)
            c = int(round((ex - x[0]) / dx))
            r = int(round((ey - y[0]) / dy))
            if 0 <= r < nrows and 0 <= c < ncols:
                rivers.setdefault(order, []).append((r, c))
    return rivers


def compute_slope_simple(dem):
    """Slope in degrees using central differences."""
    dy, dx = np.gradient(np.nan_to_num(dem, nan=0), 30, 30)  # 30m cell size
    return np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))


print("Loading DEM ...")
dem, x, y = load_dem_nc()
nrows, ncols = dem.shape
hs  = make_hillshade(dem)
slope = compute_slope_simple(dem)
rivers = load_river_cells(dem, x, y)

print("Running pysheds hydrologic analysis ...")
grid   = Grid.from_raster(str(DEM_TIF))
dem_ps = grid.read_raster(str(DEM_TIF))

# Detect pits and depressions on the raw DEM
pits        = grid.detect_pits(dem_ps)
depressions = grid.detect_depressions(dem_ps)
flats       = grid.detect_flats(dem_ps)

# Fill depressions → resolve flats → flow direction → accumulation
dem_filled   = grid.fill_depressions(dem_ps)
dem_inflated = grid.resolve_flats(dem_filled)
fdir         = grid.flowdir(dem_inflated)
acc          = grid.accumulation(fdir)

# Stagnation risk: depression OR flat AND slope < 1°
stagnation = ((depressions | flats) & (slope < 1.0))

# Log accumulation (rasterio stores top-down → flip to match dem orientation)
acc_np   = np.array(acc).astype(float)
acc_flip = np.flipud(acc_np)
log_acc  = np.log1p(acc_flip)

dep_flip  = np.flipud(np.array(depressions))
flat_flip = np.flipud(np.array(flats))
pit_flip  = np.flipud(np.array(pits))
stag_flip = dep_flip | (flat_flip & (slope < 1.0))

print("Plotting ...")

# ── Figure 1: 4-panel terrain analysis ───────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(22, 16))

order_colors = {9: "#1f78b4", 5: "#a6cee3", 2: "#b2df8a"}
order_labels = {9: "Nile (Order 9)", 5: "Order 5", 2: "Order 2 (wadi)"}

def add_rivers(ax):
    for order, cells in rivers.items():
        if cells:
            rs = [r for r,c in cells]; cs = [c for r,c in cells]
            ax.scatter(cs, rs, s=0.3, c=order_colors.get(order,"gray"),
                       alpha=0.6, linewidths=0, zorder=5)

def add_inflows(ax):
    for name, d in INFLOW_DEFS.items():
        r, c = d["row"], d["col"]
        ax.plot(c, r, "D", color=d["color"], ms=8, mec="black", mew=1, zorder=10)
        ax.annotate(name, (c, r), textcoords="offset points", xytext=(4,4),
                    fontsize=7, fontweight="bold", color=d["color"],
                    path_effects=[pe.withStroke(linewidth=2, foreground="black")])

# Panel 1: DEM hillshade + rivers
ax = axes[0,0]
ax.imshow(hs, origin="lower", cmap="gray", vmin=0.3, vmax=1.0)
im = ax.imshow(np.ma.masked_invalid(dem), origin="lower", cmap="terrain",
               alpha=0.6, vmin=290, vmax=340)
fig.colorbar(im, ax=ax, shrink=0.7, label="Elevation (m)")
add_rivers(ax)
add_inflows(ax)
# Mark Nile cells
nile_mask = dem < 296
nile_overlay = np.ma.masked_where(~nile_mask, np.ones_like(dem))
ax.imshow(nile_overlay, origin="lower", cmap=mcolors.ListedColormap(["cyan"]),
          alpha=0.5, zorder=6)
ax.set_title("v20 DEM + River Network\n(cyan = Nile cells dem<296m)", fontweight="bold")
ax.set_xlabel("col"); ax.set_ylabel("row")
# Grid every 30 cols/rows
for c in range(0, ncols, 60): ax.axvline(c, color="white", lw=0.3, alpha=0.4)
for r in range(0, nrows, 60): ax.axhline(r, color="white", lw=0.3, alpha=0.4)

# Panel 2: Slope
ax = axes[0,1]
im = ax.imshow(slope, origin="lower", cmap="YlOrRd", vmin=0, vmax=15)
fig.colorbar(im, ax=ax, shrink=0.7, label="Slope (degrees)")
add_rivers(ax)
add_inflows(ax)
# Highlight very flat zones (slope < 0.5°) = potential stagnation
flat_z = np.ma.masked_where(slope >= 0.5, slope)
ax.imshow(flat_z, origin="lower", cmap=mcolors.ListedColormap(["blue"]),
          alpha=0.4, zorder=6)
ax.set_title("Slope (degrees)\n(blue = slope<0.5° — potential flat/stagnation)", fontweight="bold")
ax.set_xlabel("col"); ax.set_ylabel("row")

# Panel 3: Log flow accumulation
ax = axes[1,0]
ax.imshow(hs, origin="lower", cmap="gray", vmin=0.3, vmax=1.0, alpha=0.5)
im = ax.imshow(log_acc, origin="lower", cmap="Blues", vmin=0, vmax=log_acc.max())
fig.colorbar(im, ax=ax, shrink=0.7, label="Log(flow accumulation)")
add_inflows(ax)
ax.set_title("Log Flow Accumulation (pysheds D8)\nhigh = drainage convergence / channel", fontweight="bold")
ax.set_xlabel("col"); ax.set_ylabel("row")

# Panel 4: Depressions, flats, pits
ax = axes[1,1]
ax.imshow(hs, origin="lower", cmap="gray", vmin=0.3, vmax=1.0, alpha=0.5)
dep_show = np.zeros((*dep_flip.shape, 4))
dep_show[dep_flip,  :] = [1.0, 0.0, 0.0, 0.8]   # red = depressions
dep_show[flat_flip & ~dep_flip, :] = [1.0, 0.5, 0.0, 0.6]  # orange = flats
dep_show[pit_flip,  :] = [1.0, 1.0, 0.0, 1.0]   # yellow = pits
ax.imshow(dep_show, origin="lower", zorder=6)
add_rivers(ax)
add_inflows(ax)
from matplotlib.patches import Patch
legend_els = [Patch(facecolor="red",    label=f"Depressions ({dep_flip.sum():,})"),
              Patch(facecolor="orange", label=f"Flats ({(flat_flip&~dep_flip).sum():,})"),
              Patch(facecolor="yellow", label=f"Pits ({pit_flip.sum():,})")]
ax.legend(handles=legend_els, loc="upper right", fontsize=8)
n_dep = dep_flip.sum(); n_flat = flat_flip.sum(); n_pit = pit_flip.sum()
ax.set_title(f"Hydrologic Sinks (pysheds)\nDepressions:{n_dep:,}  Flats:{n_flat:,}  Pits:{n_pit:,}", fontweight="bold")
ax.set_xlabel("col"); ax.set_ylabel("row")

fig.suptitle("v20 DEM Diagnostic — Terrain Analysis Before Simulation", fontsize=14, fontweight="bold")
fig.tight_layout()
out = VIZ_DIR / "v20_dem_diagnostic_terrain.png"
fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(f"  Saved: {out.name}")


# ── Figure 2: Tributary path profiles ────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(20, 12))

def path_profile(start_row, start_col, n_steps=200):
    """Follow steepest descent from a start cell, return (rows, cols, elevs)."""
    r, c = start_row, start_col
    rows, cols, elevs = [r], [c], [dem[r,c]]
    for _ in range(n_steps):
        neighbors = []
        for dr in [-1,0,1]:
            for dc in [-1,0,1]:
                if dr==0 and dc==0: continue
                nr, nc = r+dr, c+dc
                if 0<=nr<nrows and 0<=nc<ncols and not np.isnan(dem[nr,nc]):
                    neighbors.append((dem[nr,nc], nr, nc))
        if not neighbors: break
        min_elev, nr, nc = min(neighbors)
        if min_elev >= dem[r,c]: break  # no downhill neighbor — stuck
        r, c = nr, nc
        rows.append(r); cols.append(c); elevs.append(dem[r,c])
    return np.array(rows), np.array(cols), np.array(elevs)

for ax, (name, d) in zip(axes.ravel(), INFLOW_DEFS.items()):
    rows, cols, elevs = path_profile(d["row"], d["col"], n_steps=300)
    dist_m = np.arange(len(rows)) * 30 / 1000   # km
    ax.plot(dist_m, elevs, lw=1.8, color=d["color"])
    ax.axhline(294, color="blue",  lw=1, ls="--", label="Nile level (294m)")
    ax.axhline(d["sill"], color="red", lw=1, ls=":", label=f"Sill {d['sill']:.0f}m")
    # Mark where path stalls (if it does)
    if len(elevs) < 300:
        ax.axvline(dist_m[-1], color="orange", lw=1.5, ls="-", label=f"Path stops at {elevs[-1]:.1f}m")
        ax.plot(dist_m[-1], elevs[-1], "ro", ms=8)
    ax.set_xlabel("Distance from inflow (km)"); ax.set_ylabel("Elevation (m)")
    ax.set_title(f"{name} — Steepest descent path\n(row={d['row']}, col={d['col']}, n={len(rows)} steps)",
                 fontweight="bold")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    final_elev = elevs[-1]
    reaches_nile = "REACHES NILE ✓" if final_elev < 296 else f"STALLS at {final_elev:.1f}m ✗"
    ax.set_title(f"{name} — {reaches_nile}\n(row={d['row']}, col={d['col']})", fontweight="bold")

fig.suptitle("Steepest-Descent Path Profiles: Does Each Inflow Reach the Nile?",
             fontsize=13, fontweight="bold")
fig.tight_layout()
out = VIZ_DIR / "v20_dem_diagnostic_flowpaths.png"
fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(f"  Saved: {out.name}")


# ── Figure 3: DEM cross-sections at key cols ─────────────────────────────────
fig, axes = plt.subplots(2, 3, figsize=(22, 12))
cols_to_check = [175, 237, 253, 266, 281, 312]
for ax, c in zip(axes.ravel(), cols_to_check):
    rows_arr = np.arange(nrows)
    elev = dem[:, c]
    ax.plot(rows_arr, elev, lw=1.5, color="saddlebrown")
    ax.axhline(294, color="blue", lw=1, ls="--", label="Nile 294m")
    ax.axhline(301, color="cyan", lw=1, ls=":", label="Old thresh 301m")
    ax.axhline(308, color="teal", lw=1, ls=":", label="New thresh 308m")
    # Mark inflow cells at this column
    for name, d in INFLOW_DEFS.items():
        if d["col"] == c:
            ax.axvline(d["row"], color=d["color"], lw=1.5, ls="-", label=name)
            ax.plot(d["row"], dem[d["row"],c], "D", color=d["color"], ms=8)
    # Shade Nile cells
    nile_rows = rows_arr[elev < 296]
    if len(nile_rows):
        ax.fill_between(rows_arr, 290, np.where(elev<296, elev, np.nan),
                        alpha=0.3, color="cyan", label="Nile cells")
    ax.set_xlabel("Row"); ax.set_ylabel("Elevation (m)")
    ax.set_title(f"Cross-section at col={c}", fontweight="bold")
    ax.set_ylim(288, 340); ax.legend(fontsize=7); ax.grid(alpha=0.3)

fig.suptitle("DEM Cross-Sections at Key Columns — Connectivity Check",
             fontsize=13, fontweight="bold")
fig.tight_layout()
out = VIZ_DIR / "v20_dem_diagnostic_crosssections.png"
fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(f"  Saved: {out.name}")

print(f"\nAll diagnostics → {VIZ_DIR}")
print("\n=== SUMMARY ===")
print(f"Depressions: {dep_flip.sum():,}  Flats: {flat_flip.sum():,}  Pits: {pit_flip.sum():,}")
for name, d in INFLOW_DEFS.items():
    rows, cols, elevs = path_profile(d["row"], d["col"], n_steps=300)
    status = "REACHES NILE ✓" if elevs[-1] < 296 else f"STALLS at {elevs[-1]:.1f}m ✗"
    print(f"  {name}: {status}  (path length {len(rows)*30:.0f}m)")
