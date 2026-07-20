"""Crosswalk HydroBASINS (lev-5 / lev-6) ↔ ICPAC admin1 (v3).

Spatial many-to-many join between HydroBASINS Africa polygons and the
ICPAC admin1 v3 file (227 units across the 11 GHA states). Overlap
areas are computed in ESRI:102022 (Africa Albers Equal Area) so km²
is honest across the whole ICPAC footprint (multi-UTM-zone).

For each level:
  full_pairs   — every (hybas × admin1) overlap with area km² + fractions;
                 the operational lookup table for risk aggregation.
  dominant_admin1_per_basin — largest-overlap admin1 for each basin.
  dominant_basin_per_admin1 — largest-overlap basin for each admin1.
  crosswalk_lev{NN}.png — admin1 outlines coloured by their dominant basin
                          (visual QC of the mapping).

  uv run python -m shared.hydrobasins.crosswalk_hybas_admin1
  uv run python -m shared.hydrobasins.crosswalk_hybas_admin1 --levels 5,6,7
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
ADMIN1 = HERE / "icpac_adm1v3.geojson"
OUT = HERE.parents[1] / "runs" / "hydrobasins_crosswalk"

# Africa Albers Equal Area Conic — preserves km² across the whole GHA
EQ_AREA_CRS = "ESRI:102022"
DEFAULT_LEVELS = [5, 6]


def hybas_path(level: int) -> str:
    return f"/vsizip/{DATA}/hybas_af_lev{level:02d}_v1c.zip"


def crosswalk_one(level: int, adm: gpd.GeoDataFrame, adm_eq: gpd.GeoDataFrame,
                  save_dir: Path) -> pd.DataFrame:
    """Compute HYBAS × admin1 overlap table for one level."""
    bbox = tuple(float(v) for v in adm.total_bounds)
    hy = gpd.read_file(hybas_path(level), bbox=bbox).to_crs("EPSG:4326")
    hy_eq = hy.to_crs(EQ_AREA_CRS).copy()
    hy_eq["basin_km2"] = hy_eq.geometry.area / 1e6

    # spatial overlay (intersect); attribute preservation + geometry = intersection
    inter = gpd.overlay(hy_eq[["HYBAS_ID", "PFAF_ID", "MAIN_BAS", "NEXT_DOWN",
                               "basin_km2", "geometry"]],
                        adm_eq[["GID_1", "NAME_1", "iso3", "admin1_km2",
                                "geometry"]],
                        how="intersection", keep_geom_type=False)
    inter["overlap_km2"] = inter.geometry.area / 1e6
    inter = inter[inter["overlap_km2"] > 0.01]  # drop numerical sliver

    pairs = pd.DataFrame({
        "hybas_id":       inter["HYBAS_ID"].astype(int),
        "pfaf_id":        inter["PFAF_ID"].astype(int),
        "next_down":      inter["NEXT_DOWN"].astype(int),
        "gid_1":          inter["GID_1"],
        "name_1":         inter["NAME_1"],
        "iso3":           inter["iso3"],
        "overlap_km2":    inter["overlap_km2"].round(2),
        "pct_of_basin":   (100 * inter["overlap_km2"] /
                           inter["basin_km2"]).round(2),
        "pct_of_admin1":  (100 * inter["overlap_km2"] /
                           inter["admin1_km2"]).round(2),
        "basin_km2":      inter["basin_km2"].round(1),
        "admin1_km2":     inter["admin1_km2"].round(1),
    }).sort_values(["hybas_id", "overlap_km2"], ascending=[True, False])

    csv_full = save_dir / f"crosswalk_lev{level:02d}_full.csv"
    pairs.to_csv(csv_full, index=False)

    # dominant admin1 per basin (largest-overlap admin1 per hybas)
    dom_a = (pairs.sort_values("overlap_km2", ascending=False)
                  .drop_duplicates("hybas_id")
                  .sort_values("hybas_id").reset_index(drop=True))
    csv_dom_a = save_dir / f"crosswalk_lev{level:02d}_dominant_admin1.csv"
    dom_a.to_csv(csv_dom_a, index=False)

    # dominant basin per admin1
    dom_b = (pairs.sort_values("overlap_km2", ascending=False)
                  .drop_duplicates("gid_1")
                  .sort_values("gid_1").reset_index(drop=True))
    csv_dom_b = save_dir / f"crosswalk_lev{level:02d}_dominant_basin.csv"
    dom_b.to_csv(csv_dom_b, index=False)

    # ---- visual QC: admin1 coloured by dominant basin's HYBAS_ID ----------
    adm_j = adm.merge(dom_b[["gid_1", "hybas_id"]],
                      left_on="GID_1", right_on="gid_1", how="left")
    fig, ax = plt.subplots(figsize=(11, 10))
    adm_j.plot(column="hybas_id", categorical=True, cmap="tab20",
               ax=ax, edgecolor="#333", linewidth=0.35, legend=False)
    ax.set_facecolor("#f6f6f6")
    ax.set_title(f"HydroBASINS lev-{level:02d} ↔ ICPAC admin1 v3\n"
                 f"admin1 coloured by its DOMINANT basin  ·  "
                 f"{len(pairs)} pairs · {pairs['hybas_id'].nunique()} basins "
                 f"across {pairs['gid_1'].nunique()} admin1 units",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(save_dir / f"crosswalk_lev{level:02d}.png", dpi=150,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", default=",".join(str(v) for v in DEFAULT_LEVELS),
                    help=f"Comma-separated HydroBASINS levels (default: {DEFAULT_LEVELS})")
    args = ap.parse_args()
    levels = [int(x) for x in args.levels.split(",")]

    OUT.mkdir(parents=True, exist_ok=True)
    adm = gpd.read_file(ADMIN1).to_crs("EPSG:4326")
    adm["iso3"] = adm["GID_1"].str.split(".").str[0]
    adm_eq = adm.to_crs(EQ_AREA_CRS).copy()
    adm_eq["admin1_km2"] = adm_eq.geometry.area / 1e6
    adm["admin1_km2"] = adm_eq["admin1_km2"].values

    print(f"ICPAC admin1 v3: {len(adm)} units across {adm['iso3'].nunique()} "
          f"states  →  {OUT}\n")

    print(f"{'lev':>3}  {'#basins':>7}  {'#admin1':>7}  {'#pairs':>7}  "
          f"{'multi_admin1_basins':>19}  {'multi_basin_admin1':>19}")
    print("-" * 78)
    for lev in levels:
        p = crosswalk_one(lev, adm, adm_eq, OUT)
        n_basins = p["hybas_id"].nunique()
        n_admin1 = p["gid_1"].nunique()
        multi_a = (p.groupby("hybas_id").size() > 1).sum()   # basins in >1 admin1
        multi_b = (p.groupby("gid_1").size() > 1).sum()      # admin1s in >1 basin
        print(f"{lev:>3}  {n_basins:>7,d}  {n_admin1:>7,d}  {len(p):>7,d}  "
              f"{multi_a:>19,d}  {multi_b:>19,d}")


if __name__ == "__main__":
    main()
