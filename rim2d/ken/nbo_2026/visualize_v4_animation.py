#!/usr/bin/env python3
"""
Nairobi v4 Steady-State — Animation.

Plots each timestep of the 12h steady-state pre-simulation, showing
how baseflow gradually wets the channel network from entry points to
equilibrium. Stitches frames into a GIF.

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python visualize_v4_animation.py --test
    micromamba run -n zarrv3 python visualize_v4_animation.py
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

# ---------------------------------------------------------------------------
WORK_DIR   = Path(__file__).resolve().parent
V1_INPUT   = WORK_DIR / "v1" / "input"
V4_OUTPUT  = WORK_DIR / "v4" / "output"
VIS_DIR    = WORK_DIR / "v4" / "visualizations"
FRAMES_DIR = VIS_DIR / "frames"

DEM_PATH       = V1_INPUT / "dem.nc"
BUILDINGS_PATH = V1_INPUT / "buildings.nc"
ENTRIES_CSV    = V1_INPUT / "river_entries_v1.csv"

VMAX = 4.0
DPI  = 120

# CROSSING entry points to mark on each frame
CROSSINGS = [
    {"stream_order": 5, "lon": 37.019333, "lat": -1.389222},
    {"stream_order": 5, "lon": 37.100000, "lat": -1.274667},
    {"stream_order": 4, "lon": 36.862333, "lat": -1.402000},
    {"stream_order": 4, "lon": 37.100000, "lat": -1.199889},
    {"stream_order": 4, "lon": 37.100000, "lat": -1.184333},
    {"stream_order": 3, "lon": 36.782667, "lat": -1.388667},
    {"stream_order": 3, "lon": 36.821222, "lat": -1.383333},
    {"stream_order": 3, "lon": 36.872444, "lat": -1.402000},
    {"stream_order": 2, "lon": 36.600000, "lat": -1.295556},
    {"stream_order": 2, "lon": 36.604667, "lat": -1.360111},
    {"stream_order": 2, "lon": 36.607000, "lat": -1.402000},
    {"stream_order": 2, "lon": 36.618667, "lat": -1.202222},
    {"stream_order": 2, "lon": 36.738444, "lat": -1.402000},
    {"stream_order": 2, "lon": 37.086667, "lat": -1.348667},
    {"stream_order": 2, "lon": 37.086778, "lat": -1.351556},
    {"stream_order": 2, "lon": 37.100000, "lat": -1.304333},
]

ORDER_COLOR = {5: "#cc0000", 4: "#e06600", 3: "#1a66ff", 2: "#44aa44"}
ORDER_SIZE  = {5: 14, 4: 11, 3: 9, 2: 7}

# ---------------------------------------------------------------------------

def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x  = np.array(ds["x"][:])
    y  = np.array(ds["y"][:])
    vn = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[vn][:], dtype=np.float32)
    ds.close()
    data[data < -9000] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data, x, y


def make_hillshade(dem):
    az  = np.radians(315)
    alt = np.radians(45)
    dy, dx = np.gradient(np.nan_to_num(dem, nan=0))
    slope  = np.pi / 2.0 - np.arctan(np.sqrt(dx**2 + dy**2))
    aspect = np.arctan2(-dy, dx)
    return (np.sin(alt) * np.sin(slope)
            + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))


def flood_cmap():
    colors = [
        (1.0, 1.0, 1.0, 0.0),
        (0.85, 0.93, 1.0, 0.3),
        (0.6,  0.80, 1.0, 0.55),
        (0.3,  0.60, 1.0, 0.70),
        (0.15, 0.35, 0.85, 0.85),
        (0.3,  0.10, 0.70, 0.90),
        (0.6,  0.05, 0.50, 0.95),
        (0.85, 0.0,  0.15, 1.0),
    ]
    depths = [0.0, 0.01, 0.10, 0.50, 1.0, 1.5, 2.5, 4.0]
    norm   = [d / depths[-1] for d in depths]
    return mcolors.LinearSegmentedColormap.from_list(
        "flood4m", list(zip(norm, colors)), N=256)


def latlon_to_utm(lon, lat):
    from pyproj import Transformer
    tf = Transformer.from_crs("EPSG:4326", "EPSG:32737", always_xy=True)
    return tf.transform(lon, lat)


def project_entries(x_arr, y_arr):
    """Convert crossing lat/lon to UTM metres."""
    pts = []
    for e in CROSSINGS:
        utmx, utmy = latlon_to_utm(e["lon"], e["lat"])
        pts.append((utmx, utmy, e["stream_order"]))
    return pts


def plot_frame(wd, buildings, hillshade, x_arr, y_arr,
               entry_pts, t_sec, total_s, out_path):
    wd = np.where(wd > 20, np.nan, wd)
    bldg = buildings > 0
    wet  = wd > 0.01
    n_wet = int(np.sum(wet))
    max_d = float(np.nanmax(wd)) if n_wet > 0 else 0.0
    pct   = 100.0 * n_wet / wd.size
    pct_ss = 100.0 * t_sec / total_s

    ext = [float(x_arr[0]), float(x_arr[-1]),
           float(y_arr[0]), float(y_arr[-1])]

    fig, ax = plt.subplots(figsize=(14, 9))

    ax.imshow(hillshade, origin="lower", extent=ext,
              cmap="gray", vmin=0.3, vmax=1.0, alpha=0.55)

    wd_m = np.ma.masked_where(wd < 0.01, wd)
    im = ax.imshow(wd_m, origin="lower", extent=ext,
                   cmap=flood_cmap(), vmin=0, vmax=VMAX,
                   interpolation="nearest", alpha=0.88, zorder=5)

    # Building outlines
    if np.any(bldg):
        ax.contour(bldg.astype(np.float32), levels=[0.5],
                   origin="lower", extent=ext,
                   colors=["#ff8800"], linewidths=0.5, alpha=0.6, zorder=7)

    # River entry points (CROSSING only) — coloured by stream order
    for utmx, utmy, so in entry_pts:
        col  = ORDER_COLOR.get(so, "#888888")
        size = ORDER_SIZE.get(so, 7)
        ax.plot(utmx, utmy, "^", color=col, markersize=size,
                markeredgecolor="white", markeredgewidth=0.7, zorder=12)

    cbar = fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02)
    cbar.set_label("Water Depth (m)", fontsize=10)

    # Legend
    order_handles = [
        plt.Line2D([0], [0], marker="^", color="w",
                   markerfacecolor=ORDER_COLOR[so],
                   markeredgecolor="white", markersize=ORDER_SIZE[so],
                   label=f"Order {so} entry")
        for so in sorted(ORDER_COLOR.keys(), reverse=True)
    ]
    order_handles.append(
        mpatches.Patch(facecolor="none", edgecolor="#ff8800",
                       linewidth=1.0, label="Buildings")
    )
    ax.legend(handles=order_handles, loc="lower right", fontsize=8,
              framealpha=0.9, edgecolor="gray")

    h = t_sec // 3600
    m = (t_sec % 3600) // 60
    ax.set_title(
        f"Nairobi v4 — Steady-State Spin-up  "
        f"t = {int(h):02d}h{int(m):02d}m  ({pct_ss:.0f}% complete)\n"
        f"Wet cells: {n_wet:,} ({pct:.3f}%)  |  Max depth: {max_d:.2f} m  |  "
        f"16 CROSSING inflow points (constant baseflow)",
        fontsize=11, fontweight="bold"
    )

    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}"))
    ax.set_xlabel("Easting (km, UTM 37S)")
    ax.set_ylabel("Northing (km, UTM 37S)")
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])

    fig.tight_layout()
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true",
                        help="Render only one frame then exit")
    args = parser.parse_args()

    VIS_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading DEM and buildings...")
    dem, x_arr, y_arr = load_nc(DEM_PATH)
    buildings, _, _   = load_nc(BUILDINGS_PATH)
    buildings = np.flipud(buildings)
    hillshade  = make_hillshade(dem)

    entry_pts = project_entries(x_arr, y_arr)

    all_wd = glob.glob(str(V4_OUTPUT / "nbo_v4ss_wd_*.nc"))
    wd_files = sorted(
        [f for f in all_wd
         if re.search(r"nbo_v4ss_wd_\d+\.nc$", os.path.basename(f))],
        key=lambda p: int(re.search(r"nbo_v4ss_wd_(\d+)\.nc",
                                     os.path.basename(p)).group(1))
    )
    print(f"Found {len(wd_files)} steady-state timestep files")

    if not wd_files:
        print("No output files found.")
        return

    total_s = int(re.search(r"nbo_v4ss_wd_(\d+)\.nc",
                              os.path.basename(wd_files[-1])).group(1))

    if args.test:
        wd_files = [wd_files[len(wd_files) // 2]]
        print(f"TEST — rendering: {os.path.basename(wd_files[0])}")

    frame_paths = []
    for i, wf in enumerate(wd_files):
        t_sec = int(re.search(r"nbo_v4ss_wd_(\d+)\.nc",
                               os.path.basename(wf)).group(1))
        wd, _, _ = load_nc(wf)
        out_path  = FRAMES_DIR / f"ss_frame_{i:04d}_t{t_sec:06d}.png"
        plot_frame(wd, buildings, hillshade, x_arr, y_arr,
                   entry_pts, t_sec, total_s, out_path)
        frame_paths.append(str(out_path))
        h = t_sec // 3600; m = (t_sec % 3600) // 60
        print(f"  [{i+1:02d}/{len(wd_files)}] {int(h):02d}h{int(m):02d}m → {out_path.name}")

    if args.test:
        print(f"\nTest frame: {frame_paths[0]}")
        return

    # GIF
    try:
        from PIL import Image
        print("\nCreating GIF animation...")
        images = [Image.open(fp) for fp in sorted(frame_paths)]
        gif_path = VIS_DIR / "v4_steadystate_animation.gif"
        images[0].save(str(gif_path), save_all=True,
                       append_images=images[1:], duration=500, loop=0)
        gif_mb = gif_path.stat().st_size / (1024 * 1024)
        print(f"  GIF: {gif_path.name} ({gif_mb:.1f} MB, {len(images)} frames)")
    except ImportError:
        print("  Pillow not available, skipping GIF")

    print(f"\nDone. Output: {VIS_DIR}/")


if __name__ == "__main__":
    main()
