"""DEPRECATED — superseded by plot_rim2d_buildings_cog.py.

This GeoJSON-load + polygon-plot path OOMs on dense regions (RWA's 1.8 M
buildings need ~6-10 GB RAM for the geopandas read alone; SDN 3.2 M is
worse). Kept here for reference / smaller-extent use. For production,
use the COG-based approach (rasterize_buildings_cog.py + plot_rim2d_
buildings_cog.py) which has bounded memory regardless of city density.

Add Overture Maps building-footprint overlay to the rim2d basin plot.

For each of the 11 rim2d urban extents (rim2d/regions.geojson):
  - downloads Overture building polygons via the `overturemaps` CLI
    (server-side bbox filter, GeoJSON output) — same source as
    hazard-model-api/download_buildings.py. Cached locally so reruns
    don't re-download.
  - reuses the base figure from plot_rim2d_river_network.plot_region
    (HydroBASINS lev-8 basins + TDX-Hydro stream-order rivers + dashed
    rim2d extent + country side-panel) and overlays the building polygons
    on top (dark slategrey fill, α 0.65).

Overture buildings bundle Google Open Buildings, Microsoft GlobalML and
OSM — the most complete footprint source for East Africa.

Outputs:
  runs/rim2d_buildings_data/{iso}_{id}_buildings.geojson   (cache)
  runs/rim2d_buildings_plots/{iso}_{id}_rim2d_buildings.png

  uv run python -m shared.hydrobasins.plot_rim2d_buildings
  uv run python -m shared.hydrobasins.plot_rim2d_buildings --iso ken,sdn

HF upload (after run):
  uv run python -m shared.hydrobasins.upload_to_hf \\
      --folder runs/rim2d_buildings_plots --dest buildings \\
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

from shared.hydrobasins.plot_rim2d_river_network import (  # noqa: E402
    REGIONS_GEOJSON, fetch_tdx, plot_region,
)

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "runs" / "rim2d_buildings_data"
OUT = HERE.parents[1] / "runs" / "rim2d_buildings_plots"


def fetch_buildings(bbox: tuple, out_path: Path) -> Path:
    """overturemaps CLI download buildings → GeoJSON file; cache-on-disk."""
    if out_path.exists():
        return out_path
    DATA.mkdir(parents=True, exist_ok=True)
    bbox_str = ",".join(f"{v:.6f}" for v in bbox)
    cmd = ["overturemaps", "download", "--bbox", bbox_str, "-f", "geojson",
           "-t", "building", "-o", str(out_path)]
    subprocess.run(cmd, check=True)
    return out_path


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
    print(f"rim2d buildings overlay ({len(regions)} regions) → {OUT}\n")
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    for _, row in regions.iterrows():
        iso = str(row["country"])
        rid = str(row["id"])
        bbox = row.geometry.bounds
        bld_path = DATA / f"{iso.lower()}_{rid}_buildings.geojson"
        try:
            print(f"  {iso} ({rid}) {row['region']}: fetching buildings…")
            fetch_buildings(bbox, bld_path)
            buildings = gpd.read_file(bld_path).to_crs("EPSG:4326")
            n = len(buildings)
            print(f"    {n:,} buildings ({bld_path.stat().st_size/1e6:.1f} MB)")

            def overlay(ax, _bldgs=buildings):
                _bldgs.plot(ax=ax, facecolor="#2f3e4d", edgecolor="#0d1620",
                            linewidth=0.05, alpha=0.65, zorder=8)

            fc = fetch_tdx(bbox)
            s = plot_region(row, fc, overlay_fn=overlay, out_dir=OUT,
                            out_suffix="rim2d_buildings",
                            title_extra=f"  · {n:,} Overture buildings")
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
