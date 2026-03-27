#!/usr/bin/env python3
"""
Plot all v14 input data for verification.
  1. DEM comparison: v10 original vs v14 stream-burned, burn depth difference
  2. Boundary mask (4 inflow zones)
  3. Buildings footprint
  4. Inflow locations from inflowlocs_v14.txt (WSE timeseries)

Usage:
    micromamba run -n zarrv3 python analysis/plot_v14_inputs.py
"""

from pathlib import Path
import numpy as np
import netCDF4
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patheffects as pe

V10_INPUT = Path("/data/rim2d/nile_highres/v10/input")
V14_INPUT = Path("/data/rim2d/nile_highres/v14/input")
VIZ_DIR   = Path("/data/rim2d/nile_highres/v14/analysis/visualizations")
VIZ_DIR.mkdir(parents=True, exist_ok=True)
DPI = 130

KEY_SITES = [
    (212, 312, "Culvert1",     "D", "#e41a1c"),
    (222, 266, "Culvert2",     "D", "#377eb8"),
    (222, 175, "WesternWadi",  "D", "#2ca02c"),
    (183, 281, "HospitalWadi", "s", "#ff7f00"),
    (0,   354, "Nile Exit",    "v", "lime"),
]


def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = np.array(ds["x"][:], dtype=np.float64)
    y = np.array(ds["y"][:], dtype=np.float64)
    var = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[var][:], dtype=np.float64).squeeze()
    ds.close()
    data[data < -9000] = np.nan
    return data, x, y


def make_hillshade(dem, azimuth=315, altitude=45):
    az, alt = np.radians(azimuth), np.radians(altitude)
    dy, dx = np.gradient(np.nan_to_num(dem, nan=0))
    slope  = np.pi / 2 - np.arctan(np.sqrt(dx**2 + dy**2))
    aspect = np.arctan2(-dy, dx)
    return np.sin(alt)*np.sin(slope) + np.cos(alt)*np.cos(slope)*np.cos(az-aspect)


def km_extent(x, y):
    xk = (x - x[0]) / 1000
    yk = (y - y[0]) / 1000
    return xk, yk, [xk[0], xk[-1], yk[0], yk[-1]]


def add_site_markers(ax, xk, yk, show_nile=True):
    for r, c, lbl, mk, col in KEY_SITES:
        if lbl == "Nile Exit" and not show_nile:
            continue
        ax.plot(xk[c], yk[r], mk, color=col, ms=10, mew=1.2, mec="black", zorder=10)
        ax.annotate(lbl, (xk[c], yk[r]), textcoords="offset points",
                    xytext=(5, 5), fontsize=7.5, fontweight="bold", color=col,
                    path_effects=[pe.withStroke(linewidth=2, foreground="black")])


# ── 1. DEM comparison ───────────────────────────────────────────────────────
def plot_dem_comparison():
    dem10, x, y = load_nc(V10_INPUT / "dem.nc")
    dem14, _, _ = load_nc(V14_INPUT / "dem_v14.nc")
    xk, yk, ext = km_extent(x, y)
    hs10 = make_hillshade(dem10)
    hs14 = make_hillshade(dem14)
    diff = dem14 - dem10   # negative = burned deeper

    fig, axes = plt.subplots(1, 3, figsize=(20, 7))

    # v10 original DEM
    ax = axes[0]
    ax.imshow(hs10, origin="lower", extent=ext, cmap="gray", vmin=0.3, vmax=1.0, alpha=0.5)
    im = ax.imshow(np.ma.masked_invalid(dem10), origin="lower", extent=ext,
                   cmap="terrain", alpha=0.7, vmin=300, vmax=380)
    add_site_markers(ax, xk, yk)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Elevation (m)")
    ax.set_title("v10 — Original MERIT DEM", fontsize=11, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    # v14 stream-burned DEM
    ax = axes[1]
    ax.imshow(hs14, origin="lower", extent=ext, cmap="gray", vmin=0.3, vmax=1.0, alpha=0.5)
    im = ax.imshow(np.ma.masked_invalid(dem14), origin="lower", extent=ext,
                   cmap="terrain", alpha=0.7, vmin=300, vmax=380)
    add_site_markers(ax, xk, yk)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Elevation (m)")
    n_burned = int(np.sum(diff < -0.5))
    ax.set_title(f"v14 — Stream-burned DEM\n({n_burned} cells burned, TDX-Hydro orders 2/5/9)",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    # Burn depth difference
    ax = axes[2]
    ax.imshow(hs10, origin="lower", extent=ext, cmap="gray", vmin=0.3, vmax=1.0, alpha=0.4)
    burn_masked = np.ma.masked_where(diff > -0.5, diff)
    cmap_burn = plt.cm.get_cmap("YlOrRd_r")
    im = ax.imshow(burn_masked, origin="lower", extent=ext,
                   cmap=cmap_burn, vmin=-8, vmax=0, interpolation="nearest")
    add_site_markers(ax, xk, yk)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Burn depth (m, negative = deeper)")
    ax.set_title(f"DEM difference (v14 − v10)\nBurned cells: {n_burned} | Max burn: {diff.min():.1f} m",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    fig.suptitle("v14 Input — DEM Verification (stream burning)", fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = VIZ_DIR / "v14_input_dem_comparison.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


# ── 2. Boundary mask + buildings ────────────────────────────────────────────
def plot_boundary_and_buildings():
    dem14, x, y  = load_nc(V14_INPUT / "dem_v14.nc")
    mask, _, _   = load_nc(V14_INPUT / "fluvbound_mask_v14.nc")
    bldg, _, _   = load_nc(V10_INPUT / "buildings.nc")
    # Buildings from input raster have row 0 = north; flip to match DEM (row 0 = south)
    bldg = np.flipud(bldg)
    xk, yk, ext = km_extent(x, y)
    hs = make_hillshade(dem14)

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    # Boundary mask
    ax = axes[0]
    ax.imshow(hs, origin="lower", extent=ext, cmap="gray", vmin=0.3, vmax=1.0, alpha=0.5)
    n_zones = int(np.nanmax(mask[np.isfinite(mask)]))
    zone_colors = ["#e41a1c", "#377eb8", "#2ca02c", "#ff7f00"]
    zone_labels = ["Zone 1 — Culvert1", "Zone 2 — Culvert2",
                   "Zone 3 — WesternWadi", "Zone 4 — HospitalWadi"]
    cmap_z = mcolors.ListedColormap(zone_colors[:n_zones])
    im = ax.imshow(np.ma.masked_where(mask < 0.5, mask), origin="lower", extent=ext,
                   cmap=cmap_z, vmin=0.5, vmax=n_zones+0.5, interpolation="nearest")
    cb = fig.colorbar(im, ax=ax, shrink=0.7, ticks=range(1, n_zones+1))
    cb.set_ticklabels(zone_labels[:n_zones])
    add_site_markers(ax, xk, yk, show_nile=False)
    ax.set_title(f"v14 Fluvial Boundary Mask — {n_zones} inflow zones\n"
                 f"(v12 fix: HospitalWadi added as 4th zone)", fontsize=11, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    # Buildings
    ax = axes[1]
    ax.imshow(hs, origin="lower", extent=ext, cmap="gray", vmin=0.3, vmax=1.0, alpha=0.5)
    bldg_m = np.ma.masked_where(bldg < 0.5, bldg)
    ax.imshow(bldg_m, origin="lower", extent=ext,
              cmap=mcolors.ListedColormap(["#d95f02"]),
              alpha=0.7, interpolation="nearest")
    add_site_markers(ax, xk, yk, show_nile=False)
    n_bldg = int(np.sum(bldg > 0.5))
    ax.set_title(f"Buildings footprint (from v10 input, flipped)\n"
                 f"{n_bldg:,} building cells", fontsize=11, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    fig.suptitle("v14 Input — Boundary mask and buildings", fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = VIZ_DIR / "v14_input_boundary_buildings.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


# ── 3. WSE inflow timeseries ─────────────────────────────────────────────────
def plot_inflow_wse():
    inflow_file = V14_INPUT / "inflowlocs_v14.txt"
    lines = inflow_file.read_text().splitlines()
    # Format: line0=SIM_DUR, line1=DT, line2=n_cells, then one line per cell: row col wse...
    sim_dur = int(lines[0].strip())
    dt_s    = int(lines[1].strip())
    n_cells = int(lines[2].strip())
    print(f"  {n_cells} inflow cells, SIM_DUR={sim_dur}s, DT={dt_s}s")

    cells = []
    for i in range(3, 3 + n_cells):
        parts = lines[i].split()
        row_1idx, col_1idx = int(parts[0]), int(parts[1])
        row, col = row_1idx - 1, col_1idx - 1   # convert to 0-indexed
        wse = np.array([float(v) for v in parts[2:]])
        cells.append((row, col, wse))

    # Match cells to site labels by row/col
    site_map = {(r, c): (lbl, col) for r, c, lbl, _, col in KEY_SITES}

    dt_h = 0.5   # 30 min timesteps
    n_steps = len(cells[0][2])
    times_h = np.arange(n_steps) * dt_h

    fig, ax = plt.subplots(figsize=(12, 5))
    for row, col, wse in cells:
        lbl, clr = site_map.get((row, col), (f"r{row}c{col}", "gray"))
        ax.plot(times_h, wse, lw=1.5, label=f"{lbl} (row={row}, col={col})", color=clr)

    ax.set_xlabel("Hours from simulation start (Aug 25 00:00 UTC)", fontsize=10)
    ax.set_ylabel("Water surface elevation (m)", fontsize=10)
    ax.set_title(f"v14 Inflow WSE timeseries — {n_cells} boundary cells × {n_steps} timesteps\n"
                 f"(WSE = DEM elevation + water depth above sill, capped at sill+1.5m)",
                 fontsize=11, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    out = VIZ_DIR / "v14_input_inflow_wse.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


# ── 4. Fix visualize_v14.py to use v14 DEM hillshade ─────────────────────────
def check_hillshade_mismatch():
    dem10, x, y = load_nc(V10_INPUT / "dem.nc")
    dem14, _, _ = load_nc(V14_INPUT / "dem_v14.nc")
    xk, yk, ext = km_extent(x, y)

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    for ax, dem, title in [
        (axes[0], dem10, "Hillshade from v10 DEM\n(used in visualization background — ORIGINAL)"),
        (axes[1], dem14, "Hillshade from v14 DEM\n(stream-burned channels visible — CORRECT for v14)"),
    ]:
        hs = make_hillshade(dem)
        ax.imshow(hs, origin="lower", extent=ext, cmap="gray", vmin=0.3, vmax=1.0)
        add_site_markers(ax, xk, yk)
        ax.set_title(title, fontsize=10, fontweight="bold")
        ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")

    fig.suptitle("Hillshade background comparison: which DEM to use for v14 visualization?",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    out = VIZ_DIR / "v14_input_hillshade_comparison.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


if __name__ == "__main__":
    print("Plotting v14 input data ...")
    plot_dem_comparison()
    plot_boundary_and_buildings()
    plot_inflow_wse()
    check_hillshade_mismatch()
    print(f"\nAll input plots → {VIZ_DIR}")
