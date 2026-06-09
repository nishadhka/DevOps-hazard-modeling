"""TDX-Hydro river network + HydroBASINS sub-basins per rim2d urban extent.

Adapted from plot_v4_river_network.py for the small (0.15-0.80°)
hydrodynamic extents in ../rim2d/regions.geojson. The 11 regions
correspond to the 11 ICPAC countries (1 per country, urban / event-focused).

For each extent:
  - main panel: HydroBASINS Africa lev-8 sub-basins (≈100-500 km²,
    "small enough to sit within the urban extent" — selected level so
    multiple basins fit per extent) drawn as filled coloured polygons
    (tab20, α 0.45); on top, the TDX-Hydro v2 river network styled by
    stream-order (rim2d analyze_river_network_v1 lw scheme); the rim2d
    region boundary dashed black on top.
  - right side-panel: country outline (ea_ghcf_simple.geojson) + the
    rim2d region polygon filled (locator).

Output: runs/rim2d_river_network_plots/{iso}_{id}_rim2d_river.png
Upload : uv run python -m shared.hydrobasins.upload_to_hf \
         --folder runs/rim2d_river_network_plots \
         --dest rim2d_river_network_plots

  uv run python -m shared.hydrobasins.plot_rim2d_river_network
  uv run python -m shared.hydrobasins.plot_rim2d_river_network --iso ken,bdi
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.patches as mpatches  # noqa: E402
import requests  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

# Reuse v4 helpers so the styling stays consistent across deliverables
from shared.hydrobasins.plot_v4_river_network import (  # noqa: E402
    ITEMS_URL, PAGE_LIMIT, COUNTRIES_PATH, _country_for,
    _segments, lw_for,
)

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
REGIONS_GEOJSON = REPO / "rim2d" / "regions.geojson"
HYBAS_LEV08 = ("/vsizip/" + str(HERE / "data" / "hybas_af_lev08_v1c.zip"))
OUT = HERE.parents[1] / "runs" / "rim2d_river_network_plots"

HYBAS_LEVEL = 8                # HydroBASINS level (≈100-500 km² basins)
BASIN_FILL_CMAP = plt.cm.tab20
BASIN_FILL_ALPHA = 0.45

_HYBAS: gpd.GeoDataFrame | None = None


def _hybas() -> gpd.GeoDataFrame:
    """Load HydroBASINS Africa lev-08 once (≈41k basins, 2 s from /vsizip/)."""
    global _HYBAS
    if _HYBAS is None:
        _HYBAS = gpd.read_file(HYBAS_LEV08).to_crs("EPSG:4326")
    return _HYBAS


def fetch_tdx(bbox: tuple) -> dict:
    """TIPG paginated fetch (no tiling needed — rim2d extents are small)."""
    bbox_str = ",".join(f"{v:.6f}" for v in bbox)
    feats: list = []
    offset = 0
    while True:
        r = requests.get(ITEMS_URL, params={
            "bbox": bbox_str, "limit": PAGE_LIMIT, "offset": offset,
            "f": "geojson"}, timeout=120)
        r.raise_for_status()
        page = r.json().get("features", [])
        if not page:
            break
        feats.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return {"type": "FeatureCollection", "features": feats}


def plot_region(row: dict, fc: dict, *,
                overlay_fn=None, out_dir: Path = OUT,
                out_suffix: str = "rim2d_river",
                title_extra: str = "") -> dict:
    """Draw the rim2d base plot (basins + rivers + extent + side panel).

    overlay_fn(ax) is called after the base layers and before save so other
    scripts (buildings, roads, …) can add their own overlay.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    iso = str(row["country"]).lower()
    rid = str(row["id"])
    name = row["region"]
    region_geom = row["geometry"]
    w, s, e, n = region_geom.bounds

    # river segments + colour/lw by stream order (same scheme as v4 plot)
    segs = _segments(fc)
    orders = sorted({o for o, _ in segs})
    omin, omax = (orders[0], orders[-1]) if orders else (0, 1)
    span = max(omax - omin, 1)
    riv_cmap = plt.cm.turbo
    riv_color = {o: riv_cmap((o - omin) / span) for o in orders}

    # HydroBASINS lev-8 clipped to the rim2d extent
    basins = _hybas().cx[w:e, s:n].copy()
    n_basins = len(basins)
    if n_basins:
        basins["_c"] = [BASIN_FILL_CMAP(i % BASIN_FILL_CMAP.N)
                        for i in range(n_basins)]

    # ---- figure -----------------------------------------------------------
    fig, (ax, iax) = plt.subplots(
        1, 2, figsize=(12, 8),
        gridspec_kw={"width_ratios": [3.6, 1], "wspace": 0.10})
    ax.set_facecolor("#f7f7f7")

    # basins filled first (background), thin outlines on top
    if n_basins:
        basins.plot(ax=ax, color=basins["_c"], alpha=BASIN_FILL_ALPHA,
                    edgecolor="#333", linewidth=0.4, zorder=1)

    # river network — low orders first, trunk on top
    for o in orders:
        lc = LineCollection([s for so, s in segs if so == o],
                            colors=[riv_color[o]], linewidths=lw_for(o),
                            alpha=0.95, zorder=5)
        ax.add_collection(lc)

    # rim2d region boundary dashed black on top of everything
    region_gdf = gpd.GeoDataFrame({"geometry": [region_geom]}, crs="EPSG:4326")
    region_gdf.boundary.plot(ax=ax, color="black", linewidth=1.2,
                             linestyle="--", zorder=10)

    river_handles = [mpatches.Patch(color=riv_color[o],
                                    label=f"order {o} (lw {lw_for(o)})")
                     for o in orders]
    ax.legend(handles=river_handles, loc="lower right", fontsize=8,
              title="TDX-Hydro stream order", framealpha=0.92)
    ax.set_xlim(w, e); ax.set_ylim(s, n)
    ax.set_aspect("equal")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    area_km2 = (basins["SUB_AREA"].agg(["min", "median", "max"]).round().to_dict()
                if n_basins else {})
    sub = (f"  HydroBASINS lev-{HYBAS_LEVEL}: {n_basins} basin"
           f"{'s' if n_basins != 1 else ''}"
           + (f" (min/med/max area km² = {int(area_km2['min'])}/"
              f"{int(area_km2['median'])}/{int(area_km2['max'])})"
              if n_basins else ""))
    ax.set_title(f"{name} ({iso.upper()}, rim2d {rid}) — {len(segs)} river "
                 f"segments, orders {omin}–{omax}\n"
                 f"dashed black = rim2d extent" + sub + title_extra,
                 fontsize=10, fontweight="bold")

    # ---- side panel: country + rim2d extent filled --------------------------
    country = _country_for(iso)
    if country is not None:
        iax.set_facecolor("white")
        country.boundary.plot(ax=iax, color="black", linewidth=0.8)
        region_gdf.plot(ax=iax, facecolor="#d62728", edgecolor="#7a1418",
                        linewidth=0.6, alpha=0.7)
        cw, cs, ce, cn = country.total_bounds
        pad = 0.04 * max(ce - cw, cn - cs)
        iax.set_xlim(cw - pad, ce + pad); iax.set_ylim(cs - pad, cn + pad)
        iax.set_aspect("equal")
        iax.set_xticks([]); iax.set_yticks([])
        for sp in iax.spines.values():
            sp.set_edgecolor("black"); sp.set_linewidth(0.7)
        iax.set_title(f"{iso.upper()} — rim2d extent in country",
                      fontsize=9.5, fontweight="bold", pad=4)
    else:
        iax.axis("off")

    # caller-supplied overlay (buildings, roads, …) on top of base layers
    if overlay_fn is not None:
        overlay_fn(ax)

    fig.tight_layout()
    fig.savefig(out_dir / f"{iso}_{rid}_{out_suffix}.png", dpi=150,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"segments": len(segs), "orders_hist":
            {o: sum(1 for so, _ in segs if so == o) for o in orders},
            "n_basins": n_basins}


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
    print(f"rim2d river-network + HydroBASINS lev-{HYBAS_LEVEL} plots "
          f"({len(regions)} regions) → {OUT}\n")
    for _, row in regions.iterrows():
        iso = row["country"]
        rid = row["id"]
        bbox = row.geometry.bounds
        try:
            fc = fetch_tdx(bbox)
            s = plot_region(row, fc)
        except Exception as e:
            print(f"  {iso} ({rid}): FAILED ({type(e).__name__}: "
                  f"{str(e)[:120]})")
            continue
        print(f"  {iso} ({rid}) {row['region']}: "
              f"{s['segments']} segs orders {s['orders_hist']}  "
              f"basins={s['n_basins']}")
    pngs = sorted(p.name for p in OUT.glob("*.png"))
    print(f"\n{len(pngs)} PNGs written to {OUT}")


if __name__ == "__main__":
    main()
