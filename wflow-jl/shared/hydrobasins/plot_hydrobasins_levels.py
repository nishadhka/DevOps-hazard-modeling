"""HydroBASINS Africa levels 3-12 over the East Africa extent.

Renders one PNG per HydroBASINS level (from coarse lev-03 to urban lev-12)
clipped to a user-chosen bbox (default: East Africa, W,S,E,N = 20,-15,53,25),
plus a 2×5 comparison panel of all 10 levels side-by-side. Each level
shows basin polygons coloured (tab20, cycling) with Natural Earth country
borders for context. Goal: decide which HydroBASINS level is the most
natural replacement for admin1 in CRMA aggregation.

The summary table also reports **pix/basin** = median basin km² /
forecast-pixel km² at the bbox's mid-latitude, for two operational
resolutions: 1° (drought seasonal) and 0.25° (flood, GEFS / ECMWF IFS).
A level is a meaningful aggregation unit when pix/basin ≥ ~1 (so a
forecast pixel sits inside a basin). For East Africa this typically
indicates **level 5 ≈ admin1 / 1° drought**, **level 6 ≈ 0.25° flood**.

Reads shapefiles directly from data/hybas_af_lev{NN}_v1c.zip via /vsizip/
with pyogrio's bbox filter, so memory stays bounded (lev-12 over Africa
is 100k+ basins; the bbox filter keeps only the EA subset).

Outputs (runs/hydrobasins_levels/):
  level_03.png … level_12.png
  levels_compare.png

  uv run python -m shared.hydrobasins.plot_hydrobasins_levels
  uv run python -m shared.hydrobasins.plot_hydrobasins_levels --bbox 20,-15,53,25
  uv run python -m shared.hydrobasins.plot_hydrobasins_levels --levels 5,6,7,8
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE.parents[1] / "runs" / "hydrobasins_levels"
NE_COUNTRIES = DATA / "ne_50m_admin_0_countries.shp"

DEFAULT_BBOX = (20.0, -15.0, 53.0, 25.0)        # W, S, E, N — East Africa
DEFAULT_LEVELS = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
CMAP = plt.cm.tab20

# Operational forecast grid resolutions to compare basin sizes against.
# Pixel area is computed at the bbox mid-latitude in pixel_area_km2().
FORECAST_RES_DEG = {
    "1°  drought seasonal":    1.00,
    "0.25° flood GEFS/IFS":    0.25,
}


def pixel_area_km2(res_deg: float, mid_lat_deg: float) -> float:
    """Approx pixel area at latitude `mid_lat_deg`. Lat 1° ≈ 111 km;
    lon 1° ≈ 111·cos(lat) km."""
    return (111.0 * res_deg) * (111.0 * res_deg * np.cos(np.radians(mid_lat_deg)))


def hybas_path(level: int) -> str:
    return f"/vsizip/{DATA}/hybas_af_lev{level:02d}_v1c.zip"


def read_level(level: int, bbox: tuple) -> gpd.GeoDataFrame:
    """Read HydroBASINS level NN with bbox filter (pyogrio is server-side)."""
    return gpd.read_file(hybas_path(level), bbox=bbox).to_crs("EPSG:4326")


def _draw_level(ax, basins: gpd.GeoDataFrame, countries: gpd.GeoDataFrame,
                bbox: tuple, level: int, *, fontsize_title: float = 11,
                pix_areas: dict | None = None) -> None:
    w, s, e, n = bbox
    nb = len(basins)
    colors = [CMAP(i % CMAP.N) for i in range(nb)]
    basins.plot(ax=ax, color=colors, edgecolor="#222",
                linewidth=0.15, alpha=0.85, zorder=1)
    countries.boundary.plot(ax=ax, color="black", linewidth=0.6, zorder=3)
    # bbox box
    ax.plot([w, e, e, w, w], [s, s, n, n, s],
            color="red", linewidth=0.8, linestyle="--", zorder=4)
    ax.set_xlim(w, e); ax.set_ylim(s, n)
    ax.set_aspect("equal")
    if nb:
        a = basins["SUB_AREA"]
        amin, amed, amax = int(a.min()), int(a.median()), int(a.max())
        sub = f"area km² min/med/max = {amin}/{amed}/{amax}"
        if pix_areas:
            cov = "  ·  pix/bsn " + " / ".join(
                f"{label}={amed/area:.2f}"
                for label, area in pix_areas.items())
            sub += cov
    else:
        sub = "(no basins in bbox)"
    ax.set_title(f"lev-{level:02d}  ·  {nb} basins  ·  {sub}",
                 fontsize=fontsize_title, fontweight="bold")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bbox", default=",".join(str(v) for v in DEFAULT_BBOX),
                    help="W,S,E,N (default East Africa = 20,-15,53,25)")
    ap.add_argument("--levels", default=",".join(str(v) for v in DEFAULT_LEVELS),
                    help="Comma-separated levels (default: 3,4,5,6,7,8,9,10,11,12)")
    args = ap.parse_args()
    bbox = tuple(float(x) for x in args.bbox.split(","))
    if len(bbox) != 4 or not (bbox[0] < bbox[2] and bbox[1] < bbox[3]):
        raise SystemExit(f"--bbox must be W,S,E,N with W<E and S<N, got {bbox}")
    levels = [int(x) for x in args.levels.split(",")]

    OUT.mkdir(parents=True, exist_ok=True)
    mid_lat = 0.5 * (bbox[1] + bbox[3])
    pix_areas = {label: pixel_area_km2(res, mid_lat)
                 for label, res in FORECAST_RES_DEG.items()}
    print(f"HydroBASINS levels {levels} over bbox {bbox} → {OUT}")
    print(f"forecast pixel areas at mid-lat {mid_lat:.1f}°:")
    for label, area in pix_areas.items():
        print(f"    {label:<26s}  {area:>9,.0f} km²")
    print()

    countries = gpd.read_file(NE_COUNTRIES, bbox=bbox).to_crs("EPSG:4326")
    print(f"  countries in bbox: {len(countries)}")

    cached: dict[int, gpd.GeoDataFrame] = {}
    summary = []
    for lev in levels:
        t = time.time()
        try:
            basins = read_level(lev, bbox)
        except Exception as e:
            print(f"  lev-{lev:02d}: FAILED ({type(e).__name__}: "
                  f"{str(e)[:120]})")
            continue
        cached[lev] = basins
        a = basins["SUB_AREA"] if len(basins) else np.array([])
        if len(a):
            amin, amed, amax = int(a.min()), int(a.median()), int(a.max())
            q = a.quantile([0.05, 0.25, 0.75, 0.95]).to_list()
            p5, p25, p75, p95 = (int(v) for v in q)
        else:
            amin = amed = amax = p5 = p25 = p75 = p95 = 0
        cov = {label: (amed / area) if amed else 0.0
               for label, area in pix_areas.items()}
        summary.append((lev, len(basins), amin, p5, p25, amed, p75, p95,
                        amax, cov, time.time() - t))
        # individual PNG
        fig, ax = plt.subplots(figsize=(9, 9))
        ax.set_facecolor("#f7f7f7")
        _draw_level(ax, basins, countries, bbox, lev,
                    fontsize_title=12, pix_areas=pix_areas)
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        fig.tight_layout()
        fig.savefig(OUT / f"level_{lev:02d}.png", dpi=150,
                    bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"  lev-{lev:02d}: {len(basins):,} basins  "
              f"area km² min/med/max = {amin}/{amed}/{amax}  "
              f"({time.time()-t:.1f}s)")

    # comparison panel
    if cached:
        ncols = 5
        nrows = int(np.ceil(len(cached) / ncols))
        fig, axes = plt.subplots(nrows, ncols,
                                 figsize=(4.5 * ncols, 4.2 * nrows))
        axes = np.array(axes).reshape(-1)
        for i, lev in enumerate(sorted(cached)):
            ax = axes[i]
            ax.set_facecolor("#f7f7f7")
            _draw_level(ax, cached[lev], countries, bbox, lev,
                        fontsize_title=9, pix_areas=pix_areas)
            ax.set_xticks([]); ax.set_yticks([])
        for j in range(len(cached), len(axes)):
            axes[j].axis("off")
        pix_caption = "  ·  ".join(
            f"{lbl} pixel ≈ {area:,.0f} km²"
            for lbl, area in pix_areas.items())
        fig.suptitle(f"HydroBASINS Africa — levels {min(cached)}-{max(cached)}  "
                     f"over bbox W,S,E,N = {bbox}\n"
                     f"{pix_caption}",
                     fontsize=13, fontweight="bold")
        fig.tight_layout()
        fig.savefig(OUT / "levels_compare.png", dpi=140,
                    bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"\n  compare panel: levels_compare.png")

    # ---- summary table (with low percentiles + forecast pix/bsn) -----------
    print(f"\nsummary (bbox area ≈ "
          f"{(bbox[2]-bbox[0]) * (bbox[3]-bbox[1]) * 111 * 111:,.0f} km²)")
    cov_headers = list(pix_areas)
    hdr = (f"{'lev':>4}  {'#bsn':>7}  {'min':>5}  {'p5':>6}  {'p25':>7}  "
           f"{'med':>7}  {'p75':>8}  {'p95':>9}  {'max':>9}  "
           + "  ".join(f"{'pix/bsn '+h[:14]:>20s}" for h in cov_headers))
    print(hdr)
    print("-" * len(hdr))
    for (lev, n, amin, p5, p25, amed, p75, p95, amax, cov, _dt) in summary:
        row = (f"{lev:>4}  {n:>7,}  {amin:>5,}  {p5:>6,}  {p25:>7,}  "
               f"{amed:>7,}  {p75:>8,}  {p95:>9,}  {amax:>9,}  "
               + "  ".join(f"{cov[h]:>20.2f}" for h in cov_headers))
        print(row)
    print("\n'pix/bsn' = (median basin km²) / (forecast pixel km²) at mid-lat. "
          "≥ ~1 → basin can host the forecast pixel and serve as an "
          "aggregation unit. For EA: level 5 fits drought 1°, level 6 fits "
          "flood 0.25°.")


if __name__ == "__main__":
    main()
