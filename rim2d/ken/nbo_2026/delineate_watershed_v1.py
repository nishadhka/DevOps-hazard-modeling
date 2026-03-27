#!/usr/bin/env python3
"""
Delineate upstream watersheds for the 8 Nairobi v1 river entry points using HydroATLAS.

Queries WWF/HydroATLAS/v1/Basins at levels 4, 6, 8, 10, 12 from GEE for each
auto-detected river entry point.  Downloads basin polygons as GeoJSON and
computes scientifically-derived catchment areas to replace the flow-accumulation
estimates used in run_v1_river_inflow.py.

Output:
  v1/input/watersheds/entry{N}_level{LL}.geojson  — basin polygon per entry+level
  v1/input/watersheds/watershed_summary.json       — catchment areas per level
  v1/visualizations/v1_watersheds.png              — basin map over domain

Usage:
    cd /data/rim2d/nbo_2026
    micromamba run -n zarrv3 python delineate_watershed_v1.py
"""

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

SA_KEY = (
    "/data/08-2023/working_notes_jupyter/ignore_nka_gitrepos/"
    "cno-e4drr/devops/earth-engine-service-account/keys/"
    "earthengine-sa-20260130-key.json"
)

WORK_DIR = Path(__file__).parent        # /data/rim2d/nbo_2026
V1_DIR   = WORK_DIR / "v1"
WS_DIR   = V1_DIR / "input" / "watersheds"
VIS_DIR  = V1_DIR / "visualizations"

# Nairobi domain bounding box (lat/lon) for map context
DOMAIN_BBOX = {"west": 36.6, "south": -1.402004, "east": 37.1, "north": -1.098036}

LEVELS = [4, 6, 8, 10, 12]


def init_ee():
    import ee
    with open(SA_KEY) as f:
        key_data = json.load(f)
    creds = ee.ServiceAccountCredentials(key_data["client_email"], SA_KEY)
    ee.Initialize(credentials=creds)
    print(f"EE initialized: {key_data['client_email']}")
    return ee


def load_entry_points():
    """Load river entry points written by run_v1_river_inflow.py."""
    csv_path = V1_DIR / "input" / "river_entry_points.csv"
    if not csv_path.exists():
        raise FileNotFoundError(
            f"Not found: {csv_path}\nRun run_v1_river_inflow.py first."
        )
    entries = []
    with open(str(csv_path)) as f:
        for row in csv.DictReader(f):
            entries.append({
                "name":  f"entry{row['entry_id']}",
                "id":    int(row["entry_id"]),
                "lat":   float(row["lat"]),
                "lon":   float(row["lon"]),
                "acc":   float(row["flow_acc"]),
                "km2_flwacc": float(row["catchment_km2"]),
                "elev":  float(row["elevation_m"]),
            })
    print(f"  Loaded {len(entries)} entry points from CSV")
    return entries


def query_basins(ee, entries):
    """Query HydroATLAS basins at each level for every entry point."""
    results = {}

    for entry in entries:
        name = entry["name"]
        pt   = ee.Geometry.Point([entry["lon"], entry["lat"]])
        results[name] = {}
        print(f"\n  {name} (lat={entry['lat']:.5f}, lon={entry['lon']:.5f}, "
              f"flwacc_area={entry['km2_flwacc']:.1f} km2):")

        for level in LEVELS:
            collection_id = f"WWF/HydroATLAS/v1/Basins/level{level:02d}"
            try:
                basins    = ee.FeatureCollection(collection_id)
                containing = basins.filterBounds(pt)
                count     = containing.size().getInfo()

                if count > 0:
                    features  = containing.getInfo()
                    feat      = features["features"][0]
                    props     = feat["properties"]
                    sub_area  = props.get("SUB_AREA", None)
                    up_area   = props.get("UP_AREA",  None)
                    hybas_id  = props.get("HYBAS_ID", None)
                    pfaf_id   = props.get("PFAF_ID",  None)
                    order_    = props.get("ORDER_",   None)

                    results[name][level] = {
                        "hybas_id":     hybas_id,
                        "pfaf_id":      pfaf_id,
                        "sub_area_km2": sub_area,
                        "up_area_km2":  up_area,
                        "order":        order_,
                        "geojson":      feat,
                    }
                    print(f"    level {level:2d}: HYBAS_ID={hybas_id}, "
                          f"SUB_AREA={sub_area} km2, UP_AREA={up_area} km2")
                else:
                    print(f"    level {level:2d}: no basin found")
                    results[name][level] = None

            except Exception as exc:
                print(f"    level {level:2d}: ERROR — {exc}")
                results[name][level] = None

    return results


def save_geojson(results):
    """Save basin polygons as GeoJSON files."""
    WS_DIR.mkdir(parents=True, exist_ok=True)
    n_saved = 0
    for entry_name, levels in results.items():
        for level, data in levels.items():
            if data is None:
                continue
            feat = data["geojson"]
            fc   = {"type": "FeatureCollection", "features": [feat]}
            path = WS_DIR / f"{entry_name}_level{level:02d}.geojson"
            with open(str(path), "w") as f:
                json.dump(fc, f)
            n_saved += 1
    print(f"  Saved {n_saved} GeoJSON files to {WS_DIR}/")


def save_summary(results, entries):
    """Save summary JSON for use by run_v1_synthetic_flood.py."""
    summary = {}
    for entry in entries:
        name = entry["name"]
        summary[name] = {
            "lat":          entry["lat"],
            "lon":          entry["lon"],
            "flow_acc":     entry["acc"],
            "km2_flwacc":   entry["km2_flwacc"],
            "elevation_m":  entry["elev"],
            "levels":       {},
        }
        for level, data in results.get(name, {}).items():
            if data is None:
                continue
            summary[name]["levels"][str(level)] = {
                "hybas_id":     data["hybas_id"],
                "sub_area_km2": data["sub_area_km2"],
                "up_area_km2":  data["up_area_km2"],
                "order":        data["order"],
            }

    path = WS_DIR / "watershed_summary.json"
    with open(str(path), "w") as f:
        json.dump(summary, f, indent=2)
    print(f"  Saved: {path.name}")
    return summary


def visualize_watersheds(results, entries):
    """Plot HydroATLAS basin polygons for all entries over the Nairobi domain."""
    from shapely.geometry import shape

    VIS_DIR.mkdir(parents=True, exist_ok=True)

    # Show 3 most useful levels: 6, 8, 10
    vis_levels = [l for l in [6, 8, 10] if l in LEVELS]
    n_cols = len(vis_levels)
    fig, axes = plt.subplots(1, n_cols, figsize=(7 * n_cols, 9))
    if n_cols == 1:
        axes = [axes]

    cmap = plt.cm.tab10
    colors = [cmap(i / max(len(entries), 1)) for i in range(len(entries))]

    for ax_idx, level in enumerate(vis_levels):
        ax = axes[ax_idx]

        # Domain box
        bx = DOMAIN_BBOX
        ax.plot(
            [bx["west"], bx["east"], bx["east"], bx["west"], bx["west"]],
            [bx["south"], bx["south"], bx["north"], bx["north"], bx["south"]],
            "k--", linewidth=2, label="v1 domain", zorder=5
        )

        for e_idx, entry in enumerate(entries):
            name = entry["name"]
            data = results.get(name, {}).get(level)
            if data is None:
                continue

            try:
                geom = shape(data["geojson"]["geometry"])
            except Exception:
                continue

            color = colors[e_idx]
            polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
            for poly in polys:
                xs, ys = poly.exterior.xy
                ax.fill(xs, ys, alpha=0.18, color=color)
                ax.plot(xs, ys, color=color, linewidth=0.8)

            # Entry marker + area label
            ax.plot(entry["lon"], entry["lat"], "^", color=color,
                    markersize=10, markeredgecolor="black",
                    markeredgewidth=0.8, zorder=10)
            sub = data["sub_area_km2"]
            ax.annotate(
                f"{name}\n{sub:.0f} km²",
                (entry["lon"], entry["lat"]),
                textcoords="offset points", xytext=(5, 5),
                fontsize=7, color=color, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.15", fc="white",
                          ec=color, alpha=0.8),
            )

        ax.set_title(f"HydroATLAS Level {level}", fontsize=12,
                     fontweight="bold")
        ax.set_xlabel("Longitude");  ax.set_ylabel("Latitude")
        ax.set_aspect("equal");  ax.grid(alpha=0.25)

    fig.suptitle("Nairobi v1 — Upstream Watershed Delineation (HydroATLAS)",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    out = VIS_DIR / "v1_watersheds.png"
    fig.savefig(str(out), dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {out.name}")


def print_summary(results, entries):
    print("\n" + "=" * 80)
    print("WATERSHED SUMMARY — recommended catchment areas for run_v1_synthetic_flood.py")
    print("=" * 80)
    print(f"  {'Entry':<10} {'flwacc km2':>12} ", end="")
    for l in LEVELS:
        print(f"  {'L'+str(l)+' sub':>10}", end="")
    print()
    print("  " + "-" * 78)

    for entry in entries:
        name = entry["name"]
        print(f"  {name:<10} {entry['km2_flwacc']:>12.1f} ", end="")
        for l in LEVELS:
            data = results.get(name, {}).get(l)
            if data and data["sub_area_km2"]:
                print(f"  {data['sub_area_km2']:>10.1f}", end="")
            else:
                print(f"  {'N/A':>10}", end="")
        print()

    print("\nRECOMMENDATION: Use level 10 or 12 (finest) for synthetic hydrograph.")
    print("  If level 10/12 SUB_AREA is very small, use UP_AREA instead.")


def main():
    WS_DIR.mkdir(parents=True, exist_ok=True)
    VIS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Nairobi v1 — HydroATLAS Watershed Delineation")
    print(f"  Levels: {LEVELS}")
    print("=" * 60)

    entries = load_entry_points()
    ee = init_ee()

    print(f"\nQuerying HydroATLAS for {len(entries)} river entry points...")
    results = query_basins(ee, entries)

    print("\nSaving GeoJSON files...")
    save_geojson(results)

    print("\nSaving watershed summary JSON...")
    save_summary(results, entries)

    print("\nGenerating watershed visualization...")
    visualize_watersheds(results, entries)

    print_summary(results, entries)

    print("\n" + "=" * 60)
    print("Done! Next: python run_v1_synthetic_flood.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
