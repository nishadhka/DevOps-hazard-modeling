"""Plot per-case maps and a combined overview for the 11 drought cases."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from .download import ensure_natural_earth
from .select import CaseExtent
from region_configs import REGIONS

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "outputs"

CASE_COLOURS = {
    "BDI": "#1f77b4", "DJI": "#ff7f0e", "ERI": "#2ca02c", "ETH": "#d62728",
    "KEN": "#9467bd", "RWA": "#8c564b", "SOM": "#e377c2", "SSD": "#7f7f7f",
    "SDN": "#bcbd22", "TZA": "#17becf", "UGA": "#aec7e8",
}


def _load_admin() -> gpd.GeoDataFrame:
    return gpd.read_file(ensure_natural_earth(), engine="pyogrio")


def plot_case(ext: CaseExtent, admin: gpd.GeoDataFrame, out_path: Path) -> None:
    cfg = REGIONS[ext.name]
    b = cfg["bounds"]
    minx, maxx = b["west"] - 0.3, b["east"] + 0.3
    miny, maxy = b["south"] - 0.3, b["north"] + 0.3

    fig, ax = plt.subplots(figsize=(7, 6))
    admin.boundary.plot(ax=ax, color="#888", linewidth=0.4)
    ext.geometry.plot(ax=ax, color=CASE_COLOURS[ext.iso], alpha=0.55,
                      edgecolor="black", linewidth=0.6)

    # Current bbox of the existing wflow build
    ax.add_patch(Rectangle(
        (b["west"], b["south"]), b["east"] - b["west"], b["north"] - b["south"],
        fill=False, edgecolor="red", linewidth=1.2, linestyle="--", label="current bbox"
    ))

    # wflow-config outlet (the one in region_configs.py — used for the model build)
    cfg_outlet = cfg.get("outlet")
    if cfg_outlet:
        ax.plot(cfg_outlet["lon"], cfg_outlet["lat"],
                marker="x", color="red", markersize=10, mew=2,
                label=f"wflow outlet ({cfg_outlet.get('river','')})")
    # HydroBASINS outlet (the one actually used for BFS — may be an override)
    if ext.outlet_lon is not None:
        ax.plot(ext.outlet_lon, ext.outlet_lat,
                marker="*", color="black", markersize=14,
                label="HydroBASINS outlet")

    # Expand frame so the basin is visible if it extends beyond the country bbox
    g = ext.geometry.iloc[0]
    if not g.is_empty:
        gminx, gminy, gmaxx, gmaxy = g.bounds
        minx = min(minx, gminx - 0.3); maxx = max(maxx, gmaxx + 0.3)
        miny = min(miny, gminy - 0.3); maxy = max(maxy, gmaxy + 0.3)

    ax.set_xlim(minx, maxx); ax.set_ylim(miny, maxy)
    ax.set_aspect("equal")
    storyline = (f"{ext.storyline_area_km2:,.0f} km²"
                 if ext.storyline_area_km2 else "—")
    ratio = f" ({ext.ratio:.2f}×)" if ext.ratio is not None else ""
    status = "  ⚠ WARN" if ext.warning else ""
    ax.set_title(
        f"{ext.name} — {ext.title}{status}\n"
        f"HydroBASINS lvl {ext.level}: {ext.n_polygons} polys, "
        f"{ext.area_km2:,.0f} km² (storyline {storyline}{ratio}) [{ext.method}]"
    )
    ax.legend(loc="lower right", fontsize=8)
    ax.set_xlabel("lon"); ax.set_ylabel("lat")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def plot_overview(exts: list[CaseExtent], admin: gpd.GeoDataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 11))
    # East Africa frame
    ax.set_xlim(20, 52); ax.set_ylim(-13, 23)
    admin.boundary.plot(ax=ax, color="#888", linewidth=0.4)
    for ext in exts:
        ext.geometry.plot(
            ax=ax, color=CASE_COLOURS[ext.iso], alpha=0.55,
            edgecolor="black", linewidth=0.4,
            label=f"{ext.name} {ext.iso} ({ext.area_km2:,.0f} km²)"
        )
        outlet = REGIONS[ext.name].get("outlet")
        if outlet:
            ax.plot(outlet["lon"], outlet["lat"], marker="*",
                    color="black", markersize=8)
    ax.set_aspect("equal")
    ax.set_title("11 ICPAC drought cases — HydroBASINS upstream extents")
    ax.legend(loc="lower left", fontsize=8, frameon=True)
    ax.set_xlabel("lon"); ax.set_ylabel("lat")
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def write_geojson(exts: list[CaseExtent], out_path: Path) -> None:
    rows = []
    for ext in exts:
        cfg = REGIONS[ext.name]
        rows.append({
            "case": ext.name, "iso": ext.iso, "title": ext.title,
            "method": ext.method, "level": ext.level,
            "n_polygons": ext.n_polygons, "area_km2": ext.area_km2,
            "storyline_area_km2": ext.storyline_area_km2,
            "outlet_lon": (cfg.get("outlet") or {}).get("lon"),
            "outlet_lat": (cfg.get("outlet") or {}).get("lat"),
            "geometry": ext.geometry.iloc[0],
        })
    gpd.GeoDataFrame(rows, crs="EPSG:4326").to_file(out_path, driver="GeoJSON")
