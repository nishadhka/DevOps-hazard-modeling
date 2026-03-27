#!/usr/bin/env python3
"""
v2 Nairobi Event Flood — Animation.

Renders one PNG per timestep: flood depth on DEM hillshade,
buildings.nc raster overlay, damage-location markers, event clock.
Stitches all frames into v2/visualizations/v2_flood_animation.gif.

Usage:
    cd /data/rim2d/nbo_2026
    # test single frame:
    micromamba run -n zarrv3 python visualize_v2_animation.py --test
    # full animation:
    micromamba run -n zarrv3 python visualize_v2_animation.py
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
V2_OUTPUT  = WORK_DIR / "v2" / "output"
VIS_DIR    = WORK_DIR / "v2" / "visualizations"
FRAMES_DIR = VIS_DIR / "frames"

DEM_PATH       = V1_INPUT / "dem.nc"
BUILDINGS_PATH = V1_INPUT / "buildings.nc"

EVENT_START = "2026-03-06 16:00 UTC"
VMAX        = 4.0   # m
DPI         = 120

DAMAGE_LOCS = [
    {"name": "Car wash reported",  "lon": 36.8207720971431, "lat": -1.31125324510586},
    {"name": "Kirinyaga Rd\nflooding",   "lon": 36.8429, "lat": -1.2841},
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


def format_elapsed(t_sec):
    h = t_sec // 3600
    m = (t_sec % 3600) // 60
    return f"+{int(h):02d}h{int(m):02d}m"


# ---------------------------------------------------------------------------

def plot_frame(wd, buildings, hillshade, x_arr, y_arr, damage_pos,
               t_sec, out_path):
    """Render one animation frame using native UTM metre axes."""
    # Clamp extreme values (boundary artefacts)
    wd = np.where(wd > 20, np.nan, wd)

    bldg = buildings > 0
    wet  = wd > 0.01
    n_wet      = int(np.sum(wet))
    n_bldg_wet = int(np.sum(wet & bldg))
    max_d      = float(np.nanmax(wd)) if n_wet > 0 else 0.0
    pct        = 100.0 * n_wet / wd.size

    # Extent in metres (native UTM)
    ext = [float(x_arr[0]), float(x_arr[-1]),
           float(y_arr[0]), float(y_arr[-1])]

    fig, ax = plt.subplots(figsize=(14, 9))

    ax.imshow(hillshade, origin="lower", extent=ext,
              cmap="gray", vmin=0.3, vmax=1.0, alpha=0.55)

    wd_m = np.ma.masked_where(wd < 0.01, wd)
    im = ax.imshow(wd_m, origin="lower", extent=ext,
                   cmap=flood_cmap(), vmin=0, vmax=VMAX,
                   interpolation="nearest", alpha=0.85, zorder=5)

    # Buildings raster — binary mask contour
    if np.any(bldg):
        ax.contour(bldg.astype(np.float32), levels=[0.5],
                   origin="lower", extent=ext,
                   colors=["#ff8800"], linewidths=0.6, alpha=0.7, zorder=7)

    # Damage markers — thin yellow open circle + label
    for utmx, utmy, name in damage_pos:
        ax.plot(utmx, utmy, "o", color="none", markersize=16,
                markeredgecolor="yellow", markeredgewidth=1.8, zorder=12)
        ax.annotate(name, (utmx, utmy),
                    textcoords="offset points", xytext=(10, 6),
                    fontsize=8, fontweight="bold", color="yellow",
                    bbox=dict(boxstyle="round,pad=0.2",
                              fc="#333333", ec="yellow", alpha=0.85))

    cbar = fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02)
    cbar.set_label("Water Depth (m)", fontsize=10)

    handles = [
        mpatches.Patch(facecolor="none", edgecolor="#ff8800",
                       linewidth=1.0, label=f"Buildings (wet: {n_bldg_wet:,})"),
        plt.Line2D([0], [0], marker="o", color="w",
                   markerfacecolor="none", markeredgecolor="yellow",
                   markeredgewidth=1.8, markersize=11, label="Damage site"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=9,
              framealpha=0.9, edgecolor="gray")

    elapsed = format_elapsed(t_sec)
    ax.set_title(
        f"Nairobi Flash Flood — {EVENT_START}  {elapsed}\n"
        f"Flooded >1cm: {n_wet:,} cells ({pct:.1f}%)  |  "
        f"Max depth: {max_d:.2f} m  |  Buildings inundated: {n_bldg_wet:,}",
        fontsize=11, fontweight="bold"
    )
    # Tick labels in km for readability
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}"))
    ax.set_xlabel("Easting (km, UTM 37S)")
    ax.set_ylabel("Northing (km, UTM 37S)")

    # Keep axes tight to simulation domain
    ax.set_xlim(ext[0], ext[1])
    ax.set_ylim(ext[2], ext[3])

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

    print("Loading DEM and buildings rasters...")
    dem, x_arr, y_arr = load_nc(DEM_PATH)
    buildings, _, _   = load_nc(BUILDINGS_PATH)
    buildings = np.flipud(buildings)   # RIM2D output is y-flipped vs input
    hillshade  = make_hillshade(dem)

    # Damage positions in UTM metres
    damage_pos = []
    for d in DAMAGE_LOCS:
        utmx, utmy = latlon_to_utm(d["lon"], d["lat"])
        damage_pos.append((utmx, utmy, d["name"]))

    # Collect and sort output files
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
        out_path  = FRAMES_DIR / f"frame_{i:04d}_t{t_sec:06d}.png"
        plot_frame(wd, buildings, hillshade, x_arr, y_arr,
                   damage_pos, t_sec, out_path)
        frame_paths.append(str(out_path))
        elapsed = format_elapsed(t_sec)
        print(f"  [{i+1:02d}/{len(wd_files)}] {elapsed}  → {out_path.name}")

    if args.test:
        print(f"\nTest frame: {frame_paths[0]}")
        return

    # GIF
    try:
        from PIL import Image
        print("\nCreating GIF animation...")
        images = [Image.open(fp) for fp in sorted(frame_paths)]
        gif_path = VIS_DIR / "v2_flood_animation.gif"
        images[0].save(str(gif_path), save_all=True,
                       append_images=images[1:], duration=400, loop=0)
        gif_mb = gif_path.stat().st_size / (1024 * 1024)
        print(f"  GIF: {gif_path.name} ({gif_mb:.1f} MB, {len(images)} frames)")
    except ImportError:
        print("  Pillow not available, skipping GIF")

    print(f"\nDone. Output: {VIS_DIR}/")


if __name__ == "__main__":
    main()
