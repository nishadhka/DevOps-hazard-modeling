"""Per-case TDX-Hydro river network → SIMPLIFIED GeoJSON for HF upload.

Why simplified: raw TDX-Hydro is 12 m resolution (eth raw = 1.5 GB; all 11
≈ 7-8 GB). A ~100 m Douglas-Peucker simplification is visually identical at
country scale and shrinks each file 10-50×, and keeps memory bounded on a
7 GB box (raw eth via json.load would OOM).

Pipeline (memory-safe — never holds a full raw network in RAM):
  - 9 cases already have a raw cache in
    runs/v4_river_network_plots/data/{iso}_river_network_tdx.geojson :
    stream features one-at-a-time (dependency-free incremental JSON reader),
    simplify, stream-write.
  - som / ssd have no cache and OOM'd a whole-bbox fetch: tile the bbox
    (recursively split on HTTP 500), simplify each feature on arrival,
    dedup by linkno — only slim geometry is ever held.

Only linkno + stream_order properties are kept. Output:
  runs/v4_river_geojson/{iso}_river_network_tdx_simplified.geojson

  uv run python -m shared.hydrobasins.make_v4_river_geojson
  uv run python -m shared.hydrobasins.make_v4_river_geojson --iso som,ssd

Then upload with the usual code-0 uploader:
  uv run python -m shared.hydrobasins.upload_to_hf \
      --folder runs/v4_river_geojson --dest v4_river_network
"""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import requests
from shapely.geometry import mapping, shape

import xarray as xr

V4 = Path("/mnt/wflow-secondary/v4_models")
HERE = Path(__file__).resolve().parent
RAW_DIR = HERE.parents[1] / "runs" / "v4_river_network_plots" / "data"
OUT = HERE.parents[1] / "runs" / "v4_river_geojson"

API_BASE = "https://tipg-tiler-template.replit.app"
COLLECTION = "public.ea_river_networks_tdx_v2"
ITEMS_URL = f"{API_BASE}/collections/{COLLECTION}/items"
PAGE_LIMIT = 10000
TILE_DEG = 2.0
MIN_DEG = 0.25

TOL = 0.001  # ≈ 111 m Douglas-Peucker tolerance (degrees)


# --------------------------------------------------------------------------
# streaming reader for our own json.dump'd FeatureCollection (constant memory)
# --------------------------------------------------------------------------
def stream_features(path: Path):
    """Yield Feature dicts from {"...","features":[ ... ]} without loading
    the whole file. Works on the 1.5 GB eth cache within a few MB of RAM."""
    dec = json.JSONDecoder()
    with open(path, "r") as f:
        buf = ""
        # advance to the start of the features array
        while '"features"' not in buf:
            chunk = f.read(65536)
            if not chunk:
                return
            buf += chunk
        i = buf.index('"features"')
        i = buf.index("[", i) + 1
        buf = buf[i:]
        while True:
            buf = buf.lstrip()
            while buf[:1] in (",",):
                buf = buf[1:].lstrip()
            if buf[:1] == "]" or buf == "":
                if buf[:1] == "]":
                    return
            try:
                obj, end = dec.raw_decode(buf)
            except ValueError:
                chunk = f.read(262144)
                if not chunk:
                    return
                buf += chunk
                continue
            yield obj
            buf = buf[end:]


def slim(ft: dict, tol: float) -> dict | None:
    """Simplify geometry; keep only linkno + stream_order. None if degenerate."""
    try:
        g = shape(ft["geometry"]).simplify(tol, preserve_topology=False)
    except Exception:
        return None
    if g.is_empty:
        return None
    p = ft.get("properties", {})
    return {
        "type": "Feature",
        "properties": {"linkno": p.get("linkno"),
                       "stream_order": p.get("stream_order")},
        "geometry": mapping(g),
    }


class GeoJSONWriter:
    """Stream features to a FeatureCollection file without buffering them."""

    def __init__(self, path: Path):
        self.f = open(path, "w")
        self.f.write('{"type": "FeatureCollection", "features": [')
        self.n = 0

    def add(self, feat: dict) -> None:
        if self.n:
            self.f.write(",")
        json.dump(feat, self.f, separators=(",", ":"))
        self.n += 1

    def close(self) -> None:
        self.f.write("]}")
        self.f.close()


# --------------------------------------------------------------------------
# tiled API fetch (for som / ssd) — simplify on arrival, dedup by linkno
# --------------------------------------------------------------------------
def _fetch_page(bbox_str: str) -> list:
    feats, offset = [], 0
    while True:
        r = requests.get(ITEMS_URL, params={"bbox": bbox_str, "limit": PAGE_LIMIT,
                          "offset": offset, "f": "geojson"}, timeout=120)
        r.raise_for_status()
        page = r.json().get("features", [])
        if not page:
            break
        feats.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    return feats


def fetch_tiled_slim(bbox: tuple, tol: float, by_linkno: dict,
                     depth: int = 0) -> None:
    w, s, e, n = bbox
    if (e - w) <= TILE_DEG and (n - s) <= TILE_DEG:
        try:
            feats = _fetch_page(",".join(f"{v:.6f}" for v in bbox))
        except requests.HTTPError as ex:
            code = getattr(ex.response, "status_code", None)
            if code != 500 or (e - w) <= MIN_DEG or (n - s) <= MIN_DEG:
                raise
            print(f"    {'  '*depth}500 → split "
                  f"[{w:.2f},{s:.2f},{e:.2f},{n:.2f}]")
        else:
            for ft in feats:
                sf = slim(ft, tol)
                if sf is not None:
                    by_linkno[ft["properties"]["linkno"]] = sf
            print(f"    {'  '*depth}tile [{w:.2f},{s:.2f},{e:.2f},{n:.2f}] "
                  f"+{len(feats)} (uniq {len(by_linkno)})")
            del feats
            gc.collect()
            return
    if (e - w) >= (n - s):
        mx = 0.5 * (w + e)
        fetch_tiled_slim((w, s, mx, n), tol, by_linkno, depth + 1)
        fetch_tiled_slim((mx, s, e, n), tol, by_linkno, depth + 1)
    else:
        my = 0.5 * (s + n)
        fetch_tiled_slim((w, s, e, my), tol, by_linkno, depth + 1)
        fetch_tiled_slim((w, my, e, n), tol, by_linkno, depth + 1)


# --------------------------------------------------------------------------
def v4_bbox(iso: str) -> tuple:
    with xr.open_dataset(V4 / iso / "staticmaps.nc") as ds:
        lo, la = ds.lon.values, ds.lat.values
    dx, dy = abs(float(lo[1] - lo[0])), abs(float(la[1] - la[0]))
    return (float(lo.min()) - dx / 2, float(la.min()) - dy / 2,
            float(lo.max()) + dx / 2, float(la.max()) + dy / 2)


def _isos() -> list[str]:
    return sorted(p.name for p in V4.iterdir()
                  if p.is_dir() and (p / "staticmaps.nc").is_file())


def process(iso: str) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{iso}_river_network_tdx_simplified.geojson"
    raw = RAW_DIR / f"{iso}_river_network_tdx.geojson"
    wr = GeoJSONWriter(out)
    if raw.exists():
        src = f"raw cache {raw.stat().st_size/1e6:.0f} MB (streamed)"
        for ft in stream_features(raw):
            sf = slim(ft, TOL)
            if sf is not None:
                wr.add(sf)
    else:
        src = "tiled API fetch + simplify"
        by_linkno: dict = {}
        fetch_tiled_slim(v4_bbox(iso), TOL, by_linkno)
        for sf in by_linkno.values():
            wr.add(sf)
        del by_linkno
        gc.collect()
    wr.close()
    mb = out.stat().st_size / 1e6
    return f"{wr.n} segments, {mb:.1f} MB  [{src}]"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iso", default=None,
                    help="Comma-separated subset (default: all 11)")
    args = ap.parse_args()
    isos = _isos()
    if args.iso:
        want = {s.strip() for s in args.iso.split(",")}
        isos = [i for i in isos if i in want]
    print(f"simplified river GeoJSON ({len(isos)} cases, tol≈{TOL}°) → {OUT}\n")
    for iso in isos:
        try:
            info = process(iso)
        except Exception as e:
            print(f"  {iso}: FAILED ({type(e).__name__}: {str(e)[:140]})")
            continue
        print(f"  {iso}: {info}")
        gc.collect()
    files = sorted(OUT.glob("*.geojson"))
    tot = sum(f.stat().st_size for f in files) / 1e6
    print(f"\n{len(files)} GeoJSON written, {tot:.1f} MB total → {OUT}")


if __name__ == "__main__":
    main()
