#!/usr/bin/env python3
"""
Download river network from TIPG API and plot with stream-order-based styling.

Uses the ea_river_networks_tdx_v2 collection (GEOGloWS/TDX-Hydro v2) served
via OGC API Features. Downloads GeoJSON for the Nairobi v1 basin extent and
renders a publication-quality map with line widths proportional to stream order.

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python download_river_network_v1.py
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import requests

WORK_DIR = Path("/data/rim2d/nbo_2026")
V1_DIR   = WORK_DIR / "v1"
WS_DIR   = V1_DIR / "input" / "watersheds"
OUT_DIR  = V1_DIR / "visualizations"

API_BASE   = "https://tipg-tiler-template.replit.app"
COLLECTION = "public.ea_river_networks_tdx_v2"
ITEMS_URL  = f"{API_BASE}/collections/{COLLECTION}/items"

# Nairobi v1 domain bbox (lat/lon WGS84)
DOMAIN_BBOX = {"west": 36.6, "south": -1.402004, "east": 37.1, "north": -1.098036}

# UTM 37S EPSG for DEM hillshade reprojection
DEM_EPSG = "EPSG:32737"

# River entry points (auto-detected by run_v1_river_inflow.py)
ENTRY_CSV = V1_DIR / "input" / "river_entry_points.csv"

DPI = 150

# Stream order styling
STREAM_STYLES = {
    "major":  {"min_order": 7, "max_order": 99, "color": "#0033aa",
               "width": 3.5, "label": "Major Rivers (Order 7+)"},
    "large":  {"min_order": 5, "max_order": 7,  "color": "#1a66ff",
               "width": 2.2, "label": "Large Streams (Order 5-6)"},
    "medium": {"min_order": 3, "max_order": 5,  "color": "#4d8cff",
               "width": 1.2, "label": "Medium Streams (Order 3-4)"},
    "small":  {"min_order": 1, "max_order": 3,  "color": "#80b3ff",
               "width": 0.6, "label": "Small Streams (Order 1-2)"},
}


def get_basin_bbox():
    """Get bounding box from the finest watershed GeoJSON available (any entry)."""
    # Try to build a merged bbox across all entry geojsons at finest level
    all_lons, all_lats = [], []
    found_level = None
    basin_geoms = []

    for level in [12, 10, 8, 6]:
        geojsons = sorted(WS_DIR.glob(f"entry*_level{level:02d}.geojson"))
        if geojsons:
            found_level = level
            for gj_path in geojsons:
                with open(str(gj_path)) as f:
                    fc = json.load(f)
                feat = fc["features"][0]
                basin_geoms.append(feat["geometry"])
                geom = feat["geometry"]
                coords = []
                if geom["type"] == "Polygon":
                    coords = geom["coordinates"][0]
                elif geom["type"] == "MultiPolygon":
                    for poly in geom["coordinates"]:
                        coords.extend(poly[0])
                all_lons.extend(c[0] for c in coords)
                all_lats.extend(c[1] for c in coords)
            break

    if all_lons:
        bbox = {
            "west":  min(all_lons), "east": max(all_lons),
            "south": min(all_lats), "north": max(all_lats),
        }
        print(f"Basin bbox (level {found_level}, {len(basin_geoms)} entries): "
              f"W={bbox['west']:.3f} E={bbox['east']:.3f} "
              f"S={bbox['south']:.3f} N={bbox['north']:.3f}")
        return bbox, basin_geoms, found_level

    # Fallback: use domain bbox with generous buffer
    print("No watershed GeoJSON found — using domain bbox with 0.5-deg buffer")
    return {
        "west":  DOMAIN_BBOX["west"]  - 0.5,
        "east":  DOMAIN_BBOX["east"]  + 0.5,
        "south": DOMAIN_BBOX["south"] - 0.5,
        "north": DOMAIN_BBOX["north"] + 0.5,
    }, [], None


def load_entry_points():
    """Load river entry points from CSV."""
    import csv
    if not ENTRY_CSV.exists():
        return []
    entries = []
    with open(str(ENTRY_CSV)) as f:
        for row in csv.DictReader(f):
            entries.append({
                "name": f"Entry {row['entry_id']}",
                "id":   int(row["entry_id"]),
                "lat":  float(row["lat"]),
                "lon":  float(row["lon"]),
            })
    return entries


def download_river_network(bbox):
    """Download all river features within bbox from TIPG API."""
    bbox_str = (f"{bbox['west']},{bbox['south']},"
                f"{bbox['east']},{bbox['north']}")
    all_features = []
    offset = 0
    limit  = 100

    print(f"\nDownloading river network from TIPG API...")
    print(f"  bbox: {bbox_str}")

    while True:
        params = {"bbox": bbox_str, "limit": limit, "offset": offset}
        resp = requests.get(ITEMS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        total    = data.get("numberMatched", 0)
        all_features.extend(features)

        print(f"  Fetched {len(all_features)}/{total} features (offset={offset})")

        if len(all_features) >= total or not features:
            break
        offset += limit

    print(f"  Total features downloaded: {len(all_features)}")

    orders = {}
    for f in all_features:
        so = f["properties"].get("stream_order", 0)
        orders[so] = orders.get(so, 0) + 1
    for so in sorted(orders.keys()):
        print(f"    Stream order {so}: {orders[so]} segments")

    return {"type": "FeatureCollection", "features": all_features}


def save_geojson(fc, out_path):
    with open(str(out_path), "w") as f:
        json.dump(fc, f)
    n = len(fc["features"])
    size_kb = out_path.stat().st_size / 1024
    print(f"  Saved: {out_path.name} ({n} features, {size_kb:.0f} KB)")


def draw_watersheds_outline(ax, basin_geoms, basin_level, cmap, alpha=1.0):
    """Draw watershed boundaries as outlines only (no fill)."""
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
                    linestyle="--", alpha=alpha, label=lbl, zorder=4)


def draw_rivers(ax, categorized, draw_order, colors=None):
    """Draw river segments styled by stream order."""
    for cat in draw_order:
        style = STREAM_STYLES[cat]
        col = colors[cat] if colors else style["color"]
        for feat in categorized[cat]:
            geom = feat["geometry"]
            lines = (geom["coordinates"] if geom["type"] == "MultiLineString"
                     else [geom["coordinates"]])
            for line in lines:
                xs = [c[0] for c in line]
                ys = [c[1] for c in line]
                ax.plot(xs, ys, color=col,
                        linewidth=style["width"], solid_capstyle="round",
                        alpha=0.9, zorder=3)


def plot_river_network(fc, basin_geoms, basin_level, entries):
    """Two plots: clean river map, and river network on DEM hillshade."""
    import netCDF4

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    from pyproj import Transformer

    # Categorize by stream order
    categorized = {cat: [] for cat in STREAM_STYLES}
    for feat in fc["features"]:
        so = feat["properties"].get("stream_order", 1)
        for cat, style in STREAM_STYLES.items():
            if style["min_order"] <= so < style["max_order"]:
                categorized[cat].append(feat)
                break

    draw_order = ["small", "medium", "large", "major"]
    n_total = len(fc["features"])
    cmap_ws = plt.cm.tab10
    n_ws = max(len(basin_geoms), 1)

    # UTM → lat/lon transformer (needed for buildings.nc extent)
    to_ll = Transformer.from_crs(DEM_EPSG, "EPSG:4326", always_xy=True)

    # ---- Plot 1: Watershed outlines + rivers + buildings.nc raster ----
    bld_path = V1_DIR / "input" / "buildings.nc"
    fig, ax = plt.subplots(figsize=(14, 12))

    if bld_path.exists():
        ds = netCDF4.Dataset(str(bld_path))
        x_utm = np.array(ds["x"][:])
        y_utm = np.array(ds["y"][:])
        vname = [v for v in ds.variables if v not in ("x", "y")][0]
        bld = np.array(ds[vname][:], dtype=np.float32)
        ds.close()
        bld_masked = np.ma.masked_where(bld < 0.5, bld)
        lon_min, lat_min = to_ll.transform(float(x_utm[0]),  float(y_utm[0]))
        lon_max, lat_max = to_ll.transform(float(x_utm[-1]), float(y_utm[-1]))
        extent_ll = [lon_min, lon_max, lat_min, lat_max]
        ax.imshow(bld_masked, origin="lower", extent=extent_ll,
                  cmap="Oranges", vmin=0, vmax=1, alpha=0.6, zorder=1,
                  interpolation="nearest")

    # Watershed outlines (no fill)
    draw_watersheds_outline(ax, basin_geoms, basin_level, cmap_ws)

    # Rivers
    draw_rivers(ax, categorized, draw_order)

    # Domain box
    bx = DOMAIN_BBOX
    ax.plot(
        [bx["west"], bx["east"], bx["east"], bx["west"], bx["west"]],
        [bx["south"], bx["south"], bx["north"], bx["north"], bx["south"]],
        color="black", linewidth=2.5, linestyle="--",
        label="Simulation domain", zorder=5,
    )

    handles = []
    for cat in reversed(draw_order):
        style = STREAM_STYLES[cat]
        n = len(categorized[cat])
        handles.append(plt.Line2D(
            [0], [0], color=style["color"], linewidth=style["width"] * 1.5,
            label=f"{style['label']} ({n})",
        ))
    handles.append(plt.Line2D([0], [0], color="black", linestyle="--",
                              linewidth=2.5, label="Simulation domain"))
    if basin_geoms:
        handles.append(plt.Line2D([0], [0], color=cmap_ws(0), linestyle="--",
                                  linewidth=1.4,
                                  label=f"Watershed boundaries (level {basin_level})"))
    if bld_path.exists():
        handles.append(mpatches.Patch(facecolor="darkorange", alpha=0.6,
                                      label="Buildings (30 m grid)"))

    ax.legend(handles=handles, loc="upper left", fontsize=10,
              framealpha=0.95, edgecolor="gray", fancybox=True)
    ax.set_title(f"Nairobi — Watershed Boundaries + River Network + Buildings\n"
                 f"{n_total} TDX-Hydro v2 segments | HydroATLAS level {basin_level}",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_aspect("equal")
    ax.grid(alpha=0.2, linestyle=":")
    fig.tight_layout()
    out_path = OUT_DIR / "v1_river_network.png"
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out_path.name}")

    # ---- Plot 2: Building footprints (nbo.geojson) + rivers + watersheds ----
    nbo_path = WORK_DIR / "nbo.geojson"
    fig, ax = plt.subplots(figsize=(14, 12))

    if nbo_path.exists():
        print("  Loading building footprints (nbo.geojson)...")
        import json as _json
        with open(str(nbo_path)) as f:
            nbo_fc = _json.load(f)
        n_bld = len(nbo_fc["features"])
        print(f"    {n_bld:,} building polygons")
        from matplotlib.collections import PatchCollection
        from matplotlib.patches import Polygon as MplPolygon
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
                             alpha=0.55, zorder=1)
        ax.add_collection(pc)
        ax.set_xlim(DOMAIN_BBOX["west"] - 0.02, DOMAIN_BBOX["east"] + 0.02)
        ax.set_ylim(DOMAIN_BBOX["south"] - 0.02, DOMAIN_BBOX["north"] + 0.02)

    # Watershed outlines (no fill)
    draw_watersheds_outline(ax, basin_geoms, basin_level, cmap_ws)

    # Rivers
    draw_rivers(ax, categorized, draw_order)

    # Domain box
    bx = DOMAIN_BBOX
    ax.plot(
        [bx["west"], bx["east"], bx["east"], bx["west"], bx["west"]],
        [bx["south"], bx["south"], bx["north"], bx["north"], bx["south"]],
        color="black", linewidth=2.5, linestyle="--",
        label="Simulation domain", zorder=5,
    )

    handles = []
    for cat in reversed(draw_order):
        style = STREAM_STYLES[cat]
        n = len(categorized[cat])
        handles.append(plt.Line2D(
            [0], [0], color=style["color"], linewidth=style["width"] * 1.5,
            label=f"{style['label']} ({n})",
        ))
    handles.append(plt.Line2D([0], [0], color="black", linestyle="--",
                              linewidth=2.5, label="Simulation domain"))
    if basin_geoms:
        handles.append(plt.Line2D([0], [0], color=cmap_ws(0), linestyle="--",
                                  linewidth=1.4,
                                  label=f"Watershed boundaries (level {basin_level})"))
    if nbo_path.exists():
        handles.append(mpatches.Patch(facecolor="#f4a261", alpha=0.6,
                                      label=f"Building footprints ({n_bld:,})"))

    ax.legend(handles=handles, loc="upper left", fontsize=10,
              framealpha=0.95, edgecolor="gray", fancybox=True)
    ax.set_title(f"Nairobi — Building Footprints + River Network + Watershed Boundaries\n"
                 f"Microsoft ML Buildings | TDX-Hydro v2 | HydroATLAS level {basin_level}",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_aspect("equal")
    ax.grid(alpha=0.2, linestyle=":")
    fig.tight_layout()
    out_path = OUT_DIR / "v1_buildings_rivers_watersheds.png"
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out_path.name}")


def main():
    print("=" * 60)
    print("Download & Plot River Network — TDX-Hydro v2 via TIPG API")
    print("Nairobi v1 case study")
    print("=" * 60)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    bbox, basin_geoms, basin_level = get_basin_bbox()

    # Load cached GeoJSON if available, else download
    geojson_path = V1_DIR / "input" / "river_network_tdx_v2.geojson"
    geojson_path.parent.mkdir(parents=True, exist_ok=True)
    if geojson_path.exists():
        print(f"\nUsing cached river network: {geojson_path.name}")
        import json as _j
        with open(str(geojson_path)) as f:
            fc = _j.load(f)
        print(f"  {len(fc['features'])} features")
    else:
        fc = download_river_network(bbox)
        if not fc["features"]:
            print("No river features found — check API or bbox!")
            return
        save_geojson(fc, geojson_path)

    print("\nGenerating river network plots...")
    plot_river_network(fc, basin_geoms, basin_level, [])

    print("\n" + "=" * 60)
    print("Done!")
    print(f"  Outputs: {OUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
