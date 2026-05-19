"""Walk-upstream-from-outlet basin selection.

For each case in region_configs.REGIONS, find the HydroBASINS polygon containing
the outlet point, then BFS upstream via the NEXT_DOWN field to collect the full
upstream contributing area.

Outlet source priority:
  1. shared.hydrobasins.overrides.HYDROBASINS_OUTLETS  (river-mouth, hand-tuned)
  2. REGIONS[*]["outlet"]                              (wflow-pixel outlet)
  3. bbox-intersect fallback                           (no outlet anywhere)
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point, box

from .download import ensure_level
from . import overrides

import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from region_configs import REGIONS  # noqa: E402

# Sanity-check thresholds: WARN when BFS area is more than 3× off from storyline.
RATIO_WARN_LOW = 1 / 3.0
RATIO_WARN_HIGH = 3.0


@dataclass
class CaseExtent:
    name: str
    iso: str
    title: str
    method: str  # "upstream-override" | "upstream-config" | "bbox-fallback"
    outlet_lon: float | None
    outlet_lat: float | None
    outlet_note: str | None
    level: int
    n_polygons: int
    area_km2: float
    storyline_area_km2: float | None
    ratio: float | None  # area_km2 / storyline_area_km2
    warning: str | None
    geometry: gpd.GeoSeries  # one row, dissolved


def _build_reverse(hb: gpd.GeoDataFrame) -> dict[int, list[int]]:
    rev: dict[int, list[int]] = defaultdict(list)
    for hid, ndown in zip(hb["HYBAS_ID"].to_numpy(), hb["NEXT_DOWN"].to_numpy()):
        if ndown != 0:
            rev[int(ndown)].append(int(hid))
    return rev


def _snap_outlet(hb: gpd.GeoDataFrame, lon: float, lat: float) -> int:
    """Polygon containing (lon, lat); nearest if not contained.

    Used as the seed when no storyline area is available for smarter snapping.
    """
    pt = Point(lon, lat)
    hit = hb[hb.contains(pt)]
    if len(hit) > 0:
        return int(hit.iloc[0]["HYBAS_ID"])
    proj = hb.to_crs("ESRI:54009")
    pt_proj = gpd.GeoSeries([pt], crs="EPSG:4326").to_crs("ESRI:54009").iloc[0]
    nearest_idx = proj.geometry.distance(pt_proj).idxmin()
    return int(hb.loc[nearest_idx, "HYBAS_ID"])


def _neighborhood_ids(hb: gpd.GeoDataFrame, lon: float, lat: float,
                      radius_deg: float = 0.5) -> list[int]:
    """HYBAS_IDs of polygons intersecting a radius_deg buffer around (lon, lat)."""
    buf = Point(lon, lat).buffer(radius_deg)
    sel = hb[hb.intersects(buf)]
    return [int(x) for x in sel["HYBAS_ID"].to_numpy()]


def _smart_snap(hb: gpd.GeoDataFrame, areas_by_id: dict[int, float],
                reverse: dict[int, list[int]], lon: float, lat: float,
                storyline_area_km2: float | None) -> int:
    """Among polygons within ~0.5° of the outlet point, pick the one whose
    upstream BFS area is closest to the storyline area (or the largest area
    if no storyline is given). This recovers from cases where the outlet
    point lands on a coastal/lake-shore polygon that has no upstream
    contributors in the HydroBASINS NEXT_DOWN graph.
    """
    candidates = _neighborhood_ids(hb, lon, lat)
    if not candidates:
        return _snap_outlet(hb, lon, lat)
    best_id, best_score = candidates[0], math.inf
    for cid in candidates:
        ids = _bfs_upstream(cid, reverse)
        area = sum(areas_by_id.get(i, 0.0) for i in ids)
        if storyline_area_km2 is None:
            # No target: pick polygon whose BFS area is largest (river mouth).
            score = -area
        else:
            # Pick the polygon whose BFS area is closest to storyline in log space.
            score = abs(math.log(area / storyline_area_km2)) if area > 0 else math.inf
        if score < best_score:
            best_id, best_score = cid, score
    return best_id


def _bfs_upstream(start_id: int, reverse: dict[int, list[int]]) -> set[int]:
    seen = {start_id}
    queue = deque([start_id])
    while queue:
        cur = queue.popleft()
        for up in reverse.get(cur, ()):
            if up not in seen:
                seen.add(up)
                queue.append(up)
    return seen


def _resolve_outlet(cfg: dict) -> tuple[tuple[float, float] | None, str | None, str]:
    """Return ((lon, lat) | None, note | None, source)."""
    iso = cfg["country_iso"]
    ov = overrides.get(iso)
    if ov is not None:
        return ov, overrides.note(iso), "upstream-override"
    o = cfg.get("outlet")
    if o is not None:
        return (o["lon"], o["lat"]), None, "upstream-config"
    return None, None, "bbox-fallback"


def select_basin(case_name: str, hb: gpd.GeoDataFrame, level: int,
                 *, areas_by_id: dict[int, float] | None = None,
                 reverse: dict[int, list[int]] | None = None) -> CaseExtent:
    cfg = REGIONS[case_name]
    (outlet_xy, outlet_note, method) = _resolve_outlet(cfg)
    storyline_area = (cfg.get("outlet") or {}).get("upstream_km2")

    if outlet_xy is not None:
        if reverse is None:
            reverse = _build_reverse(hb)
        if areas_by_id is None:
            proj_areas = hb.to_crs("ESRI:54009").geometry.area / 1e6
            areas_by_id = dict(zip(hb["HYBAS_ID"].astype(int).tolist(),
                                   proj_areas.tolist()))
        outlet_id = _smart_snap(hb, areas_by_id, reverse,
                                outlet_xy[0], outlet_xy[1], storyline_area)
        ids = _bfs_upstream(outlet_id, reverse)
        subset = hb[hb["HYBAS_ID"].isin(ids)]
    else:
        b = cfg["bounds"]
        bbox = box(b["west"], b["south"], b["east"], b["north"])
        subset = hb[hb.intersects(bbox)]

    dissolved = subset.dissolve()
    area_km2 = float(subset.to_crs("ESRI:54009").area.sum() / 1e6)

    ratio: float | None = None
    warning: str | None = None
    if storyline_area:
        ratio = area_km2 / storyline_area
        if ratio < RATIO_WARN_LOW or ratio > RATIO_WARN_HIGH:
            direction = "under" if ratio < 1 else "over"
            warning = (
                f"area {area_km2:,.0f} km² {direction}-shoots storyline "
                f"{storyline_area:,.0f} km² (ratio {ratio:.2f}× — outside "
                f"[{RATIO_WARN_LOW:.2f}, {RATIO_WARN_HIGH:.1f}])"
            )

    return CaseExtent(
        name=case_name,
        iso=cfg["country_iso"],
        title=cfg["title"],
        method=method,
        outlet_lon=outlet_xy[0] if outlet_xy else None,
        outlet_lat=outlet_xy[1] if outlet_xy else None,
        outlet_note=outlet_note,
        level=level,
        n_polygons=len(subset),
        area_km2=area_km2,
        storyline_area_km2=storyline_area,
        ratio=ratio,
        warning=warning,
        geometry=dissolved.geometry.iloc[[0]],
    )


def case_extents(level: int = 8) -> list[CaseExtent]:
    shp = ensure_level(level)
    hb = gpd.read_file(shp, engine="pyogrio")
    # Precompute once to share across all cases — projection + reverse-map.
    proj_areas = hb.to_crs("ESRI:54009").geometry.area / 1e6
    areas_by_id = dict(zip(hb["HYBAS_ID"].astype(int).tolist(),
                           proj_areas.tolist()))
    reverse = _build_reverse(hb)
    return [select_basin(name, hb, level,
                         areas_by_id=areas_by_id, reverse=reverse)
            for name in REGIONS]
