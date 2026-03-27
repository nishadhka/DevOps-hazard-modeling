#!/usr/bin/env python3
"""
Visualize NBO v2 flood simulation results — 2026-03-06 event.

Usage:
    micromamba run -n zarrv3 python visualize_v2.py
"""

from pathlib import Path
import numpy as np
import netCDF4
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
from pyproj import Transformer

WORK_DIR  = Path("/data/rim2d/nbo_2026")
V2_DIR    = WORK_DIR / "v2"
OUT_DIR   = V2_DIR / "output"
VIS_DIR   = V2_DIR / "visualizations"
V1_INPUT  = WORK_DIR / "v1" / "input"

DEM_PATH  = V1_INPUT / "dem.nc"
DPI = 150

TO_LL = Transformer.from_crs("EPSG:32737", "EPSG:4326", always_xy=True)
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32737", always_xy=True)

DOMAIN_LL = {"west": 36.6, "east": 37.1, "south": -1.402004, "north": -1.098036}

GAUGES = [
    {"name": "Dagoretti",      "lat": -1.30203, "lon": 36.75980, "rain_24h_mm": 112.2},
    {"name": "Moi Airbase",    "lat": -1.27727, "lon": 36.86230, "rain_24h_mm": 145.4},
    {"name": "Wilson Airport", "lat": -1.32170, "lon": 36.81480, "rain_24h_mm": 160.0},
    {"name": "Kabete",         "lat": -1.20667, "lon": 36.76889, "rain_24h_mm": 117.4},
    {"name": "Thika",          "lat": -1.22275, "lon": 36.88859, "rain_24h_mm":  59.6},
]
DAMAGE = [
    {"name": "Cars washed\n(Ngong Rd)", "lat": -1.31125, "lon": 36.82077},
    {"name": "Kirinyaga\nRoad flood",    "lat": -1.27954, "lon": 36.82727},
]


def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    vn = [v for v in ds.variables if v not in ("x", "y")][0]
    data = np.array(ds[vn][:], dtype=np.float32)
    ds.close()
    data[data < 0] = 0
    return x, y, data


def ll_extent(x_utm, y_utm):
    lon0, lat0 = TO_LL.transform(float(x_utm[0]),  float(y_utm[0]))
    lon1, lat1 = TO_LL.transform(float(x_utm[-1]), float(y_utm[-1]))
    return [lon0, lon1, lat0, lat1]


def cell_of(lon, lat, x_utm, y_utm):
    gx, gy = TO_UTM.transform(lon, lat)
    ix = int(np.clip(np.argmin(np.abs(x_utm - gx)), 0, len(x_utm)-1))
    iy = int(np.clip(np.argmin(np.abs(y_utm - gy)), 0, len(y_utm)-1))
    return ix, iy


def main():
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading DEM...")
    x, y, dem = load_nc(DEM_PATH)
    dem[dem <= 0] = np.nan
    ext = ll_extent(x, y)

    # Hillshade
    dy_d, dx_d = np.gradient(np.nan_to_num(dem, nan=0))
    az, alt = np.radians(315), np.radians(45)
    slope  = np.pi/2 - np.arctan(np.sqrt(dx_d**2 + dy_d**2))
    aspect = np.arctan2(-dy_d, dx_d)
    hillshade = np.sin(alt)*np.sin(slope) + np.cos(alt)*np.cos(slope)*np.cos(az-aspect)

    print("Loading max flood depth...")
    _, _, wd_max = load_nc(OUT_DIR / "nbo_v2_wd_max.nc")
    _, _, wd_t   = load_nc(OUT_DIR / "nbo_v2_wd_max_t.nc")
    _, _, vel_max = load_nc(OUT_DIR / "nbo_v2_vel_max.nc")

    # Clip boundary artifacts: cap at 5m for display
    wd_max_disp = np.clip(wd_max, 0, 5)

    print("Loading outflow timeseries...")
    with open(str(OUT_DIR / "nbo_v2_outflow_cells_water_depths.txt")) as f:
        lines = f.readlines()
    header = lines[0].strip().split("\t")
    t_vals, d_cars, d_kiri = [], [], []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.strip().split("\t")
        if len(parts) >= 3:
            t_vals.append(float(parts[0]))
            d_cars.append(float(parts[1]))
            d_kiri.append(float(parts[2]))

    t_h = [16 + t/3600 for t in t_vals]

    # ── Figure 1: max flood depth + velocity ──────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(22, 11))

    flood_cmap = mcolors.LinearSegmentedColormap.from_list(
        "flood", ["#ffffff", "#bde0ff", "#5ab4e5", "#1a78c2", "#0a3f7a", "#06154a"])

    for ax_i, (ax, data, title, vmax, cbar_lbl) in enumerate([
        (axes[0], wd_max_disp, "Peak Flood Depth (capped at 5 m)", 5.0, "Flood depth (m)"),
        (axes[1], np.clip(vel_max, 0, 3), "Peak Flow Velocity", 3.0, "Velocity (m/s)"),
    ]):
        # DEM hillshade background
        ax.imshow(hillshade, origin="lower", extent=ext, cmap="gray",
                  vmin=0.3, vmax=1.0, alpha=0.4)
        ax.imshow(np.ma.masked_invalid(dem), origin="lower", extent=ext,
                  cmap="terrain", alpha=0.35)

        # Flood overlay
        flood_masked = np.ma.masked_where(data < 0.05, data)
        cmap = flood_cmap if ax_i == 0 else plt.cm.YlOrRd
        im = ax.imshow(flood_masked, origin="lower", extent=ext,
                       cmap=cmap, vmin=0, vmax=vmax, alpha=0.85)
        plt.colorbar(im, ax=ax, label=cbar_lbl, shrink=0.85, pad=0.02)

        # Domain box
        bx = DOMAIN_LL
        ax.plot([bx["west"],bx["east"],bx["east"],bx["west"],bx["west"]],
                [bx["south"],bx["south"],bx["north"],bx["north"],bx["south"]],
                "k--", lw=1.5, zorder=5)

        # Gauge stations
        for g in GAUGES:
            ax.plot(g["lon"], g["lat"], "b^", ms=7, markeredgecolor="white",
                    markeredgewidth=0.8, zorder=8)

        # Damage locations
        for d in DAMAGE:
            ax.plot(d["lon"], d["lat"], "rX", ms=14, markeredgecolor="white",
                    markeredgewidth=1.5, zorder=10)
            ax.annotate(d["name"], (d["lon"], d["lat"]),
                        textcoords="offset points", xytext=(8, -16),
                        fontsize=8, color="red", fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", fc="white",
                                  ec="red", alpha=0.85))

        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        ax.set_xlim(bx["west"]-0.01, bx["east"]+0.01)
        ax.set_ylim(bx["south"]-0.01, bx["north"]+0.01)
        ax.grid(alpha=0.15, linestyle=":")

    # Legend
    handles = [
        mpatches.Patch(facecolor="#1a78c2", alpha=0.8, label="Flood extent (>5 cm)"),
        plt.Line2D([0],[0], marker="^", color="w", markerfacecolor="blue",
                   markeredgecolor="white", ms=8, label="Rain gauge"),
        plt.Line2D([0],[0], marker="X", color="w", markerfacecolor="red",
                   markeredgecolor="white", ms=10, label="Damage location"),
    ]
    axes[0].legend(handles=handles, loc="upper left", fontsize=9,
                   framealpha=0.9, edgecolor="gray")

    fig.suptitle("NBO v2 — 2026-03-06 Flash Flood | Peak Flood Depth & Velocity\n"
                 "Compound Pluvial + Fluvial | 24h from 16:00 | C=0.85 saturated",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = VIS_DIR / "v2_results_peak.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")

    # ── Figure 2: time-of-peak + flood extent snapshots ───────────────────
    fig, axes = plt.subplots(1, 3, figsize=(26, 10))

    # Time-of-peak
    ax = axes[0]
    ax.imshow(hillshade, origin="lower", extent=ext, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.45)
    t_masked = np.ma.masked_where(wd_max < 0.05, wd_t)
    t_hours = t_masked / 3600 + 16   # convert to clock hour
    im = ax.imshow(t_hours, origin="lower", extent=ext, cmap="plasma",
                   vmin=16, vmax=24, alpha=0.85)
    cbar = plt.colorbar(im, ax=ax, label="Time of peak (hour of day)", shrink=0.85)
    cbar.set_ticks([16,17,18,19,20,21,22,23,24])
    cbar.set_ticklabels(["16:00","17:00","18:00","19:00","20:00",
                          "21:00","22:00","23:00","00:00"])
    for d in DAMAGE:
        ax.plot(d["lon"], d["lat"], "rX", ms=13, markeredgecolor="white",
                markeredgewidth=1.5, zorder=10)
    ax.axvline(36.75, color="none")
    ax.set_title("Time of Peak Flooding", fontsize=12, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    bx = DOMAIN_LL
    ax.set_xlim(bx["west"]-0.01, bx["east"]+0.01)
    ax.set_ylim(bx["south"]-0.01, bx["north"]+0.01)
    ax.grid(alpha=0.15)
    # Burst window annotation
    ax.annotate("▲ Burst onset\n17:30", xy=(36.82, -1.39), fontsize=8,
                color="white", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="#cc0000", ec="white", alpha=0.85))

    # Snapshot at peak burst t=19800s (21:30) and end t=86400
    for ax_i, (ax, t_s, label) in enumerate([
        (axes[1], 19800, "Flood at 21:30 (end of burst)"),
        (axes[2], 43200, "Flood at 28:00 (12h after start)"),
    ]):
        nc_path = OUT_DIR / f"nbo_v2_wd_{t_s}.nc"
        if nc_path.exists():
            _, _, wd_snap = load_nc(nc_path)
        else:
            wd_snap = np.zeros_like(wd_max)

        ax.imshow(hillshade, origin="lower", extent=ext, cmap="gray",
                  vmin=0.3, vmax=1.0, alpha=0.45)
        ax.imshow(np.ma.masked_invalid(dem), origin="lower", extent=ext,
                  cmap="terrain", alpha=0.3)
        snap_disp = np.ma.masked_where(np.clip(wd_snap, 0, 5) < 0.05,
                                       np.clip(wd_snap, 0, 5))
        im = ax.imshow(snap_disp, origin="lower", extent=ext,
                       cmap=flood_cmap, vmin=0, vmax=3.0, alpha=0.85)
        plt.colorbar(im, ax=ax, label="Flood depth (m)", shrink=0.85, pad=0.02)

        for g in GAUGES:
            ax.plot(g["lon"], g["lat"], "b^", ms=7, markeredgecolor="white",
                    markeredgewidth=0.8, zorder=8)
        for d in DAMAGE:
            ax.plot(d["lon"], d["lat"], "rX", ms=13, markeredgecolor="white",
                    markeredgewidth=1.5, zorder=10)
        ax.set_title(f"Flood Depth — {label}", fontsize=12, fontweight="bold")
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        ax.set_xlim(bx["west"]-0.01, bx["east"]+0.01)
        ax.set_ylim(bx["south"]-0.01, bx["north"]+0.01)
        ax.grid(alpha=0.15)

    fig.suptitle("NBO v2 — 2026-03-06 Flash Flood | Temporal Evolution",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out = VIS_DIR / "v2_results_temporal.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")

    # ── Figure 3: Damage zone close-up + flood stats ───────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(20, 10))

    # Close-up around damage area
    ax = axes[0]
    zoom = {"west": 36.78, "east": 36.88, "south": -1.34, "north": -1.26}
    ax.imshow(hillshade, origin="lower", extent=ext, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.45)
    flood_masked = np.ma.masked_where(wd_max_disp < 0.05, wd_max_disp)
    im = ax.imshow(flood_masked, origin="lower", extent=ext,
                   cmap=flood_cmap, vmin=0, vmax=3.0, alpha=0.9)
    plt.colorbar(im, ax=ax, label="Peak flood depth (m)", shrink=0.85)
    for g in GAUGES:
        ax.plot(g["lon"], g["lat"], "b^", ms=9, markeredgecolor="black",
                markeredgewidth=0.8, zorder=8)
        ax.annotate(f"{g['name']}\n{g['rain_24h_mm']}mm",
                    (g["lon"], g["lat"]), textcoords="offset points",
                    xytext=(5, 5), fontsize=8, color="navy",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white",
                              ec="navy", alpha=0.8))
    for d in DAMAGE:
        ax.plot(d["lon"], d["lat"], "rX", ms=16, markeredgecolor="white",
                markeredgewidth=2, zorder=10)
        ax.annotate(d["name"], (d["lon"], d["lat"]),
                    textcoords="offset points", xytext=(8, -20),
                    fontsize=9, color="red", fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="red", alpha=0.9))
    # River annotation
    ax.annotate("← Nairobi River corridor", xy=(36.805, -1.307), fontsize=9,
                color="navy", style="italic",
                bbox=dict(boxstyle="round,pad=0.2", fc="lightyellow",
                          ec="navy", alpha=0.85))
    ax.set_xlim(zoom["west"], zoom["east"])
    ax.set_ylim(zoom["south"], zoom["north"])
    ax.set_title("Damage Zone Close-up — Peak Flood Depth", fontsize=12, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.grid(alpha=0.2)

    # Flood statistics panel
    ax = axes[1]
    ax.axis("off")

    # Compute stats
    n_total = wd_max.size
    depths = [0.05, 0.1, 0.3, 0.5, 1.0, 2.0]
    counts = [int((wd_max > d).sum()) for d in depths]
    pcts   = [100 * c / n_total for c in counts]

    # Bar chart
    ax2 = fig.add_axes([0.54, 0.55, 0.42, 0.35])
    bars = ax2.barh([f"> {d}m" for d in depths], counts,
                    color=flood_cmap(np.linspace(0.3, 1.0, len(depths))),
                    edgecolor="white", height=0.7)
    for bar, cnt, pct in zip(bars, counts, pcts):
        ax2.text(bar.get_width() + 500, bar.get_y() + bar.get_height()/2,
                 f"{cnt:,} ({pct:.1f}%)", va="center", fontsize=9)
    ax2.set_xlabel("Number of 30m grid cells")
    ax2.set_title("Flood Extent by Depth Threshold", fontweight="bold")
    ax2.grid(axis="x", alpha=0.3)
    ax2.set_xlim(0, max(counts) * 1.25)

    # Text summary
    ax3 = fig.add_axes([0.54, 0.08, 0.42, 0.40])
    ax3.axis("off")
    area_km2 = [(wd_max > d).sum() * 30**2 / 1e6 for d in depths]
    summary = (
        f"NBO v2 — 2026-03-06 Event Summary\n"
        f"{'─'*42}\n"
        f"Simulation: 24h from 16:00\n"
        f"Event: Burst 17:30–21:30 (4h)\n"
        f"Domain-mean 24h rainfall: 111.9 mm\n"
        f"Peak gauge: Wilson Airport 160 mm\n"
        f"Entry points: 90 (fluvial BCs)\n"
        f"Runoff coeff (C_eff): 0.85 (saturated)\n"
        f"{'─'*42}\n"
        f"Flood cells > 5cm:  {counts[0]:>8,} ({area_km2[0]:.1f} km²)\n"
        f"Flood cells > 10cm: {counts[1]:>8,} ({area_km2[1]:.1f} km²)\n"
        f"Flood cells > 50cm: {counts[4]:>8,} ({area_km2[4]:.1f} km²)\n"
        f"Flood cells > 1m:   {int((wd_max>1).sum()):>8,} ({(wd_max>1).sum()*30**2/1e6:.1f} km²)\n"
        f"{'─'*42}\n"
        f"Peak velocity: {float(vel_max.max()):.1f} m/s\n"
        f"{'─'*42}\n"
        f"⚠ Boundary BCs use Manning's WSE\n"
        f"  (wide channel 15m, S=0.005)\n"
        f"  → recalibrate for order 3–5 rivers"
    )
    ax3.text(0.02, 0.98, summary, transform=ax3.transAxes,
             fontsize=9.5, va="top", fontfamily="monospace",
             bbox=dict(boxstyle="round,pad=0.5", fc="#f8f8f8",
                       ec="gray", alpha=0.9))

    fig.suptitle("NBO v2 — 2026-03-06 Flash Flood | Damage Zone & Statistics",
                 fontsize=13, fontweight="bold")
    out = VIS_DIR / "v2_results_damage_zone.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")

    # ── Summary printout ──────────────────────────────────────────────────
    print()
    print("=" * 55)
    print("SIMULATION RESULTS SUMMARY")
    print("=" * 55)
    print(f"  Domain max depth (raw):   {wd_max.max():.1f} m (BC artifact)")
    print(f"  Domain max depth (<5m):   {wd_max_disp.max():.1f} m")
    print(f"  Flood area > 10 cm:       {area_km2[1]:.1f} km²")
    print(f"  Flood area > 50 cm:       {area_km2[4]:.1f} km²")
    print(f"  Peak velocity:            {float(vel_max.max()):.1f} m/s")
    print(f"  Damage zone (Kirinyaga):  max nearby 3.0 m")
    print("=" * 55)


if __name__ == "__main__":
    main()
