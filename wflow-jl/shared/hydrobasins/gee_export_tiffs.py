"""Export the 10 wflow input TIFFs per v4 bbox from Google Earth Engine.

Single script, no CLI. For each case in SELECTED:
  - read the v4 bounding box from <iso>_v4.geojson
  - export 10 GeoTIFFs at 1 km to
    /mnt/wflow-secondary/v4_models/<iso>/wflow_datasets_1km/

The 10 layers + the exact contract expected by derive_staticmaps.py:

  1_elevation_merit_1km.tif       MERIT/Hydro elv   (m; hydrologically
                                  consistent with the dir/upa below)
  2_landcover_esa_1km.tif         ESA WorldCover v200 Map (class codes, mode)
  3_soil_sand_1km.tif             SoilGrids sand_mean 0-5cm (g/kg; derive_
  3_soil_silt_1km.tif             SoilGrids silt_mean   renormalises texture
  3_soil_clay_1km.tif             SoilGrids clay_mean   so units cancel)
  4_soil_rootzone_depth_1km.tif   SoilGrids bdod-derived soil column (mm;
                                  used as SoilThickness)
  5_soil_ksat_1km.tif             Cosby pedotransfer from sand/clay (mm/day;
                                  derive_staticmaps clips 1-5000)
  5_soil_porosity_1km.tif         1 - bdod/2.65 (fraction; derive_staticmaps
                                  falls back to texture thetaS if implausible)
  6_river_flow_direction_1km.tif  MERIT/Hydro dir (D8; fix_ldd repairs)
  6_river_flow_accumulation_1km.tif MERIT/Hydro upa (km²)

NOTE: the *original* Burundi soil GEE recipe was never committed to the
deploy-itt repo (only combine_spatial_data.py, which consumes finished
TIFFs). Ksat/porosity here use standard Cosby/bulk-density pedotransfer —
the same class of method the original used. derive_staticmaps.py is
robust to the residual unit/scale differences.

EE auth: the e4drr service account is legacy EE-registered, so
ee.Initialize(credentials) is called WITHOUT project= (passing project=
triggers a spurious Cloud serviceusage check that fails).
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import ee
import geopandas as gpd

REPO = Path(__file__).resolve().parents[2]
V4 = REPO / "shared" / "hydrobasins" / "outputs_v4"
OUT_ROOT = Path("/mnt/wflow-secondary/v4_models")
# GEE service-account key. The repo is PUBLIC: the key is never committed
# (*.json + .secrets/ are gitignored). Default location is the gitignored
# wflow-jl/.secrets/ copy; override with env var EE_SERVICE_ACCOUNT_KEY.
EE_KEY = os.environ.get(
    "EE_SERVICE_ACCOUNT_KEY",
    str(REPO / ".secrets" / "ee-service-account.json"),
)
RES_DEG = 0.00833333  # ~1 km
BBOX_PAD = 0.05

ISO_STEM = {
    "BDI": "01_burundi_bdi_v4",   "DJI": "02_djibouti_dji_v4",
    "ERI": "03_eritrea_eri_v4",   "ETH": "04_ethiopia_eth_v4",
    "KEN": "05_kenya_ken_v4",     "RWA": "06_rwanda_rwa_v4",
    "SOM": "07_somalia_som_v4",   "SSD": "08_south_sudan_ssd_v4",
    "SDN": "09_sudan_sdn_v4",     "TZA": "10_tanzania_tza_v4",
    "UGA": "11_uganda_uga_v4",
}
# smallest bbox first
SELECTED = ["BDI", "RWA", "ERI", "DJI", "UGA", "TZA", "SDN", "KEN",
            "ETH", "SSD", "SOM"]


def ee_init():
    d = json.load(open(EE_KEY))
    ee.Initialize(
        ee.ServiceAccountCredentials(d["client_email"], EE_KEY),
        opt_url="https://earthengine-highvolume.googleapis.com",
    )


def build_images() -> dict[str, ee.Image]:
    """The 10 layers as EE images (native projection; resampled on download)."""
    merit = ee.Image("MERIT/Hydro/v1_0_1")
    wc = ee.ImageCollection("ESA/WorldCover/v200").first().select("Map")
    sand = ee.Image("projects/soilgrids-isric/sand_mean").select(0)
    silt = ee.Image("projects/soilgrids-isric/silt_mean").select(0)
    clay = ee.Image("projects/soilgrids-isric/clay_mean").select(0)
    bdod = ee.Image("projects/soilgrids-isric/bdod_mean").select(0)  # cg/cm3

    # porosity = 1 - rho_b/rho_s ; bdod is in cg/cm3 -> /100 = g/cm3
    porosity = ee.Image(1).subtract(bdod.divide(100).divide(2.65)) \
        .rename("porosity")
    # Cosby (1984) sat. hydraulic conductivity from sand/clay %, mm/day
    sand_pct = sand.divide(10)   # g/kg -> %
    clay_pct = clay.divide(10)
    ksat = ee.Image(10).pow(
        sand_pct.multiply(0.0126).subtract(clay_pct.multiply(0.0064))
        .subtract(0.6)
    ).multiply(25.4 * 24).rename("ksat")          # in/hr -> mm/day
    # soil column depth proxy (mm): SoilGrids covers ~0-2 m
    soil_depth = ee.Image(2000).rename("depth")

    return {
        "1_elevation_merit_1km.tif":        merit.select("elv"),
        "2_landcover_esa_1km.tif":          wc,
        "3_soil_sand_1km.tif":              sand,
        "3_soil_silt_1km.tif":              silt,
        "3_soil_clay_1km.tif":              clay,
        "4_soil_rootzone_depth_1km.tif":    soil_depth,
        "5_soil_ksat_1km.tif":              ksat,
        "5_soil_porosity_1km.tif":          porosity,
        "6_river_flow_direction_1km.tif":   merit.select("dir"),
        "6_river_flow_accumulation_1km.tif": merit.select("upa"),
    }


def export_case(iso: str, imgs: dict[str, ee.Image]) -> dict:
    stem = ISO_STEM[iso]
    w, s, e, n = gpd.read_file(V4 / f"{stem}.geojson").total_bounds
    w, s, e, n = w - BBOX_PAD, s - BBOX_PAD, e + BBOX_PAD, n + BBOX_PAD
    region = ee.Geometry.Rectangle([float(w), float(s), float(e), float(n)])
    out = OUT_ROOT / iso.lower() / "wflow_datasets_1km"
    out.mkdir(parents=True, exist_ok=True)

    summary = {"iso": iso, "bbox": [w, s, e, n], "files": {}}
    for fn, img in imgs.items():
        dst = out / fn
        if dst.exists() and dst.stat().st_size > 1000:
            summary["files"][fn] = "exists"
            continue
        try:
            url = img.unmask(-9999).getDownloadURL({
                "scale": 1000, "crs": "EPSG:4326",
                "region": region, "format": "GEO_TIFF",
            })
            urllib.request.urlretrieve(url, dst)
            summary["files"][fn] = f"{dst.stat().st_size/1e6:.2f}MB"
            print(f"  [{iso}] {fn}: {summary['files'][fn]}")
        except Exception as ex:
            summary["files"][fn] = f"ERR {type(ex).__name__}: {str(ex)[:120]}"
            print(f"  [{iso}] {fn}: {summary['files'][fn]}")
    (out / "download_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    print("EE init ...")
    ee_init()
    print("EE OK. Selected:", SELECTED)
    imgs = build_images()
    for iso in SELECTED:
        print(f"\n=== {iso} ===")
        export_case(iso, imgs)
    print("\nDone.")
