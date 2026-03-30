#!/usr/bin/env python3
"""
RIM2D v1 visualization — Addis Akaki River
==================================================
Produces: snapshots, GIF animation, max-depth map, time series.
True flood depth = max(0, WSE - original_terrain)

Usage:
    micromamba run -n zarrv3 python visualize_v1.py
"""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import netCDF4
from PIL import Image

CASE_DIR = Path(__file__).parent.parent
INPUT_DIR = CASE_DIR / "input"
OUT_DIR   = CASE_DIR / "output"
VIZ_DIR   = CASE_DIR / "analysis" / "visualizations"
VIZ_DIR.mkdir(parents=True, exist_ok=True)

DEPTH_MAX = 3.0
DPI = 130

EVENT_LABEL = "2021-08-16 to 2021-08-18"
REGION      = "Addis Akaki River"
COUNTRY     = "ETH"


def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = np.array(ds["x"][:], dtype=np.float64)
    y = np.array(ds["y"][:], dtype=np.float64)
    varname = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[varname][:], dtype=np.float64).squeeze()
    ds.close()
    data[data < -9000] = np.nan
    data[~np.isfinite(data)] = np.nan
    return data, x, y


def flood_cmap():
    colors = [
        (1.0, 1.0, 1.0, 0.0), (0.85, 0.93, 1.0, 0.3),
        (0.6, 0.8, 1.0, 0.5), (0.3, 0.6, 1.0, 0.7),
        (0.15, 0.35, 0.85, 0.85), (0.05, 0.14, 0.35, 1.0),
    ]
    depths = [0.0, 0.01, 0.10, 0.50, 1.5, 3.0]
    norm = [d / depths[-1] for d in depths]
    return mcolors.LinearSegmentedColormap.from_list(
        "flood3m", list(zip(norm, colors)), N=256)


def true_flood_depth(wd, dem_burned, dem_orig):
    wse = dem_burned + wd
    return np.where(np.isfinite(wse - dem_orig), np.maximum(wse - dem_orig, 0.0), 0.0)


def plot_max_depth(wd_max, dem_burned, dem_orig, x, y):
    print("Plotting max depth map ...")
    fd_max = true_flood_depth(wd_max, dem_burned, dem_orig)
    flooded_01 = int(np.sum(fd_max > 0.1))
    flooded_03 = int(np.sum(fd_max > 0.3))
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    extent = [float(x_km[0]), float(x_km[-1]), float(y_km[0]), float(y_km[-1])]
    FCMAP = flood_cmap()
    fig, ax = plt.subplots(figsize=(12, 9))
    fd_masked = np.ma.masked_where(fd_max < 0.05, fd_max)
    im = ax.imshow(fd_masked, origin="lower", extent=extent,
                   cmap=FCMAP, vmin=0, vmax=DEPTH_MAX,
                   interpolation="nearest", alpha=0.9)
    cb = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cb.set_label("Flood depth above orig. terrain (m)", fontsize=10)
    ax.set_title(
        f"{COUNTRY} — {REGION} | {EVENT_LABEL}\n"
        f"Peak flood depth | Cells >0.1m: {flooded_01:,} | Cells >0.3m: {flooded_03:,}",
        fontsize=10,
    )
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")
    fig.tight_layout()
    out = VIZ_DIR / "v1_max_depth_map.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out}")


if __name__ == "__main__":
    print(f"Visualizing RIM2D v1 — {REGION}")
    dem_burned, x, y = load_nc(INPUT_DIR / "dem_v1.nc")
    # dem_orig: load pre-conditioning DEM if available, else use burned
    try:
        dem_orig, _, _ = load_nc(INPUT_DIR / "dem_orig.nc")
    except Exception:
        dem_orig = dem_burned
    wd_max, _, _ = load_nc(OUT_DIR / "v1_wd_max.nc")
    plot_max_depth(wd_max, dem_burned, dem_orig, x, y)
    print(f"Outputs → {VIZ_DIR}")
