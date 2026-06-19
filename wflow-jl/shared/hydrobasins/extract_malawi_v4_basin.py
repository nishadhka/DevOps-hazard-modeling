"""Extract Malawi's v4-style basin domain from HydroBASINS Africa.

Pulls the **lev-5 anchor basin** (HYBAS_ID 1051472390, PFAF 12221, the Lake
Malawi / Shire / Upper Zambezi system, 42,695 km², 76% inside Malawi) and
its **lev-6 alternative** (HYBAS_ID 1061442640, PFAF 122217, 17,137 km²,
95% inside MWI). Saves each as GeoJSON matching the existing v4 naming
(outputs_v4/12_malawi_mwi_v4_basin.geojson) so it is launch-ready for a
v4-style wflow run.

Also renders a focused two-panel comparison PNG.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
GEOJSON_DIR = HERE / "outputs_v4"
OUT = HERE.parents[1] / "runs" / "hydrobasins_malawi"
NE = DATA / "ne_50m_admin_0_countries.shp"

ANCHORS = [
    # (level, HYBAS_ID, label, recommended)
    (5, 1051472390, "Primary (v4-style country-scale)", True),
    (6, 1061442640, "Alternative (mostly inside MWI)",  False),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    GEOJSON_DIR.mkdir(parents=True, exist_ok=True)

    ne = gpd.read_file(NE, columns=["ADM0_A3", "NAME"]).to_crs("EPSG:4326")
    mwi = ne[ne["ADM0_A3"] == "MWI"].copy()

    fig, axes = plt.subplots(1, 2, figsize=(13, 9))
    fig.suptitle("Malawi v4-style basin domain — HydroBASINS anchor candidates\n"
                 "(largest basin polygon overlapping Malawi, per level)",
                 fontsize=13, fontweight="bold")

    for ax, (lev, hid, label, recommended) in zip(axes, ANCHORS):
        zp = f"/vsizip/{DATA}/hybas_af_lev{lev:02d}_v1c.zip"
        # Filter by HYBAS_ID — pyogrio supports a WHERE clause
        try:
            basin = gpd.read_file(zp, where=f"HYBAS_ID = {hid}")
        except Exception:
            # fallback: read all and filter in pandas
            basin = gpd.read_file(zp)
            basin = basin[basin["HYBAS_ID"] == hid]
        basin = basin.to_crs("EPSG:4326").copy()

        # Save with v4 naming convention. Primary uses the canonical name
        # so v4 tooling that globs '*_mwi_v4_basin.geojson' picks it up.
        suffix = "" if recommended else f"_lev{lev:02d}"
        out_geo = GEOJSON_DIR / f"12_malawi_mwi_v4_basin{suffix}.geojson"
        basin.to_file(out_geo, driver="GeoJSON")
        size_kb = out_geo.stat().st_size / 1024
        print(f"  lev-{lev:02d} HYBAS_ID={hid}  →  {out_geo.name} ({size_kb:.1f} KB)")

        # ---- plot ----
        # bbox = basin bounds + small padding (so context is visible)
        bw, bs, be, bn = basin.total_bounds
        pad = 0.4
        bbox = (bw - pad, bs - pad, be + pad, bn + pad)
        neighbours = ne[ne["ADM0_A3"] != "MWI"]
        ax.set_facecolor("#fafafa")
        # neighbour countries
        n_in_bbox = neighbours.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
        n_in_bbox.boundary.plot(ax=ax, color="black", linewidth=0.5,
                                zorder=2)
        for _, row in n_in_bbox.iterrows():
            cx, cy = row.geometry.representative_point().coords[0]
            if bbox[0] < cx < bbox[2] and bbox[1] < cy < bbox[3]:
                ax.text(cx, cy, row["ADM0_A3"], fontsize=8, color="#666",
                        ha="center", va="center", zorder=3, alpha=0.8)
        # basin: filled
        basin.plot(ax=ax, color="#4682b4", edgecolor="#19478f",
                   linewidth=1.4, alpha=0.55, zorder=4)
        # malawi
        mwi.boundary.plot(ax=ax, color="#cc0000", linewidth=1.8, zorder=5)
        mwi_in = bbox[0] < mwi.geometry.centroid.x.iloc[0] < bbox[2]
        if mwi_in:
            cx, cy = mwi.geometry.representative_point().iloc[0].coords[0]
            ax.text(cx, cy, "MWI", fontsize=11, color="#cc0000",
                    ha="center", va="center", weight="bold", zorder=6)

        ax.set_xlim(bbox[0], bbox[2]); ax.set_ylim(bbox[1], bbox[3])
        ax.set_aspect("equal")
        ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
        # title block
        # compute equal-area km²
        b_utm = basin.to_crs("EPSG:32736")
        mwi_utm = mwi.to_crs("EPSG:32736")
        inter_km2 = (b_utm.geometry.intersection(
            mwi_utm.geometry.union_all()).area.iloc[0] / 1e6)
        full_km2 = b_utm.geometry.area.iloc[0] / 1e6
        pct = 100 * inter_km2 / full_km2
        flag = "  ★ RECOMMENDED" if recommended else ""
        ax.set_title(
            f"lev-{lev:02d}  ·  {label}{flag}\n"
            f"HYBAS_ID = {hid}  ·  basin = {full_km2:,.0f} km²  ·  "
            f"in MWI = {inter_km2:,.0f} km² ({pct:.0f} %)",
            fontsize=10, fontweight="bold")

    fig.tight_layout()
    png = OUT / "mwi_v4_basin_choice.png"
    fig.savefig(png, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  plot → {png.name}")
    print(f"\ngeojson(s) in {GEOJSON_DIR}; plot in {OUT}")


if __name__ == "__main__":
    main()
