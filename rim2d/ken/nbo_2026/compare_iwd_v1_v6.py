#!/usr/bin/env python3
"""
IWD comparison: v1, v6-geometric, v6-steady-state.

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python compare_iwd_v1_v6.py
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import netCDF4
import numpy as np

WORK_DIR = Path(__file__).resolve().parent
DEM_PATH = WORK_DIR / "v1" / "input" / "dem.nc"

VERSIONS = [
    ("v1",      WORK_DIR / "v1"  / "input" / "iwd.nc",
     "v1 — MERIT HND\n(uniform 3m burn)", "#e17055"),
    ("v6 geom", WORK_DIR / "v6"  / "input" / "iwd_geometric.nc",
     "v6 geometric\n(TDX + HND gap-fill)", "#6c5ce7"),
    ("v6 SS",   WORK_DIR / "v6"  / "input" / "iwd_ss.nc",
     "v6 steady-state\n(12h equilibrated)", "#0984e3"),
]

VIS_DIR = WORK_DIR / "visualizations"
DPI = 150

def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    var = [v for v in ds.variables if v not in ("x","y")][0]
    d = np.array(ds[var][:], dtype=np.float32)
    ds.close()
    d[d < -9000] = np.nan
    d = np.where(d < 0, 0, d)
    return d, x, y

def make_hillshade(dem):
    az, alt = np.radians(315), np.radians(45)
    dy, dx  = np.gradient(np.nan_to_num(dem, nan=0))
    slope   = np.pi/2 - np.arctan(np.sqrt(dx**2 + dy**2))
    aspect  = np.arctan2(-dy, dx)
    return np.sin(alt)*np.sin(slope) + np.cos(alt)*np.cos(slope)*np.cos(az-aspect)

def main():
    VIS_DIR.mkdir(parents=True, exist_ok=True)
    dem, x, y = load_nc(DEM_PATH)
    hs = make_hillshade(dem)
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    ext  = [float(x_km[0]), float(x_km[-1]),
            float(y_km[0]), float(y_km[-1])]

    data = {}
    for key, path, _, _ in VERSIONS:
        d, _, _ = load_nc(path)
        data[key] = d
        wet = d > 0
        print(f"{key:10s}: wet={wet.sum():,}  mean={d[wet].mean():.2f}m  max={d[wet].max():.2f}m")

    # custom colormap — transparent at 0, blue→purple at depth
    cmap_iwd = mcolors.LinearSegmentedColormap.from_list("iwd", [
        (1,1,1,0), (0.68,0.85,1,0.4), (0.28,0.60,1,0.75),
        (0.10,0.25,0.80,0.9), (0.4,0.0,0.6,1.0)
    ], N=256)
    cmap_diff = plt.cm.RdBu_r

    fig = plt.figure(figsize=(22, 20))
    gs  = fig.add_gridspec(3, 3, hspace=0.38, wspace=0.08)

    # ---- Row 1: three IWD maps ----
    vmax_iwd = 4.0
    axes_row1 = []
    for col, (key, _, label, color) in enumerate(VERSIONS):
        ax = fig.add_subplot(gs[0, col])
        axes_row1.append(ax)
        ax.imshow(hs, origin="lower", extent=ext,
                  cmap="gray", vmin=0.3, vmax=1.0, alpha=0.55)
        d = data[key]
        dm = np.ma.masked_where(d <= 0, d)
        im = ax.imshow(dm, origin="lower", extent=ext,
                       cmap=cmap_iwd, vmin=0, vmax=vmax_iwd,
                       interpolation="nearest", alpha=0.88, zorder=5)
        wet = d > 0
        ax.set_title(f"{label}\n"
                     f"Wet: {wet.sum():,}  Mean: {d[wet].mean():.2f}m  "
                     f"Max: {d[wet].max():.2f}m",
                     fontsize=10, fontweight="bold", color=color)
        ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v,_: f"{v:.0f}"))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v,_: f"{v:.0f}"))
        if col == 2:
            fig.colorbar(im, ax=ax, shrink=0.8, label="IWD (m)")

    # ---- Row 2: difference maps + agreement ----
    diff_pairs = [
        ("v6 geom − v1",   data["v6 geom"] - data["v1"],    2.5),
        ("v6 SS − v6 geom",data["v6 SS"]   - data["v6 geom"], 5.0),
    ]
    for col, (title, diff, vmax_d) in enumerate(diff_pairs):
        ax = fig.add_subplot(gs[1, col])
        ax.imshow(hs, origin="lower", extent=ext,
                  cmap="gray", vmin=0.3, vmax=1.0, alpha=0.45)
        mask = (data["v6 SS"] == 0) & (data["v1"] == 0) & (diff == 0)
        dm   = np.ma.masked_where(mask, diff)
        im2  = ax.imshow(dm, origin="lower", extent=ext,
                         cmap=cmap_diff, vmin=-vmax_d, vmax=vmax_d,
                         interpolation="nearest", alpha=0.85, zorder=5)
        n_pos = int((diff >  0.01).sum())
        n_neg = int((diff < -0.01).sum())
        ax.set_title(f"{title}\n+deeper: {n_pos:,}  −shallower: {n_neg:,}",
                     fontsize=10, fontweight="bold")
        ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v,_: f"{v:.0f}"))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v,_: f"{v:.0f}"))
        fig.colorbar(im2, ax=ax, shrink=0.8, label="ΔIWD (m)")

    # Agreement panel
    ax = fig.add_subplot(gs[1, 2])
    ax.imshow(hs, origin="lower", extent=ext,
              cmap="gray", vmin=0.3, vmax=1.0, alpha=0.55)
    w1   = data["v1"]     > 0
    wg   = data["v6 geom"] > 0
    wss  = data["v6 SS"]  > 0
    only_v1    = w1  & ~wg  & ~wss
    only_v6    = ~w1 & (wg | wss)
    all_agree  = w1  & wg  & wss
    ss_new     = wss & ~w1 & ~wg

    rgba = np.zeros((*dem.shape, 4), dtype=np.float32)
    rgba[only_v1]   = [0.85, 0.20, 0.10, 0.75]  # red
    rgba[only_v6]   = [0.43, 0.36, 0.91, 0.70]  # purple
    rgba[ss_new]    = [0.10, 0.52, 0.90, 0.70]  # blue
    rgba[all_agree] = [0.10, 0.70, 0.30, 0.75]  # green
    ax.imshow(rgba, origin="lower", extent=ext, zorder=5)
    handles = [
        mpatches.Patch(color="#d63031", alpha=0.75,
                       label=f"v1 only ({only_v1.sum():,})"),
        mpatches.Patch(color="#6c5ce7", alpha=0.70,
                       label=f"v6 geom only ({only_v6.sum():,})"),
        mpatches.Patch(color="#1a85e5", alpha=0.70,
                       label=f"SS new ({ss_new.sum():,})"),
        mpatches.Patch(color="#00b894", alpha=0.75,
                       label=f"All agree ({all_agree.sum():,})"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.9)
    ax.set_title("Wet extent agreement\nv1 / v6-geom / v6-SS",
                 fontsize=10, fontweight="bold")
    ax.set_xlabel("x (km)"); ax.set_ylabel("y (km)")
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v,_: f"{v:.0f}"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v,_: f"{v:.0f}"))

    # ---- Row 3: bar chart + histogram ----
    ax_bar = fig.add_subplot(gs[2, 0])
    keys    = [k for k,_,_,_ in VERSIONS]
    counts  = [int((data[k] > 0).sum()) for k in keys]
    colors  = [c for _,_,_,c in VERSIONS]
    bars = ax_bar.bar(["v1","v6\ngeom","v6\nSS"], counts,
                      color=colors, edgecolor="white", width=0.5)
    for bar, cnt in zip(bars, counts):
        ax_bar.text(bar.get_x() + bar.get_width()/2,
                    cnt + 500, f"{cnt:,}", ha="center", va="bottom", fontsize=9)
    ax_bar.set_ylabel("Wet cells (IWD > 0)")
    ax_bar.set_title("Wet cell count", fontsize=10, fontweight="bold")
    ax_bar.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v,_: f"{v/1000:.0f}k"))

    ax_hist = fig.add_subplot(gs[2, 1:])
    for key, _, label, color in VERSIONS:
        d    = data[key]
        vals = d[d > 0].flatten()
        ax_hist.hist(vals, bins=60, alpha=0.55, color=color, density=True,
                     label=f"{key}  (n={len(vals):,}, μ={vals.mean():.2f}m, "
                           f"max={vals.max():.1f}m)")
    ax_hist.set_xlabel("Initial Water Depth (m)")
    ax_hist.set_ylabel("Density")
    ax_hist.set_title("IWD depth distribution (wet cells only)",
                      fontsize=10, fontweight="bold")
    ax_hist.legend(fontsize=9, framealpha=0.9)
    ax_hist.set_xlim(0, 6)

    fig.suptitle(
        "Nairobi IWD Comparison — v1  ·  v6 geometric  ·  v6 steady-state (12h)\n"
        "v1: MERIT HND uniform 3m  ·  v6 geom: TDX+HND  ·  v6 SS: equilibrated",
        fontsize=13, fontweight="bold"
    )

    out = VIS_DIR / "iwd_comparison_v1_v6geom_v6ss.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"\nSaved: {out}")

if __name__ == "__main__":
    main()
