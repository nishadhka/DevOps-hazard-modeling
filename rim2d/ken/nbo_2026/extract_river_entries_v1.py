#!/usr/bin/env python3
"""
Extract one river entry point per TDX-Hydro v2 river segment that lies
within or crosses into the Nairobi v1 simulation domain.

Three categories:
  CROSSING  — segment whose upstream end is outside the domain but crosses in;
              entry point = first coordinate inside the domain (boundary crossing)
  HEADWATER — segment entirely inside the domain with no upstream neighbour
              inside the domain; entry point = segment start (upstream end)
  INTERIOR  — segment entirely inside with upstream neighbours; these are
              included but flagged so they can be filtered if only boundary
              inflows are desired

One lat/lon is assigned per segment (by linkno). No deduplication — every
river in the domain gets a point.

Only segments with stream_order >= MIN_ORDER are included.

Outputs:
  v1/input/river_entries_v1.csv      — full entry point table
  v1/input/river_entries_v1.geojson  — GeoJSON points
  v1/visualizations/v1_river_entries.png  — map coloured by stream order

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python extract_river_entries_v1.py
"""

import json
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

WORK_DIR  = Path("/data/rim2d/nbo_2026")
V1_DIR    = WORK_DIR / "v1"
INPUT_DIR = V1_DIR / "input"
VIS_DIR   = V1_DIR / "visualizations"
WS_DIR    = INPUT_DIR / "watersheds"

RIVER_NET_PATH = INPUT_DIR / "river_network_tdx_v2.geojson"

DOMAIN = {"west": 36.6, "south": -1.402004, "east": 37.1, "north": -1.098036}

# Minimum stream order to include
MIN_ORDER = 2

DPI = 150

# Colour per stream order for scatter plot
ORDER_COLORS = {2: "#80b3ff", 3: "#4d8cff", 4: "#1a66ff", 5: "#0033aa"}
ORDER_SIZES  = {2: 20, 3: 40, 4: 70, 5: 110}

STREAM_STYLES = {
    "major":  {"min_order": 7, "max_order": 99, "color": "#0033aa", "width": 3.5},
    "large":  {"min_order": 5, "max_order": 7,  "color": "#1a66ff", "width": 2.2},
    "medium": {"min_order": 3, "max_order": 5,  "color": "#4d8cff", "width": 1.2},
    "small":  {"min_order": 1, "max_order": 3,  "color": "#80b3ff", "width": 0.6},
}


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def inside(lon, lat):
    return (DOMAIN["west"] <= lon <= DOMAIN["east"] and
            DOMAIN["south"] <= lat <= DOMAIN["north"])


def get_all_coords(feat):
    """Return flat list of (lon, lat) coords for the segment."""
    geom = feat["geometry"]
    lines = (geom["coordinates"] if geom["type"] == "MultiLineString"
             else [geom["coordinates"]])
    return [(c[0], c[1]) for line in lines for c in line]


def get_start_coord(feat):
    """First coordinate of the segment (upstream end in TDX-Hydro)."""
    geom = feat["geometry"]
    lines = (geom["coordinates"] if geom["type"] == "MultiLineString"
             else [geom["coordinates"]])
    return lines[0][0][0], lines[0][0][1]


def first_inside_coord(feat):
    """First coordinate that lies inside the domain (for crossing segments)."""
    for lon, lat in get_all_coords(feat):
        if inside(lon, lat):
            return lon, lat
    return None


def midpoint_inside(feat):
    """Midpoint of the portion of the segment inside the domain."""
    pts = [(lon, lat) for lon, lat in get_all_coords(feat) if inside(lon, lat)]
    if not pts:
        return None
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    return sum(lons) / len(lons), sum(lats) / len(lats)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_segments(fc):
    """
    Classify each segment and assign one entry point per segment.

    Returns list of dicts with keys:
        entry_id, linkno, stream_order, lon, lat, category
    """
    # Build set of linknos whose start is inside the domain
    # (to identify headwaters vs interior segments)
    starts_inside = set()
    for feat in fc["features"]:
        lon, lat = get_start_coord(feat)
        if inside(lon, lat):
            starts_inside.add(feat["properties"]["linkno"])

    # All end-points inside domain → which linknos drain into another inside segment
    # (i.e. their end-coord is the start of another inside segment)
    # We approximate: a segment is a headwater if none of the other segments'
    # end-points coincide with its start-point within a small tolerance.
    end_coords = set()
    for feat in fc["features"]:
        coords = get_all_coords(feat)
        lon, lat = coords[-1]
        end_coords.add((round(lon, 4), round(lat, 4)))

    entries = []
    for feat in fc["features"]:
        so = feat["properties"]["stream_order"]
        linkno = feat["properties"]["linkno"]
        if so < MIN_ORDER:
            continue

        coords = get_all_coords(feat)
        n_inside = sum(1 for lon, lat in coords if inside(lon, lat))
        total    = len(coords)

        if n_inside == 0:
            continue  # fully outside

        if n_inside < total:
            # CROSSING — enters domain from outside
            lon, lat = first_inside_coord(feat)
            category = "crossing"
        else:
            # Fully inside — check if it is a headwater
            start_lon, start_lat = coords[0]
            start_key = (round(start_lon, 4), round(start_lat, 4))
            if start_key not in end_coords:
                category = "headwater"
            else:
                category = "interior"
            # Use midpoint of segment for interior/headwater
            lon, lat = midpoint_inside(feat)

        entries.append({
            "linkno":       linkno,
            "stream_order": so,
            "lon":          round(lon, 6),
            "lat":          round(lat, 6),
            "category":     category,
        })

    # Assign IDs sorted by stream order desc then lon
    entries.sort(key=lambda e: (-e["stream_order"], e["lon"]))
    for i, e in enumerate(entries, start=1):
        e["entry_id"] = i

    return entries


# ---------------------------------------------------------------------------
# Save outputs
# ---------------------------------------------------------------------------

def save_csv(entries):
    path = INPUT_DIR / "river_entries_v1.csv"
    fields = ["entry_id", "category", "stream_order", "lon", "lat", "linkno"]
    with open(str(path), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(entries)
    print(f"  Saved: {path.name}  ({len(entries)} entries)")


def save_geojson(entries):
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]},
            "properties": {k: v for k, v in e.items() if k not in ("lon", "lat")},
        }
        for e in entries
    ]
    path = INPUT_DIR / "river_entries_v1.geojson"
    with open(str(path), "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=2)
    print(f"  Saved: {path.name}")


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def load_watersheds():
    for level in [12, 10, 8, 6]:
        gjs = sorted(WS_DIR.glob(f"entry*_level{level:02d}.geojson"))
        if gjs:
            geoms = []
            for gj in gjs:
                with open(str(gj)) as f:
                    fc_ws = json.load(f)
                geoms.append(fc_ws["features"][0]["geometry"])
            return geoms, level
    return [], None


def draw_rivers(ax, fc):
    for feat in fc["features"]:
        so = feat["properties"]["stream_order"]
        geom = feat["geometry"]
        lines = (geom["coordinates"] if geom["type"] == "MultiLineString"
                 else [geom["coordinates"]])
        for s in STREAM_STYLES.values():
            if s["min_order"] <= so < s["max_order"]:
                col, lw = s["color"], s["width"]
                break
        for line in lines:
            xs = [c[0] for c in line]
            ys = [c[1] for c in line]
            ax.plot(xs, ys, color=col, linewidth=lw,
                    solid_capstyle="round", alpha=0.7, zorder=2)


def draw_watershed_outlines(ax, basin_geoms, basin_level):
    cmap = plt.cm.tab10
    n = max(len(basin_geoms), 1)
    for i, geom in enumerate(basin_geoms):
        color = cmap(i / n)
        polys = ([geom["coordinates"]] if geom["type"] == "Polygon"
                 else geom["coordinates"])
        for j, poly in enumerate(polys):
            xs = [c[0] for c in poly[0]]
            ys = [c[1] for c in poly[0]]
            lbl = (f"Watershed outlines (level {basin_level})"
                   if i == 0 and j == 0 else None)
            ax.plot(xs, ys, color=color, linewidth=1.1,
                    linestyle="--", alpha=0.6, label=lbl, zorder=3)


def visualize(entries, fc, basin_geoms, basin_level):
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    # Split by category
    cats = {"crossing": [], "headwater": [], "interior": []}
    for e in entries:
        cats[e["category"]].append(e)

    cat_style = {
        "crossing":  {"marker": "^", "color": "#cc0000",  "size": 70,  "label": "Crossing (domain boundary)"},
        "headwater": {"marker": "D", "color": "#e06600",  "size": 55,  "label": "Headwater (starts in domain)"},
        "interior":  {"marker": "o", "color": "#1a66ff",  "size": 35,  "label": "Interior node (mid-segment)"},
    }

    fig, axes = plt.subplots(1, 2, figsize=(22, 12))

    for ax_idx, ax in enumerate(axes):
        # Watershed outlines
        draw_watershed_outlines(ax, basin_geoms, basin_level)

        # River network
        draw_rivers(ax, fc)

        # Domain box
        bx = DOMAIN
        ax.plot(
            [bx["west"], bx["east"], bx["east"], bx["west"], bx["west"]],
            [bx["south"], bx["south"], bx["north"], bx["north"], bx["south"]],
            color="black", linewidth=2.2, linestyle="--", zorder=6,
            label="Simulation domain",
        )

        if ax_idx == 0:
            # Left panel: colour by category
            for cat, pts in cats.items():
                s = cat_style[cat]
                if not pts:
                    continue
                lons = [p["lon"] for p in pts]
                lats = [p["lat"] for p in pts]
                ax.scatter(lons, lats, marker=s["marker"], c=s["color"],
                           s=s["size"], edgecolors="white", linewidths=0.6,
                           zorder=10, label=f"{s['label']} ({len(pts)})")
                for p in pts:
                    ax.annotate(str(p["entry_id"]), (p["lon"], p["lat"]),
                                textcoords="offset points", xytext=(3, 3),
                                fontsize=5.5, color=s["color"],
                                bbox=dict(boxstyle="round,pad=0.1",
                                          fc="white", ec=s["color"],
                                          alpha=0.65))
            ax.set_title(
                f"Nairobi v1 — All River Entry Points by Category\n"
                f"{len(entries)} points | {len(cats['crossing'])} crossing, "
                f"{len(cats['headwater'])} headwater, {len(cats['interior'])} interior",
                fontsize=12, fontweight="bold",
            )
        else:
            # Right panel: colour by stream order
            for so in sorted(ORDER_COLORS.keys(), reverse=True):
                pts = [e for e in entries if e["stream_order"] == so]
                if not pts:
                    continue
                lons = [p["lon"] for p in pts]
                lats = [p["lat"] for p in pts]
                ax.scatter(lons, lats, marker="o",
                           c=ORDER_COLORS[so], s=ORDER_SIZES[so],
                           edgecolors="white", linewidths=0.5,
                           zorder=10, label=f"Order {so} ({len(pts)})")
                for p in pts:
                    ax.annotate(str(p["entry_id"]), (p["lon"], p["lat"]),
                                textcoords="offset points", xytext=(3, 3),
                                fontsize=5.5, color=ORDER_COLORS[so],
                                bbox=dict(boxstyle="round,pad=0.1",
                                          fc="white", ec=ORDER_COLORS[so],
                                          alpha=0.65))
            ax.set_title(
                f"Nairobi v1 — All River Entry Points by Stream Order\n"
                f"{len(entries)} points | orders {MIN_ORDER}–5",
                fontsize=12, fontweight="bold",
            )

        # Shared formatting
        ax.legend(loc="upper left", fontsize=9, framealpha=0.95,
                  edgecolor="gray", fancybox=True)
        ax.set_xlabel("Longitude", fontsize=11)
        ax.set_ylabel("Latitude", fontsize=11)
        ax.set_xlim(DOMAIN["west"] - 0.05, DOMAIN["east"] + 0.05)
        ax.set_ylim(DOMAIN["south"] - 0.05, DOMAIN["north"] + 0.05)
        ax.set_aspect("equal")
        ax.grid(alpha=0.2, linestyle=":")

    fig.tight_layout()
    out = VIS_DIR / "v1_river_entries.png"
    fig.savefig(str(out), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Extract All River Entry Points from TDX-Hydro v2 Network")
    print(f"  Domain: W={DOMAIN['west']} E={DOMAIN['east']} "
          f"S={DOMAIN['south']} N={DOMAIN['north']}")
    print(f"  Min stream order: {MIN_ORDER}")
    print("=" * 60)

    with open(str(RIVER_NET_PATH)) as f:
        fc = json.load(f)
    print(f"  Loaded {len(fc['features'])} river segments")

    print("\nClassifying segments...")
    entries = classify_segments(fc)

    cats = {"crossing": 0, "headwater": 0, "interior": 0}
    for e in entries:
        cats[e["category"]] += 1
    print(f"  Total entry points: {len(entries)}")
    print(f"    crossing:  {cats['crossing']}")
    print(f"    headwater: {cats['headwater']}")
    print(f"    interior:  {cats['interior']}")

    print()
    print(f"  {'ID':<4} {'Cat':<10} {'Order':>5} {'Lon':>10} {'Lat':>10}")
    print("  " + "-" * 44)
    for e in entries:
        print(f"  {e['entry_id']:<4} {e['category']:<10} "
              f"{e['stream_order']:>5} {e['lon']:>10.5f} {e['lat']:>10.5f}")

    print("\nSaving outputs...")
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_csv(entries)
    save_geojson(entries)

    print("\nLoading watershed polygons...")
    basin_geoms, basin_level = load_watersheds()

    print("\nGenerating visualization...")
    visualize(entries, fc, basin_geoms, basin_level)

    print("\n" + "=" * 60)
    print("Done.")
    print("  Next: feed river_entries_v1.csv into run_v1_synthetic_flood.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
