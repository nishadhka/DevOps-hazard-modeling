#!/usr/bin/env python3
"""Build a permanent-water mask (lakes / reservoirs / sea) for a FastFlood case,
so those bodies are not shown as flood in the animation / max-depth maps.

DEM-flatness alone can't separate a flat dry floodplain (e.g. Lower Shabelle,
the Nile plain) from a lake, so we use two reliable, offline signals:

  1. Natural Earth 10m lakes  -> inland water bodies (Tanganyika, Victoria, ...)
  2. DEM sea                  -> cells at/below 0 m connected to a domain edge
                                 (true ocean; Copernicus DEM puts sea ~0/below,
                                 coastal land above 0, so inland plains are spared)

Writes <out>/permanent_water.tif (1 = permanent water) on the case grid.

Usage: build_water_mask.py <dem.tif> <out_dir> [natural_earth_dir]
"""
import sys
import numpy as np, rasterio, shapefile
from rasterio.features import rasterize
from pyproj import Transformer
from shapely.geometry import shape, box
from shapely.ops import transform as shp_transform
from scipy import ndimage
from pathlib import Path

NE_DEFAULT = "/mnt/wflow-secondary/fastflood-data/naturalearth"

def water_mask(dem_tif, ne_dir, sea_level=0.0):
    with rasterio.open(dem_tif) as s:
        crs, tr, W, H, b = s.crs, s.transform, s.width, s.height, s.bounds
        dem = s.read(1).astype("float64")
    # (1) Natural Earth lakes clipped to the domain and reprojected to the grid CRS
    lakes = [shape(sh.__geo_interface__)
             for sh in shapefile.Reader(str(Path(ne_dir) / "ne_10m_lakes.shp")).shapes()]
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    tow = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon0, lat0 = tow.transform(b.left, b.bottom); lon1, lat1 = tow.transform(b.right, b.top)
    bb = box(min(lon0, lon1) - 0.05, min(lat0, lat1) - 0.05,
             max(lon0, lon1) + 0.05, max(lat0, lat1) + 0.05)
    geoms = [shp_transform(lambda x, y, z=None: fwd.transform(x, y), g.intersection(bb))
             for g in lakes if g.is_valid and g.intersects(bb)]
    lake = (rasterize([(g, 1) for g in geoms], out_shape=(H, W), transform=tr,
                      fill=0, dtype="uint8").astype(bool)
            if geoms else np.zeros((H, W), bool))
    # (2) DEM sea: low cells connected to a domain edge
    low = (dem <= sea_level) & np.isfinite(dem)
    lbl, n = ndimage.label(low)
    edge = (set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1]))
    edge.discard(0)
    sea = np.isin(lbl, list(edge)) if edge else np.zeros((H, W), bool)
    return (lake | sea), lake.mean(), sea.mean()

def main():
    dem_tif = sys.argv[1]; out = Path(sys.argv[2])
    ne = sys.argv[3] if len(sys.argv) > 3 else NE_DEFAULT
    out.mkdir(parents=True, exist_ok=True)
    m, lf, sf = water_mask(dem_tif, ne)
    with rasterio.open(dem_tif) as s:
        prof = s.profile
    prof.update(count=1, dtype="float32", compress="deflate", nodata=None)
    with rasterio.open(out / "permanent_water.tif", "w", **prof) as d:
        d.write(m.astype("float32"), 1)
    print(f"permanent_water.tif  water={100*m.mean():.1f}% (lake={100*lf:.1f}% sea={100*sf:.1f}%)")

if __name__ == "__main__":
    main()
