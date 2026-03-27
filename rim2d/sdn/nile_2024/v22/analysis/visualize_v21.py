#!/usr/bin/env python3
"""
v21 RIM2D output — animation + analysis
========================================
Produces:
  1. PNG snapshots for each 6-h timestep
  2. Animated GIF of flood progression
  3. Static max-depth map
  4. Time-series: flooded area, max depth, Nile exit depth, Hospital wadi depth

Usage:
    micromamba run -n zarrv3 python v21/analysis/visualize_v21.py
"""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import netCDF4
from PIL import Image

# ---------------------------------------------------------------------------
V21_INPUT = Path("/data/rim2d/nile_highres/v21/input")
OUT_DIR   = Path("/data/rim2d/nile_highres/v21/output")
VIZ_DIR   = Path("/data/rim2d/nile_highres/v21/analysis/visualizations")
VIZ_DIR.mkdir(parents=True, exist_ok=True)

KEY_SITES = [
    (212, 312, "Culvert1",    "D", "#e41a1c"),
    (222, 266, "Culvert2",    "D", "#377eb8"),
    (222, 175, "WesternWadi", "D", "#2ca02c"),
    (183, 281, "HospitalWadi","s", "#ff7f00"),
    (0,   354, "Nile Exit",   "v", "lime"),
]

NILE_ROW     = 0
NILE_COL     = 354
HOSPITAL_ROW = 183
HOSPITAL_COL = 281

DEPTH_MAX = 3.0
DPI = 130


# ---------------------------------------------------------------------------
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


def make_hillshade(dem, azimuth=315, altitude=45):
    az  = np.radians(azimuth)
    alt = np.radians(altitude)
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
        (0.05, 0.14, 0.35, 1.0),
    ]
    depths = [0.0, 0.01, 0.10, 0.50, 1.5, 3.0]
    norm = [d / depths[-1] for d in depths]
    return mcolors.LinearSegmentedColormap.from_list(
        "flood3m", list(zip(norm, colors)), N=256
    )

FCMAP = flood_cmap()


def make_extent_km(x, y):
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    extent = [float(x_km[0]), float(x_km[-1]),
              float(y_km[0]), float(y_km[-1])]
    return x_km, y_km, extent


def site_km(x, y):
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    return [(x_km[c], y_km[r], lbl, mk, col)
            for r, c, lbl, mk, col in KEY_SITES]


# ---------------------------------------------------------------------------
def plot_frame(ax, wd, hillshade, extent, sites_km, title):
    ax.clear()
    ax.imshow(hillshade, origin="lower", extent=extent,
              cmap="gray", vmin=0.3, vmax=1.0, alpha=0.6)
    wd_masked = np.ma.masked_where(wd < 0.05, wd)
    im = ax.imshow(wd_masked, origin="lower", extent=extent,
                   cmap=FCMAP, vmin=0, vmax=DEPTH_MAX,
                   interpolation="nearest", alpha=0.85)
    for xk, yk, lbl, mk, col in sites_km:
        ax.plot(xk, yk, mk, color=col, ms=9, mew=1.0, mec="black", zorder=10)
        ax.annotate(lbl, (xk, yk), textcoords="offset points",
                    xytext=(5, 5), fontsize=7, fontweight="bold", color=col,
                    path_effects=[pe.withStroke(linewidth=2, foreground="black")])
    n_wet = int(np.sum(wd > 0.1))
    ax.text(0.02, 0.02, f"Cells >0.1m: {n_wet:,}",
            transform=ax.transAxes, fontsize=7,
            color="white", bbox=dict(fc="black", alpha=0.5, pad=2))
    ax.set_title(title, fontsize=9, pad=4)
    ax.set_xlabel("x (km)", fontsize=8)
    ax.set_ylabel("y (km)", fontsize=8)
    ax.tick_params(labelsize=7)
    return im


# ---------------------------------------------------------------------------
def load_snapshots():
    files = sorted(
        OUT_DIR.glob("nile_v21_wd_*.nc"),
        key=lambda f: int(f.stem.split("_wd_")[1])
        if f.stem.split("_wd_")[1].isdigit() else -1,
    )
    snaps = []
    for f in files:
        sfx = f.stem.split("_wd_")[1]
        if not sfx.isdigit():
            continue
        wd, _, _ = load_nc(f)
        snaps.append((int(sfx), wd))
    return snaps


# ---------------------------------------------------------------------------
def plot_snapshots(snaps, hillshade, extent, sites_km):
    print("Plotting snapshots ...")
    for t, wd in snaps:
        hours = t // 3600
        day   = hours // 24
        hr    = hours % 24
        title = f"v21 — Aug {25+day} {hr:02d}:00 UTC  ({hours}h)"
        fig, ax = plt.subplots(figsize=(12, 8))
        im = plot_frame(ax, wd, hillshade, extent, sites_km, title)
        cb = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
        cb.set_label("Water depth (m)", fontsize=9)
        fig.tight_layout()
        fig.savefig(VIZ_DIR / f"v21_wd_{t:07d}.png", dpi=DPI,
                    bbox_inches="tight", facecolor="white")
        plt.close(fig)
    print(f"  Saved {len(snaps)} PNGs to {VIZ_DIR}")


# ---------------------------------------------------------------------------
def make_animation(snaps):
    print("Building GIF animation ...")
    images = []
    for t, _ in snaps:
        fp = VIZ_DIR / f"v21_wd_{t:07d}.png"
        if fp.exists():
            images.append(Image.open(str(fp)))
    if not images:
        print("  No frames found — run plot_snapshots first")
        return
    gif_path = VIZ_DIR / "v21_flood_animation.gif"
    images[0].save(gif_path, save_all=True, append_images=images[1:],
                   duration=400, loop=0)
    print(f"  Animation saved: {gif_path}")


# ---------------------------------------------------------------------------
def plot_max_depth(wd_max, hillshade, extent, sites_km):
    print("Plotting max depth map ...")
    flooded_01 = int(np.sum(wd_max > 0.1))
    flooded_03 = int(np.sum(wd_max > 0.3))

    fig, ax = plt.subplots(figsize=(14, 10))
    ax.imshow(hillshade, origin="lower", extent=extent,
              cmap="gray", vmin=0.3, vmax=1.0, alpha=0.6)
    wd_masked = np.ma.masked_where(wd_max < 0.05, wd_max)
    im = ax.imshow(wd_masked, origin="lower", extent=extent,
                   cmap=FCMAP, vmin=0, vmax=DEPTH_MAX,
                   interpolation="nearest", alpha=0.85)
    cb = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cb.set_label("Max water depth (m)", fontsize=11)

    for xk, yk, lbl, mk, col in sites_km:
        r, c = [(s[0], s[1]) for s in KEY_SITES if s[2] == lbl][0]
        depth = wd_max[r, c]
        ax.plot(xk, yk, mk, color=col, ms=12, mew=1.2, mec="black", zorder=10)
        ax.annotate(
            f"{lbl}\n{depth:.2f}m",
            (xk, yk), textcoords="offset points", xytext=(6, 6),
            fontsize=8, fontweight="bold", color=col,
            path_effects=[pe.withStroke(linewidth=2.5, foreground="black")],
        )

    ax.set_title(
        f"v21 — Peak flood depth | Abu Hamad, Aug 25–31 2024\n"
        f"Depression-filled DEM + stream burns + culvert | "
        f"Cells >0.1m: {flooded_01:,}  |  Cells >0.3m: {flooded_03:,}",
        fontsize=10,
    )
    ax.set_xlabel("x (km)", fontsize=10)
    ax.set_ylabel("y (km)", fontsize=10)
    fig.tight_layout()
    out = VIZ_DIR / "v21_max_depth_map.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out}")


# ---------------------------------------------------------------------------
def plot_timeseries(snaps):
    print("Plotting time series ...")
    times_h, flooded, max_depth, nile_exit, hosp_wadi = [], [], [], [], []
    for t, wd in snaps:
        times_h.append(t / 3600)
        flooded.append(int(np.sum(wd > 0.1)))
        max_depth.append(float(np.nanmax(wd)))
        nile_exit.append(float(wd[NILE_ROW, NILE_COL]))
        hosp_wadi.append(float(wd[HOSPITAL_ROW, HOSPITAL_COL]))

    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)

    axes[0].plot(times_h, flooded, "b-o", ms=4, lw=1.5)
    axes[0].set_ylabel("Cells >0.1m flooded", fontsize=9)
    axes[0].grid(True, alpha=0.3)
    axes[0].set_title("v21 — Flood evolution (Aug 25–31 2024)", fontsize=10)

    axes[1].plot(times_h, max_depth, "r-o", ms=4, lw=1.5, label="Domain max")
    axes[1].plot(times_h, hosp_wadi, "m--s", ms=5, lw=1.2, label="HospitalWadi")
    axes[1].axhline(1.0, color="gray", lw=0.8, ls=":")
    axes[1].set_ylabel("Water depth (m)", fontsize=9)
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(times_h, nile_exit, "g-o", ms=4, lw=1.5,
                 label="Nile exit (row=0, col=354)")
    axes[2].set_ylabel("Nile exit depth (m)", fontsize=9)
    axes[2].set_xlabel("Hours from Aug 25 00:00 UTC", fontsize=9)
    axes[2].legend(fontsize=8)
    axes[2].grid(True, alpha=0.3)

    for ax in axes:
        ax.axvspan(24, 60, alpha=0.08, color="orange", label="Peak rainfall")

    fig.tight_layout()
    out = VIZ_DIR / "v21_timeseries.png"
    fig.savefig(out, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out}")


# ---------------------------------------------------------------------------
def print_analysis(wd_max, snaps):
    print("\n" + "=" * 60)
    print("v21 ANALYSIS SUMMARY")
    print("=" * 60)
    print(f"Domain:              {wd_max.shape[0]} rows × {wd_max.shape[1]} cols")
    print(f"Max depth (domain):  {np.nanmax(wd_max):.2f} m")
    print(f"Cells >0.1m:         {int(np.sum(wd_max > 0.1)):,}")
    print(f"Cells >0.3m:         {int(np.sum(wd_max > 0.3)):,}")
    print(f"Cells >1.0m:         {int(np.sum(wd_max > 1.0)):,}")
    print(f"Timesteps output:    {len(snaps)}")
    print()
    print("Key site max depths:")
    for r, c, lbl, _, _ in KEY_SITES:
        print(f"  {lbl:<18} row={r:3d}, col={c:3d}  → {wd_max[r, c]:.2f} m")
    print("=" * 60)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Loading DEM ...")
    dem, x_ref, y_ref = load_nc(V21_INPUT / "dem_v21.nc")
    hillshade = make_hillshade(dem)
    x_km, y_km, extent = make_extent_km(x_ref, y_ref)
    sites_km = site_km(x_ref, y_ref)

    print("Loading v21 output ...")
    wd_max, _, _ = load_nc(OUT_DIR / "nile_v21_wd_max.nc")
    snaps = load_snapshots()
    print(f"  {len(snaps)} timesteps found")

    print_analysis(wd_max, snaps)
    plot_snapshots(snaps, hillshade, extent, sites_km)
    make_animation(snaps)
    plot_max_depth(wd_max, hillshade, extent, sites_km)
    plot_timeseries(snaps)

    print(f"\nAll outputs → {VIZ_DIR}")
