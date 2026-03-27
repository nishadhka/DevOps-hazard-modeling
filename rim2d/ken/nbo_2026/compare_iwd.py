#!/usr/bin/env python3
"""
IWD comparison: v1, v3, v5.

  v1 — stream-burn from MERIT HND drainage mask (uniform 3m)
  v3 — ESA WorldCover class-80 channel mask (uniform 3m)
  v5 — TDX-Hydro river network, width/depth by stream order (0.5–2.5m)

Panels:
  Row 1 — IWD maps side-by-side on hillshade
  Row 2 — Difference maps: (v5 - v1), (v5 - v3), union wet extent
  Bottom — Bar chart: wet cell counts + depth distributions

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python compare_iwd.py
"""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import netCDF4
import numpy as np

# ---------------------------------------------------------------------------
WORK_DIR = Path(__file__).resolve().parent
DEM_PATH = WORK_DIR / "v1" / "input" / "dem.nc"

VERSIONS = {
    "v1": {
        "path":  WORK_DIR / "v1" / "input" / "iwd.nc",
        "label": "v1 — MERIT HND drainage mask\n(uniform 3m burn)",
        "color": "#e17055",
    },
    "v3": {
        "path":  WORK_DIR / "v3" / "input" / "iwd.nc",
        "label": "v3 — ESA WorldCover class-80\n(uniform 3m burn)",
        "color": "#fdcb6e",
    },
    "v5": {
        "path":  WORK_DIR / "v5" / "input" / "iwd.nc",
        "label": "v5 — TDX-Hydro stream order\n(0.5–2.5m by order)",
        "color": "#0984e3",
    },
}

VIS_DIR = WORK_DIR / "visualizations"
DPI = 150

# ---------------------------------------------------------------------------

def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    var = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[var][:], dtype=np.float32)
    ds.close()
    data[data < -9000] = np.nan
    return data, x, y


def make_hillshade(dem, azimuth=315, altitude=45):
    az  = np.radians(azimuth)
    alt = np.radians(altitude)
    dy, dx = np.gradient(np.nan_to_num(dem, nan=0))
    slope  = np.pi / 2.0 - np.arctan(np.sqrt(dx**2 + dy**2))
    aspect = np.arctan2(-dy, dx)
    return (np.sin(alt) * np.sin(slope)
            + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))


def iwd_cmap():
    colors = [
        (1.0, 1.0, 1.0, 0.0),
        (0.68, 0.85, 1.0, 0.4),
        (0.28, 0.60, 1.0, 0.7),
        (0.10, 0.25, 0.80, 0.9),
        (0.05, 0.05, 0.50, 1.0),
    ]
    return mcolors.LinearSegmentedColormap.from_list("iwd", colors, N=256)


# ---------------------------------------------------------------------------

def main():
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading DEM...")
    dem, x, y = load_nc(DEM_PATH)
    hs = make_hillshade(dem)
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    ext  = [float(x_km[0]), float(x_km[-1]),
            float(y_km[0]), float(y_km[-1])]

    print("Loading IWD files...")
    data = {}
    for key, meta in VERSIONS.items():
        iwd, _, _ = load_nc(meta["path"])
        iwd[~np.isfinite(iwd)] = 0.0
        data[key] = iwd
        wet = iwd > 0
        print(f"  {key}: wet={wet.sum():,}  "
              f"mean={iwd[wet].mean():.2f}m  max={iwd[wet].max():.2f}m")

    cmap_iwd = iwd_cmap()
    cmap_diff = plt.cm.RdBu_r

    fig = plt.figure(figsize=(20, 18))
    gs  = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.08)

    # -----------------------------------------------------------------------
    # Row 1 — IWD maps
    # -----------------------------------------------------------------------
    vmax_iwd = 3.5
    for col, (key, meta) in enumerate(VERSIONS.items()):
        ax = fig.add_subplot(gs[0, col])
        ax.imshow(hs, origin="lower", extent=ext,
                  cmap="gray", vmin=0.3, vmax=1.0, alpha=0.55)
        iwd_m = np.ma.masked_where(data[key] <= 0, data[key])
        im = ax.imshow(iwd_m, origin="lower", extent=ext,
                       cmap=cmap_iwd, vmin=0, vmax=vmax_iwd,
                       interpolation="nearest", alpha=0.88, zorder=5)
        wet = data[key] > 0
        ax.set_title(f"{meta['label']}\n"
                     f"Wet: {wet.sum():,} cells  "
                     f"Mean: {data[key][wet].mean():.2f}m  "
                     f"Max: {data[key][wet].max():.2f}m",
                     fontsize=10, fontweight="bold")
        ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
        if col == 2:
            fig.colorbar(im, ax=ax, shrink=0.8, label="IWD (m)")

    # -----------------------------------------------------------------------
    # Row 2 — Difference maps
    # -----------------------------------------------------------------------
    diff_pairs = [
        ("v5 − v1", data["v5"] - data["v1"]),
        ("v5 − v3", data["v5"] - data["v3"]),
    ]
    vmax_diff = 3.0
    for col, (title, diff) in enumerate(diff_pairs):
        ax = fig.add_subplot(gs[1, col])
        ax.imshow(hs, origin="lower", extent=ext,
                  cmap="gray", vmin=0.3, vmax=1.0, alpha=0.45)
        diff_m = np.ma.masked_where(
            (data["v5"] == 0) & (diff == 0), diff
        )
        im2 = ax.imshow(diff_m, origin="lower", extent=ext,
                        cmap=cmap_diff, vmin=-vmax_diff, vmax=vmax_diff,
                        interpolation="nearest", alpha=0.85, zorder=5)
        n_pos = int((diff > 0.01).sum())
        n_neg = int((diff < -0.01).sum())
        ax.set_title(f"{title}\n"
                     f"v5 deeper: {n_pos:,}  |  v5 shallower: {n_neg:,}",
                     fontsize=10, fontweight="bold")
        ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
        fig.colorbar(im2, ax=ax, shrink=0.8, label="ΔIWD (m)")

    # Union wet extent panel
    ax = fig.add_subplot(gs[1, 2])
    ax.imshow(hs, origin="lower", extent=ext,
              cmap="gray", vmin=0.3, vmax=1.0, alpha=0.55)
    union  = (data["v1"] > 0) | (data["v3"] > 0) | (data["v5"] > 0)
    only_v5 = (data["v5"] > 0) & ~((data["v1"] > 0) | (data["v3"] > 0))
    shared  = (data["v1"] > 0) & (data["v3"] > 0) & (data["v5"] > 0)
    v1v3_only = (data["v1"] > 0) & (data["v3"] > 0) & ~(data["v5"] > 0)

    colors_map = np.zeros((*dem.shape, 4), dtype=np.float32)
    # v1/v3 only — red
    colors_map[v1v3_only] = [0.85, 0.2, 0.1, 0.75]
    # v5 only — blue
    colors_map[only_v5]   = [0.1, 0.5, 0.9, 0.75]
    # all shared — green
    colors_map[shared]    = [0.1, 0.7, 0.3, 0.75]
    ax.imshow(colors_map, origin="lower", extent=ext, zorder=5)
    handles = [
        mpatches.Patch(color="#d63031", alpha=0.75,
                       label=f"v1+v3 only ({v1v3_only.sum():,})"),
        mpatches.Patch(color="#0984e3", alpha=0.75,
                       label=f"v5 only ({only_v5.sum():,})"),
        mpatches.Patch(color="#00b894", alpha=0.75,
                       label=f"All agree ({shared.sum():,})"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.9)
    ax.set_title(f"Wet extent agreement\nUnion: {union.sum():,} cells",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))

    # -----------------------------------------------------------------------
    # Row 3 — Statistics: bar chart + depth histograms
    # -----------------------------------------------------------------------
    ax_bar = fig.add_subplot(gs[2, 0])
    keys   = list(VERSIONS.keys())
    counts = [int((data[k] > 0).sum()) for k in keys]
    colors = [VERSIONS[k]["color"] for k in keys]
    bars   = ax_bar.bar(keys, counts, color=colors, edgecolor="white", width=0.5)
    for bar, cnt in zip(bars, counts):
        ax_bar.text(bar.get_x() + bar.get_width() / 2,
                    cnt + 200, f"{cnt:,}", ha="center", va="bottom", fontsize=9)
    ax_bar.set_ylabel("Wet cells (IWD > 0)")
    ax_bar.set_title("Wet cell count by version", fontsize=10, fontweight="bold")
    ax_bar.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}k"))

    ax_hist = fig.add_subplot(gs[2, 1:])
    for key, meta in VERSIONS.items():
        iwd = data[key]
        vals = iwd[iwd > 0].flatten()
        ax_hist.hist(vals, bins=40, alpha=0.6, color=meta["color"],
                     label=f"{key} (n={len(vals):,}, μ={vals.mean():.2f}m)",
                     density=True)
    ax_hist.set_xlabel("Initial Water Depth (m)")
    ax_hist.set_ylabel("Density")
    ax_hist.set_title("IWD depth distribution (wet cells only)",
                      fontsize=10, fontweight="bold")
    ax_hist.legend(fontsize=9, framealpha=0.9)

    # -----------------------------------------------------------------------
    fig.suptitle(
        "Nairobi IWD Comparison — v1 vs v3 vs v5\n"
        "v1: MERIT HND  ·  v3: WorldCover mask  ·  v5: TDX-Hydro stream order",
        fontsize=13, fontweight="bold"
    )

    out = VIS_DIR / "iwd_comparison_v1_v3_v5.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
