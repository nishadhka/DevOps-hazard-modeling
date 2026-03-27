#!/usr/bin/env python3
"""
Download river network from TIPG API and plot with stream-order-based styling.

Uses the ea_river_networks_tdx_v2 collection (GEOGloWS/TDX-Hydro v2) served
via OGC API Features. Downloads GeoJSON for the v11 basin extent and renders
a publication-quality map with line widths proportional to stream order.

Usage:
    micromamba run -n zarrv3 python download_river_network.py
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import requests

WORK_DIR = Path("/data/rim2d/nile_highres")
V10_DIR = WORK_DIR / "v10"
V11_DIR = WORK_DIR / "v11"
WS_DIR = V10_DIR / "input" / "watersheds"
OUT_DIR = V11_DIR / "visualizations"

API_BASE = "https://tipg-tiler-template.replit.app"
COLLECTION = "public.ea_river_networks_tdx_v2"
ITEMS_URL = f"{API_BASE}/collections/{COLLECTION}/items"

# v10 domain bbox for context
DOMAIN_BBOX = {"west": 33.25, "south": 19.49, "east": 33.36, "north": 19.57}

# Culvert locations
CULVERTS = [
    {"name": "Culvert 1", "lat": 19.547450, "lon": 33.339139},
    {"name": "Culvert 2", "lat": 19.550000, "lon": 33.325906},
]

DPI = 150

# Stream order styling (matching the HTML visualization)
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
    """Get bounding box from the finest watershed GeoJSON available."""
    for level in [12, 10, 8]:
        gj_path = WS_DIR / f"Culvert1_level{level:02d}.geojson"
        if gj_path.exists():
            with open(str(gj_path)) as f:
                fc = json.load(f)
            geom = fc["features"][0]["geometry"]
            coords = []
            if geom["type"] == "Polygon":
                coords = geom["coordinates"][0]
            elif geom["type"] == "MultiPolygon":
                for poly in geom["coordinates"]:
                    coords.extend(poly[0])
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            bbox = {
                "west": min(lons), "east": max(lons),
                "south": min(lats), "north": max(lats),
            }
            print(f"Basin bbox (level {level}): "
                  f"W={bbox['west']:.3f} E={bbox['east']:.3f} "
                  f"S={bbox['south']:.3f} N={bbox['north']:.3f}")
            return bbox, fc["features"][0]["geometry"], level

    # Fallback to domain bbox with buffer
    print("No watershed GeoJSON found, using domain bbox with buffer")
    return {
        "west": DOMAIN_BBOX["west"] - 0.1,
        "east": DOMAIN_BBOX["east"] + 0.1,
        "south": DOMAIN_BBOX["south"] - 0.1,
        "north": DOMAIN_BBOX["north"] + 0.1,
    }, None, None


def download_river_network(bbox):
    """Download all river features within bbox from TIPG API.

    OGC API Features supports bbox and pagination via limit/offset.
    """
    bbox_str = f"{bbox['west']},{bbox['south']},{bbox['east']},{bbox['north']}"
    all_features = []
    offset = 0
    limit = 100  # max per page

    print(f"\nDownloading river network from TIPG API...")
    print(f"  bbox: {bbox_str}")

    while True:
        params = {"bbox": bbox_str, "limit": limit, "offset": offset}
        resp = requests.get(ITEMS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        total = data.get("numberMatched", 0)
        all_features.extend(features)

        print(f"  Fetched {len(all_features)}/{total} features "
              f"(offset={offset})")

        if len(all_features) >= total or not features:
            break
        offset += limit

    print(f"  Total features downloaded: {len(all_features)}")

    # Summary by stream order
    orders = {}
    for f in all_features:
        so = f["properties"].get("stream_order", 0)
        orders[so] = orders.get(so, 0) + 1
    for so in sorted(orders.keys()):
        print(f"    Stream order {so}: {orders[so]} segments")

    return {
        "type": "FeatureCollection",
        "features": all_features,
    }


def save_geojson(fc, out_path):
    """Save FeatureCollection as GeoJSON."""
    with open(str(out_path), "w") as f:
        json.dump(fc, f)
    n = len(fc["features"])
    size_kb = out_path.stat().st_size / 1024
    print(f"  Saved: {out_path.name} ({n} features, {size_kb:.0f} KB)")


def plot_river_network(fc, basin_geom, basin_level):
    """Plot river network with stream-order-based styling.

    Produces two figures:
    1. River network on white background with basin polygon
    2. River network with DEM hillshade (if available)
    """
    import netCDF4

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Categorize features by stream order
    categorized = {cat: [] for cat in STREAM_STYLES}
    for feat in fc["features"]:
        so = feat["properties"].get("stream_order", 1)
        for cat, style in STREAM_STYLES.items():
            if style["min_order"] <= so < style["max_order"]:
                categorized[cat].append(feat)
                break

    # ---- Plot 1: Clean river network map ----
    fig, ax = plt.subplots(figsize=(14, 12))

    # Basin polygon
    if basin_geom is not None:
        if basin_geom["type"] == "Polygon":
            coords = basin_geom["coordinates"][0]
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            ax.fill(xs, ys, alpha=0.08, color="#4d8cff",
                    edgecolor="#4d8cff", linewidth=1.5, linestyle="--",
                    label=f"Watershed (level {basin_level})")
        elif basin_geom["type"] == "MultiPolygon":
            for j, poly in enumerate(basin_geom["coordinates"]):
                coords = poly[0]
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                lbl = (f"Watershed (level {basin_level})" if j == 0
                       else None)
                ax.fill(xs, ys, alpha=0.08, color="#4d8cff",
                        edgecolor="#4d8cff", linewidth=1.5, linestyle="--",
                        label=lbl)

    # Draw rivers: small first (background), major last (foreground)
    draw_order = ["small", "medium", "large", "major"]
    for cat in draw_order:
        style = STREAM_STYLES[cat]
        features = categorized[cat]
        for feat in features:
            geom = feat["geometry"]
            if geom["type"] == "MultiLineString":
                for line in geom["coordinates"]:
                    xs = [c[0] for c in line]
                    ys = [c[1] for c in line]
                    ax.plot(xs, ys, color=style["color"],
                            linewidth=style["width"], solid_capstyle="round",
                            alpha=0.85, zorder=2)
            elif geom["type"] == "LineString":
                xs = [c[0] for c in geom["coordinates"]]
                ys = [c[1] for c in geom["coordinates"]]
                ax.plot(xs, ys, color=style["color"],
                        linewidth=style["width"], solid_capstyle="round",
                        alpha=0.85, zorder=2)

    # Domain box
    ax.plot(
        [DOMAIN_BBOX["west"], DOMAIN_BBOX["east"], DOMAIN_BBOX["east"],
         DOMAIN_BBOX["west"], DOMAIN_BBOX["west"]],
        [DOMAIN_BBOX["south"], DOMAIN_BBOX["south"], DOMAIN_BBOX["north"],
         DOMAIN_BBOX["north"], DOMAIN_BBOX["south"]],
        color="black", linewidth=2, linestyle="--",
        label="Simulation domain", zorder=5,
    )

    # Culvert markers
    for cv in CULVERTS:
        ax.plot(cv["lon"], cv["lat"], "D", color="red", markersize=10,
                markeredgecolor="black", markeredgewidth=1.2, zorder=10)
        ax.annotate(cv["name"], (cv["lon"], cv["lat"]),
                    textcoords="offset points", xytext=(8, 8),
                    fontsize=9, fontweight="bold", color="red",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white",
                              ec="red", alpha=0.8))

    # Legend
    handles = []
    for cat in reversed(draw_order):
        style = STREAM_STYLES[cat]
        n = len(categorized[cat])
        handles.append(plt.Line2D(
            [0], [0], color=style["color"], linewidth=style["width"] * 1.5,
            label=f"{style['label']} ({n})",
        ))
    handles.append(plt.Line2D([0], [0], color="black", linestyle="--",
                              linewidth=2, label="Simulation domain"))
    if basin_geom is not None:
        handles.append(mpatches.Patch(facecolor="#4d8cff", alpha=0.15,
                                      edgecolor="#4d8cff", linestyle="--",
                                      label=f"Watershed (level {basin_level})"))
    handles.append(plt.Line2D([0], [0], marker="D", color="w",
                              markerfacecolor="red", markeredgecolor="black",
                              markersize=10, label="Culvert inflow"))

    ax.legend(handles=handles, loc="upper left", fontsize=10,
              framealpha=0.95, edgecolor="gray", fancybox=True)

    n_total = len(fc["features"])
    ax.set_title(f"TDX-Hydro v2 River Network — Abu Hamad Basin\n"
                 f"{n_total} stream segments | "
                 f"GEOGloWS ea_river_networks_tdx_v2",
                 fontsize=14, fontweight="bold")
    ax.set_xlabel("Longitude", fontsize=12)
    ax.set_ylabel("Latitude", fontsize=12)
    ax.set_aspect("equal")
    ax.grid(alpha=0.2, linestyle=":")

    fig.tight_layout()
    out_path = OUT_DIR / "v11_river_network.png"
    fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out_path.name}")

    # ---- Plot 2: River network on DEM hillshade ----
    dem_path = V10_DIR / "input" / "dem.nc"
    if dem_path.exists():
        ds = netCDF4.Dataset(str(dem_path))
        x = ds["x"][:]
        y_arr = ds["y"][:]
        varname = [v for v in ds.variables if v not in ("x", "y")][0]
        dem = np.array(ds[varname][:], dtype=np.float64)
        ds.close()
        dem[dem < -9000] = np.nan

        # Hillshade
        az = np.radians(315)
        alt = np.radians(45)
        dy, dx = np.gradient(np.nan_to_num(dem, nan=0))
        slope = np.pi / 2.0 - np.arctan(np.sqrt(dx**2 + dy**2))
        aspect = np.arctan2(-dy, dx)
        hillshade = (np.sin(alt) * np.sin(slope)
                     + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))

        # Convert UTM to lat/lon for extent
        from pyproj import Transformer
        to_ll = Transformer.from_crs("EPSG:32636", "EPSG:4326", always_xy=True)
        lon_min, lat_min = to_ll.transform(float(x[0]), float(y_arr[0]))
        lon_max, lat_max = to_ll.transform(float(x[-1]), float(y_arr[-1]))
        extent_ll = [lon_min, lon_max, lat_min, lat_max]

        fig, ax = plt.subplots(figsize=(14, 10))

        # DEM + hillshade
        ax.imshow(hillshade, origin="lower", extent=extent_ll, cmap="gray",
                  vmin=0.3, vmax=1.0, alpha=0.5)
        im = ax.imshow(np.ma.masked_invalid(dem), origin="lower",
                       extent=extent_ll, cmap="terrain", alpha=0.6)

        # Rivers on DEM — brighter colors for contrast
        dem_colors = {
            "major": "#0055ff", "large": "#3388ff",
            "medium": "#66aaff", "small": "#99ccff",
        }
        for cat in draw_order:
            style = STREAM_STYLES[cat]
            for feat in categorized[cat]:
                geom = feat["geometry"]
                if geom["type"] == "MultiLineString":
                    for line in geom["coordinates"]:
                        xs = [c[0] for c in line]
                        ys = [c[1] for c in line]
                        ax.plot(xs, ys, color=dem_colors[cat],
                                linewidth=style["width"] * 1.2,
                                solid_capstyle="round", alpha=0.9, zorder=3)
                elif geom["type"] == "LineString":
                    xs = [c[0] for c in geom["coordinates"]]
                    ys = [c[1] for c in geom["coordinates"]]
                    ax.plot(xs, ys, color=dem_colors[cat],
                            linewidth=style["width"] * 1.2,
                            solid_capstyle="round", alpha=0.9, zorder=3)

        # Culvert markers
        for cv in CULVERTS:
            ax.plot(cv["lon"], cv["lat"], "D", color="red", markersize=12,
                    markeredgecolor="white", markeredgewidth=2, zorder=10)
            ax.annotate(cv["name"], (cv["lon"], cv["lat"]),
                        textcoords="offset points", xytext=(8, 8),
                        fontsize=10, fontweight="bold", color="white",
                        bbox=dict(boxstyle="round,pad=0.2", fc="red",
                                  ec="white", alpha=0.9))

        cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
        cbar.set_label("Elevation (m)", fontsize=11)

        # Legend
        handles = []
        for cat in reversed(draw_order):
            style = STREAM_STYLES[cat]
            n = len(categorized[cat])
            if n > 0:
                handles.append(plt.Line2D(
                    [0], [0], color=dem_colors[cat],
                    linewidth=style["width"] * 1.5,
                    label=f"{style['label']} ({n})",
                ))
        handles.append(plt.Line2D([0], [0], marker="D", color="w",
                                  markerfacecolor="red",
                                  markeredgecolor="white", markersize=10,
                                  label="Culvert inflow"))
        ax.legend(handles=handles, loc="lower right", fontsize=9,
                  framealpha=0.9, edgecolor="gray")

        ax.set_title(f"River Network on DEM — v11 Simulation Domain\n"
                     f"{n_total} TDX-Hydro v2 segments",
                     fontsize=13, fontweight="bold")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")

        # Zoom to domain
        ax.set_xlim(lon_min, lon_max)
        ax.set_ylim(lat_min, lat_max)

        fig.tight_layout()
        out_path = OUT_DIR / "v11_river_network_dem.png"
        fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight",
                    facecolor="white")
        plt.close(fig)
        print(f"  Saved: {out_path.name}")


def main():
    print("=" * 60)
    print("Download & Plot River Network — TDX-Hydro v2 via TIPG API")
    print("=" * 60)

    # Get basin bounding box
    bbox, basin_geom, basin_level = get_basin_bbox()

    # Download river network GeoJSON
    fc = download_river_network(bbox)

    if not fc["features"]:
        print("No river features found in basin extent!")
        return

    # Save GeoJSON
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    geojson_path = V11_DIR / "input" / "river_network_tdx_v2.geojson"
    geojson_path.parent.mkdir(parents=True, exist_ok=True)
    save_geojson(fc, geojson_path)

    # Plot
    print("\nGenerating river network plots...")
    plot_river_network(fc, basin_geom, basin_level)

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
