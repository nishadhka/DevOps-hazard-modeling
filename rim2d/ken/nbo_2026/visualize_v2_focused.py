#!/usr/bin/env python3
"""
v2 Nairobi Event Flood — Focused Animation around damage sites.

Renders one PNG per timestep: flood depth on DEM hillshade,
yellow damage-site circles, zoomed to a 3 km buffer around the
two reported damage locations. No building footprint overlay.

Title shows actual clock time (EVENT_START + elapsed).

Usage:
    cd /data/rim2d/nbo_2026
    # test single frame:
    micromamba run -n zarrv3 python visualize_v2_focused.py --test
    # full animation:
    micromamba run -n zarrv3 python visualize_v2_focused.py
"""

import argparse
import glob
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import netCDF4
import numpy as np

# ---------------------------------------------------------------------------
WORK_DIR   = Path(__file__).resolve().parent
V1_INPUT   = WORK_DIR / "v1" / "input"
V2_OUTPUT  = WORK_DIR / "v2" / "output"
VIS_DIR    = WORK_DIR / "v2" / "visualizations"
FRAMES_DIR = VIS_DIR / "frames_focused"

DEM_PATH = V1_INPUT / "dem.nc"

EVENT_START_UTC = datetime(2026, 3, 6, 16, 0, 0, tzinfo=timezone.utc)

VMAX    = 4.0   # m
DPI     = 120
BUFFER  = 3000  # 3 km buffer around damage sites (metres)

DAMAGE_LOCS = [
    {"name": "Flood reported",    "lon": 36.8207720971431, "lat": -1.31125324510586},
    {"name": "Kirinyaga Rd flooding", "lon": 36.8429,          "lat": -1.2841},
]

# ---------------------------------------------------------------------------

def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[varname][:], dtype=np.float32)
    ds.close()
    data[data < -9000] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data, x, y


def make_hillshade(dem, azimuth=315, altitude=45):
    az  = np.radians(azimuth)
    alt = np.radians(altitude)
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
        (0.5,  0.0,  0.0,  1.0),
    ]
    depths = [0.0, 0.01, 0.10, 0.50, 1.0, 1.5, 2.5, 3.5, 4.0]
    norm   = [d / depths[-1] for d in depths]
    return mcolors.LinearSegmentedColormap.from_list(
        "flood4m", list(zip(norm, colors)), N=256)


def latlon_to_utm(lon, lat):
    from pyproj import Transformer
    tf = Transformer.from_crs("EPSG:4326", "EPSG:32737", always_xy=True)
    return tf.transform(lon, lat)


def format_clock(t_sec):
    dt = EVENT_START_UTC + timedelta(seconds=int(t_sec))
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def compute_focus_extent(damage_pos, x_arr, y_arr, buffer):
    xs = [p[0] for p in damage_pos]
    ys = [p[1] for p in damage_pos]
    cx = sum(xs) / len(xs)   # centroid of markers
    cy = sum(ys) / len(ys)
    xmin = max(cx - buffer, float(x_arr[0]))
    xmax = min(cx + buffer, float(x_arr[-1]))
    ymin = max(cy - buffer, float(y_arr[0]))
    ymax = min(cy + buffer, float(y_arr[-1]))
    return xmin, xmax, ymin, ymax


# ---------------------------------------------------------------------------

def plot_frame(wd, hillshade, x_arr, y_arr, damage_pos, focus_ext,
               t_sec, out_path):
    wd = np.where(wd > 20, np.nan, wd)

    wet    = wd > 0.01
    n_wet  = int(np.sum(wet))
    max_d  = float(np.nanmax(wd)) if n_wet > 0 else 0.0
    pct    = 100.0 * n_wet / wd.size

    full_ext = [float(x_arr[0]), float(x_arr[-1]),
                float(y_arr[0]), float(y_arr[-1])]

    fig, ax = plt.subplots(figsize=(10, 9))

    ax.imshow(hillshade, origin="lower", extent=full_ext,
              cmap="gray", vmin=0.3, vmax=1.0, alpha=0.55)

    wd_m = np.ma.masked_where(wd < 0.01, wd)
    im = ax.imshow(wd_m, origin="lower", extent=full_ext,
                   cmap=flood_cmap(), vmin=0, vmax=VMAX,
                   interpolation="nearest", alpha=0.85, zorder=5)

    for utmx, utmy, name in damage_pos:
        ax.plot(utmx, utmy, "o", color="none", markersize=18,
                markeredgecolor="yellow", markeredgewidth=2.0, zorder=12)
        ax.annotate(name, (utmx, utmy),
                    textcoords="offset points", xytext=(12, 7),
                    fontsize=9, fontweight="bold", color="yellow",
                    bbox=dict(boxstyle="round,pad=0.3",
                              fc="#222222", ec="yellow", alpha=0.88))

    cbar = fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02)
    cbar.set_label("Water Depth (m)", fontsize=10)

    clock = format_clock(t_sec)
    ax.set_title(
        f"Nairobi Flash Flood — {clock}  |  "
        f"Flooded: {n_wet:,} cells ({pct:.1f}%)  |  Max depth: {max_d:.2f} m",
        fontsize=11, fontweight="bold"
    )

    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.1f}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.1f}"))
    ax.set_xlabel("Easting (km, UTM 37S)")
    ax.set_ylabel("Northing (km, UTM 37S)")

    xmin, xmax, ymin, ymax = focus_ext
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)

    fig.tight_layout()
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true",
                        help="Render only the middle timestep then exit")
    args = parser.parse_args()

    VIS_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading DEM raster...")
    dem, x_arr, y_arr = load_nc(DEM_PATH)
    hillshade = make_hillshade(dem)

    # Damage positions in UTM metres
    damage_pos = []
    for d in DAMAGE_LOCS:
        utmx, utmy = latlon_to_utm(d["lon"], d["lat"])
        damage_pos.append((utmx, utmy, d["name"]))

    focus_ext = compute_focus_extent(damage_pos, x_arr, y_arr, BUFFER)
    print(f"Focus extent (UTM m): x=[{focus_ext[0]:.0f}, {focus_ext[1]:.0f}]  "
          f"y=[{focus_ext[2]:.0f}, {focus_ext[3]:.0f}]  (±{BUFFER/1000:.0f} km buffer)")

    all_wd = glob.glob(str(V2_OUTPUT / "nbo_v2_wd_*.nc"))
    wd_files = sorted(
        [f for f in all_wd
         if re.search(r"nbo_v2_wd_\d+\.nc$", os.path.basename(f))],
        key=lambda p: int(re.search(r"nbo_v2_wd_(\d+)\.nc",
                                     os.path.basename(p)).group(1))
    )
    print(f"Found {len(wd_files)} water depth timestep files")

    if not wd_files:
        print("No output files found.")
        return

    if args.test:
        wd_files = [wd_files[len(wd_files) // 2]]
        print(f"TEST mode — rendering 1 frame: {os.path.basename(wd_files[0])}")

    frame_paths = []
    for i, wf in enumerate(wd_files):
        t_sec = int(re.search(r"nbo_v2_wd_(\d+)\.nc",
                               os.path.basename(wf)).group(1))
        wd, _, _ = load_nc(wf)
        out_path  = FRAMES_DIR / f"focused_{i:04d}_t{t_sec:06d}.png"
        plot_frame(wd, hillshade, x_arr, y_arr, damage_pos, focus_ext,
                   t_sec, out_path)
        frame_paths.append(str(out_path))
        clock = format_clock(t_sec)
        print(f"  [{i+1:02d}/{len(wd_files)}] {clock}  → {out_path.name}")

    if args.test:
        print(f"\nTest frame: {frame_paths[0]}")
        return

    # GIF
    try:
        from PIL import Image
        print("\nCreating GIF animation...")
        images = [Image.open(fp) for fp in sorted(frame_paths)]
        gif_path = VIS_DIR / "v2_flood_focused.gif"
        images[0].save(str(gif_path), save_all=True,
                       append_images=images[1:], duration=400, loop=0)
        gif_mb = gif_path.stat().st_size / (1024 * 1024)
        print(f"  GIF: {gif_path.name} ({gif_mb:.1f} MB, {len(images)} frames)")
    except ImportError:
        print("  Pillow not available, skipping GIF")

    print(f"\nDone. Output: {VIS_DIR}/")


if __name__ == "__main__":
    main()
