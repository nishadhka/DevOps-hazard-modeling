#!/usr/bin/env python3
"""
v7 Analysis Visualizations — Overflow and Pluvial Pathway Analysis.

Generates:
  1. v7_overflow_analysis.png — Bank height, freeboard, cross-sections
  2. v7_pluvial_analysis.png — Wadi networks through buildings, rainfall

Usage:
    micromamba run -n zarrv3 python visualize_v7_analysis.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import netCDF4
import numpy as np
from scipy.ndimage import binary_dilation

INPUT_DIR = Path("input")
OUT_DIR = Path("visualizations/v7_run")
BURN_DEPTH = 3.0


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


def plot_overflow_analysis(out_path):
    """Bank height, freeboard, cross-sections, and required FLOOD_RISE."""
    dem_burned, x, y = load_nc(INPUT_DIR / "dem.nc")
    channel, _, _ = load_nc(INPUT_DIR / "channel_mask.nc")
    buildings, _, _ = load_nc(INPUT_DIR / "buildings.nc")
    iwd, _, _ = load_nc(INPUT_DIR / "iwd.nc")

    original_dem = dem_burned.copy()
    ch = channel > 0
    original_dem[ch] += BURN_DEPTH

    bldg = buildings > 0
    nrows, ncols = dem_burned.shape
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    extent = [x_km[0], x_km[-1], y_km[0], y_km[-1]]

    mean_wse = np.nanmean(dem_burned[ch] + iwd[ch])

    fig, axes = plt.subplots(3, 2, figsize=(20, 18))

    # Panel 1: E-W cross-section at mid row
    mid_row = nrows // 2
    dem_xs = original_dem[mid_row, :]
    burned_xs = dem_burned[mid_row, :]
    ch_xs = ch[mid_row, :]
    bldg_xs = bldg[mid_row, :]
    wse_xs = np.where(ch_xs, burned_xs + BURN_DEPTH, np.nan)
    wse_flood = np.where(ch_xs, burned_xs + BURN_DEPTH + 2.0, np.nan)

    ax = axes[0, 0]
    ax.fill_between(x_km, dem_xs, color="sienna", alpha=0.4, label="Original DEM")
    ax.plot(x_km, dem_xs, "k-", lw=0.5)
    ax.plot(x_km, burned_xs, "r-", lw=0.8, label="Burned DEM")
    if np.any(ch_xs):
        ax.fill_between(x_km, burned_xs, wse_xs, where=ch_xs,
                         color="dodgerblue", alpha=0.7, label="IWD (3m)")
        ax.plot(x_km, wse_flood, "b--", lw=1.5, label="Flood peak (+2m rise)")
    ax.scatter(x_km[bldg_xs], dem_xs[bldg_xs], c="red", s=5, zorder=5,
               label="Buildings")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("Elevation (m ASL)")
    ax.set_title(f"E-W Cross-section at row {mid_row} (y={y_km[mid_row]:.2f} km)")
    ax.legend(fontsize=8)

    # Panel 2: Cross-section at 3/4 row (further north)
    row_34 = int(nrows * 0.75)
    dem_xs2 = original_dem[row_34, :]
    burned_xs2 = dem_burned[row_34, :]
    ch_xs2 = ch[row_34, :]
    bldg_xs2 = bldg[row_34, :]
    wse_xs2 = np.where(ch_xs2, burned_xs2 + BURN_DEPTH, np.nan)

    ax = axes[0, 1]
    ax.fill_between(x_km, dem_xs2, color="sienna", alpha=0.4, label="Original DEM")
    ax.plot(x_km, dem_xs2, "k-", lw=0.5)
    ax.plot(x_km, burned_xs2, "r-", lw=0.8, label="Burned DEM")
    if np.any(ch_xs2):
        ax.fill_between(x_km, burned_xs2, wse_xs2, where=ch_xs2,
                         color="dodgerblue", alpha=0.7, label="IWD (3m)")
    ax.scatter(x_km[bldg_xs2], dem_xs2[bldg_xs2], c="red", s=5, zorder=5,
               label="Buildings")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("Elevation (m ASL)")
    ax.set_title(f"E-W Cross-section at row {row_34} (y={y_km[row_34]:.2f} km)")
    ax.legend(fontsize=8)

    # Panel 3: Map of DEM + channel + buildings
    ax = axes[1, 0]
    valid = original_dem[np.isfinite(original_dem)]
    im = ax.imshow(original_dem, origin="lower", extent=extent, cmap="terrain",
                   vmin=np.nanpercentile(valid, 2),
                   vmax=np.nanpercentile(valid, 98))
    ch_plot = np.where(ch, 1.0, np.nan)
    ax.imshow(ch_plot, origin="lower", extent=extent, cmap="Blues",
              alpha=0.6, vmin=0, vmax=1)
    bldg_plot = np.where(bldg, 1.0, np.nan)
    ax.imshow(bldg_plot, origin="lower", extent=extent, cmap="Reds",
              alpha=0.5, vmin=0, vmax=1)
    ax.set_title("DEM + Channel (blue) + Buildings (red)")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Elevation (m ASL)")

    # Panel 4: Freeboard map
    freeboard = original_dem - mean_wse
    ax = axes[1, 1]
    im = ax.imshow(freeboard, origin="lower", extent=extent, cmap="RdYlGn",
                   vmin=-5, vmax=25)
    ax.imshow(ch_plot, origin="lower", extent=extent, cmap="Blues",
              alpha=0.4, vmin=0, vmax=1)
    ax.imshow(bldg_plot, origin="lower", extent=extent, cmap="Reds",
              alpha=0.3, vmin=0, vmax=1)
    ax.set_title(f"Freeboard above mean WSE ({mean_wse:.1f}m ASL)\n"
                 f"Channel=blue, Buildings=red")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    fig.colorbar(im, ax=ax, shrink=0.8, label="Freeboard (m)")

    # Panel 5: Building freeboard histogram
    bldg_fb = original_dem[bldg] - mean_wse
    ax = axes[2, 0]
    ax.hist(bldg_fb[np.isfinite(bldg_fb)], bins=60, color="firebrick",
            edgecolor="white", lw=0.3)
    ax.axvline(0, color="blue", lw=2, ls="--",
               label=f"Mean WSE = {mean_wse:.1f}m ASL")
    ax.set_xlabel("Building freeboard above WSE (m)")
    ax.set_ylabel("Count")
    ax.set_title(f"Building freeboard distribution\n"
                 f"Median={np.nanmedian(bldg_fb):.1f}m, "
                 f"need FLOOD_RISE > freeboard")
    ax.legend()

    # Panel 6: Required FLOOD_RISE curve
    ax = axes[2, 1]
    pcts = np.arange(0, 101, 1)
    fb_pcts = np.nanpercentile(bldg_fb, pcts)
    for target_ft, color in [(1, "green"), (3, "orange"), (6, "red")]:
        target_m = target_ft * 0.3048
        rise_needed = fb_pcts + target_m
        ax.plot(pcts, rise_needed, color=color, lw=2,
                label=f"{target_ft}ft ({target_m:.1f}m) depth")
    ax.axhline(2.0, color="gray", ls=":", label="Current FLOOD_RISE=2m")
    ax.axhline(5.0, color="gray", ls="--", alpha=0.5, label="Moderate flood (5m)")
    ax.axhline(10.0, color="gray", ls="--", alpha=0.3, label="Extreme flood (10m)")
    ax.set_xlabel("Percent of buildings flooded")
    ax.set_ylabel("Required FLOOD_RISE (m)")
    ax.set_title("FLOOD_RISE needed vs % buildings inundated")
    ax.legend(fontsize=8)
    ax.set_ylim(-5, 30)
    ax.grid(True, alpha=0.3)

    fig.suptitle("v7 Bank Height & Overflow Analysis — Abu Hamad, Nile",
                 fontsize=16, fontweight="bold")
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path.name}")


def plot_pluvial_analysis(out_path):
    """Wadi networks through buildings and rainfall intensity."""
    dem, x, y = load_nc(INPUT_DIR / "dem.nc")
    channel, _, _ = load_nc(INPUT_DIR / "channel_mask.nc")
    buildings, _, _ = load_nc(INPUT_DIR / "buildings.nc")
    hnd, _, _ = load_nc(INPUT_DIR / "hnd_30m.nc")
    flwacc, _, _ = load_nc(INPUT_DIR / "flwacc_30m.nc")

    ch = channel > 0
    bldg = buildings > 0
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    extent = [x_km[0], x_km[-1], y_km[0], y_km[-1]]

    ch_plot = np.where(ch, 1.0, np.nan)
    bldg_plot = np.where(bldg, 1.0, np.nan)

    fig, axes = plt.subplots(2, 2, figsize=(18, 14))

    # Panel 1: Flow accumulation + buildings + channel
    ax = axes[0, 0]
    flwacc_log = np.log10(np.maximum(np.nan_to_num(flwacc, nan=0), 1))
    im = ax.imshow(flwacc_log, origin="lower", extent=extent, cmap="hot_r",
                   vmin=0, vmax=4.5)
    ax.imshow(bldg_plot, origin="lower", extent=extent, cmap="Greens",
              alpha=0.5, vmin=0, vmax=1)
    ax.imshow(ch_plot, origin="lower", extent=extent, cmap="Blues",
              alpha=0.3, vmin=0, vmax=1)
    ax.set_title("Flow accumulation (log10) + Buildings (green) + "
                 "Channel (blue)\nWadi networks pass through settlement areas")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    fig.colorbar(im, ax=ax, shrink=0.8, label="log10(upstream cells)")

    # Panel 2: Wadi cells at different thresholds
    ax = axes[0, 1]
    valid = dem[np.isfinite(dem)]
    ax.imshow(dem, origin="lower", extent=extent, cmap="terrain",
              vmin=np.nanpercentile(valid, 2),
              vmax=np.nanpercentile(valid, 98), alpha=0.6)
    wadi_50 = (flwacc >= 50) & (~ch)
    wadi_500 = (flwacc >= 500) & (~ch)
    w50_plot = np.where(wadi_50, 1.0, np.nan)
    w500_plot = np.where(wadi_500, 1.0, np.nan)
    ax.imshow(w50_plot, origin="lower", extent=extent, cmap="Purples",
              alpha=0.4, vmin=0, vmax=1)
    ax.imshow(w500_plot, origin="lower", extent=extent, cmap="Reds",
              alpha=0.7, vmin=0, vmax=1)
    ax.imshow(bldg_plot, origin="lower", extent=extent, cmap="Greens",
              alpha=0.4, vmin=0, vmax=1)
    ax.imshow(ch_plot, origin="lower", extent=extent, cmap="Blues",
              alpha=0.3, vmin=0, vmax=1)
    ax.set_title("Wadi networks: purple=acc>=50, red=acc>=500\n"
                 "Green=buildings, Blue=channel")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")

    # Panel 3: HND at wadi + building cells
    ax = axes[1, 0]
    hnd_bldg = np.where(bldg | wadi_50, hnd, np.nan)
    im = ax.imshow(hnd_bldg, origin="lower", extent=extent, cmap="YlGnBu_r",
                   vmin=0, vmax=5)
    ax.set_title("HND at wadi + building cells\n"
                 "Low HND = natural drainage paths through settlement")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    fig.colorbar(im, ax=ax, shrink=0.8, label="HND (m)")

    # Panel 4: Rainfall time series (original + amplified)
    rain_vals = []
    for t in range(1, 337):
        rain_path = INPUT_DIR / "rain" / f"nile_highres_t{t}.nc"
        if not rain_path.exists():
            rain_vals.append(0.0)
            continue
        ds = netCDF4.Dataset(str(rain_path))
        v = ds["Band1"][ds["Band1"].shape[0] // 2, ds["Band1"].shape[1] // 2]
        ds.close()
        v = float(v)
        if v < -9000 or not np.isfinite(v):
            v = 0.0
        rain_vals.append(v)
    rain_arr = np.array(rain_vals)
    times_h = np.arange(1, 337) * 0.5

    ax = axes[1, 1]
    ax.bar(times_h, rain_arr, width=0.45, color="steelblue", alpha=0.7,
           label="Current GPM (real)")
    ax.bar(times_h, rain_arr * 20, width=0.45, color="red", alpha=0.4,
           label="20x amplified (extreme)")
    ax.set_xlabel("Time (hours)")
    ax.set_ylabel("Rainfall (mm/h)")
    total_orig = rain_arr.sum() * 0.5
    total_amp = total_orig * 20
    ax.set_title(f"Rainfall: current total={total_orig:.1f}mm "
                 f"(too low for flash flood)\n"
                 f"20x amplified total={total_amp:.0f}mm — "
                 f"realistic extreme event")
    ax.legend()
    ax.set_xlim(0, 170)

    fig.suptitle("v7 Pluvial Flooding Analysis — Wadi Networks Through Buildings",
                 fontsize=16, fontweight="bold")
    fig.tight_layout()
    fig.savefig(str(out_path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  {out_path.name}")


def main():
    import os
    os.chdir(Path(__file__).parent)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating v7 analysis plots...\n")

    print("Overflow analysis:")
    plot_overflow_analysis(OUT_DIR / "v7_overflow_analysis.png")

    print("\nPluvial analysis:")
    plot_pluvial_analysis(OUT_DIR / "v7_pluvial_analysis.png")

    print(f"\nAll analysis plots saved to {OUT_DIR}/")


if __name__ == "__main__":
    main()
