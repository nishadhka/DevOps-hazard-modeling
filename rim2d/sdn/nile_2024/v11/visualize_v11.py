#!/usr/bin/env python3
"""
v11 Basin-Derived Synthetic Hydrograph — Visualization.

Two modes:
  --inputs:  Verify input data (basin overlay, rainfall comparison, hydrograph)
  --results: Post-simulation flood depth maps + GIF animation

Usage:
    micromamba run -n zarrv3 python visualize_v11.py --inputs
    micromamba run -n zarrv3 python visualize_v11.py --results
"""

import argparse
import glob
import json
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


WORK_DIR = Path(__file__).resolve().parent.parent   # nile_highres/
V10_DIR = WORK_DIR / "v10"
V11_DIR = Path(__file__).resolve().parent             # nile_highres/v11/
V10_INPUT = V10_DIR / "input"
V11_INPUT = V11_DIR / "input"
V11_OUTPUT = V11_DIR / "output"
VIS_DIR = V11_DIR / "visualizations"
WS_DIR = V10_DIR / "input" / "watersheds"

VMAX = 8.0  # max depth for color scale (m)
DPI = 150

CULVERTS = [
    {"name": "Culvert 1", "lat": 19.547450, "lon": 33.339139},
    {"name": "Culvert 2", "lat": 19.550000, "lon": 33.325906},
]

WESTERN_ENTRY = {"name": "Western Wadi", "lat": 19.550, "lon": 33.300}

# All inflow points (for plots that need all 3)
ALL_INFLOWS = CULVERTS + [WESTERN_ENTRY]

BBOX = {"west": 33.25, "south": 19.49, "east": 33.36, "north": 19.57}

SIM_DUR = 3196800       # 37 days (Jul 25 — Aug 31)
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


def inflow_xy_km(x, y, points=None):
    """Get inflow point positions in km coordinates."""
    from pyproj import Transformer
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    if points is None:
        points = ALL_INFLOWS
    positions = []
    for pt in points:
        utm_x, utm_y = to_utm.transform(pt["lon"], pt["lat"])
        xk = (utm_x - float(x[0])) / 1000.0
        yk = (utm_y - float(y[0])) / 1000.0
        positions.append((xk, yk, pt["name"]))
    return positions


# Backward-compatible alias
def culvert_xy_km(x, y):
    return inflow_xy_km(x, y, CULVERTS)


def load_metadata():
    """Load v11 metadata."""
    meta_path = V11_INPUT / "v11_metadata.json"
    if meta_path.exists():
        with open(str(meta_path)) as f:
            return json.load(f)
    return None


# =============================================================================
# INPUT VERIFICATION
# =============================================================================

def plot_watershed_overlay():
    """Plot basin polygons overlaid on DEM with domain box."""
    try:
        from shapely.geometry import shape
    except ImportError:
        print("  Skipping watershed overlay (shapely not available)")
        return

    # Find available GeoJSON files
    geojson_files = sorted(glob.glob(str(WS_DIR / "*.geojson")))
    if not geojson_files:
        print("  Skipping watershed overlay (no GeoJSON files)")
        return

    meta = load_metadata()

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))

    colors_cv = {"Culvert1": "#e41a1c", "Culvert2": "#377eb8"}

    for ax_idx, cv in enumerate(CULVERTS):
        ax = axes[ax_idx]
        cv_key = cv["name"].replace(" ", "")

        # Find finest level GeoJSON
        for level in [12, 10, 8, 6, 4]:
            gj_path = WS_DIR / f"{cv_key}_level{level:02d}.geojson"
            if gj_path.exists():
                with open(str(gj_path)) as f:
                    fc = json.load(f)
                geom = shape(fc["features"][0]["geometry"])

                if geom.geom_type == "Polygon":
                    xs, ys = geom.exterior.xy
                    ax.fill(xs, ys, alpha=0.2, color=colors_cv[cv_key])
                    ax.plot(xs, ys, color=colors_cv[cv_key], linewidth=1.5,
                            label=f"Basin (level {level})")
                elif geom.geom_type == "MultiPolygon":
                    for j, poly in enumerate(geom.geoms):
                        xs, ys = poly.exterior.xy
                        ax.fill(xs, ys, alpha=0.2, color=colors_cv[cv_key])
                        lbl = f"Basin (level {level})" if j == 0 else None
                        ax.plot(xs, ys, color=colors_cv[cv_key],
                                linewidth=1.5, label=lbl)

                area = geom.area  # approx degrees^2
                centroid = geom.centroid
                if meta:
                    cv_meta = [c for c in meta["culverts"]
                               if c["name"] == cv_key]
                    if cv_meta:
                        area_km2 = cv_meta[0]["catchment_km2"]
                        ax.text(centroid.x, centroid.y,
                                f"{area_km2:.0f} km2",
                                ha="center", va="center", fontsize=11,
                                fontweight="bold", color=colors_cv[cv_key],
                                bbox=dict(fc="white", alpha=0.7, pad=2))
                break

        # Domain box
        ax.plot(
            [BBOX["west"], BBOX["east"], BBOX["east"],
             BBOX["west"], BBOX["west"]],
            [BBOX["south"], BBOX["south"], BBOX["north"],
             BBOX["north"], BBOX["south"]],
            "k--", linewidth=2, label="Simulation domain"
        )

        # Culvert marker
        ax.plot(cv["lon"], cv["lat"], "D", color=colors_cv[cv_key],
                markersize=10, markeredgecolor="black", markeredgewidth=1.5,
                zorder=10)

        ax.set_title(f"{cv['name']}", fontsize=13, fontweight="bold")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_aspect("equal")
        ax.legend(loc="upper right", fontsize=9)
        ax.grid(alpha=0.3)

    fig.suptitle("v11 — HydroATLAS Basin Polygons vs Simulation Domain",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    out_path = VIS_DIR / "v11_basin_overlay.png"
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


def plot_rainfall_comparison():
    """Compare basin-mean vs domain-mean rainfall."""
    hydro_path = V11_INPUT / "culvert_hydrographs_v11.npz"
    if not hydro_path.exists():
        print("  Skipping rainfall comparison (npz not found)")
        return

    data = np.load(str(hydro_path))
    domain_rain = data["domain_rain"]

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    colors_cv = ["#e41a1c", "#377eb8"]
    cv_keys = ["Culvert1", "Culvert2"]

    # Handle both old (per-culvert basin rain) and new (single basin rain) formats
    basin_rain_raw = data.get("basin_rain_raw", None)
    basin_rain_int = data.get("basin_rain_intensified", None)

    for i, cv_key in enumerate(cv_keys):
        # Check for per-culvert or shared basin rain
        basin_key = f"basin_rain_{cv_key}"
        has_per_cv = basin_key in data
        has_shared = basin_rain_raw is not None

        # Time series
        ax = axes[0, i]
        days_domain = np.arange(len(domain_rain)) * 0.5 / 24.0

        if has_shared:
            days_basin = np.arange(len(basin_rain_raw)) * 0.5 / 24.0
            ax.bar(days_basin, basin_rain_raw, width=0.5/24.0,
                   color=colors_cv[i], alpha=0.4, label="Basin-mean (raw)")
            if basin_rain_int is not None:
                ax.plot(days_basin, basin_rain_int, color="darkred",
                        linewidth=0.8, alpha=0.7, label="Intensified")
        elif has_per_cv:
            basin_rain = data[basin_key]
            days_basin = np.arange(len(basin_rain)) * 0.5 / 24.0
            ax.plot(days_basin, basin_rain, color=colors_cv[i],
                    linewidth=0.8, alpha=0.8, label="Basin-mean")

        ax.plot(days_domain, domain_rain, color="gray",
                linewidth=0.5, alpha=0.6, label="Domain-mean")
        ax.set_xlabel("Days from Jul 25")
        ax.set_ylabel("Rain rate (mm/hr)")
        ax.set_title(f"{CULVERTS[i]['name']} — Rainfall Time Series",
                     fontsize=11, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

        # Cumulative
        ax2 = axes[1, i]
        cum_domain = np.cumsum(domain_rain * 0.5)
        ax2.plot(days_domain, cum_domain, color="gray", linewidth=2,
                 alpha=0.6, label=f"Domain ({cum_domain[-1]:.0f} mm)")

        if has_shared:
            cum_raw = np.cumsum(basin_rain_raw * 0.5)
            ax2.plot(days_basin, cum_raw, color=colors_cv[i], linewidth=2,
                     alpha=0.8, label=f"Basin raw ({cum_raw[-1]:.0f} mm)")
            if basin_rain_int is not None:
                cum_int = np.cumsum(basin_rain_int * 0.5)
                ax2.plot(days_basin, cum_int, color="darkred", linewidth=2,
                         alpha=0.7, label=f"Intensified ({cum_int[-1]:.0f} mm)")
        elif has_per_cv:
            basin_rain = data[basin_key]
            cum_basin = np.cumsum(basin_rain * 0.5)
            ax2.plot(days_basin, cum_basin, color=colors_cv[i], linewidth=2,
                     alpha=0.8, label=f"Basin ({cum_basin[-1]:.0f} mm)")

        ax2.set_xlabel("Days from Jul 25")
        ax2.set_ylabel("Cumulative rainfall (mm)")
        ax2.set_title(f"{CULVERTS[i]['name']} — Cumulative Rainfall",
                      fontsize=11, fontweight="bold")
        ax2.legend(fontsize=9)
        ax2.grid(alpha=0.3)

    fig.suptitle("v11 — Basin-Scale vs Domain-Scale IMERG Rainfall",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    out_path = VIS_DIR / "v11_rainfall_comparison.png"
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


def plot_wadi_culvert_assignment():
    """Plot river network with wadi-to-culvert assignment and building overlay."""
    river_path = V11_INPUT / "river_network_tdx_v2.geojson"
    if not river_path.exists():
        print("  Skipping wadi-culvert assignment (no river network GeoJSON)")
        return

    with open(str(river_path)) as f:
        fc = json.load(f)

    meta = load_metadata()

    # Load buildings (UTM → lat/lon)
    bldg_lons, bldg_lats, bldg_mask = None, None, None
    bldg_path = V10_INPUT / "buildings.nc"
    if bldg_path.exists():
        from pyproj import Transformer
        ds = netCDF4.Dataset(str(bldg_path))
        bldg = ds.variables["Band1"][:].squeeze()
        x = ds.variables["x"][:]
        y = ds.variables["y"][:]
        ds.close()
        bldg_mask = np.where(bldg > 0, 1.0, np.nan)
        to_ll = Transformer.from_crs("EPSG:32636", "EPSG:4326", always_xy=True)
        xx, yy = np.meshgrid(x, y)
        bldg_lons, bldg_lats = to_ll.transform(xx, yy)

    # Feeding wadis from metadata
    feeding_wadis = {}
    western_wadis = set()
    if meta:
        for pt_meta in meta.get("inflow_points", meta.get("culverts", [])):
            linkno = pt_meta.get("feeding_wadi_linkno")
            if linkno:
                feeding_wadis[linkno] = pt_meta["name"]
            for linkno in pt_meta.get("feeding_wadi_linknos", []):
                feeding_wadis[linkno] = pt_meta["name"]
                if pt_meta.get("type") == "western_wadi":
                    western_wadis.add(linkno)

    fig, ax = plt.subplots(figsize=(14, 12))

    # Stream order styling
    stream_styles = {
        9: {"color": "#0033aa", "width": 3.5, "label": "Nile (Order 9)"},
        5: {"color": "#1a66ff", "width": 2.0, "label": "Large streams (Order 5)"},
        2: {"color": "#80b3ff", "width": 0.8, "label": "Wadis (Order 2)"},
    }

    culv_colors = {
        "Culvert1": "#e41a1c", "Culvert2": "#377eb8",
        "WesternWadi": "#2ca02c",
    }

    # Draw all streams
    for feat in fc["features"]:
        so = feat["properties"].get("stream_order", 1)
        linkno = feat["properties"].get("linkno")
        geom = feat["geometry"]

        # Check if this is a feeding wadi
        is_feeding = linkno in feeding_wadis
        assigned_cv = feeding_wadis.get(linkno)

        style = stream_styles.get(so, {"color": "#80b3ff", "width": 0.6})

        coords = []
        if geom["type"] == "MultiLineString":
            for line in geom["coordinates"]:
                coords.append(line)
        elif geom["type"] == "LineString":
            coords.append(geom["coordinates"])

        for line in coords:
            xs = [c[0] for c in line]
            ys = [c[1] for c in line]

            if is_feeding:
                # Highlight feeding wadis with culvert color
                ax.plot(xs, ys, color=culv_colors[assigned_cv],
                        linewidth=style["width"] * 3, solid_capstyle="round",
                        alpha=0.9, zorder=4)
                ax.plot(xs, ys, color="white",
                        linewidth=style["width"] * 1, solid_capstyle="round",
                        alpha=0.5, zorder=5)
            else:
                ax.plot(xs, ys, color=style["color"],
                        linewidth=style["width"], solid_capstyle="round",
                        alpha=0.7, zorder=2)

    # Buildings overlay
    if bldg_lons is not None:
        ax.pcolormesh(bldg_lons, bldg_lats, bldg_mask,
                      cmap=mcolors.ListedColormap(["#d95f02"]),
                      alpha=0.6, zorder=3, rasterized=True)

    # Domain box
    ax.plot(
        [BBOX["west"], BBOX["east"], BBOX["east"],
         BBOX["west"], BBOX["west"]],
        [BBOX["south"], BBOX["south"], BBOX["north"],
         BBOX["north"], BBOX["south"]],
        color="black", linewidth=2, linestyle="--", zorder=6,
    )

    # Inflow point markers with catchment labels
    for pt in ALL_INFLOWS:
        pt_key = pt["name"].replace(" ", "")
        color = culv_colors.get(pt_key, "#333333")
        ax.plot(pt["lon"], pt["lat"], "D", color=color, markersize=14,
                markeredgecolor="black", markeredgewidth=2, zorder=10)

        area_str = ""
        if meta:
            for ip in meta.get("inflow_points", meta.get("culverts", [])):
                if ip["name"] == pt_key:
                    area_str = f"\n{ip['catchment_km2']:.0f} km²"
                    if ip.get("nile_blocking"):
                        area_str += " (Nile-blocked)"
                    break

        ax.annotate(f"{pt['name']}{area_str}", (pt["lon"], pt["lat"]),
                    textcoords="offset points", xytext=(10, 10),
                    fontsize=11, fontweight="bold", color=color,
                    bbox=dict(boxstyle="round,pad=0.3", fc="white",
                              ec=color, alpha=0.9))

    # Legend
    handles = [
        plt.Line2D([0], [0], color="#0033aa", linewidth=3.5, label="Nile (Order 9)"),
        plt.Line2D([0], [0], color="#1a66ff", linewidth=2.0, label="Large streams (Order 5)"),
        plt.Line2D([0], [0], color="#80b3ff", linewidth=0.8, label="Other wadis (Order 2)"),
        plt.Line2D([0], [0], color="#e41a1c", linewidth=3.0,
                   label="Culvert 1 feeding wadi"),
        plt.Line2D([0], [0], color="#377eb8", linewidth=3.0,
                   label="Culvert 2 feeding wadi"),
        plt.Line2D([0], [0], color="#2ca02c", linewidth=3.0,
                   label="Western wadi (Nile-blocked)"),
        plt.Line2D([0], [0], color="black", linestyle="--", linewidth=2,
                   label="Simulation domain"),
        mpatches.Patch(facecolor="#d95f02", alpha=0.6, label="Buildings"),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=10,
              framealpha=0.95, edgecolor="gray")

    ax.set_title("v11 Compound Flooding — Wadi + Culvert Assignment\n"
                 "2 culverts (north) + western wadi entry (Nile-blocked)",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_aspect("equal")
    ax.grid(alpha=0.2, linestyle=":")

    fig.tight_layout()
    out_path = VIS_DIR / "v11_wadi_culvert_assignment.png"
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


def plot_hydrograph_comparison():
    """Compare v11 corrected hydrograph with raw and v10."""
    v11_hydro = V11_INPUT / "culvert_hydrographs_v11.npz"
    v10_hydro = V10_INPUT / "culvert_hydrographs.npz"

    if not v11_hydro.exists():
        print("  Skipping hydrograph comparison (v11 npz not found)")
        return

    d11 = np.load(str(v11_hydro))
    meta = load_metadata()

    fig, axes = plt.subplots(4, 1, figsize=(16, 22))

    cv_keys = ["Culvert1", "Culvert2"]
    colors = ["#e41a1c", "#377eb8"]

    # Panel 1: Final hydrographs (all 3 inflows)
    ax = axes[0]
    times_h = d11["times_h"]
    days = times_h / 24.0

    for i, cv_key in enumerate(cv_keys):
        q_key = f"q_{cv_key}"
        if q_key in d11:
            q = d11[q_key]
            label = f"{CULVERTS[i]['name']}"
            if meta:
                cv_meta = [c for c in meta.get("culverts", []) if c["name"] == cv_key]
                if cv_meta:
                    label += f" ({cv_meta[0]['catchment_km2']:.0f} km²)"
            ax.plot(days, q, color=colors[i], linewidth=1.5, label=label)

        # Also plot raw (un-intensified)
        q_raw_key = f"q_raw_{cv_key}"
        if q_raw_key in d11:
            ax.plot(days, d11[q_raw_key], color=colors[i], linewidth=0.8,
                    linestyle=":", alpha=0.5,
                    label=f"{CULVERTS[i]['name']} (raw, no intensification)")

    # Western wadi hydrograph
    if "q_WesternWadi" in d11:
        q_west = d11["q_WesternWadi"]
        west_label = "Western Wadi (75 km², Nile-blocked)"
        if meta:
            for ip in meta.get("inflow_points", []):
                if ip["name"] == "WesternWadi":
                    west_label = f"Western Wadi ({ip['catchment_km2']:.0f} km², Nile-blocked)"
                    break
        ax.plot(days, q_west, color="#2ca02c", linewidth=2.0, label=west_label)

    if "q_WesternWadi_unblocked" in d11:
        ax.plot(days, d11["q_WesternWadi_unblocked"], color="#2ca02c",
                linewidth=0.8, linestyle=":", alpha=0.5,
                label="Western Wadi (unblocked, if Nile low)")

    if meta:
        q_cap = meta.get("culvert_capacity_m3s", 0)
        if q_cap > 0:
            ax.axhline(y=q_cap, color="gray", linestyle=":", linewidth=1,
                       label=f"Culvert capacity ({q_cap:.1f} m³/s)")

    ax.set_xlabel("Days from Jul 25")
    ax.set_ylabel("Flow (m³/s)")
    ax.set_title("Compound Flooding Hydrographs — 3 Inflow Sources",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=8, ncol=2, loc="upper right")
    ax.grid(alpha=0.3)

    # Panel 2: Nile blocking factor + western wadi context
    ax_nile = axes[1]
    if "nile_blocking_factor" in d11:
        bf = d11["nile_blocking_factor"]
        bf_days = np.arange(len(bf)) * 0.5 / 24.0
        ax_nile.fill_between(bf_days, 0, bf, color="#2ca02c", alpha=0.3,
                             label="Nile blocking factor")
        ax_nile.plot(bf_days, bf, color="#2ca02c", linewidth=1.5)
        ax_nile.set_ylabel("Blocking factor (0-1)", color="#2ca02c")
        ax_nile.set_ylim(-0.05, 1.15)
        ax_nile.tick_params(axis="y", labelcolor="#2ca02c")

        # Secondary axis: Nile flow
        ax_nile2 = ax_nile.twinx()
        # Reconstruct Nile flow from blocking factor
        if meta:
            q_min = meta.get("nile_baseline_m3s", 14895)
            q_max = meta.get("nile_peak_m3s", 31694)
        else:
            q_min, q_max = 14895, 31694
        nile_flow = q_min + bf * (q_max - q_min)
        ax_nile2.plot(bf_days, nile_flow / 1000, color="#0033aa", linewidth=1.5,
                      alpha=0.7, label="Nile flow (GEOGloWS)")
        ax_nile2.set_ylabel("Nile flow (×10³ m³/s)", color="#0033aa")
        ax_nile2.tick_params(axis="y", labelcolor="#0033aa")

        # Combine legends
        lines1, labels1 = ax_nile.get_legend_handles_labels()
        lines2, labels2 = ax_nile2.get_legend_handles_labels()
        ax_nile.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper left")
    else:
        ax_nile.text(0.5, 0.5, "Nile blocking factor not available",
                     transform=ax_nile.transAxes, ha="center", fontsize=14)

    ax_nile.set_xlabel("Days from Jul 25")
    ax_nile.set_title("Nile Blocking Factor — Western Drainage Outlet Submergence",
                      fontsize=12, fontweight="bold")
    ax_nile.grid(alpha=0.3)

    # Panel 3: Rainfall — raw vs intensified
    ax2 = axes[2]
    domain_rain = d11["domain_rain"]
    rain_days = np.arange(len(domain_rain)) * 0.5 / 24.0

    if "basin_rain_raw" in d11:
        br_raw = d11["basin_rain_raw"]
        br_days = np.arange(len(br_raw)) * 0.5 / 24.0
        ax2.bar(br_days, br_raw, width=0.5/24.0, color="steelblue",
                alpha=0.5, label="Basin-mean IMERG (raw)")

        if "basin_rain_intensified" in d11:
            br_int = d11["basin_rain_intensified"]
            ax2.plot(br_days, br_int, color="darkred", linewidth=1.0,
                     alpha=0.7, label="Basin-mean IMERG (intensified)")

            if "imerg_factor" in d11:
                factor = float(d11["imerg_factor"][0])
                ax2.text(0.02, 0.95, f"IMERG factor: {factor:.2f}x",
                         transform=ax2.transAxes, fontsize=11,
                         fontweight="bold", va="top",
                         bbox=dict(fc="lightyellow", alpha=0.9, pad=4))
    else:
        ax2.bar(rain_days, domain_rain, width=0.5/24.0, color="steelblue",
                alpha=0.5, label="Domain-mean IMERG")

    # Overlay blocking factor on rainfall panel
    if "nile_blocking_factor" in d11:
        ax2b = ax2.twinx()
        bf = d11["nile_blocking_factor"]
        bf_days = np.arange(len(bf)) * 0.5 / 24.0
        ax2b.plot(bf_days, bf, color="#2ca02c", linewidth=1.0, alpha=0.5,
                  linestyle="--", label="Nile blocking")
        ax2b.set_ylabel("Blocking factor", color="#2ca02c", fontsize=9)
        ax2b.set_ylim(-0.05, 1.15)
        ax2b.tick_params(axis="y", labelcolor="#2ca02c", labelsize=8)

    ax2.set_xlabel("Days from Jul 25")
    ax2.set_ylabel("Rain rate (mm/hr)")
    ax2.set_title("IMERG Rainfall + Nile Blocking Timeline",
                  fontsize=12, fontweight="bold")
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)

    # Panel 4: Parameter comparison table
    ax3 = axes[3]
    ax3.axis("off")

    table_data = [
        ["Parameter", "v10", "v11 (2 culverts)", "v11 (compound)"],
        ["Inflow sources", "2 culverts", "2 culverts", "2 culverts + western wadi"],
        ["C1 catchment", "30 km²", "25 km²", "25 km²"],
        ["C2 catchment", "20 km²", "35 km²", "35 km²"],
        ["Western wadi", "—", "—", "75 km² (Nile-blocked)"],
        ["Total inflow area", "50 km²", "60 km²", "135 km²"],
        ["Runoff coeff C", "0.30", "0.65", "0.65"],
        ["IMERG correction", "None", f"{float(d11.get('imerg_factor', [0])[0]):.1f}x", f"{float(d11.get('imerg_factor', [0])[0]):.1f}x"],
        ["Nile interaction", "None", "None", "Backwater blocking"],
    ]

    if meta:
        for ip in meta.get("inflow_points", meta.get("culverts", [])):
            peak = ip["peak_flow_m3s"]
            table_data.append([
                f"{ip['name']} peak Q",
                "—",
                "—",
                f"{peak:.1f} m³/s",
            ])

    table = ax3.table(cellText=table_data[1:], colLabels=table_data[0],
                      loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.8)

    # Color header
    for j in range(len(table_data[0])):
        table[0, j].set_facecolor("#d4e6f1")
        table[0, j].set_text_props(fontweight="bold")
    # Highlight compound column
    for i in range(1, len(table_data)):
        table[i, 3].set_facecolor("#eafaf1")

    ax3.set_title("Parameter Comparison: Compound Flooding Update",
                  fontsize=13, fontweight="bold", pad=20)

    fig.suptitle("v11 — Compound Flooding: Culverts + Nile-Blocked Western Wadi",
                 fontsize=15, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out_path = VIS_DIR / "v11_hydrograph_comparison.png"
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


def plot_dem_with_culverts(dem, hillshade, x_km, y_km, extent, inflow_pos):
    """DEM + hillshade + inflow point markers."""
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.imshow(hillshade, origin="lower", extent=extent, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.5)
    im = ax.imshow(np.ma.masked_invalid(dem), origin="lower", extent=extent,
                   cmap="terrain", alpha=0.7)
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Elevation (m)", fontsize=11)

    marker_colors = ["#e41a1c", "#377eb8", "#2ca02c"]
    for i, (xk, yk, name) in enumerate(inflow_pos):
        color = marker_colors[i] if i < len(marker_colors) else "red"
        ax.plot(xk, yk, "D", color=color, markersize=12,
                markeredgecolor="black", markeredgewidth=1.5, zorder=10)
        ax.annotate(name, (xk, yk), textcoords="offset points",
                    xytext=(8, 8), fontsize=10, fontweight="bold",
                    color=color, bbox=dict(boxstyle="round,pad=0.2",
                                           fc="white", ec=color, alpha=0.8))

    nrows, ncols = dem.shape
    ax.set_title(f"v11 DEM + Inflow Locations | {ncols}x{nrows} cells",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    fig.tight_layout()
    fig.savefig(str(VIS_DIR / "v11_dem_culverts.png"), dpi=DPI,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  Saved: v11_dem_culverts.png")


def plot_boundary_mask(x, y, extent, inflow_pos):
    """Boundary mask showing zone 1, 2, and 3 cells."""
    mask_path = V11_INPUT / "fluvbound_mask_v11.nc"
    if not mask_path.exists():
        print("  Skipping boundary mask (not found)")
        return

    mask, _, _ = load_nc(mask_path)
    n_zones = int(np.nanmax(mask))
    fig, ax = plt.subplots(figsize=(14, 10))
    im = ax.imshow(np.ma.masked_where(mask == 0, mask), origin="lower",
                   extent=extent, cmap="Set1", vmin=0.5, vmax=n_zones + 0.5,
                   interpolation="nearest")
    ticks = list(range(1, n_zones + 1))
    zone_labels = ["Zone 1 (Culvert 1)", "Zone 2 (Culvert 2)", "Zone 3 (Western Wadi)"]
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02, ticks=ticks)
    cbar.set_label("Boundary Zone", fontsize=11)
    cbar.set_ticklabels(zone_labels[:n_zones])

    marker_colors = ["#e41a1c", "#377eb8", "#2ca02c"]
    for i, (xk, yk, name) in enumerate(inflow_pos):
        color = marker_colors[i] if i < len(marker_colors) else "red"
        ax.plot(xk, yk, "D", color=color, markersize=12,
                markeredgecolor="black", markeredgewidth=1.5, zorder=10)
        ax.annotate(name, (xk, yk), textcoords="offset points",
                    xytext=(8, 8), fontsize=10, fontweight="bold", color=color)

    ax.set_title(f"v11 Fluvial Boundary Mask ({n_zones} zones)", fontsize=13, fontweight="bold")
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")
    fig.tight_layout()
    fig.savefig(str(VIS_DIR / "v11_boundary_mask.png"), dpi=DPI,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  Saved: v11_boundary_mask.png")


def visualize_inputs():
    """Generate all input verification plots."""
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading reference rasters...")
    dem, x, y = load_nc(V10_INPUT / "dem.nc")
    hillshade = make_hillshade(dem)

    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    extent = [float(x_km[0]), float(x_km[-1]),
              float(y_km[0]), float(y_km[-1])]
    all_pos = inflow_xy_km(x, y)

    print("\nGenerating v11 input verification plots...")
    plot_dem_with_culverts(dem, hillshade, x_km, y_km, extent, all_pos)
    plot_boundary_mask(x, y, extent, all_pos)
    plot_watershed_overlay()
    plot_wadi_culvert_assignment()
    plot_rainfall_comparison()
    plot_hydrograph_comparison()

    print(f"\nAll input plots saved to {VIS_DIR}/")


# =============================================================================
# FLOOD RESULTS
# =============================================================================

def get_inflow_flows(t_sec):
    """Get all inflow flows at time t_sec. Returns (q1, q2, q_west)."""
    hydro_path = V11_INPUT / "culvert_hydrographs_v11.npz"
    if not hydro_path.exists():
        return 0.0, 0.0, 0.0
    data = np.load(str(hydro_path))
    idx = int(t_sec / DT_INFLOW)
    q1_arr = data.get("q_Culvert1", np.zeros(1))
    q2_arr = data.get("q_Culvert2", np.zeros(1))
    qw_arr = data.get("q_WesternWadi", np.zeros(1))
    q1 = float(q1_arr[min(idx, len(q1_arr) - 1)])
    q2 = float(q2_arr[min(idx, len(q2_arr) - 1)])
    qw = float(qw_arr[min(idx, len(qw_arr) - 1)])
    return q1, q2, qw


def plot_flood_frame(wd, channel, buildings, hillshade, extent, x_km, y_km,
                     t_sec, out_path, culv_pos, label=None):
    """Plot a single flood depth frame."""
    days = t_sec / 86400.0
    bldg = buildings > 0
    wet = wd > 0.01
    n_wet = int(np.sum(wet))
    n_bldg_wet = int(np.sum(wet & bldg))
    max_d = float(np.nanmax(wd)) if n_wet > 0 else 0.0
    pct = 100.0 * n_wet / wd.size

    # Mean depth at wet buildings
    mean_bldg_depth = 0.0
    if n_bldg_wet > 0:
        mean_bldg_depth = float(np.nanmean(wd[wet & bldg]))

    q1, q2, qw = get_inflow_flows(t_sec)

    fig, ax = plt.subplots(figsize=(14, 10))

    ax.imshow(hillshade, origin="lower", extent=extent, cmap="gray",
              vmin=0.3, vmax=1.0, alpha=0.6)

    wd_masked = np.ma.masked_where(wd < 0.01, wd)
    im = ax.imshow(wd_masked, origin="lower", extent=extent,
                   cmap=flood_cmap(), vmin=0, vmax=VMAX,
                   interpolation="nearest", alpha=0.85)

    if np.any(bldg):
        ax.contour(bldg.astype(float), levels=[0.5],
                   origin="lower", extent=extent,
                   colors=["red"], linewidths=0.6, alpha=0.7)

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
        f"v11 Compound Flood -- {time_str} | "
        f"Q1={q1:.0f} Q2={q2:.0f} Qw={qw:.0f} m³/s\n"
        f"Wet: {n_wet} ({pct:.1f}%) | "
        f"Buildings wet: {n_bldg_wet} (mean {mean_bldg_depth:.2f}m) | "
        f"Max: {max_d:.2f}m",
        fontsize=12, fontweight="bold"
    )
    ax.set_xlabel("x (km)")
    ax.set_ylabel("y (km)")

    handles = [
        plt.Line2D([0], [0], marker="D", color="w", markerfacecolor="red",
                   markeredgecolor="black", markersize=10, label="Culvert"),
        plt.Line2D([0], [0], color="red", lw=1, label="Buildings"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=9,
              framealpha=0.9, edgecolor="gray")

    fig.tight_layout()
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_building_damage_assessment(wd_max, buildings, x_km, y_km, extent,
                                    hillshade, culv_pos):
    """Building damage assessment based on max flood depth."""
    bldg = buildings > 0
    n_total_bldg = int(np.sum(bldg))

    # Depth thresholds for damage categories
    thresholds = [
        (0.01, "Any water"),
        (0.10, ">10cm"),
        (0.30, ">30cm"),
        (0.60, ">60cm (2ft target)"),
        (1.00, ">1m"),
        (2.00, ">2m"),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(20, 14))

    for idx, (thresh, label) in enumerate(thresholds):
        ax = axes[idx // 3, idx % 3]

        ax.imshow(hillshade, origin="lower", extent=extent, cmap="gray",
                  vmin=0.3, vmax=1.0, alpha=0.5)

        # Show flood above threshold
        wd_above = np.ma.masked_where(wd_max < thresh, wd_max)
        im = ax.imshow(wd_above, origin="lower", extent=extent,
                       cmap=flood_cmap(), vmin=0, vmax=VMAX,
                       interpolation="nearest", alpha=0.85)

        if np.any(bldg):
            ax.contour(bldg.astype(float), levels=[0.5],
                       origin="lower", extent=extent,
                       colors=["red"], linewidths=0.4, alpha=0.5)

        # Stats
        affected = (wd_max >= thresh) & bldg
        n_affected = int(np.sum(affected))
        pct = 100.0 * n_affected / max(n_total_bldg, 1)

        for xk, yk, name in culv_pos:
            ax.plot(xk, yk, "D", color="red", markersize=6,
                    markeredgecolor="black", markeredgewidth=0.8, zorder=10)

        ax.set_title(f"{label}\n{n_affected} buildings ({pct:.0f}%)",
                     fontsize=11, fontweight="bold")
        ax.set_xlabel("x (km)")
        ax.set_ylabel("y (km)")

    fig.suptitle(f"v11 Building Damage Assessment | "
                 f"Total buildings: {n_total_bldg}",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    out_path = VIS_DIR / "v11_building_damage.png"
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


def visualize_results():
    """Generate flood result visualizations."""
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading reference rasters...")
    dem, x, y = load_nc(V10_INPUT / "dem.nc")
    channel, _, _ = load_nc(V10_INPUT / "channel_mask.nc")
    buildings, _, _ = load_nc(V10_INPUT / "buildings.nc")

    # RIM2D output is y-flipped relative to input rasters.
    # Flip buildings/channel to match output grid for statistics.
    buildings = np.flipud(buildings)
    channel = np.flipud(channel)

    hillshade = make_hillshade(dem)
    x_km = (x - x[0]) / 1000.0
    y_km = (y - y[0]) / 1000.0
    extent = [float(x_km[0]), float(x_km[-1]),
              float(y_km[0]), float(y_km[-1])]
    culv_pos = inflow_xy_km(x, y)

    # Find output files
    wd_files = sorted(glob.glob(str(V11_OUTPUT / "nile_v11_wd_*[0-9].nc")))
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
        out_path = VIS_DIR / f"v11_flood_{t_sec:08d}.png"
        plot_flood_frame(wd, channel, buildings, hillshade, extent,
                         x_km, y_km, t_sec, out_path, culv_pos)
        frame_paths.append(str(out_path))

        if (i + 1) % 20 == 0 or i == len(wd_files) - 1:
            print(f"  [{i+1}/{len(wd_files)}] t={t_sec/86400:.1f}d")

    # Max depth frame
    max_path = V11_OUTPUT / "nile_v11_wd_max.nc"
    if max_path.exists():
        wd_max, _, _ = load_nc(max_path)
        out_max = VIS_DIR / "v11_flood_wd_max.png"
        plot_flood_frame(wd_max, channel, buildings, hillshade, extent,
                         x_km, y_km, SIM_DUR, out_max, culv_pos,
                         label="Max Depth (22d)")
        print("  Max depth frame saved")

        bldg = buildings > 0
        wet_bldg = (wd_max > 0.01) & bldg
        print(f"\n  --- v11 RESULTS SUMMARY ---")
        print(f"  Max depth overall: {np.nanmax(wd_max):.2f}m")
        print(f"  Buildings with water: {int(np.sum(wet_bldg))}")
        if np.any(wet_bldg):
            bldg_depths = wd_max[bldg & (wd_max > 0.01)]
            print(f"  Max depth at buildings: {float(np.nanmax(bldg_depths)):.2f}m")
            print(f"  Mean depth at wet buildings: "
                  f"{float(np.nanmean(bldg_depths)):.2f}m")
            # Count buildings above 0.6m target
            n_above_06 = int(np.sum((wd_max > 0.6) & bldg))
            print(f"  Buildings >0.6m (target): {n_above_06}")

        # Building damage assessment
        plot_building_damage_assessment(wd_max, buildings, x_km, y_km,
                                       extent, hillshade, culv_pos)

    # GIF animation
    if frame_paths:
        try:
            from PIL import Image
            print("\nCreating GIF animation...")
            images = [Image.open(fp) for fp in sorted(frame_paths)]
            gif_path = VIS_DIR / "v11_flood_animation.gif"
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
        description="v11 Basin-Derived Synthetic Hydrograph Visualization"
    )
    parser.add_argument("--inputs", action="store_true",
                        help="Verify input data (basin, rainfall, hydrograph)")
    parser.add_argument("--results", action="store_true",
                        help="Visualize simulation results + damage assessment")
    args = parser.parse_args()

    if not args.inputs and not args.results:
        print("Specify --inputs or --results (or both)")
        return

    if args.inputs:
        print("=" * 60)
        print("v11 Input Verification")
        print("=" * 60)
        visualize_inputs()

    if args.results:
        print("=" * 60)
        print("v11 Flood Results + Building Damage Assessment")
        print("=" * 60)
        visualize_results()


if __name__ == "__main__":
    main()
