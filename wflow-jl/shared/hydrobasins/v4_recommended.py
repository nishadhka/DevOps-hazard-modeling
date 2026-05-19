"""v4_recommended: revised per-event HydroBASINS selection.

v4 corrects 5 v3 selections after review:
  - BDI: moved SOUTH of the upper-Akagera/Rusumo unit to the Ruvubu
         system (central/E Burundi, drains NE into the Kagera).
  - ERI: moved EAST of Tekeze–Setit to the Anseba / Red Sea coastal
         drainage.
  - SSD: switched from Sudd/Bahr el Jebel (which pulls in the whole
         White Nile incl. all of Uganda) to Bahr el Ghazal — the
         SSD-internal western system that does not originate in Uganda.
  - SDN: switched to the 2nd recommended option, Lower Blue Nile
         (Sennar reach).
  - TZA: switched to the 2nd recommended option, Pangani (EM-DAT NE).
The other 6 events carry over unchanged from v3.

Same machinery as v3 (seed -> smart-snap/BFS upstream or single tile;
area sanity vs the recommendation). Single script, no CLI. Outputs go
to outputs_v4/ and the HuggingFace dataset under hydrobasins/v4/.

Seeds are best-effort from the recommendation rationale + geography. Eyeball
each plot; tweak SEED coords / LEVEL / TARGET_KM2 below and re-run to iterate.
"""
from pathlib import Path
import sys

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from region_configs import REGIONS
from shared.hydrobasins.download import ensure_level, ensure_natural_earth
from shared.hydrobasins.select import (
    _build_reverse, _bfs_upstream, _smart_snap, _snap_outlet,
)

OUT_DIR = HERE / "outputs_v4"
OUT_DIR.mkdir(exist_ok=True)

# --- SINGLE primary basin per event (current focus) ---
#   name      : drainage-system label (legend entry)
#   level     : HydroBASINS Pfafstetter level
#   seed      : (lon, lat) — mode="basin": on the named river just upstream
#               of its confluence; mode="unit": inside the target tile
#   target_km2: approx area from the recommendation
#   mode      : "basin" → BFS upstream of the snapped outlet (full drainage)
#               "unit"  → the single HydroBASINS tile containing the seed
# One selector per event = the IBF-priority system from the recommendation
# rationale. Secondary basins for the multi-basin events are parked in
# SECONDARY_BASINS (not processed) so the info isn't lost.
RECS: dict[str, list[dict]] = {
    "01_Burundi": [
        # v4: moved SOUTH of the upper-Akagera/Rusumo unit to the Ruvubu
        # system (central/E Burundi, drains NE into the Kagera).
        dict(name="Ruvubu (S Burundi Kagera tributary)", level=6,
             seed=(30.30, -3.10), target_km2=12000, mode="basin"),
    ],
    "02_Djibouti": [
        dict(name="Lake Asal–Lake Abbé endorheic (Afar)", level=4,
             seed=(41.80, 11.16), target_km2=23000, mode="basin"),
    ],
    "03_Eritrea": [
        # v4: moved EAST of Tekeze–Setit to the Anseba / Red Sea coastal
        # drainage. lev-6 + basin mode to aggregate a tighter Anseba unit
        # near the ~15,000 km² target (lev-5 there is one coarse tile).
        dict(name="Anseba / Red Sea coastal", level=6, seed=(38.45, 15.78),
             target_km2=15000, mode="basin"),
    ],
    "04_Ethiopia": [
        dict(name="Blue Nile / Abbay", level=4, seed=(34.95, 11.13),
             target_km2=200000, mode="basin"),
    ],
    "05_Kenya": [
        dict(name="Tana", level=4, seed=(40.30, -2.40),
             target_km2=95000, mode="basin"),
    ],
    "06_Rwanda": [
        dict(name="Lower Akagera", level=6, seed=(30.79, -2.38),
             target_km2=25000, mode="basin"),
    ],
    "07_Somalia": [
        dict(name="Juba-Shabelle (combined)", level=4, seed=(42.55, -0.36),
             target_km2=810000, mode="basin"),
    ],
    "08_South_Sudan": [
        # v4: Sudd/Bahr el Jebel pulled in the entire White Nile incl.
        # all of Uganda. Bahr el Ghazal is the SSD-internal western
        # system (NBG/Warrap/W. Bahr el Ghazal) — does not originate in
        # Uganda, so it stays within South Sudan.
        dict(name="Bahr el Ghazal (SSD-internal)", level=4,
             seed=(27.40, 8.77), target_km2=520000, mode="basin"),
    ],
    "09_Sudan": [
        # v4: 2nd recommended option — Lower Blue Nile (Sennar reach).
        dict(name="Lower Blue Nile (Sennar reach)", level=5,
             seed=(33.63, 13.55), target_km2=80000, mode="unit"),
    ],
    "10_Tanzania": [
        # v4: 2nd recommended option — Pangani (EM-DAT NE Tanzania).
        dict(name="Pangani (EM-DAT NE)", level=5, seed=(37.80, -4.30),
             target_km2=43000, mode="unit"),
    ],
    "11_Uganda": [
        dict(name="Lake Kyoga drainage (S Karamoja)", level=5,
             seed=(34.00, 2.00), target_km2=75000, mode="unit"),
    ],
}

# Secondary basins for the multi-basin events — documented for the next
# phase, NOT processed while we focus on a single basin per event.
SECONDARY_BASINS: dict[str, list[dict]] = {
    "03_Eritrea": [
        dict(name="Mereb-Gash", level=5, seed=(37.30, 15.05)),
        dict(name="Anseba / Red Sea coastal", level=5, seed=(38.45, 15.78)),
    ],
    "04_Ethiopia": [
        dict(name="Tekeze", level=4, seed=(38.00, 13.80)),
        dict(name="Awash (endorheic → Lake Abbé)", level=4,
             seed=(41.80, 11.16)),
    ],
    "05_Kenya": [
        dict(name="Ewaso Ng'iro N. / Lorian (endorheic)", level=4,
             seed=(39.50, 0.70)),
        dict(name="Juba-Shabelle headwaters (KE)", level=5,
             seed=(40.80, 3.30)),
        dict(name="Athi-Galana", level=4, seed=(38.80, -2.80)),
    ],
    "08_South_Sudan": [
        dict(name="Bahr el Ghazal", level=4, seed=(27.40, 8.77)),
    ],
    "09_Sudan": [
        dict(name="Lower Blue Nile (Sennar reach)", level=5,
             seed=(33.63, 13.55)),
    ],
    "10_Tanzania": [
        dict(name="Pangani (EM-DAT NE)", level=5, seed=(37.80, -4.30)),
        dict(name="Lake Natron endorheic", level=5, seed=(36.00, -2.40)),
    ],
    "11_Uganda": [
        dict(name="Lake Turkana drainage (E Karamoja)", level=5,
             seed=(33.90, 3.70)),
    ],
}

PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd",
           "#ff7f0e", "#17becf", "#8c564b"]


def _resolve(hb, areas_by_id, reverse, seed, target_km2, mode):
    """Return (subset_gdf, area_km2) for one selector.

    mode="basin": smart-snap the seed to the outlet whose upstream area best
                  matches target, then BFS upstream → full drainage.
    mode="unit" : take the single HydroBASINS tile containing the seed
                  (a sub-basin; no upstream walk).
    """
    if mode == "unit":
        sid = _snap_outlet(hb, seed[0], seed[1])
        subset = hb[hb["HYBAS_ID"] == sid]
    else:
        sid = _smart_snap(hb, areas_by_id, reverse, seed[0], seed[1],
                          target_km2)
        ids = _bfs_upstream(sid, reverse)
        subset = hb[hb["HYBAS_ID"].isin(ids)]
    area = float(subset["SUB_AREA"].sum())
    return subset, area


# Pre-load shapefiles per level used anywhere
levels = sorted({s["level"] for sels in RECS.values() for s in sels})
print(f"Loading HydroBASINS levels {levels} + admin ...")
hb_by_lvl = {}
meta_by_lvl = {}
for lvl in levels:
    hb = gpd.read_file(ensure_level(lvl), engine="pyogrio")
    hb_by_lvl[lvl] = hb
    proj = hb.to_crs("ESRI:54009").geometry.area / 1e6
    meta_by_lvl[lvl] = (
        dict(zip(hb["HYBAS_ID"].astype(int), proj)),
        _build_reverse(hb),
    )
admin = gpd.read_file(ensure_natural_earth(), engine="pyogrio")
print("Loaded.\n")

print(f"{'event':<16}{'basin':<34}{'mode':<7}{'lvl':>4}{'polys':>7}"
      f"{'area_km2':>12}{'target':>10}{'ratio':>8}")
print("-" * 100)

overview_rows = []
for ev, selectors in RECS.items():
    cfg = REGIONS[ev]
    iso = cfg["country_iso"]

    fig, ax = plt.subplots(figsize=(12, 11))
    admin.boundary.plot(ax=ax, color="#888", linewidth=0.5)

    minx = miny = 1e9
    maxx = maxy = -1e9
    geo_rows = []
    for i, sel in enumerate(selectors):
        lvl = sel["level"]
        hb = hb_by_lvl[lvl]
        areas_by_id, reverse = meta_by_lvl[lvl]
        subset, area = _resolve(hb, areas_by_id, reverse,
                                sel["seed"], sel["target_km2"],
                                sel.get("mode", "basin"))
        colour = PALETTE[i % len(PALETTE)]
        diss = subset.dissolve()
        diss.plot(ax=ax, color=colour, alpha=0.5, edgecolor="black",
                  linewidth=0.5)
        ax.plot(*sel["seed"], marker="*", color=colour, markersize=15,
                markeredgecolor="black")

        ratio = area / sel["target_km2"]
        flag = "" if 1/3 <= ratio <= 3 else "  WARN"
        mode = sel.get("mode", "basin")
        print(f"{ev:<16}{sel['name'][:33]:<34}{mode:<7}{lvl:>4}"
              f"{len(subset):>7}{area:>12,.0f}{sel['target_km2']:>10,.0f}"
              f"{ratio:>7.2f}×{flag}")

        gx0, gy0, gx1, gy1 = diss.total_bounds
        minx, miny = min(minx, gx0), min(miny, gy0)
        maxx, maxy = max(maxx, gx1), max(maxy, gy1)

        g = diss.geometry.iloc[0]
        geo_rows.append({
            "event": ev, "iso": iso, "basin": sel["name"],
            "level": lvl, "n_polygons": len(subset),
            "area_km2": area, "target_km2": sel["target_km2"],
            "seed_lon": sel["seed"][0], "seed_lat": sel["seed"][1],
            "geometry": g,
        })
        overview_rows.append({"event": ev, "iso": iso,
                              "basin": sel["name"], "geometry": g,
                              "colour": colour})

        # legend proxy
        ax.plot([], [], color=colour, linewidth=8, alpha=0.5,
                label=f"{sel['name']} — {area:,.0f} km² (lvl {lvl})")

    # v4 basin BOUNDING BOX = the actual run extent (what staticmaps/
    # forcing get subset to). This replaces the old country-bbox dashed
    # box, which was misleading.
    bbox_geom = box(minx, miny, maxx, maxy)
    ax.add_patch(Rectangle(
        (minx, miny), maxx - minx, maxy - miny,
        fill=False, edgecolor="red", linewidth=1.4, linestyle="--",
        label="v4 basin bbox (run extent)"))

    pad = 0.4
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_aspect("equal")
    ax.set_xlabel("lon"); ax.set_ylabel("lat")
    ax.set_title(f"{ev} {iso} — v4 HydroBASINS basin + bbox run extent")
    ax.legend(loc="lower left", fontsize=8, frameon=True)

    fig.savefig(OUT_DIR / f"{ev.lower()}_{iso.lower()}_v4.png",
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    # <ev>_v4.geojson  = the hydrobasin BOUNDING BOX (run extent)
    bx0, by0, bx1, by1 = bbox_geom.bounds
    gpd.GeoDataFrame([{
        "event": ev, "iso": iso,
        "basin": "; ".join(s["name"] for s in selectors),
        "west": bx0, "south": by0, "east": bx1, "north": by1,
        "geometry": bbox_geom,
    }], crs="EPSG:4326").to_file(
        OUT_DIR / f"{ev.lower()}_{iso.lower()}_v4.geojson", driver="GeoJSON")
    # <ev>_v4_basin.geojson = the actual basin polygon(s) (for WRSI mask)
    gpd.GeoDataFrame(geo_rows, crs="EPSG:4326").to_file(
        OUT_DIR / f"{ev.lower()}_{iso.lower()}_v4_basin.geojson",
        driver="GeoJSON")

# Overview
fig, ax = plt.subplots(figsize=(13, 12))
ax.set_xlim(20, 52); ax.set_ylim(-13, 23)
admin.boundary.plot(ax=ax, color="#888", linewidth=0.4)
seen = set()
for r in overview_rows:
    lbl = r["event"] if r["event"] not in seen else None
    seen.add(r["event"])
    gpd.GeoSeries([r["geometry"]], crs="EPSG:4326").plot(
        ax=ax, color=r["colour"], alpha=0.55, edgecolor="black",
        linewidth=0.3, label=lbl)
ax.set_aspect("equal")
ax.set_title("11 ICPAC events — recommended HydroBASINS units (v4)")
ax.set_xlabel("lon"); ax.set_ylabel("lat")
ax.legend(loc="lower left", fontsize=7, frameon=True, ncol=2)
fig.savefig(OUT_DIR / "overview_v4.png", dpi=160, bbox_inches="tight")
plt.close(fig)

print(f"\nDone. Outputs in {OUT_DIR}")
