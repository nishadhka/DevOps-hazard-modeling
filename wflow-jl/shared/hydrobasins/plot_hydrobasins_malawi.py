"""HydroBASINS basins covering Malawi — level comparison for new simulation.

Adapted from plot_hydrobasins_levels.py for a single-country focus.
For each level (default 4-8, coarse-to-urban):
  - clips HydroBASINS Africa to a ~1° buffered Malawi bbox (so transboundary
    basins extending into TZA / MOZ / ZMB are visible);
  - highlights basins that intersect Malawi (color by tab20);
  - the rest of the bbox basins are drawn grey (background context);
  - Malawi boundary is drawn in heavy RED;
  - surrounding country borders from Natural Earth 50 m in thin black.

The per-level summary table reports the "anchor basin" — the single basin
with the largest absolute Malawi area (km²). That's the natural wflow
simulation domain at that level.

Output (runs/hydrobasins_malawi/):
  level_04.png … level_08.png
  levels_compare.png      (side-by-side panel)
  malawi_basins_summary.csv

  uv run python -m shared.hydrobasins.plot_hydrobasins_malawi
  uv run python -m shared.hydrobasins.plot_hydrobasins_malawi --levels 5,6
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE.parents[1] / "runs" / "hydrobasins_malawi"
NE_COUNTRIES = DATA / "ne_50m_admin_0_countries.shp"

DEFAULT_LEVELS = [4, 5, 6, 7, 8]
DEFAULT_PAD_DEG = 1.0      # buffer around Malawi bbox to capture neighbours
CMAP = plt.cm.tab20


def hybas_path(level: int) -> str:
    return f"/vsizip/{DATA}/hybas_af_lev{level:02d}_v1c.zip"


def malawi_polygon() -> gpd.GeoDataFrame:
    ne = gpd.read_file(NE_COUNTRIES, columns=["ADM0_A3", "NAME"]).to_crs("EPSG:4326")
    mwi = ne[ne["ADM0_A3"] == "MWI"].copy()
    if not len(mwi):
        raise RuntimeError("Malawi not found in ne_50m_admin_0_countries.shp")
    return mwi


def project_for_area(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Project to an equal-area-ish CRS so .area gives km² (≈)."""
    # Tanzania UTM 36S works for the whole Malawi region (UTM 36 covers 30E-36E)
    return gdf.to_crs("EPSG:32736")


def overlap_summary(basins: gpd.GeoDataFrame, mwi_poly) -> gpd.GeoDataFrame:
    """For each basin: km² inside Malawi (in projected equal-area CRS)."""
    b_utm = project_for_area(basins)
    mwi_utm = project_for_area(gpd.GeoDataFrame({"geometry": [mwi_poly]},
                                                crs="EPSG:4326"))
    mwi_g = mwi_utm.geometry.union_all()
    inter = b_utm.geometry.intersection(mwi_g)
    basins = basins.copy()
    basins["mwi_km2"] = inter.area.values / 1e6
    basins["basin_km2"] = b_utm.geometry.area.values / 1e6
    basins["mwi_pct"]  = 100 * basins["mwi_km2"] / basins["basin_km2"]
    return basins


def _draw_level(ax, basins_in_mwi: gpd.GeoDataFrame,
                basins_others: gpd.GeoDataFrame, mwi: gpd.GeoDataFrame,
                neighbours: gpd.GeoDataFrame, bbox: tuple, level: int,
                *, fontsize_title: float = 11) -> None:
    w, s, e, n = bbox
    ax.set_facecolor("#fafafa")

    # background: bbox basins NOT intersecting MWI in light grey
    if len(basins_others):
        basins_others.plot(ax=ax, color="#e5e5e5", edgecolor="#888",
                           linewidth=0.2, alpha=0.85, zorder=1)

    # foreground: MWI-touching basins, color cycled, edge dark
    colors = [CMAP(i % CMAP.N) for i in range(len(basins_in_mwi))]
    basins_in_mwi.plot(ax=ax, color=colors, edgecolor="#222",
                       linewidth=0.35, alpha=0.78, zorder=2)

    # neighbour country borders (NE 50m): thin black
    if len(neighbours):
        neighbours.boundary.plot(ax=ax, color="black", linewidth=0.45,
                                 zorder=4)

    # Malawi border: heavy red
    mwi.boundary.plot(ax=ax, color="#cc0000", linewidth=1.6, zorder=5)

    # anchor basin marker
    if len(basins_in_mwi):
        anchor = basins_in_mwi.iloc[basins_in_mwi["mwi_km2"].argmax()]
        cx, cy = anchor.geometry.representative_point().coords[0]
        ax.plot(cx, cy, marker="*", color="#000", markersize=18,
                markeredgecolor="white", markeredgewidth=1.0, zorder=6)

    ax.set_xlim(w, e); ax.set_ylim(s, n)
    ax.set_aspect("equal")
    nb = len(basins_in_mwi)
    a_med = float(basins_in_mwi["basin_km2"].median()) if nb else 0
    sub = (f"{nb} basins overlap MWI · "
           f"med basin {a_med:,.0f} km² · ★ = anchor")
    ax.set_title(f"HydroBASINS lev-{level:02d}\n{sub}",
                 fontsize=fontsize_title, fontweight="bold")


def process_level(level: int, mwi: gpd.GeoDataFrame, bbox: tuple,
                  neighbours: gpd.GeoDataFrame, *, save_dir: Path,
                  individual: bool = True) -> tuple:
    all_b = gpd.read_file(hybas_path(level), bbox=bbox).to_crs("EPSG:4326")
    mwi_g = mwi.geometry.union_all()
    in_mask = all_b.geometry.intersects(mwi_g)
    in_mwi = overlap_summary(all_b[in_mask].copy(), mwi_g)
    in_mwi = in_mwi.sort_values("mwi_km2", ascending=False).reset_index(drop=True)
    others = all_b[~in_mask].copy()
    if individual:
        fig, ax = plt.subplots(figsize=(8.5, 10))
        _draw_level(ax, in_mwi, others, mwi, neighbours, bbox, level,
                    fontsize_title=12)
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        fig.tight_layout()
        fig.savefig(save_dir / f"level_{level:02d}.png", dpi=150,
                    bbox_inches="tight", facecolor="white")
        plt.close(fig)
    return in_mwi, others


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", default=",".join(str(v) for v in DEFAULT_LEVELS),
                    help=f"Comma-separated levels (default: {DEFAULT_LEVELS})")
    ap.add_argument("--pad", type=float, default=DEFAULT_PAD_DEG,
                    help=f"bbox buffer around Malawi in degrees "
                         f"(default: {DEFAULT_PAD_DEG})")
    args = ap.parse_args()
    levels = [int(x) for x in args.levels.split(",")]

    OUT.mkdir(parents=True, exist_ok=True)
    mwi = malawi_polygon()
    w, s, e, n = mwi.total_bounds
    bbox = (w - args.pad, s - args.pad, e + args.pad, n + args.pad)
    print(f"Malawi bbox + {args.pad}° pad: {bbox}")

    # neighbouring countries inside the bbox (drawn behind basins)
    ne = gpd.read_file(NE_COUNTRIES, bbox=bbox,
                       columns=["ADM0_A3", "NAME"]).to_crs("EPSG:4326")
    neighbours = ne[ne["ADM0_A3"] != "MWI"]

    cached = {}
    rows = []
    for lev in levels:
        in_mwi, others = process_level(lev, mwi, bbox, neighbours,
                                        save_dir=OUT, individual=True)
        cached[lev] = (in_mwi, others)
        nb = len(in_mwi)
        if nb:
            anchor = in_mwi.iloc[0]
            rows.append({
                "level": lev,
                "n_basins_overlap": nb,
                "anchor_hybas_id": int(anchor["HYBAS_ID"]),
                "anchor_pfaf_id": int(anchor.get("PFAF_ID", -1)),
                "anchor_basin_km2": round(float(anchor["basin_km2"]), 1),
                "anchor_mwi_km2":   round(float(anchor["mwi_km2"]), 1),
                "anchor_mwi_pct":   round(float(anchor["mwi_pct"]), 1),
                "median_basin_km2": round(float(in_mwi["basin_km2"].median()), 1),
                "total_mwi_coverage_km2": round(float(in_mwi["mwi_km2"].sum()), 1),
            })
        print(f"  lev-{lev:02d}: {nb} basins overlap MWI; anchor basin km² = "
              f"{anchor['basin_km2']:.0f} ({anchor['mwi_pct']:.0f}% inside MWI)")

    # ---- compare panel ------------------------------------------------------
    ncols = min(len(cached), 5)
    nrows = int(np.ceil(len(cached) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.6 * ncols, 6.5 * nrows))
    axes = np.array(axes).reshape(-1)
    for i, (lev, (in_mwi, others)) in enumerate(sorted(cached.items())):
        ax = axes[i]
        _draw_level(ax, in_mwi, others, mwi, neighbours, bbox, lev,
                    fontsize_title=10)
        ax.set_xticks([]); ax.set_yticks([])
    for j in range(len(cached), len(axes)):
        axes[j].axis("off")
    fig.suptitle(f"HydroBASINS basins overlapping Malawi — levels "
                 f"{min(cached)}-{max(cached)}.  Coloured = touches MWI; "
                 f"grey = bbox context; red border = MWI; ★ = anchor "
                 f"(largest km² inside MWI).",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "levels_compare.png", dpi=140,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # ---- CSV summary --------------------------------------------------------
    csv_path = OUT / "malawi_basins_summary.csv"
    with csv_path.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(f"\nsummary → {csv_path.name}")
    print(f"{'lev':>3} {'#basins':>8} {'anchor_km²':>10} {'in_MWI_km²':>11} "
          f"{'in_MWI_%':>9} {'med_basin_km²':>13}")
    for r in rows:
        print(f"{r['level']:>3} {r['n_basins_overlap']:>8} "
              f"{r['anchor_basin_km2']:>10,.0f} {r['anchor_mwi_km2']:>11,.0f} "
              f"{r['anchor_mwi_pct']:>8.0f}% {r['median_basin_km2']:>13,.0f}")
    print(f"\n{len(list(OUT.glob('*.png')))} PNGs written to {OUT}")


if __name__ == "__main__":
    main()
