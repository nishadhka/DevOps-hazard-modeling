#!/usr/bin/env python3
"""
Nairobi v1 Visualization — Input verification and flood result maps.

Two modes:
  --inputs:  Verify terrain, channel mask, buildings, rainfall, river entry points,
             hydrographs.  Run this BEFORE starting the simulation.
  --results: Post-simulation flood depth maps + GIF animation.

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python visualize_v1.py --inputs
    micromamba run -n zarrv3 python visualize_v1.py --results
"""

import argparse
import csv
import glob
import os
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import netCDF4
import numpy as np

WORK_DIR  = Path(__file__).parent   # /data/rim2d/nbo_2026
V1_DIR    = WORK_DIR / "v1"
INPUT_DIR = V1_DIR / "input"
OUTPUT_DIR = V1_DIR / "output"
VIS_DIR   = V1_DIR / "visualizations"

CRS_UTM = "EPSG:32737"
VMAX    = 3.0   # m — max depth for color scale (Nairobi urban floods)
DPI     = 150

SIM_DUR   = 2592000   # 30 days
DT_INFLOW = 1800


# -- Utilities ----------------------------------------------------------------

def load_nc(path):
    ds      = netCDF4.Dataset(str(path))
    x       = ds["x"][:]
    y       = ds["y"][:]
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    data    = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    data[data < -9000] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data, x, y


def make_hillshade(dem, azimuth=315, altitude=45):
    az  = np.radians(azimuth);  alt = np.radians(altitude)
    dy, dx = np.gradient(np.nan_to_num(dem, nan=0))
    slope  = np.pi / 2.0 - np.arctan(np.sqrt(dx**2 + dy**2))
    aspect = np.arctan2(-dy, dx)
    shade  = (np.sin(alt) * np.sin(slope)
              + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))
    return shade


def flood_cmap():
    colors = [
        (1.0, 1.0, 1.0, 0.0),
        (0.85, 0.93, 1.0, 0.3),
        (0.6,  0.8,  1.0, 0.5),
        (0.3,  0.6,  1.0, 0.7),
        (0.15, 0.35, 0.85, 0.85),
        (0.3,  0.1,  0.7,  0.9),
        (0.6,  0.05, 0.5,  0.95),
        (0.85, 0.0,  0.15, 1.0),
    ]
    depths = [0.0, 0.01, 0.10, 0.30, 0.60, 1.0, 2.0, 3.0]
    norm   = [d / depths[-1] for d in depths]
    return mcolors.LinearSegmentedColormap.from_list(
        "flood3m", list(zip(norm, colors)), N=256
    )


def load_entry_points():
    """Load river entry points from CSV (written by run_v1_river_inflow.py)."""
    csv_path = INPUT_DIR / "river_entry_points.csv"
    if not csv_path.exists():
        return []
    entries = []
    with open(str(csv_path)) as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append({
                "id":    int(row["entry_id"]),
                "row":   int(row["row"]),
                "col":   int(row["col"]),
                "acc":   float(row["flow_acc"]),
                "km2":   float(row["catchment_km2"]),
                "lat":   float(row["lat"]),
                "lon":   float(row["lon"]),
                "elev":  float(row["elevation_m"]),
            })
    return entries


def entry_xy_km(entries, x, y):
    """Convert entry point row/col to km coordinates for plotting."""
    positions = []
    for e in entries:
        xk = (float(x[e["col"]]) - float(x[0])) / 1000.0
        yk = (float(y[e["row"]]) - float(y[0])) / 1000.0
        positions.append((xk, yk, f"R{e['id']}", e["km2"]))
    return positions


# =============================================================================
# INPUT VERIFICATION
# =============================================================================

def plot_dem_overview(dem, hillshade, x_km, y_km, extent, entry_pos):
    fig, ax = plt.subplots(figsize=(16, 8))
    ax.imshow(hillshade, origin="lower", extent=extent, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.5)
    im = ax.imshow(np.ma.masked_invalid(dem), origin="lower", extent=extent,
                   cmap="terrain", alpha=0.7)
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Elevation (m)", fontsize=11)

    for xk, yk, name, km2 in entry_pos:
        ax.plot(xk, yk, "^", color="crimson", markersize=12,
                markeredgecolor="black", markeredgewidth=1.2, zorder=10)
        ax.annotate(f"{name}\n{km2:.0f}km²", (xk, yk),
                    textcoords="offset points", xytext=(6, 6),
                    fontsize=8, fontweight="bold", color="crimson",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="crimson", alpha=0.8))

    nrows, ncols = dem.shape
    ax.set_title(
        f"Nairobi v1 DEM + River Entry Points | {ncols}x{nrows} cells | ~30m",
        fontsize=13, fontweight="bold"
    )
    ax.set_xlabel("x (km)");  ax.set_ylabel("y (km)")
    fig.tight_layout()
    out = VIS_DIR / "v1_dem_overview.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def plot_input_rasters(x_km, y_km, extent, entry_pos):
    panels = [
        ("Channel Mask",       "channel_mask.nc",      "Blues",   "Channel (0/1)"),
        ("Buildings",          "buildings.nc",          "Oranges", "Buildings (0/1)"),
        ("Roughness",          "roughness.nc",          "YlOrBr",  "Manning's n"),
        ("Flow Accumulation",  "flwacc_30m.nc",         "plasma",  "Upstream cells"),
        ("HND",                "hnd_30m.nc",            "RdYlGn_r","HAND (m)"),
        ("Sealed Surface",     "sealed_surface.nc",     "Reds",    "Fraction"),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(22, 12))
    axes = axes.ravel()

    for idx, (name, fname, cmap, label) in enumerate(panels):
        ax   = axes[idx]
        path = INPUT_DIR / fname
        if not path.exists():
            ax.set_title(f"{name} (not found)");  ax.axis("off");  continue
        data, _, _ = load_nc(path)
        # Log scale for flow accumulation
        if "flwacc" in fname:
            data = np.log1p(data)
            label = "log(1+acc)"
        im = ax.imshow(np.ma.masked_invalid(data), origin="lower",
                       extent=extent, cmap=cmap, interpolation="nearest")
        fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02, label=label)
        ax.set_title(name, fontsize=11, fontweight="bold")
        ax.set_xlabel("x (km)");  ax.set_ylabel("y (km)")
        for xk, yk, n2, _ in entry_pos:
            ax.plot(xk, yk, "^", color="red", markersize=7,
                    markeredgecolor="black", markeredgewidth=0.8, zorder=10)

    fig.suptitle("Nairobi v1 — Input Raster Verification",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    out = VIS_DIR / "v1_input_rasters.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def plot_boundary_mask(x_km, y_km, extent, entry_pos):
    mask_path = INPUT_DIR / "fluvbound_mask_v1.nc"
    if not mask_path.exists():
        print("  Skipping boundary mask (not generated yet)")
        return
    mask, _, _ = load_nc(mask_path)
    n_zones    = int(np.nanmax(mask))

    fig, ax = plt.subplots(figsize=(16, 8))
    masked = np.ma.masked_where(~np.isfinite(mask) | (mask == 0), mask)
    im = ax.imshow(masked, origin="lower", extent=extent,
                   cmap="tab10", vmin=0.5, vmax=n_zones + 0.5,
                   interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02,
                        ticks=range(1, n_zones + 1))
    cbar.set_label("River Entry Zone", fontsize=11)

    for xk, yk, name, km2 in entry_pos:
        ax.plot(xk, yk, "^", color="crimson", markersize=12,
                markeredgecolor="black", markeredgewidth=1.2, zorder=10)
        ax.annotate(f"{name}", (xk, yk), textcoords="offset points",
                    xytext=(5, 5), fontsize=9, fontweight="bold", color="crimson")

    ax.set_title(f"v1 Fluvial Boundary Mask ({n_zones} river entries)",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("x (km)");  ax.set_ylabel("y (km)")
    fig.tight_layout()
    out = VIS_DIR / "v1_boundary_mask.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def plot_rainfall_summary():
    rain_files = sorted(glob.glob(str(INPUT_DIR / "rain" / "imerg_v1_t*.nc")))
    if not rain_files:
        print("  Skipping rainfall (no files found)")
        return
    n     = len(rain_files)
    rates = np.zeros(n)
    for i, f in enumerate(rain_files):
        ds   = netCDF4.Dataset(f)
        data = np.array(ds["Band1"][:], dtype=np.float32)
        ds.close()
        data[data < -9000] = 0.0
        data[~np.isfinite(data)] = 0.0
        rates[i] = float(np.mean(data))

    days       = np.arange(n) * 0.5 / 24.0
    n_days     = int(np.ceil(n / 48))
    daily_mm   = np.array([np.sum(rates[d*48:(d+1)*48]) * 0.5 for d in range(n_days)])
    cumul_mm   = np.cumsum(rates * 0.5)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 12))

    ax1.bar(range(n_days), daily_mm, color="steelblue", alpha=0.8)
    ax1.set_xlabel("Day (from Apr 1 2025)");  ax1.set_ylabel("Daily rainfall (mm)")
    ax1.set_title("IMERG April 2025 Daily Rainfall", fontsize=12, fontweight="bold")
    ax1.grid(axis="y", alpha=0.3)

    ax2.plot(days, cumul_mm, color="darkblue", linewidth=2)
    ax2.set_xlabel("Days from Apr 1");  ax2.set_ylabel("Cumulative rainfall (mm)")
    ax2.set_title("Cumulative Rainfall", fontsize=12, fontweight="bold")
    ax2.grid(alpha=0.3)

    ax3.plot(days, rates, color="steelblue", linewidth=0.5, alpha=0.8)
    ax3.set_xlabel("Days from Apr 1");  ax3.set_ylabel("Rain rate (mm/hr)")
    ax3.set_title("Half-Hourly Rain Rate", fontsize=12, fontweight="bold")
    ax3.grid(alpha=0.3)

    total = cumul_mm[-1] if len(cumul_mm) > 0 else 0
    fig.suptitle(f"Nairobi v1 IMERG Apr 2025 | Total: {total:.1f} mm | "
                 f"Peak: {rates.max():.1f} mm/hr",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = VIS_DIR / "v1_rainfall_summary.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name} (total={total:.1f}mm)")


def plot_river_hydrographs():
    hydro_path = INPUT_DIR / "river_hydrographs.npz"
    if not hydro_path.exists():
        print("  Skipping hydrograph (npz not found)")
        return
    data    = np.load(str(hydro_path))
    times_h = data["times_h"]
    days    = times_h / 24.0

    q_keys = [k for k in data.files if k.startswith("q_entry")]
    n_entries = len(q_keys)

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    colors = plt.cm.tab10(np.linspace(0, 0.9, max(n_entries, 1)))

    for i, key in enumerate(sorted(q_keys)):
        q = data[key]
        axes[0].plot(days, q, color=colors[i], linewidth=1.5,
                     label=f"{key.replace('q_', '')} (peak={q.max():.0f} m3/s)")

    axes[0].set_xlabel("Days from Apr 1 2025")
    axes[0].set_ylabel("Flow (m3/s)")
    axes[0].set_title(f"River Entry Hydrographs ({n_entries} entries)",
                      fontsize=12, fontweight="bold")
    axes[0].legend(fontsize=9, ncol=2)
    axes[0].grid(alpha=0.3)

    rain = data["rain_rates"]
    rain_days = np.arange(len(rain)) * 0.5 / 24.0
    axes[1].bar(rain_days, rain, width=0.5/24.0, color="steelblue", alpha=0.7)
    axes[1].set_xlabel("Days from Apr 1 2025")
    axes[1].set_ylabel("Rain rate (mm/hr)")
    axes[1].set_title("IMERG Domain-Mean Rainfall", fontsize=12, fontweight="bold")
    axes[1].grid(alpha=0.3)

    fig.suptitle("Nairobi v1 River Hydrograph + Rainfall Forcing",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = VIS_DIR / "v1_river_hydrographs.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def plot_iwd_channel_check(x_km, y_km, extent):
    """IWD sanity check: show IWD and channel mask side-by-side."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 8))

    for ax, fname, label, cmap in [
        (ax1, "iwd.nc",          "IWD (m)",       "Blues"),
        (ax2, "channel_mask.nc", "Channel (0/1)", "Blues"),
    ]:
        path = INPUT_DIR / fname
        if not path.exists():
            ax.set_title(f"{fname} not found");  continue
        data, _, _ = load_nc(path)
        n_wet = int(np.sum(data > 0))
        im = ax.imshow(np.ma.masked_where(data <= 0, data),
                       origin="lower", extent=extent, cmap=cmap,
                       interpolation="nearest")
        fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02, label=label)
        ax.set_title(f"{fname} | wet cells: {n_wet} ({100*n_wet/data.size:.1f}%)",
                     fontsize=11, fontweight="bold")
        ax.set_xlabel("x (km)");  ax.set_ylabel("y (km)")

    fig.suptitle("Nairobi v1 — IWD + Channel Mask Sanity Check",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = VIS_DIR / "v1_iwd_check.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def visualize_inputs():
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading reference rasters...")
    dem, x, y = load_nc(INPUT_DIR / "dem.nc")
    hillshade  = make_hillshade(dem)
    x_km       = (x - x[0]) / 1000.0
    y_km       = (y - y[0]) / 1000.0
    extent     = [float(x_km[0]), float(x_km[-1]),
                  float(y_km[0]), float(y_km[-1])]

    entries   = load_entry_points()
    entry_pos = entry_xy_km(entries, x, y)
    print(f"  River entries loaded: {len(entries)}")

    print("\nGenerating input verification plots...")
    plot_dem_overview(dem, hillshade, x_km, y_km, extent, entry_pos)
    plot_input_rasters(x_km, y_km, extent, entry_pos)
    plot_boundary_mask(x_km, y_km, extent, entry_pos)
    plot_iwd_channel_check(x_km, y_km, extent)
    plot_rainfall_summary()
    plot_river_hydrographs()

    print(f"\nAll input plots saved to {VIS_DIR}/")
    print("\nREVIEW CHECKLIST:")
    print("  [ ] v1_dem_overview.png   — terrain looks correct, entry points on river edges")
    print("  [ ] v1_input_rasters.png  — channel mask follows actual rivers, buildings present")
    print("  [ ] v1_boundary_mask.png  — entry zones at expected locations")
    print("  [ ] v1_iwd_check.png      — IWD covers channel only (~5-15% of domain)")
    print("  [ ] v1_rainfall_summary   — April 2025 Nairobi rainfall looks plausible")
    print("  [ ] v1_river_hydrographs  — peak flows reasonable for catchment sizes")
    print("\nIf entry points need adjustment, edit ACC_THRESH or TOP_N in")
    print("run_v1_river_inflow.py and re-run it, then re-run this script.")


# =============================================================================
# FLOOD RESULTS
# =============================================================================

def plot_flood_frame(wd, channel, buildings, hillshade, extent, x_km, y_km,
                     t_sec, out_path, entry_pos, label=None):
    ch   = channel > 0
    bldg = buildings > 0
    wet  = wd > 0.01
    n_wet      = int(np.sum(wet))
    n_bldg_wet = int(np.sum(wet & bldg))
    max_d = float(np.nanmax(wd)) if n_wet > 0 else 0.0
    pct   = 100.0 * n_wet / wd.size
    days  = t_sec / 86400.0

    fig, ax = plt.subplots(figsize=(16, 8))
    ax.imshow(hillshade, origin="lower", extent=extent, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.6)

    wd_masked = np.ma.masked_where(wd < 0.01, wd)
    im = ax.imshow(wd_masked, origin="lower", extent=extent,
                   cmap=flood_cmap(), vmin=0, vmax=VMAX,
                   interpolation="nearest", alpha=0.85)

    if np.any(bldg):
        ax.contour(bldg.astype(float), levels=[0.5],
                   origin="lower", extent=extent,
                   colors=["red"], linewidths=0.5, alpha=0.7)

    for xk, yk, name, _ in entry_pos:
        ax.plot(xk, yk, "^", color="crimson", markersize=9,
                markeredgecolor="black", markeredgewidth=1.0, zorder=10)
        ax.annotate(name, (xk, yk), textcoords="offset points",
                    xytext=(5, 5), fontsize=7, fontweight="bold",
                    color="crimson",
                    bbox=dict(boxstyle="round,pad=0.1", fc="white",
                              ec="crimson", alpha=0.7))

    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Water Depth (m)", fontsize=11)
    time_str = label if label else f"Day {days:.1f} (Apr 2025)"

    ax.set_title(
        f"Nairobi v1 — {time_str}\n"
        f"Wet: {n_wet} ({pct:.1f}%) | Buildings wet: {n_bldg_wet} | Max: {max_d:.2f}m",
        fontsize=12, fontweight="bold"
    )
    ax.set_xlabel("x (km)");  ax.set_ylabel("y (km)")
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def visualize_results():
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading reference rasters...")
    dem,       x, y = load_nc(INPUT_DIR / "dem.nc")
    channel,   _, _ = load_nc(INPUT_DIR / "channel_mask.nc")
    buildings, _, _ = load_nc(INPUT_DIR / "buildings.nc")
    hillshade  = make_hillshade(dem)
    x_km       = (x - x[0]) / 1000.0
    y_km       = (y - y[0]) / 1000.0
    extent     = [float(x_km[0]), float(x_km[-1]),
                  float(y_km[0]), float(y_km[-1])]

    entries   = load_entry_points()
    entry_pos = entry_xy_km(entries, x, y)

    wd_files = sorted(glob.glob(str(OUTPUT_DIR / "nbo_v1_wd_*[0-9].nc")))
    wd_files = [f for f in wd_files
                if re.search(r"wd_\d+\.nc$", os.path.basename(f))
                and "max" not in os.path.basename(f)]
    print(f"Found {len(wd_files)} water depth output files")

    if not wd_files:
        print("No output files found. Run the simulation first.")
        return

    frame_paths = []
    for i, wf in enumerate(wd_files):
        match = re.search(r"wd_(\d+)\.nc", os.path.basename(wf))
        if not match:
            continue
        t_sec   = int(match.group(1))
        wd, _, _ = load_nc(wf)
        out_path = VIS_DIR / f"v1_flood_{t_sec:08d}.png"
        plot_flood_frame(wd, channel, buildings, hillshade, extent,
                         x_km, y_km, t_sec, out_path, entry_pos)
        frame_paths.append(str(out_path))
        if (i + 1) % 20 == 0 or i == len(wd_files) - 1:
            print(f"  [{i+1}/{len(wd_files)}] t={t_sec/86400:.1f}d")

    # Max depth
    max_path = OUTPUT_DIR / "nbo_v1_wd_max.nc"
    if max_path.exists():
        wd_max, _, _ = load_nc(max_path)
        out_max = VIS_DIR / "v1_flood_wd_max.png"
        plot_flood_frame(wd_max, channel, buildings, hillshade, extent,
                         x_km, y_km, SIM_DUR, out_max, entry_pos,
                         label="Max Depth (30d)")
        bldg     = buildings > 0
        wet_bldg = (wd_max > 0.01) & bldg
        print(f"\n  Max depth overall:       {np.nanmax(wd_max):.2f}m")
        print(f"  Buildings with water:    {int(np.sum(wet_bldg))}")
        if np.any(wet_bldg):
            print(f"  Max depth at buildings:  {float(np.nanmax(wd_max[bldg])):.2f}m")

    # GIF
    if frame_paths:
        try:
            from PIL import Image
            print("\nCreating GIF animation...")
            images   = [Image.open(fp) for fp in sorted(frame_paths)]
            gif_path = VIS_DIR / "v1_flood_animation.gif"
            images[0].save(
                str(gif_path), save_all=True,
                append_images=images[1:], duration=300, loop=0
            )
            gif_mb = gif_path.stat().st_size / (1024 * 1024)
            print(f"  GIF: {gif_path.name} ({gif_mb:.1f} MB, {len(images)} frames)")
        except ImportError:
            print("  Pillow not available, skipping GIF")

    print(f"\nAll visualizations saved to {VIS_DIR}/")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Nairobi v1 Visualization")
    parser.add_argument("--inputs",  action="store_true",
                        help="Verify input data (run before simulation)")
    parser.add_argument("--results", action="store_true",
                        help="Visualize simulation results")
    args = parser.parse_args()

    if not args.inputs and not args.results:
        print("Specify --inputs or --results (or both)")
        return

    if args.inputs:
        print("=" * 60)
        print("Nairobi v1 — Input Verification")
        print("=" * 60)
        visualize_inputs()

    if args.results:
        print("=" * 60)
        print("Nairobi v1 — Flood Results")
        print("=" * 60)
        visualize_results()


if __name__ == "__main__":
    main()
