"""rim2d buildings overlay from the 5 m COG (replaces the OOM-prone GeoJSON path).

For each of the 11 rim2d regions:
  - opens runs/rim2d_buildings_cog/{iso}_{id}_buildings_5m.tif (5 m UTM,
    built by rasterize_buildings_cog.py from the Overture parquet cache)
  - virtually reprojects to EPSG:4326 (WarpedVRT, Resampling.max preserves
    the binary footprint)
  - layers onto plot_rim2d_river_network.plot_region via overlay_fn — a
    single ax.imshow of the masked raster. No vector polygons in flight;
    peak memory is the raster (a few MB) regardless of city density.

Output : runs/rim2d_buildings_plots/{iso}_{id}_rim2d_buildings.png
HF dest: buildings_plots/  on  E4DRR/rim2d-simulations

  uv run python -m shared.hydrobasins.plot_rim2d_buildings_cog
  uv run python -m shared.hydrobasins.plot_rim2d_buildings_cog --iso sdn,rwa
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from rasterio.transform import from_bounds as transform_from_bounds  # noqa: E402
from rasterio.vrt import WarpedVRT  # noqa: E402
from rasterio.warp import Resampling, transform_bounds  # noqa: E402

from shared.hydrobasins.plot_rim2d_river_network import (  # noqa: E402
    REGIONS_GEOJSON, fetch_tdx, plot_region,
)

HERE = Path(__file__).resolve().parent
COG_DIR = HERE.parents[1] / "runs" / "rim2d_buildings_cog"
OUT = HERE.parents[1] / "runs" / "rim2d_buildings_plots"

BLD_RGBA = (0.18, 0.24, 0.30, 0.75)   # slate-grey w/ alpha
BLD_CMAP = ListedColormap([BLD_RGBA])

# Downsample target — keeps memory bounded for big rasters (rwa 5 m UTM is
# 14501 × 13308 = 193 M px; full-resolution imshow OOMs matplotlib at the
# RGBA mapping step on a 7 GB box). 2400 px wide ≥ a 1800-px PNG at dpi 150,
# so visually lossless.
MAX_DISPLAY_PX = 2400


def load_buildings_4326(iso: str, rid: str) -> tuple[np.ndarray, tuple]:
    """Read 5 m UTM COG → WarpedVRT to EPSG:4326 at MAX_DISPLAY_PX wide
    (single warp does both reprojection AND downsampling with
    Resampling.max → preserves binary footprints), return (uint8, ext)."""
    cog = COG_DIR / f"{iso.lower()}_{rid}_buildings_5m.tif"
    if not cog.exists():
        raise FileNotFoundError(cog)
    with rasterio.open(cog) as src:
        w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
        aspect = (n - s) / (e - w)
        tw = min(MAX_DISPLAY_PX, src.width)
        th = max(1, int(round(tw * aspect)))
        transform = transform_from_bounds(w, s, e, n, tw, th)
        with WarpedVRT(src, crs="EPSG:4326", transform=transform,
                       width=tw, height=th,
                       resampling=Resampling.max) as vrt:
            arr = vrt.read(1)
    return arr, (w, e, s, n)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", default=None,
                    help="Comma-separated ISO3 subset (default: all 11)")
    args = ap.parse_args()
    regions = gpd.read_file(REGIONS_GEOJSON).to_crs("EPSG:4326")
    if args.iso:
        want = {s.strip().upper() for s in args.iso.split(",")}
        regions = regions[regions["country"].isin(want)]
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"rim2d buildings (COG @5m) overlay ({len(regions)} regions) "
          f"→ {OUT}\n")
    for _, row in regions.iterrows():
        iso = str(row["country"]); rid = str(row["id"])
        try:
            arr, ext = load_buildings_4326(iso, rid)
        except FileNotFoundError:
            print(f"  {iso} ({rid}): COG not found — skip")
            continue
        built_pct = 100.0 * (arr > 0).mean()

        def overlay(ax, _arr=arr, _ext=ext):
            masked = np.ma.masked_equal(_arr, 0)
            ax.imshow(masked, extent=_ext, cmap=BLD_CMAP,
                      vmin=1, vmax=1, zorder=8,
                      interpolation="nearest", origin="upper")

        bbox = row.geometry.bounds
        try:
            fc = fetch_tdx(bbox)
            s = plot_region(row, fc, overlay_fn=overlay, out_dir=OUT,
                            out_suffix="rim2d_buildings",
                            title_extra=f"  · buildings {built_pct:.2f}% "
                            f"(COG 5 m)")
        except Exception as e:
            print(f"  {iso} ({rid}): FAILED ({type(e).__name__}: "
                  f"{str(e)[:120]})")
            continue
        print(f"  {iso} ({rid}) {row['region']}: built {built_pct:.2f}%  "
              f"({s['segments']} river segs, {s['n_basins']} basins)")

    pngs = sorted(p.name for p in OUT.glob("*.png"))
    print(f"\n{len(pngs)} PNGs written to {OUT}")


if __name__ == "__main__":
    main()
