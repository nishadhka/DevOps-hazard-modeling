#!/usr/bin/env python3
"""
Download Overture Maps road network (segment type) for the Abu Hamad v11
simulation domain and plot with road-class-based styling overlaid on
buildings, river network, and culvert locations.

Usage:
    cd /data/rim2d/nile_highres
    micromamba run -n zarrv3 python download_roads_v11.py
"""

import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import netCDF4
import numpy as np

WORK_DIR   = Path("/data/rim2d/nile_highres")
V10_DIR    = WORK_DIR / "v10"
V11_DIR    = WORK_DIR / "v11"
V10_INPUT  = V10_DIR / "input"
V11_INPUT  = V11_DIR / "input"
WS_DIR     = V10_INPUT / "watersheds"
VIS_DIR    = V11_DIR / "visualizations"

ROADS_PATH = V11_INPUT / "roads_overture.geojson"

# Abu Hamad v11 domain (west, south, east, north)
BBOX = "33.25,19.49,33.36,19.57"
DOMAIN_BBOX = {"west": 33.25, "south": 19.49, "east": 33.36, "north": 19.57}

DEM_EPSG = "EPSG:32636"
DPI = 150

CULVERTS = [
    {"name": "Culvert 1", "lat": 19.547450, "lon": 33.339139},
    {"name": "Culvert 2", "lat": 19.550000, "lon": 33.325906},
]

# Road class styling
ROAD_STYLES = {
    "motorway":    {"color": "#cc0000", "width": 2.5, "label": "Motorway / Trunk"},
    "primary":     {"color": "#e06600", "width": 1.8, "label": "Primary Road"},
    "secondary":   {"color": "#e6b800", "width": 1.2, "label": "Secondary Road"},
    "tertiary":    {"color": "#888888", "width": 0.7, "label": "Tertiary Road"},
    "residential": {"color": "#bbbbbb", "width": 0.4, "label": "Residential / Local"},
    "other":       {"color": "#dddddd", "width": 0.3, "label": "Other"},
}

CLASS_MAP = {
    "motorway": "motorway", "trunk": "motorway",
    "primary": "primary",
    "secondary": "secondary",
    "tertiary": "tertiary",
    "residential": "residential", "living_street": "residential",
    "unclassified": "residential", "service": "residential",
    "track": "other", "path": "other", "footway": "other",
    "cycleway": "other", "steps": "other", "pedestrian": "other",
}

# Stream order styles
STREAM_STYLES = {
    9: {"color": "#0033aa", "width": 3.5, "label": "Nile (Order 9)"},
    5: {"color": "#1a66ff", "width": 2.0, "label": "Large streams (Order 5)"},
    2: {"color": "#80b3ff", "width": 0.8, "label": "Wadis (Order 2)"},
}


def download_roads():
    """Download Overture road segments via overturemaps CLI."""
    if ROADS_PATH.exists():
        size_mb = ROADS_PATH.stat().st_size / 1e6
        print(f"  Using cached roads: {ROADS_PATH.name} ({size_mb:.1f} MB)")
        with open(str(ROADS_PATH)) as f:
            return json.load(f)

    print(f"  Downloading road segments (bbox={BBOX})...")
    V11_INPUT.mkdir(parents=True, exist_ok=True)
    cmd = [
        "overturemaps", "download",
        "--bbox", BBOX,
        "-t", "segment",
        "-f", "geojson",
        "-o", str(ROADS_PATH),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr}")
        raise RuntimeError("overturemaps download failed")

    size_mb = ROADS_PATH.stat().st_size / 1e6
    print(f"  Downloaded: {ROADS_PATH.name} ({size_mb:.1f} MB)")

    with open(str(ROADS_PATH)) as f:
        return json.load(f)


def categorize_roads(fc):
    """Split road features by class."""
    cats = {k: [] for k in ROAD_STYLES}
    for feat in fc.get("features", []):
        props = feat.get("properties", {})
        road_class = props.get("class", "")
        if not road_class:
            road_class = props.get("subtype", "other")
        style_key = CLASS_MAP.get(road_class, "other")
        cats[style_key].append(feat)
    for k, v in cats.items():
        if v:
            print(f"    {ROAD_STYLES[k]['label']}: {len(v)}")
    return cats


def load_river_network():
    """Load cached TDX-Hydro river network GeoJSON."""
    rn_path = V11_INPUT / "river_network_tdx_v2.geojson"
    if not rn_path.exists():
        print("  River network not found — run download_river_network.py first")
        return None
    with open(str(rn_path)) as f:
        fc = json.load(f)
    print(f"  Loaded river network: {len(fc['features'])} segments")
    return fc


def load_buildings_latlon():
    """Load buildings.nc (UTM) and convert to lat/lon arrays."""
    bldg_path = V10_INPUT / "buildings.nc"
    if not bldg_path.exists():
        print("  Buildings not found")
        return None, None, None
    from pyproj import Transformer
    ds = netCDF4.Dataset(str(bldg_path))
    bldg = ds.variables["Band1"][:].squeeze()
    x = ds.variables["x"][:]
    y = ds.variables["y"][:]
    ds.close()
    bldg_mask = np.where(bldg > 0, 1.0, np.nan)
    to_ll = Transformer.from_crs(DEM_EPSG, "EPSG:4326", always_xy=True)
    xx, yy = np.meshgrid(x, y)
    lons, lats = to_ll.transform(xx, yy)
    print(f"  Loaded buildings: {int(np.nansum(bldg > 0))} cells")
    return lons, lats, bldg_mask


def draw_lines(ax, geom, **kwargs):
    """Draw a LineString or MultiLineString geometry."""
    if geom["type"] == "LineString":
        lines = [geom["coordinates"]]
    elif geom["type"] == "MultiLineString":
        lines = geom["coordinates"]
    else:
        return
    for line in lines:
        xs = [c[0] for c in line]
        ys = [c[1] for c in line]
        ax.plot(xs, ys, **kwargs)


def draw_roads(ax, road_cats):
    draw_order = ["other", "residential", "tertiary", "secondary",
                  "primary", "motorway"]
    for style_key in draw_order:
        style = ROAD_STYLES[style_key]
        for feat in road_cats[style_key]:
            geom = feat.get("geometry")
            if geom is None:
                continue
            draw_lines(ax, geom, color=style["color"], linewidth=style["width"],
                       solid_capstyle="round", alpha=0.8, zorder=3)


def draw_rivers(ax, river_fc):
    if river_fc is None:
        return
    for feat in river_fc["features"]:
        so = feat["properties"].get("stream_order", 1)
        style = STREAM_STYLES.get(so, {"color": "#80b3ff", "width": 0.6})
        geom = feat["geometry"]
        draw_lines(ax, geom, color=style["color"], linewidth=style["width"],
                   solid_capstyle="round", alpha=0.9, zorder=4)


def plot_roads_only(road_cats, river_fc):
    """Plot 1: Roads + rivers + culverts on white background."""
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 12))

    draw_roads(ax, road_cats)
    draw_rivers(ax, river_fc)

    # Domain box
    bx = DOMAIN_BBOX
    ax.plot([bx["west"], bx["east"], bx["east"], bx["west"], bx["west"]],
            [bx["south"], bx["south"], bx["north"], bx["north"], bx["south"]],
            color="black", linewidth=2, linestyle="--", zorder=6)

    # Culverts
    culv_colors = ["#e41a1c", "#377eb8"]
    for i, cv in enumerate(CULVERTS):
        ax.plot(cv["lon"], cv["lat"], "D", color=culv_colors[i], markersize=12,
                markeredgecolor="black", markeredgewidth=1.5, zorder=10)
        ax.annotate(cv["name"], (cv["lon"], cv["lat"]),
                    textcoords="offset points", xytext=(10, 8),
                    fontsize=10, fontweight="bold", color=culv_colors[i],
                    bbox=dict(boxstyle="round,pad=0.3", fc="white",
                              ec=culv_colors[i], alpha=0.9))

    # Legend
    handles = []
    for so in [9, 5, 2]:
        s = STREAM_STYLES[so]
        handles.append(plt.Line2D([0], [0], color=s["color"],
                                  linewidth=s["width"] * 1.5, label=s["label"]))
    for key in ["motorway", "primary", "secondary", "tertiary", "residential"]:
        s = ROAD_STYLES[key]
        n = len(road_cats[key])
        if n:
            handles.append(plt.Line2D([0], [0], color=s["color"],
                                      linewidth=s["width"] * 1.5,
                                      label=f"{s['label']} ({n})"))
    handles.append(plt.Line2D([0], [0], color="black", linestyle="--",
                              linewidth=2, label="Simulation domain"))

    ax.legend(handles=handles, loc="upper left", fontsize=9,
              framealpha=0.95, edgecolor="gray")
    ax.set_title("Abu Hamad v11 — Road Network + River Network\n"
                 "Overture Maps segments | TDX-Hydro v2",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_xlim(bx["west"] - 0.005, bx["east"] + 0.005)
    ax.set_ylim(bx["south"] - 0.005, bx["north"] + 0.005)
    ax.set_aspect("equal")
    ax.grid(alpha=0.15, linestyle=":")
    fig.tight_layout()
    out = VIS_DIR / "v11_roads_rivers.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def plot_roads_buildings(road_cats, river_fc, bldg_lons, bldg_lats, bldg_mask):
    """Plot 2: Roads + buildings + rivers + culverts."""
    import matplotlib.colors as mcolors

    VIS_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(14, 12))

    # Buildings
    has_bldg = bldg_lons is not None
    if has_bldg:
        ax.pcolormesh(bldg_lons, bldg_lats, bldg_mask,
                      cmap=mcolors.ListedColormap(["#d95f02"]),
                      alpha=0.5, zorder=1, rasterized=True)

    draw_roads(ax, road_cats)
    draw_rivers(ax, river_fc)

    # Domain box
    bx = DOMAIN_BBOX
    ax.plot([bx["west"], bx["east"], bx["east"], bx["west"], bx["west"]],
            [bx["south"], bx["south"], bx["north"], bx["north"], bx["south"]],
            color="black", linewidth=2, linestyle="--", zorder=6)

    # Culverts
    culv_colors = ["#e41a1c", "#377eb8"]
    for i, cv in enumerate(CULVERTS):
        ax.plot(cv["lon"], cv["lat"], "D", color=culv_colors[i], markersize=12,
                markeredgecolor="black", markeredgewidth=1.5, zorder=10)
        ax.annotate(cv["name"], (cv["lon"], cv["lat"]),
                    textcoords="offset points", xytext=(10, 8),
                    fontsize=10, fontweight="bold", color=culv_colors[i],
                    bbox=dict(boxstyle="round,pad=0.3", fc="white",
                              ec=culv_colors[i], alpha=0.9))

    # Legend
    handles = []
    if has_bldg:
        handles.append(mpatches.Patch(facecolor="#d95f02", alpha=0.5,
                                      label="Buildings"))
    for so in [9, 5, 2]:
        s = STREAM_STYLES[so]
        handles.append(plt.Line2D([0], [0], color=s["color"],
                                  linewidth=s["width"] * 1.5, label=s["label"]))
    for key in ["motorway", "primary", "secondary", "tertiary", "residential"]:
        s = ROAD_STYLES[key]
        n = len(road_cats[key])
        if n:
            handles.append(plt.Line2D([0], [0], color=s["color"],
                                      linewidth=s["width"] * 1.5,
                                      label=f"{s['label']} ({n})"))
    handles.append(plt.Line2D([0], [0], color="black", linestyle="--",
                              linewidth=2, label="Simulation domain"))

    ax.legend(handles=handles, loc="upper left", fontsize=9,
              framealpha=0.95, edgecolor="gray")
    ax.set_title("Abu Hamad v11 — Buildings + Roads + River Network\n"
                 "Overture Maps | TDX-Hydro v2",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_xlim(bx["west"] - 0.005, bx["east"] + 0.005)
    ax.set_ylim(bx["south"] - 0.005, bx["north"] + 0.005)
    ax.set_aspect("equal")
    ax.grid(alpha=0.15, linestyle=":")
    fig.tight_layout()
    out = VIS_DIR / "v11_buildings_roads_rivers.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def main():
    print("=" * 60)
    print("Download & Plot Road Network — Overture Maps")
    print("Abu Hamad v11 case study")
    print("=" * 60)

    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("\nDownloading roads...")
    roads_fc = download_roads()
    n_roads = len(roads_fc.get("features", []))
    print(f"  {n_roads:,} road segments")

    print("\nCategorizing road classes...")
    road_cats = categorize_roads(roads_fc)

    print("\nLoading supporting layers...")
    river_fc = load_river_network()
    bldg_lons, bldg_lats, bldg_mask = load_buildings_latlon()

    print("\nPlot 1: Roads + rivers...")
    plot_roads_only(road_cats, river_fc)

    print("\nPlot 2: Buildings + roads + rivers...")
    plot_roads_buildings(road_cats, river_fc, bldg_lons, bldg_lats, bldg_mask)

    print("\n" + "=" * 60)
    print("Done!")
    print(f"  Outputs: {VIS_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
