"""Add Overture Maps road-network overlay to the rim2d basin plot.

For each of the 11 rim2d urban extents (rim2d/regions.geojson):
  - downloads Overture `segment` features (roads + railways) via the
    `overturemaps` CLI — same source as hazard-model-api/download_roads.py.
    Overture segments are OSM-derived plus a few proprietary additions —
    matches the "OSM road network" deliverable. Railways are filtered out;
    only road classes are kept. Cached locally so reruns don't re-download.
  - reuses plot_rim2d_river_network.plot_region (HydroBASINS lev-8 basins
    + TDX-Hydro stream-order rivers + dashed rim2d extent + country
    side-panel) and overlays roads as LineStrings with width by road class.

Class → line-width mapping (matplotlib lw, roughly OSM hierarchy):
    motorway / trunk        2.0    (major arterials)
    primary                 1.4
    secondary               1.0
    tertiary                0.7
    residential / service   0.4
    other (footway, …)      0.25

Outputs:
  runs/rim2d_roads_data/{iso}_{id}_segments.geojson      (cache)
  runs/rim2d_roads_plots/{iso}_{id}_rim2d_roads.png

  uv run python -m shared.hydrobasins.plot_rim2d_roads
  uv run python -m shared.hydrobasins.plot_rim2d_roads --iso ken,sdn

HF upload (after run):
  uv run python -m shared.hydrobasins.upload_to_hf \\
      --folder runs/rim2d_roads_plots --dest roads \\
      --repo E4DRR/rim2d-simulations
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from shapely.geometry import LineString, MultiLineString  # noqa: E402

from shared.hydrobasins.plot_rim2d_river_network import (  # noqa: E402
    REGIONS_GEOJSON, fetch_tdx, plot_region,
)

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "runs" / "rim2d_roads_data"
OUT = HERE.parents[1] / "runs" / "rim2d_roads_plots"

# Overture segment "class" → (line width, hierarchy bucket label, colour)
ROAD_STYLE = {
    "motorway":    (2.0, "motorway/trunk", "#b30000"),
    "trunk":       (2.0, "motorway/trunk", "#b30000"),
    "primary":     (1.4, "primary",        "#cc4c02"),
    "secondary":   (1.0, "secondary",      "#ec7014"),
    "tertiary":    (0.7, "tertiary",       "#fe9929"),
    "residential": (0.4, "residential/service", "#444444"),
    "service":     (0.4, "residential/service", "#444444"),
    "living_street": (0.4, "residential/service", "#444444"),
}
OTHER_STYLE = (0.25, "other", "#888888")  # footways, paths, unknown
RAIL_CLASSES = {"rail"}  # exclude


def fetch_segments(bbox: tuple, out_path: Path) -> Path:
    """overturemaps CLI download `segment` → GeoJSON file; cache-on-disk."""
    if out_path.exists():
        return out_path
    DATA.mkdir(parents=True, exist_ok=True)
    bbox_str = ",".join(f"{v:.6f}" for v in bbox)
    cmd = ["overturemaps", "download", "--bbox", bbox_str, "-f", "geojson",
           "-t", "segment", "-o", str(out_path)]
    subprocess.run(cmd, check=True)
    return out_path


def _bucketize(roads: gpd.GeoDataFrame) -> dict[str, list[tuple]]:
    """Group roads by (lw, label, colour); return {label: [coords lists]}."""
    by_bucket: dict[tuple, list] = {}
    for cls, geom in zip(roads["class"], roads.geometry):
        style = ROAD_STYLE.get(cls, OTHER_STYLE)
        coords_list = []
        if isinstance(geom, LineString):
            coords_list.append(list(geom.coords))
        elif isinstance(geom, MultiLineString):
            for ln in geom.geoms:
                coords_list.append(list(ln.coords))
        else:
            continue
        by_bucket.setdefault(style, []).extend(coords_list)
    return by_bucket


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", default=None,
                    help="Comma-separated ISO3 subset (default: all 11)")
    args = ap.parse_args()
    if shutil.which("overturemaps") is None:
        raise SystemExit("overturemaps CLI not found — run `uv add overturemaps`")

    regions = gpd.read_file(REGIONS_GEOJSON).to_crs("EPSG:4326")
    if args.iso:
        want = {s.strip().upper() for s in args.iso.split(",")}
        regions = regions[regions["country"].isin(want)]
    print(f"rim2d roads overlay ({len(regions)} regions) → {OUT}\n")
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    for _, row in regions.iterrows():
        iso = str(row["country"])
        rid = str(row["id"])
        bbox = row.geometry.bounds
        seg_path = DATA / f"{iso.lower()}_{rid}_segments.geojson"
        try:
            print(f"  {iso} ({rid}) {row['region']}: fetching segments…")
            fetch_segments(bbox, seg_path)
            segs_gdf = gpd.read_file(seg_path).to_crs("EPSG:4326")
            n_all = len(segs_gdf)
            roads = segs_gdf[~segs_gdf["class"].isin(RAIL_CLASSES)].copy()
            n_roads = len(roads)
            print(f"    {n_all:,} segments ({n_all - n_roads} rail dropped); "
                  f"{seg_path.stat().st_size/1e6:.1f} MB")
            buckets = _bucketize(roads)

            def overlay(ax, _buckets=buckets):
                for (lw, label, colour), lines in _buckets.items():
                    if not lines:
                        continue
                    ax.add_collection(LineCollection(
                        lines, colors=[colour], linewidths=lw, alpha=0.85,
                        zorder=8))
                # add a small road legend on the upper-left so it doesn't
                # collide with the river-order legend (lower-right)
                used = {(lw, label, c): None for (lw, label, c) in _buckets}
                handles = [mpatches.Patch(color=c, label=f"{label} (lw {lw})")
                           for (lw, label, c) in used]
                ax.legend(handles=handles, loc="upper left", fontsize=7,
                          title="Overture road class", framealpha=0.92)

            fc = fetch_tdx(bbox)
            s = plot_region(row, fc, overlay_fn=overlay, out_dir=OUT,
                            out_suffix="rim2d_roads",
                            title_extra=f"  · {n_roads:,} Overture roads")
        except subprocess.CalledProcessError as e:
            print(f"    FAILED overturemaps: returncode={e.returncode}")
            continue
        except Exception as e:
            print(f"    FAILED ({type(e).__name__}: {str(e)[:120]})")
            continue
        print(f"    OK · {s['segments']} river segs · {s['n_basins']} basins")

    pngs = sorted(p.name for p in OUT.glob("*.png"))
    print(f"\n{len(pngs)} PNGs written to {OUT}")


if __name__ == "__main__":
    main()
