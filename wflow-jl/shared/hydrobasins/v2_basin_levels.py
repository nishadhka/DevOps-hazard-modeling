"""v2_basin_levels: HydroBASINS boundary plots at lvl 4 / 5 / 6 per case.

The lvl-8 polygons used in v2_cdi.py were too fine (hundreds–thousands per
case bbox) for picking the right storyline sub-basin by ID. This script
regenerates boundary-only plots at the three coarser levels so the right
HYBAS_ID can be read off the map and dropped into overrides.py.

Single script, no CLI. Three PNGs per case (33 total) go to outputs_v2_cdi/
and then to the HuggingFace dataset under hydrobasins/v2_cdi/.
"""
from pathlib import Path
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from region_configs import REGIONS
from shared.hydrobasins.download import ensure_level, ensure_natural_earth

OUT_DIR = HERE / "outputs_v2_cdi"
OUT_DIR.mkdir(exist_ok=True)

LEVELS = [4, 5, 6]

print(f"Loading admin + HydroBASINS levels {LEVELS} ...")
admin = gpd.read_file(ensure_natural_earth(), engine="pyogrio")
hb_by_lvl = {lvl: gpd.read_file(ensure_level(lvl), engine="pyogrio")
             for lvl in LEVELS}
print("Loaded.")

for case_name, cfg in REGIONS.items():
    iso = cfg["country_iso"]
    b = cfg["bounds"]
    bbox = box(b["west"], b["south"], b["east"], b["north"])

    for lvl in LEVELS:
        hb = hb_by_lvl[lvl]
        nearby = hb[hb.intersects(bbox)].copy()

        fig, ax = plt.subplots(figsize=(11, 10))
        admin.boundary.plot(ax=ax, color="#444", linewidth=0.6)
        nearby.boundary.plot(ax=ax, color="black", linewidth=0.6)
        nearby.plot(ax=ax, color="lightsteelblue", edgecolor="black",
                    linewidth=0.4, alpha=0.35)

        for _, row in nearby.iterrows():
            c = row.geometry.representative_point()
            ax.annotate(str(int(row["HYBAS_ID"])),
                        xy=(c.x, c.y), fontsize=7, ha="center",
                        color="darkred",
                        bbox=dict(facecolor="white", alpha=0.7,
                                  edgecolor="none", pad=0.6))

        ax.set_xlim(b["west"], b["east"])
        ax.set_ylim(b["south"], b["north"])
        ax.set_aspect("equal")
        ax.set_xlabel("lon"); ax.set_ylabel("lat")
        ax.set_title(
            f"{case_name} {iso} — HydroBASINS lvl {lvl} "
            f"({len(nearby)} polygons in case bbox)"
        )

        out_path = OUT_DIR / f"{iso.lower()}_basins_lvl{lvl:02d}.png"
        fig.savefig(out_path, dpi=160, bbox_inches="tight")
        plt.close(fig)

    print(f"  [{iso}] {case_name}: " + ", ".join(
        f"lvl{lvl}={len(hb_by_lvl[lvl][hb_by_lvl[lvl].intersects(bbox)])}"
        for lvl in LEVELS))

print(f"\nDone. Outputs in {OUT_DIR}")
