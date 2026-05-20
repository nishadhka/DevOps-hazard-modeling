"""TDX-Hydro river network per v4 case study, styled by stream order.

Combines two rim2d/ken/nbo_2026 routines, retargeted to the wflow v4
simulation extents:
  - download : the TIPG paginated fetch from
    hazard-model-api/download_river_network.py (collection
    public.ea_river_networks_tdx_v2, props: linkno, stream_order)
  - plot     : the stream-order styling from
    rim2d/ken/nbo_2026/analyze_river_network_v1.py:visualize()
    (higher stream order → thicker line + hotter colour)

For each of the 11 cases the bbox is the staticmaps.nc grid extent
(the actual wflow v4 domain). The _v4_basin.geojson outline is overlaid
for context. Raw GeoJSON is cached so reruns don't re-download.

  uv run python -m shared.hydrobasins.plot_v4_river_network
  uv run python -m shared.hydrobasins.plot_v4_river_network --iso bdi,rwa

Outputs -> runs/v4_river_network_plots/{iso}_river_network.png
           runs/v4_river_network_plots/data/{iso}_river_network_tdx.geojson
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
import xarray as xr  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

V4 = Path("/mnt/wflow-secondary/v4_models")
HERE = Path(__file__).resolve().parent
GEOJSON_DIR = HERE / "outputs_v4"
COUNTRIES_PATH = HERE / "ea_ghcf_simple.geojson"  # ICPAC GHA 11-country ADM0
OUT = HERE.parents[1] / "runs" / "v4_river_network_plots"
DATA = OUT / "data"
SIMPLIFIED_DIR = HERE.parents[1] / "runs" / "v4_river_geojson"

_COUNTRIES: gpd.GeoDataFrame | None = None


def _country_for(iso: str) -> gpd.GeoDataFrame | None:
    """ADM0 polygon for the case's ISO3 from ea_ghcf_simple.geojson."""
    global _COUNTRIES
    if _COUNTRIES is None:
        _COUNTRIES = gpd.read_file(COUNTRIES_PATH).to_crs("EPSG:4326")
    sel = _COUNTRIES[_COUNTRIES["GID_0"].str.upper() == iso.upper()]
    return sel if len(sel) else None

API_BASE = "https://tipg-tiler-template.replit.app"
COLLECTION = "public.ea_river_networks_tdx_v2"
ITEMS_URL = f"{API_BASE}/collections/{COLLECTION}/items"
PAGE_LIMIT = 10000  # API max per page


def v4_bbox(iso: str) -> tuple[float, float, float, float]:
    """west,south,east,north of the staticmaps.nc grid (half-pixel padded)."""
    with xr.open_dataset(V4 / iso / "staticmaps.nc") as ds:
        lo, la = ds.lon.values, ds.lat.values
    dx = abs(float(lo[1] - lo[0]))
    dy = abs(float(la[1] - la[0]))
    return (float(lo.min()) - dx / 2, float(la.min()) - dy / 2,
            float(lo.max()) + dx / 2, float(la.max()) + dy / 2)


TILE_DEG = 2.0   # max tile side; large bboxes 500 the API, so subdivide
MIN_DEG = 0.25   # stop splitting below this (give up on the tile instead)


def fetch_all(bbox_str: str) -> list:
    """Paginate one bbox until an empty/short page (download_*.py logic)."""
    features: list = []
    offset = 0
    while True:
        params = {"bbox": bbox_str, "limit": PAGE_LIMIT, "offset": offset,
                  "f": "geojson"}
        r = requests.get(ITEMS_URL, params=params, timeout=120)
        r.raise_for_status()
        feats = r.json().get("features", [])
        if not feats:
            break
        features.extend(feats)
        if len(feats) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return features


def fetch_bbox(bbox: tuple, *, by_linkno: dict | None = None,
               depth: int = 0) -> dict:
    """Fetch a bbox, recursively splitting on HTTP 500 (server can't handle
    large-area queries). Segments are de-duplicated across tiles by linkno."""
    by_linkno = {} if by_linkno is None else by_linkno
    w, s, e, n = bbox
    pad = "  " * depth
    if (e - w) <= TILE_DEG and (n - s) <= TILE_DEG:
        try:
            feats = fetch_all(",".join(f"{v:.6f}" for v in bbox))
            for ft in feats:
                by_linkno[int(ft["properties"]["linkno"])] = ft
            print(f"    {pad}tile [{w:.2f},{s:.2f},{e:.2f},{n:.2f}] "
                  f"→ {len(feats)} (uniq {len(by_linkno)})")
            return {"type": "FeatureCollection",
                    "features": list(by_linkno.values())}
        except requests.HTTPError as ex:
            code = getattr(ex.response, "status_code", None)
            if code != 500 or (e - w) <= MIN_DEG or (n - s) <= MIN_DEG:
                raise
            print(f"    {pad}tile 500 → split [{w:.2f},{s:.2f},{e:.2f},{n:.2f}]")
    # split the longer axis in two
    if (e - w) >= (n - s):
        mx = 0.5 * (w + e)
        for sub in ((w, s, mx, n), (mx, s, e, n)):
            fetch_bbox(sub, by_linkno=by_linkno, depth=depth + 1)
    else:
        my = 0.5 * (s + n)
        for sub in ((w, s, e, my), (w, my, e, n)):
            fetch_bbox(sub, by_linkno=by_linkno, depth=depth + 1)
    return {"type": "FeatureCollection", "features": list(by_linkno.values())}


def load_or_download(iso: str, bbox: tuple) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    cache = DATA / f"{iso}_river_network_tdx.geojson"
    if cache.exists():
        print(f"  {iso}: cache {cache.name} ({cache.stat().st_size/1e6:.1f} MB)")
        with open(cache) as f:
            return json.load(f)
    # Fallback: simplified GeoJSON (avoids API re-fetch + OOM on som/ssd)
    simp = SIMPLIFIED_DIR / f"{iso}_river_network_tdx_simplified.geojson"
    if simp.exists():
        print(f"  {iso}: simplified {simp.name} "
              f"({simp.stat().st_size/1e6:.1f} MB)")
        with open(simp) as f:
            return json.load(f)
    print(f"  {iso}: fetching TDX-Hydro bbox="
          f"{','.join(f'{v:.4f}' for v in bbox)} (tiled ≤{TILE_DEG}°)")
    fc = fetch_bbox(bbox)
    with open(cache, "w") as f:
        json.dump(fc, f)
    return fc


def _segments(fc: dict) -> list[tuple[int, list]]:
    """(stream_order, [(lon,lat),…]) per feature; splits MultiLineString."""
    segs = []
    for ft in fc["features"]:
        o = int(ft["properties"].get("stream_order", 0))
        g = ft["geometry"]
        if g["type"] == "LineString":
            lines = [g["coordinates"]]
        elif g["type"] == "MultiLineString":
            lines = g["coordinates"]
        else:
            continue
        for ln in lines:
            if len(ln) >= 2:
                segs.append((o, ln))
    return segs


def _geojson_for(iso: str) -> Path | None:
    hits = sorted(GEOJSON_DIR.glob(f"*_{iso}_v4_basin.geojson"))
    return hits[0] if hits else None


def lw_for(order: int) -> float:
    """Stream-order → line width (rim2d feel: ord2≈0.5 … grows linearly)."""
    return round(0.30 + 0.45 * max(order - 1, 0), 2)


def plot_case(iso: str, fc: dict) -> dict:
    segs = _segments(fc)
    orders = sorted({o for o, _ in segs})
    cmap = plt.cm.turbo
    omin, omax = (orders[0], orders[-1]) if orders else (0, 1)
    span = max(omax - omin, 1)
    color_for = {o: cmap((o - omin) / span) for o in orders}

    fig, (ax, iax) = plt.subplots(
        1, 2, figsize=(12, 9),
        gridspec_kw={"width_ratios": [3.6, 1], "wspace": 0.10})
    ax.set_facecolor("#f0f0f0")
    # low orders first (thin, behind), trunk rivers last (thick, on top)
    for o in orders:
        lc = LineCollection([s for so, s in segs if so == o],
                            colors=[color_for[o]], linewidths=lw_for(o),
                            alpha=0.9)
        ax.add_collection(lc)

    geo = _geojson_for(iso)
    basin = gpd.read_file(geo).to_crs("EPSG:4326") if geo is not None else None
    if basin is not None:
        # main map: dashed basin boundary, no fill
        basin.boundary.plot(ax=ax, color="black", linewidth=1.0,
                            linestyle="--", zorder=10)

    handles = [mpatches.Patch(color=color_for[o],
                              label=f"order {o} (lw {lw_for(o)})")
               for o in orders]
    ax.legend(handles=handles, loc="lower right", fontsize=8,
              title="stream order", framealpha=0.9)
    w, s, e, n = v4_bbox(iso)
    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    ax.set_aspect("equal")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"{iso} — TDX-Hydro v2 river network "
                 f"({len(segs)} segments, orders {omin}–{omax})\n"
                 f"v4 simulation extent; dashed black = _v4_basin outline",
                 fontsize=10, fontweight="bold")

    # right-side panel (separate subplot, not overlay): country outline +
    # basin filled, anchored to the country extent for geographic context
    country = _country_for(iso)
    if country is not None and basin is not None:
        iax.set_facecolor("white")
        country.boundary.plot(ax=iax, color="black", linewidth=0.8)
        basin.plot(ax=iax, facecolor="#1f77b4", edgecolor="#0b3d66",
                   linewidth=0.5, alpha=0.7)
        cw, cs, ce, cn = country.total_bounds
        pad = 0.04 * max(ce - cw, cn - cs)
        iax.set_xlim(cw - pad, ce + pad)
        iax.set_ylim(cs - pad, cn + pad)
        iax.set_aspect("equal")
        iax.set_xticks([]); iax.set_yticks([])
        for sp in iax.spines.values():
            sp.set_edgecolor("black"); sp.set_linewidth(0.7)
        iax.set_title(f"{iso.upper()} — basin in country",
                      fontsize=9.5, fontweight="bold", pad=4)
    else:
        iax.axis("off")

    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{iso}_river_network.png", dpi=150,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    hist = {o: sum(1 for so, _ in segs if so == o) for o in orders}
    return {"segments": len(segs), "orders": hist, "geo": geo is not None}


def _isos() -> list[str]:
    return sorted(p.name for p in V4.iterdir()
                  if p.is_dir() and (p / "staticmaps.nc").is_file())


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", default=None,
                    help="Comma-separated ISO subset (default: all 11)")
    args = ap.parse_args()

    isos = _isos()
    if args.iso:
        want = {s.strip() for s in args.iso.split(",")}
        isos = [i for i in isos if i in want]

    print(f"v4 river-network plots ({len(isos)} cases) → {OUT}\n")
    for iso in isos:
        bbox = v4_bbox(iso)
        try:
            fc = load_or_download(iso, bbox)
            if not fc["features"]:
                print(f"  {iso}: 0 features for bbox — skip")
                continue
            s = plot_case(iso, fc)
        except Exception as e:  # network / parse — keep the batch going
            print(f"  {iso}: FAILED ({type(e).__name__}: {str(e)[:120]})")
            continue
        print(f"  {iso}: {s['segments']} segments  orders {s['orders']}  "
              f"basin_overlay={s['geo']}")

    pngs = sorted(p.name for p in OUT.glob("*.png"))
    print(f"\n{len(pngs)} PNGs written to {OUT}")


if __name__ == "__main__":
    main()
