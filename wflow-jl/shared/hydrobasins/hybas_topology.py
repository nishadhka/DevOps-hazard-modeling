"""HydroBASINS upstream/downstream topology at lev-5 / lev-6 over ICPAC 11.

Builds a directed acyclic graph from the built-in `NEXT_DOWN` attribute
(edge  basin → next_down  where next_down != 0). From that graph:
  - ancestors(X)   = every basin upstream of X (contributes to X's outflow)
  - descendants(X) = every basin downstream of X (affected by X's runoff)
  - distance_to_outlet  =  number of hops from X to its sink

Per-level outputs (runs/hydrobasins_topology/):
  hybas_lev{NN}_topology.geojson
      each basin + `n_upstream`, `n_downstream`, `dist_to_outlet`,
      `is_headwater`, `is_outlet`, `main_bas`, plus original attrs;
      column `chain_ids` = comma-joined downstream HYBAS_IDs from this basin
      to its sink (the "flood propagation chain").
  hybas_lev{NN}_graph.gpickle
      networkx.DiGraph pickle for downstream tooling.
  hybas_lev{NN}_topology.png
      basins coloured by `dist_to_outlet` (blue=source, red=outlet); a picked
      hotspot's downstream chain is highlighted in yellow with arrows.

  uv run python -m shared.hydrobasins.hybas_topology
"""
from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import networkx as nx  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
ADMIN1 = HERE / "icpac_adm1v3.geojson"
OUT = HERE.parents[1] / "runs" / "hydrobasins_topology"

DEFAULT_LEVELS = [5, 6]


def hybas_path(level: int) -> str:
    return f"/vsizip/{DATA}/hybas_af_lev{level:02d}_v1c.zip"


def build_graph(hy: gpd.GeoDataFrame) -> nx.DiGraph:
    """DiGraph edges basin -> next_down (downstream direction)."""
    g = nx.DiGraph()
    for hid in hy["HYBAS_ID"].astype(int):
        g.add_node(int(hid))
    for hid, nd in zip(hy["HYBAS_ID"].astype(int),
                       hy["NEXT_DOWN"].astype(int)):
        if nd != 0 and nd in g:
            g.add_edge(int(hid), int(nd))
    return g


def annotate(hy: gpd.GeoDataFrame, g: nx.DiGraph) -> gpd.GeoDataFrame:
    """Add topology columns to the GeoDataFrame."""
    idx = {int(h): i for i, h in enumerate(hy["HYBAS_ID"].astype(int))}
    n_up   = np.zeros(len(hy), dtype=int)
    n_down = np.zeros(len(hy), dtype=int)
    dist   = np.full(len(hy), -1, dtype=int)
    chain  = [""] * len(hy)
    for hid in hy["HYBAS_ID"].astype(int):
        i = idx[int(hid)]
        n_up[i]   = len(nx.ancestors(g, int(hid)))
        # downstream path: walk NEXT_DOWN until sink (or leaves this level's set)
        path = []
        cur = int(hid)
        while True:
            succ = list(g.successors(cur))
            if not succ:
                break
            cur = succ[0]
            path.append(cur)
        n_down[i] = len(path)
        dist[i]   = len(path)   # hops to sink at this level
        chain[i]  = ",".join(str(x) for x in path)
    hy = hy.copy()
    hy["n_upstream"]      = n_up
    hy["n_downstream"]    = n_down
    hy["dist_to_outlet"]  = dist
    hy["is_headwater"]    = (n_up == 0)
    hy["is_outlet"]       = (n_down == 0)
    hy["chain_ids"]       = chain
    return hy


def _plot(hy: gpd.GeoDataFrame, g: nx.DiGraph, adm: gpd.GeoDataFrame,
          level: int, out_path: Path) -> dict:
    """Plot: basins coloured by dist_to_outlet; the largest-UP_AREA basin's
    downstream chain highlighted."""
    # pick hotspot: the basin with the largest UP_AREA that has downstream
    cand = hy[(hy["n_downstream"] > 0)].sort_values("UP_AREA", ascending=False)
    hotspot_id = int(cand.iloc[0]["HYBAS_ID"]) if len(cand) else None
    if hotspot_id is not None:
        chain_ids = [int(x) for x in
                     cand.iloc[0]["chain_ids"].split(",") if x]
    else:
        chain_ids = []

    fig, ax = plt.subplots(figsize=(11, 10))
    ax.set_facecolor("#eaf1f5")
    adm.boundary.plot(ax=ax, color="black", linewidth=0.5, zorder=3)
    hy.plot(column="dist_to_outlet", cmap="RdYlBu_r", ax=ax,
            edgecolor="#333", linewidth=0.25, alpha=0.85, zorder=2,
            legend=True, legend_kwds={"label": "hops to sink",
                                      "shrink": 0.6})
    # highlight hotspot + downstream chain
    if hotspot_id is not None:
        chain_gdf = hy[hy["HYBAS_ID"].astype(int).isin(chain_ids + [hotspot_id])]
        chain_gdf.boundary.plot(ax=ax, color="#ff7f00", linewidth=1.6, zorder=5)
        hy[hy["HYBAS_ID"].astype(int) == hotspot_id].boundary.plot(
            ax=ax, color="#e6001a", linewidth=2.6, zorder=6)
        # arrows from each basin centroid to its successor centroid
        cent = {int(r["HYBAS_ID"]): r.geometry.representative_point()
                for _, r in hy.iterrows()}
        prev = hotspot_id
        for nxt in chain_ids:
            p0, p1 = cent[prev], cent[nxt]
            ax.annotate("", xy=(p1.x, p1.y), xytext=(p0.x, p0.y),
                        arrowprops=dict(arrowstyle="->", color="#a30013",
                                        lw=1.4, alpha=0.9), zorder=7)
            prev = nxt

    n_out = int(hy["is_outlet"].sum())
    n_hw  = int(hy["is_headwater"].sum())
    ax.set_title(f"HydroBASINS lev-{level:02d} topology  ·  "
                 f"{len(hy)} basins  ·  {n_hw} headwaters  ·  "
                 f"{n_out} outlets\n"
                 f"red-boxed = largest-UP_AREA basin  ·  orange chain = "
                 f"flood-propagation path to its sink ({len(chain_ids)} hops)",
                 fontsize=11, fontweight="bold")
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"hotspot_id": hotspot_id, "chain_len": len(chain_ids)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--levels", default=",".join(str(v) for v in DEFAULT_LEVELS),
                    help=f"Comma-separated levels (default: {DEFAULT_LEVELS})")
    args = ap.parse_args()
    levels = [int(x) for x in args.levels.split(",")]

    OUT.mkdir(parents=True, exist_ok=True)
    adm = gpd.read_file(ADMIN1).to_crs("EPSG:4326")
    bbox = tuple(adm.total_bounds)
    print(f"Bbox (ICPAC admin1 union): {bbox}  →  {OUT}\n")

    print(f"{'lev':>3}  {'#basins':>7}  {'#edges':>7}  {'#headwaters':>11}  "
          f"{'#outlets':>8}  {'max_chain':>9}  hotspot HYBAS_ID")
    print("-" * 85)
    for lev in levels:
        hy = gpd.read_file(hybas_path(lev), bbox=bbox).to_crs("EPSG:4326")
        g = build_graph(hy)
        hy = annotate(hy, g)
        # save geojson (with topology cols)
        gj = OUT / f"hybas_lev{lev:02d}_topology.geojson"
        hy_out = hy.copy()
        # keep only the essentials + topology cols
        cols_keep = ["HYBAS_ID", "NEXT_DOWN", "MAIN_BAS", "PFAF_ID",
                     "DIST_SINK", "DIST_MAIN", "SUB_AREA", "UP_AREA", "ORDER",
                     "n_upstream", "n_downstream", "dist_to_outlet",
                     "is_headwater", "is_outlet", "chain_ids", "geometry"]
        hy_out[[c for c in cols_keep if c in hy_out.columns]].to_file(
            gj, driver="GeoJSON")
        # pickle graph
        with open(OUT / f"hybas_lev{lev:02d}_graph.gpickle", "wb") as f:
            pickle.dump(g, f)
        # plot
        info = _plot(hy, g, adm, lev,
                     OUT / f"hybas_lev{lev:02d}_topology.png")
        print(f"{lev:>3}  {len(hy):>7,d}  {g.number_of_edges():>7,d}  "
              f"{int(hy['is_headwater'].sum()):>11,d}  "
              f"{int(hy['is_outlet'].sum()):>8,d}  "
              f"{int(hy['dist_to_outlet'].max()):>9,d}  "
              f"{info['hotspot_id']}")


if __name__ == "__main__":
    main()
