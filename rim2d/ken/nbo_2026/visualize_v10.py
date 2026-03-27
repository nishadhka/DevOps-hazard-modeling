#!/usr/bin/env python3
"""
v10 Culvert Inflow Visualization — Maps with culvert overlay.

Two modes:
  --inputs:  Verify input data (DEM, channel mask, culverts, rainfall, hydrograph)
  --results: Post-simulation flood depth maps + GIF animation

Usage:
    micromamba run -n zarrv3 python visualize_v10.py --inputs
    micromamba run -n zarrv3 python visualize_v10.py --results
"""

import argparse
import glob
import os
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import netCDF4
import numpy as np


WORK_DIR = Path(__file__).parent
V10_DIR = WORK_DIR / "v10"
INPUT_DIR = V10_DIR / "input"
OUTPUT_DIR = V10_DIR / "output"
VIS_DIR = V10_DIR / "visualizations"

VMAX = 8.0  # max depth for color scale (m)
DPI = 150

# Culvert locations (must match run_v10_culvert_inflow.py)
CULVERTS = [
    {"name": "Culvert 1", "lat": 19.547450, "lon": 33.339139, "catchment_km2": 30.0},
    {"name": "Culvert 2", "lat": 19.550000, "lon": 33.325906, "catchment_km2": 20.0},
]

SIM_DUR = 3283200
DT_INFLOW = 1800


def load_nc(path):
    """Load a RIM2D NetCDF file, return (data, x, y)."""
    ds = netCDF4.Dataset(str(path))
    x = ds["x"][:]
    y = ds["y"][:]
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[varname][:], dtype=np.float64)
    ds.close()
    data[data < -9000] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data, x, y


def make_hillshade(dem, azimuth=315, altitude=45):
    """Create hillshade from DEM."""
    az = np.radians(azimuth)
    alt = np.radians(altitude)
    dy, dx = np.gradient(np.nan_to_num(dem, nan=0))
    slope = np.pi / 2.0 - np.arctan(np.sqrt(dx**2 + dy**2))
    aspect = np.arctan2(-dy, dx)
    shade = (np.sin(alt) * np.sin(slope)
             + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))
    return shade


def flood_cmap():
    """Custom flood depth colormap 0-8m."""
    colors = [
        (1.0, 1.0, 1.0, 0.0),
        (0.85, 0.93, 1.0, 0.3),
        (0.6, 0.8, 1.0, 0.5),
        (0.3, 0.6, 1.0, 0.7),
        (0.15, 0.35, 0.85, 0.85),
        (0.3, 0.1, 0.7, 0.9),
        (0.6, 0.05, 0.5, 0.95),
        (0.85, 0.0, 0.15, 1.0),
        (0.5, 0.0, 0.0, 1.0),
    ]
    depths = [0.0, 0.01, 0.10, 0.50, 1.0, 2.0, 4.0, 6.0, 8.0]
    norm = [d / depths[-1] for d in depths]
    return mcolors.LinearSegmentedColormap.from_list(
        "flood8m", list(zip(norm, colors)), N=256
    )


def culvert_xy_km(x, y):
    """Get culvert positions in km coordinates."""
    from pyproj import Transformer
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    positions = []
    for cv in CULVERTS:
        utm_x, utm_y = to_utm.transform(cv["lon"], cv["lat"])
        xk = (utm_x - float(x[0])) / 1000.0
        yk = (utm_y - float(y[0])) / 1000.0
        positions.append((xk, yk, cv["name"]))
    return positions


# =============================================================================
# INPUT VERIFICATION
# =============================================================================

def plot_dem_with_culverts(dem, hillshade, x, y, extent, culv_pos):
    """DEM + hillshade + culvert markers."""
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.imshow(hillshade, origin="lower", extent=extent, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.5)
    im = ax.imshow(np.ma.masked_invalid(dem), origin="lower", extent=extent,
                   cmap="terrain", alpha=0.7)
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Elevation (m)", fontsize=11)

    for xk, yk, name in culv_pos:
        ax.plot(xk, yk, "D", color="red", markersize=12,
                markeredgecolor="black", markeredgewidth=1.5, zorder=10)
        ax.annotate(name, (xk, yk), textcoords="offset points",
                    xytext=(8, 8), fontsize=10, fontweight="bold",
                    color="red", bbox=dict(boxstyle="round,pad=0.2",
                                           fc="white", ec="red", alpha=0.8))

    nrows, ncols = dem.shape
    ax.set_title(f"v10 DEM + Culvert Locations | {ncols}x{nrows} cells",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    fig.tight_layout()
    fig.savefig(str(VIS_DIR / "v10_dem_culverts.png"), dpi=DPI,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  Saved: v10_dem_culverts.png")


def plot_boundary_mask(x, y, extent, culv_pos):
    """Boundary mask showing zone 1 and zone 2 cells."""
    mask_path = INPUT_DIR / "fluvbound_mask_v10.nc"
    if not mask_path.exists():
        print("  Skipping boundary mask (not found)")
        return

    mask, _, _ = load_nc(mask_path)
    fig, ax = plt.subplots(figsize=(14, 10))
    im = ax.imshow(np.ma.masked_where(mask == 0, mask), origin="lower",
                   extent=extent, cmap="Set1", vmin=0.5, vmax=2.5,
                   interpolation="nearest")
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02, ticks=[1, 2])
    cbar.set_label("Boundary Zone", fontsize=11)
    cbar.set_ticklabels(["Zone 1 (Culvert 1)", "Zone 2 (Culvert 2)"])

    for xk, yk, name in culv_pos:
        ax.plot(xk, yk, "D", color="red", markersize=12,
                markeredgecolor="black", markeredgewidth=1.5, zorder=10)
        ax.annotate(name, (xk, yk), textcoords="offset points",
                    xytext=(8, 8), fontsize=10, fontweight="bold", color="red")

    ax.set_title("v10 Fluvial Boundary Mask", fontsize=13, fontweight="bold")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    fig.tight_layout()
    fig.savefig(str(VIS_DIR / "v10_boundary_mask.png"), dpi=DPI,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  Saved: v10_boundary_mask.png")


def plot_channel_and_buildings(x, y, extent, culv_pos):
    """Channel mask, buildings, roughness."""
    fig, axes = plt.subplots(1, 3, figsize=(20, 7))

    for name, fname, cmap, label in [
        ("Channel Mask", "channel_mask.nc", "Blues", "Channel (0/1)"),
        ("Buildings", "buildings.nc", "Reds", "Buildings (0/1)"),
        ("Roughness", "roughness.nc", "YlOrBr", "Manning's n"),
    ]:
        ax = axes[["Channel Mask", "Buildings", "Roughness"].index(name)]
        path = INPUT_DIR / fname
        if not path.exists():
            ax.set_title(f"{name} (not found)")
            continue
        data, _, _ = load_nc(path)
        im = ax.imshow(np.ma.masked_invalid(data), origin="lower",
                       extent=extent, cmap=cmap, interpolation="nearest")
        fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02, label=label)
        ax.set_title(name, fontsize=12, fontweight="bold")
        ax.set_xlabel("x (km)")
        ax.set_ylabel("y (km)")

        for xk, yk, _ in culv_pos:
            ax.plot(xk, yk, "D", color="red", markersize=8,
                    markeredgecolor="black", markeredgewidth=1.0, zorder=10)

    fig.suptitle("v10 Input Rasters", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(str(VIS_DIR / "v10_inputs_rasters.png"), dpi=DPI,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  Saved: v10_inputs_rasters.png")


def plot_rainfall_summary():
    """IMERG rainfall summary: daily bars + cumulative."""
    rain_files = sorted(glob.glob(str(INPUT_DIR / "rain" / "imerg_v10_t*.nc")))
    if not rain_files:
        print("  Skipping rainfall summary (no rain files)")
        return

    n = len(rain_files)
    rates = np.zeros(n)
    for i, f in enumerate(rain_files):
        ds = netCDF4.Dataset(f)
        data = np.array(ds["Band1"][:], dtype=np.float32)
        ds.close()
        data[data < -9000] = 0.0
        data[~np.isfinite(data)] = 0.0
        rates[i] = float(np.mean(data))

    hours = np.arange(n) * 0.5  # half-hourly
    days = hours / 24.0

    # Daily totals (mm) = sum of half-hourly rates * 0.5
    n_days = int(np.ceil(n / 48))
    daily_mm = np.zeros(n_days)
    for d in range(n_days):
        i0 = d * 48
        i1 = min((d + 1) * 48, n)
        daily_mm[d] = np.sum(rates[i0:i1]) * 0.5

    cumulative_mm = np.cumsum(rates * 0.5)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 12))

    # Daily bars
    ax1.bar(range(n_days), daily_mm, color="steelblue", alpha=0.8)
    ax1.set_xlabel("Day (from Jul 25)")
    ax1.set_ylabel("Daily rainfall (mm)")
    ax1.set_title("IMERG 2025 Daily Rainfall", fontsize=12, fontweight="bold")
    ax1.grid(axis="y", alpha=0.3)

    # Cumulative
    ax2.plot(days, cumulative_mm, color="darkblue", linewidth=2)
    ax2.set_xlabel("Days from Jul 25")
    ax2.set_ylabel("Cumulative rainfall (mm)")
    ax2.set_title("Cumulative Rainfall", fontsize=12, fontweight="bold")
    ax2.grid(alpha=0.3)

    # Intensity time series
    ax3.plot(days, rates, color="steelblue", linewidth=0.5, alpha=0.7)
    ax3.set_xlabel("Days from Jul 25")
    ax3.set_ylabel("Rain rate (mm/hr)")
    ax3.set_title("Half-Hourly Rain Rate", fontsize=12, fontweight="bold")
    ax3.grid(alpha=0.3)

    total_mm = cumulative_mm[-1] if len(cumulative_mm) > 0 else 0
    fig.suptitle(f"v10 IMERG 2025 Rainfall Summary | Total: {total_mm:.1f} mm | "
                 f"Peak: {rates.max():.1f} mm/hr",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(str(VIS_DIR / "v10_rainfall_summary.png"), dpi=DPI,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: v10_rainfall_summary.png (total={total_mm:.1f}mm)")


def plot_culvert_hydrograph():
    """Culvert hydrograph Q vs time for both culverts."""
    hydro_path = INPUT_DIR / "culvert_hydrographs.npz"
    if not hydro_path.exists():
        print("  Skipping hydrograph plot (npz not found)")
        return

    data = np.load(str(hydro_path))
    times_h = data["times_h"]
    days = times_h / 24.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    colors = ["#e41a1c", "#377eb8"]
    for i, cv in enumerate(CULVERTS):
        key = f"q_{cv['name'].replace(' ', '')}"
        if key not in data:
            # Try without space
            key = f"q_Culvert{i+1}"
        if key not in data:
            print(f"  WARNING: key {key} not found in npz")
            continue
        q = data[key]
        ax1.plot(days, q, color=colors[i], linewidth=1.5,
                 label=f"{cv['name']} ({cv['catchment_km2']:.0f} km2)")

    ax1.set_xlabel("Days from Jul 25")
    ax1.set_ylabel("Flow (m3/s)")
    ax1.set_title("Culvert Inflow Hydrograph", fontsize=12, fontweight="bold")
    ax1.legend(fontsize=11)
    ax1.grid(alpha=0.3)

    # Also plot domain-mean rain on second axis
    rain = data["rain_rates"]
    rain_days = np.arange(len(rain)) * 0.5 / 24.0
    ax2.bar(rain_days, rain, width=0.5/24.0, color="steelblue", alpha=0.7)
    ax2.set_xlabel("Days from Jul 25")
    ax2.set_ylabel("Rain rate (mm/hr)")
    ax2.set_title("IMERG Domain-Mean Rainfall", fontsize=12, fontweight="bold")
    ax2.grid(alpha=0.3)

    fig.suptitle("v10 Culvert Hydrograph + Rainfall Forcing",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(str(VIS_DIR / "v10_culvert_hydrograph.png"), dpi=DPI,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  Saved: v10_culvert_hydrograph.png")


def visualize_inputs():
    """Generate all input verification plots."""
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading reference rasters...")
    dem, x, y = load_nc(INPUT_DIR / "dem.nc")
    hillshade = make_hillshade(dem)

    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    extent = [float(x_km[0]), float(x_km[-1]),
              float(y_km[0]), float(y_km[-1])]
    culv_pos = culvert_xy_km(x, y)

    print("\nGenerating input verification plots...")
    plot_dem_with_culverts(dem, hillshade, x_km, y_km, extent, culv_pos)
    plot_boundary_mask(x, y, extent, culv_pos)
    plot_channel_and_buildings(x, y, extent, culv_pos)
    plot_rainfall_summary()
    plot_culvert_hydrograph()

    print(f"\nAll input plots saved to {VIS_DIR}/")


# =============================================================================
# FLOOD RESULTS
# =============================================================================

def get_culvert_flow(t_sec):
    """Get culvert flow at time t_sec (from saved hydrograph data)."""
    hydro_path = INPUT_DIR / "culvert_hydrographs.npz"
    if not hydro_path.exists():
        return 0.0, 0.0
    data = np.load(str(hydro_path))
    idx = int(t_sec / DT_INFLOW)
    q1 = float(data.get("q_Culvert1", np.zeros(1))[min(idx, len(data.get("q_Culvert1", [0]))-1)])
    q2 = float(data.get("q_Culvert2", np.zeros(1))[min(idx, len(data.get("q_Culvert2", [0]))-1)])
    return q1, q2


def plot_flood_frame(wd, channel, buildings, hillshade, extent, x_km, y_km,
                     t_sec, out_path, culv_pos, label=None):
    """Plot a single flood depth frame with culvert overlay."""
    days = t_sec / 86400.0
    ch = channel > 0
    bldg = buildings > 0
    wet = wd > 0.01
    n_wet = int(np.sum(wet))
    n_bldg_wet = int(np.sum(wet & bldg))
    max_d = float(np.nanmax(wd)) if n_wet > 0 else 0.0
    pct = 100.0 * n_wet / wd.size

    q1, q2 = get_culvert_flow(t_sec)

    fig, ax = plt.subplots(figsize=(14, 10))

    # Hillshade
    ax.imshow(hillshade, origin="lower", extent=extent, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.6)

    # Flood depth
    wd_masked = np.ma.masked_where(wd < 0.01, wd)
    im = ax.imshow(wd_masked, origin="lower", extent=extent,
                   cmap=flood_cmap(), vmin=0, vmax=VMAX,
                   interpolation="nearest", alpha=0.85)

    # Building outlines
    if np.any(bldg):
        ax.contour(bldg.astype(float), levels=[0.5],
                   origin="lower", extent=extent,
                   colors=["red"], linewidths=0.6, alpha=0.7)

    # Culvert markers
    for xk, yk, name in culv_pos:
        ax.plot(xk, yk, "D", color="red", markersize=10,
                markeredgecolor="black", markeredgewidth=1.2, zorder=10)
        ax.annotate(name, (xk, yk), textcoords="offset points",
                    xytext=(6, 6), fontsize=8, fontweight="bold",
                    color="red", bbox=dict(boxstyle="round,pad=0.2",
                                           fc="white", ec="red", alpha=0.7))

    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Water Depth (m)", fontsize=11)

    if label:
        time_str = label
    else:
        time_str = f"Day {days:.1f}"

    ax.set_title(
        f"v10 Culvert Inflow -- {time_str} | "
        f"Q1={q1:.0f} Q2={q2:.0f} m3/s\n"
        f"Wet: {n_wet} ({pct:.1f}%) | "
        f"Buildings wet: {n_bldg_wet} | "
        f"Max: {max_d:.2f}m",
        fontsize=12, fontweight="bold"
    )
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")

    handles = [
        plt.Line2D([0], [0], marker="D", color="w", markerfacecolor="red",
                   markeredgecolor="black", markersize=10,
                   label="Culvert"),
        plt.Line2D([0], [0], color="red", lw=1, label="Buildings"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=9,
              framealpha=0.9, edgecolor="gray")

    fig.tight_layout()
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def visualize_results():
    """Generate flood result visualizations."""
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading reference rasters...")
    dem, x, y = load_nc(INPUT_DIR / "dem.nc")
    channel, _, _ = load_nc(INPUT_DIR / "channel_mask.nc")
    buildings, _, _ = load_nc(INPUT_DIR / "buildings.nc")

    hillshade = make_hillshade(dem)
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    extent = [float(x_km[0]), float(x_km[-1]),
              float(y_km[0]), float(y_km[-1])]
    culv_pos = culvert_xy_km(x, y)

    # Find output files
    wd_files = sorted(glob.glob(str(OUTPUT_DIR / "nile_v10_wd_*[0-9].nc")))
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
        t_sec = int(match.group(1))

        wd, _, _ = load_nc(wf)
        out_path = VIS_DIR / f"v10_flood_{t_sec:08d}.png"
        plot_flood_frame(wd, channel, buildings, hillshade, extent,
                         x_km, y_km, t_sec, out_path, culv_pos)
        frame_paths.append(str(out_path))

        if (i + 1) % 20 == 0 or i == len(wd_files) - 1:
            print(f"  [{i+1}/{len(wd_files)}] t={t_sec/86400:.1f}d")

    # Max depth frame
    max_path = OUTPUT_DIR / "nile_v10_wd_max.nc"
    if max_path.exists():
        wd_max, _, _ = load_nc(max_path)
        out_max = VIS_DIR / "v10_flood_wd_max.png"
        plot_flood_frame(wd_max, channel, buildings, hillshade, extent,
                         x_km, y_km, SIM_DUR, out_max, culv_pos,
                         label="Max Depth (38d)")
        print("  Max depth frame saved")

        bldg = buildings > 0
        wet_bldg = (wd_max > 0.01) & bldg
        print(f"\n  Max depth overall: {np.nanmax(wd_max):.2f}m")
        print(f"  Buildings with water: {int(np.sum(wet_bldg))}")
        if np.any(wet_bldg):
            print(f"  Max depth at buildings: "
                  f"{float(np.nanmax(wd_max[bldg])):.2f}m")

    # GIF animation
    if frame_paths:
        try:
            from PIL import Image
            print("\nCreating GIF animation...")
            images = [Image.open(fp) for fp in sorted(frame_paths)]
            gif_path = VIS_DIR / "v10_flood_animation.gif"
            images[0].save(
                str(gif_path), save_all=True,
                append_images=images[1:],
                duration=300, loop=0
            )
            gif_mb = gif_path.stat().st_size / (1024 * 1024)
            print(f"  GIF: {gif_path.name} ({gif_mb:.1f} MB, "
                  f"{len(images)} frames)")
        except ImportError:
            print("  Pillow not available, skipping GIF")

    print(f"\nAll visualizations saved to {VIS_DIR}/")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="v10 Culvert Inflow Visualization"
    )
    parser.add_argument("--inputs", action="store_true",
                        help="Verify input data")
    parser.add_argument("--results", action="store_true",
                        help="Visualize simulation results")
    args = parser.parse_args()

    if not args.inputs and not args.results:
        print("Specify --inputs or --results (or both)")
        return

    if args.inputs:
        print("=" * 60)
        print("v10 Input Verification")
        print("=" * 60)
        visualize_inputs()

    if args.results:
        print("=" * 60)
        print("v10 Flood Results")
        print("=" * 60)
        visualize_results()


if __name__ == "__main__":
    main()
