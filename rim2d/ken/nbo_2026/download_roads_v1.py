#!/usr/bin/env python3
"""
Download Overture Maps road network (segment type) for the Nairobi v1
simulation domain and plot with road-class-based styling overlaid on
building footprints, river network, and watershed boundaries.

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python download_roads_v1.py
"""

import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

WORK_DIR   = Path("/data/rim2d/nbo_2026")
V1_DIR     = WORK_DIR / "v1"
WS_DIR     = V1_DIR / "input" / "watersheds"
OUT_DIR    = V1_DIR / "visualizations"
INPUT_DIR  = V1_DIR / "input"

# Output GeoJSON
ROADS_PATH = INPUT_DIR / "roads_overture.geojson"

# Nairobi v1 domain (west, south, east, north)
BBOX = "36.6,-1.402004,37.1,-1.098036"
DOMAIN_BBOX = {"west": 36.6, "south": -1.402004, "east": 37.1, "north": -1.098036}

DEM_EPSG = "EPSG:32737"
DPI = 150

# Road class styling (Overture 'subtype' / 'class' attribute hierarchy)
ROAD_STYLES = {
    "motorway":    {"color": "#cc0000", "width": 2.5, "label": "Motorway / Expressway"},
    "primary":     {"color": "#e06600", "width": 1.8, "label": "Primary Road"},
    "secondary":   {"color": "#e6b800", "width": 1.2, "label": "Secondary Road"},
    "tertiary":    {"color": "#888888", "width": 0.7, "label": "Tertiary Road"},
    "residential": {"color": "#bbbbbb", "width": 0.4, "label": "Residential / Local"},
    "other":       {"color": "#dddddd", "width": 0.3, "label": "Other"},
}

# Map Overture road class values → style keys
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

# Stream order styles (reused from download_river_network_v1.py)
STREAM_STYLES = {
    "major":  {"min_order": 7, "max_order": 99, "color": "#0033aa", "width": 3.5,
               "label": "Major Rivers (Order 7+)"},
    "large":  {"min_order": 5, "max_order": 7,  "color": "#1a66ff", "width": 2.2,
               "label": "Large Streams (Order 5-6)"},
    "medium": {"min_order": 3, "max_order": 5,  "color": "#4d8cff", "width": 1.2,
               "label": "Medium Streams (Order 3-4)"},
    "small":  {"min_order": 1, "max_order": 3,  "color": "#80b3ff", "width": 0.6,
               "label": "Small Streams (Order 1-2)"},
}


def download_roads():
    """Download Overture road segments via overturemaps CLI."""
    if ROADS_PATH.exists():
        size_mb = ROADS_PATH.stat().st_size / 1e6
        print(f"  Using cached roads: {ROADS_PATH.name} ({size_mb:.1f} MB)")
        with open(str(ROADS_PATH)) as f:
            return json.load(f)

    print(f"  Downloading road segments (bbox={BBOX})...")
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
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


def load_watersheds():
    """Load all entry watershed polygons at finest available level."""
    for level in [12, 10, 8, 6]:
        geojsons = sorted(WS_DIR.glob(f"entry*_level{level:02d}.geojson"))
        if geojsons:
            basin_geoms = []
            for gj in geojsons:
                with open(str(gj)) as f:
                    fc = json.load(f)
                basin_geoms.append(fc["features"][0]["geometry"])
            print(f"  Loaded {len(basin_geoms)} watershed polygons (level {level})")
            return basin_geoms, level
    return [], None


def load_river_network():
    """Load cached TDX-Hydro river network GeoJSON."""
    rn_path = INPUT_DIR / "river_network_tdx_v2.geojson"
    if not rn_path.exists():
        print("  River network not found — run download_river_network_v1.py first")
        return None
    with open(str(rn_path)) as f:
        fc = json.load(f)
    print(f"  Loaded river network: {len(fc['features'])} segments")
    return fc


def categorize_roads(fc):
    """Split road features by class."""
    cats = {k: [] for k in ROAD_STYLES}
    for feat in fc.get("features", []):
        props = feat.get("properties", {})
        # Overture road class is in properties.class or properties.road[].value
        road_class = props.get("class", "")
        if not road_class:
            # fallback: check subtype
            road_class = props.get("subtype", "other")
        style_key = CLASS_MAP.get(road_class, "other")
        cats[style_key].append(feat)
    for k, v in cats.items():
        if v:
            print(f"    {ROAD_STYLES[k]['label']}: {len(v)}")
    return cats


def categorize_rivers(fc):
    cats = {cat: [] for cat in STREAM_STYLES}
    for feat in fc["features"]:
        so = feat["properties"].get("stream_order", 1)
        for cat, style in STREAM_STYLES.items():
            if style["min_order"] <= so < style["max_order"]:
                cats[cat].append(feat)
                break
    return cats


def draw_watershed_outlines(ax, basin_geoms, basin_level, cmap):
    n = max(len(basin_geoms), 1)
    for i, geom in enumerate(basin_geoms):
        color = cmap(i / n)
        polys = ([geom["coordinates"]] if geom["type"] == "Polygon"
                 else geom["coordinates"])
        for j, poly in enumerate(polys):
            xs = [c[0] for c in poly[0]]
            ys = [c[1] for c in poly[0]]
            lbl = (f"Watersheds (level {basin_level})" if i == 0 and j == 0
                   else None)
            ax.plot(xs, ys, color=color, linewidth=1.4,
                    linestyle="--", alpha=0.9, label=lbl, zorder=5)


def draw_roads(ax, road_cats, draw_order):
    for style_key in draw_order:
        style = ROAD_STYLES[style_key]
        for feat in road_cats[style_key]:
            geom = feat.get("geometry")
            if geom is None:
                continue
            if geom["type"] == "LineString":
                lines = [geom["coordinates"]]
            elif geom["type"] == "MultiLineString":
                lines = geom["coordinates"]
            else:
                continue
            for line in lines:
                xs = [c[0] for c in line]
                ys = [c[1] for c in line]
                ax.plot(xs, ys, color=style["color"], linewidth=style["width"],
                        solid_capstyle="round", alpha=0.8, zorder=3)


def draw_rivers(ax, river_cats):
    draw_order = ["small", "medium", "large", "major"]
    for cat in draw_order:
        style = STREAM_STYLES[cat]
        for feat in river_cats[cat]:
            geom = feat["geometry"]
            lines = (geom["coordinates"] if geom["type"] == "MultiLineString"
                     else [geom["coordinates"]])
            for line in lines:
                xs = [c[0] for c in line]
                ys = [c[1] for c in line]
                ax.plot(xs, ys, color=style["color"], linewidth=style["width"],
                        solid_capstyle="round", alpha=0.9, zorder=4)


def domain_box(ax, color="black", lw=2.0):
    bx = DOMAIN_BBOX
    ax.plot(
        [bx["west"], bx["east"], bx["east"], bx["west"], bx["west"]],
        [bx["south"], bx["south"], bx["north"], bx["north"], bx["south"]],
        color=color, linewidth=lw, linestyle="--", zorder=6,
    )


def plot_roads_rivers_watersheds(road_cats, river_cats, basin_geoms, basin_level):
    """Plot 1: Roads + rivers + watershed outlines (white background)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cmap_ws = plt.cm.tab10
    road_draw_order = ["other", "residential", "tertiary", "secondary",
                       "primary", "motorway"]

    fig, ax = plt.subplots(figsize=(14, 12))

    # Watershed outlines
    draw_watershed_outlines(ax, basin_geoms, basin_level, cmap_ws)

    # Roads (coarse → fine)
    draw_roads(ax, road_cats, road_draw_order)

    # Rivers on top
    draw_rivers(ax, river_cats)

    # Domain box
    domain_box(ax)

    # Legend
    handles = []
    # Rivers
    for cat in ["major", "large", "medium", "small"]:
        s = STREAM_STYLES[cat]
        n = len(river_cats[cat])
        if n:
            handles.append(plt.Line2D([0], [0], color=s["color"],
                                      linewidth=s["width"] * 1.5,
                                      label=f"{s['label']} ({n})"))
    # Roads
    for key in ["motorway", "primary", "secondary", "tertiary", "residential"]:
        s = ROAD_STYLES[key]
        n = len(road_cats[key])
        if n:
            handles.append(plt.Line2D([0], [0], color=s["color"],
                                      linewidth=s["width"] * 1.5,
                                      label=f"{s['label']} ({n})"))
    handles.append(plt.Line2D([0], [0], color="black", linestyle="--",
                              linewidth=2, label="Simulation domain"))
    if basin_geoms:
        handles.append(plt.Line2D([0], [0], color=cmap_ws(0), linestyle="--",
                                  linewidth=1.4,
                                  label=f"Watershed boundaries (level {basin_level})"))

    ax.legend(handles=handles, loc="upper left", fontsize=9,
              framealpha=0.95, edgecolor="gray", fancybox=True)
    ax.set_title("Nairobi v1 — Roads + River Network + Watershed Boundaries\n"
                 "Overture Maps segments | TDX-Hydro v2 | HydroATLAS",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_xlim(DOMAIN_BBOX["west"] - 0.05, DOMAIN_BBOX["east"] + 0.05)
    ax.set_ylim(DOMAIN_BBOX["south"] - 0.05, DOMAIN_BBOX["north"] + 0.05)
    ax.set_aspect("equal")
    ax.grid(alpha=0.15, linestyle=":")
    fig.tight_layout()
    out = OUT_DIR / "v1_roads_rivers_watersheds.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def plot_roads_buildings(road_cats, basin_geoms, basin_level, river_cats):
    """Plot 2: Buildings (nbo.geojson) + roads + rivers + watershed outlines."""
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Polygon as MplPolygon

    cmap_ws = plt.cm.tab10
    road_draw_order = ["other", "residential", "tertiary", "secondary",
                       "primary", "motorway"]

    nbo_path = WORK_DIR / "nbo.geojson"
    fig, ax = plt.subplots(figsize=(14, 12))

    n_bld = 0
    if nbo_path.exists():
        print("  Loading building footprints (nbo.geojson)...")
        with open(str(nbo_path)) as f:
            nbo_fc = json.load(f)
        n_bld = len(nbo_fc["features"])
        print(f"    {n_bld:,} building polygons")
        patches = []
        for feat in nbo_fc["features"]:
            geom = feat["geometry"]
            if geom is None:
                continue
            polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                     else [geom["coordinates"]])
            for poly in polys:
                ring = np.array(poly[0])
                patches.append(MplPolygon(ring[:, :2], closed=True))
        pc = PatchCollection(patches, facecolor="#f4a261", edgecolor="none",
                             alpha=0.5, zorder=1)
        ax.add_collection(pc)

    # Watershed outlines
    draw_watershed_outlines(ax, basin_geoms, basin_level, cmap_ws)

    # Roads
    draw_roads(ax, road_cats, road_draw_order)

    # Rivers on top
    draw_rivers(ax, river_cats)

    # Domain box
    domain_box(ax, color="black")

    # Legend
    handles = []
    if n_bld:
        handles.append(mpatches.Patch(facecolor="#f4a261", alpha=0.6,
                                      label=f"Building footprints ({n_bld:,})"))
    for key in ["motorway", "primary", "secondary", "tertiary", "residential"]:
        s = ROAD_STYLES[key]
        n = len(road_cats[key])
        if n:
            handles.append(plt.Line2D([0], [0], color=s["color"],
                                      linewidth=s["width"] * 1.5,
                                      label=f"{s['label']} ({n})"))
    for cat in ["major", "large", "medium", "small"]:
        s = STREAM_STYLES[cat]
        n = len(river_cats[cat])
        if n:
            handles.append(plt.Line2D([0], [0], color=s["color"],
                                      linewidth=s["width"] * 1.5,
                                      label=f"{s['label']} ({n})"))
    handles.append(plt.Line2D([0], [0], color="black", linestyle="--",
                              linewidth=2, label="Simulation domain"))
    if basin_geoms:
        handles.append(plt.Line2D([0], [0], color=cmap_ws(0), linestyle="--",
                                  linewidth=1.4,
                                  label=f"Watershed boundaries (level {basin_level})"))

    ax.legend(handles=handles, loc="upper left", fontsize=9,
              framealpha=0.95, edgecolor="gray", fancybox=True)
    ax.set_title("Nairobi v1 — Buildings + Roads + River Network + Watershed Boundaries\n"
                 "Microsoft ML Buildings | Overture Maps | TDX-Hydro v2 | HydroATLAS",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_xlim(DOMAIN_BBOX["west"] - 0.01, DOMAIN_BBOX["east"] + 0.01)
    ax.set_ylim(DOMAIN_BBOX["south"] - 0.01, DOMAIN_BBOX["north"] + 0.01)
    ax.set_aspect("equal")
    ax.grid(alpha=0.15, linestyle=":")
    fig.tight_layout()
    out = OUT_DIR / "v1_buildings_roads_rivers_watersheds.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def main():
    print("=" * 60)
    print("Download & Plot Road Network — Overture Maps")
    print("Nairobi v1 case study")
    print("=" * 60)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\nDownloading roads...")
    roads_fc = download_roads()
    n_roads = len(roads_fc.get("features", []))
    print(f"  {n_roads:,} road segments")

    print("\nCategorizing road classes...")
    road_cats = categorize_roads(roads_fc)

    print("\nLoading supporting layers...")
    basin_geoms, basin_level = load_watersheds()
    river_fc = load_river_network()
    river_cats = categorize_rivers(river_fc) if river_fc else {c: [] for c in STREAM_STYLES}

    print("\nPlot 1: Roads + rivers + watershed outlines...")
    plot_roads_rivers_watersheds(road_cats, river_cats, basin_geoms, basin_level)

    print("\nPlot 2: Buildings + roads + rivers + watershed outlines...")
    plot_roads_buildings(road_cats, basin_geoms, basin_level, river_cats)

    print("\n" + "=" * 60)
    print("Done!")
    print(f"  Outputs: {OUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
