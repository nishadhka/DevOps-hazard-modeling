"""CLI entrypoint.

Usage:
    uv run python -m shared.hydrobasins                 # level 8 (default)
    uv run python -m shared.hydrobasins --level 7       # coarser, fewer polygons
    uv run python -m shared.hydrobasins --only ETH      # single case
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .download import ensure_natural_earth
from .plot import OUT_DIR, plot_case, plot_overview, write_geojson
from .select import case_extents
from region_configs import REGIONS


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--level", type=int, default=8, help="HydroBASINS Pfafstetter level (3-12)")
    p.add_argument("--only", help="Process a single case by ISO (e.g. ETH)")
    args = p.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    exts = case_extents(level=args.level)
    if args.only:
        exts = [e for e in exts if e.iso == args.only.upper()]
        if not exts:
            raise SystemExit(f"No case found with ISO {args.only}")

    import geopandas as gpd
    admin = gpd.read_file(ensure_natural_earth(), engine="pyogrio")

    print(f"\n{'case':<14}{'iso':<5}{'method':<20}{'polys':>7}"
          f"{'area_km2':>14}{'storyline':>14}{'ratio':>8}  status")
    print("-" * 95)
    warns: list[str] = []
    for ext in exts:
        story = f"{ext.storyline_area_km2:,.0f}" if ext.storyline_area_km2 else "—"
        ratio = f"{ext.ratio:.2f}×" if ext.ratio is not None else "—"
        status = "WARN" if ext.warning else "ok"
        print(f"{ext.name:<14}{ext.iso:<5}{ext.method:<20}{ext.n_polygons:>7}"
              f"{ext.area_km2:>14,.0f}{story:>14}{ratio:>8}  {status}")
        if ext.warning:
            warns.append(f"  [{ext.iso}] {ext.warning}")
        plot_case(ext, admin, OUT_DIR / f"case_{ext.iso.lower()}.png")

    if warns:
        print("\nWARNINGS (area ratio outside [0.33, 3.0]):")
        for w in warns:
            print(w)

    if not args.only:
        plot_overview(exts, admin, OUT_DIR / "overview_east_africa.png")
        write_geojson(exts, OUT_DIR / "case_extents.geojson")
        print(f"\nWrote {len(exts)} per-case PNGs, overview map, and GeoJSON to {OUT_DIR}")


if __name__ == "__main__":
    main()
