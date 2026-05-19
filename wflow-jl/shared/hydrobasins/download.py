"""Download HydroBASINS Africa shapefiles from the HydroSHEDS data portal.

HydroBASINS levels:
  03 — major basins         05 — ~10,000 km²
  07 — ~1,500 km²           08 — ~500 km²   (recommended default for upstream walks)
  12 — smallest leaves

Source: https://www.hydrosheds.org/products/hydrobasins
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import requests
from tqdm import tqdm

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
BASE_URL = "https://data.hydrosheds.org/file/HydroBASINS/standard"
NE_URL = "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip"


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(dest, "wb") as f, tqdm(
            total=total, unit="B", unit_scale=True, desc=dest.name
        ) as pbar:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
                pbar.update(len(chunk))
    return dest


def _unzip(zip_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target_dir)


def ensure_level(level: int, *, region: str = "af") -> Path:
    """Return path to a HydroBASINS shapefile, downloading + extracting if missing."""
    lvl = f"{level:02d}"
    shp_name = f"hybas_{region}_lev{lvl}_v1c.shp"
    shp_path = DATA_DIR / shp_name
    if shp_path.exists():
        return shp_path
    zip_name = f"hybas_{region}_lev{lvl}_v1c.zip"
    zip_path = DATA_DIR / zip_name
    if not zip_path.exists():
        _download(f"{BASE_URL}/{zip_name}", zip_path)
    _unzip(zip_path, DATA_DIR)
    if not shp_path.exists():
        raise FileNotFoundError(f"Extraction did not produce {shp_path}")
    return shp_path


def ensure_natural_earth() -> Path:
    """Natural Earth 1:50m admin0 polygons for country-boundary context in plots."""
    shp_path = DATA_DIR / "ne_50m_admin_0_countries.shp"
    if shp_path.exists():
        return shp_path
    zip_path = DATA_DIR / "ne_50m_admin_0_countries.zip"
    if not zip_path.exists():
        _download(NE_URL, zip_path)
    _unzip(zip_path, DATA_DIR)
    return shp_path
