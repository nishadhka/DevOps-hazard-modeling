"""Rebuild a cycle-free ldd from the DEM with pyflwdir, for given cases.

fix_ldd_pyflwdir.py only patches local cycles; the large/endorheic v4
domains (DJI/TZA/KEN/ETH/SOM) keep loops Wflow rejects. pyflwdir.from_dem
priority-floods the DEM and derives a D8 network that is loop-free by
construction. We overwrite wflow_ldd, recompute wflow_pits (ldd==5) and a
single wflow_subcatch over the active DEM, then leave river params as the
median-repair left them.

Usage: python rebuild_ldd.py dji tza ken eth som
"""
import sys
from pathlib import Path
import numpy as np
import xarray as xr
import pyflwdir
from rasterio.transform import from_origin

M = Path("/mnt/wflow-secondary/v4_models")


def rebuild(iso: str) -> str:
    fp = M / iso / "staticmaps.nc"
    ds = xr.load_dataset(fp)
    dem = ds["wflow_dem"].values.astype("float32")
    lat, lon = ds["lat"].values, ds["lon"].values
    xres = abs(lon[1] - lon[0])
    yres = abs(lat[1] - lat[0])
    # lat is descending (north→south) → origin = top-left (west, north)
    transform = from_origin(lon.min() - xres / 2.0,
                            lat.max() + yres / 2.0, xres, yres)
    nod = np.nanmin(dem) - 1e4
    demf = np.where(np.isfinite(dem), dem, nod).astype("float32")
    # Pre-fill depressions so flat lake/sink terrain (e.g. ETH Lake Tana)
    # cannot leave a residual loop that Wflow rejects.
    try:
        demf = pyflwdir.dem.fill_depressions(demf, nodata=nod)[0].astype(
            "float32")
    except Exception:
        pass
    flw = pyflwdir.from_dem(data=demf, nodata=nod, transform=transform,
                            latlon=True)
    ldd = flw.to_array(ftype="ldd").astype("float32")
    active = np.isfinite(dem)
    ldd = np.where(active, ldd, np.nan)
    ds["wflow_ldd"] = (("lat", "lon"), ldd)
    ds["wflow_pits"] = (("lat", "lon"),
                        np.where(ldd == 5, 1.0, 0.0).astype("float32"))
    ds["wflow_subcatch"] = (("lat", "lon"),
                            np.where(active, 1.0, np.nan).astype("float32"))
    enc = {v: {"_FillValue": None} for v in ds.data_vars}
    ds.to_netcdf(fp, encoding=enc)
    npit = int((ldd == 5).sum())
    return f"{iso}: ldd rebuilt, {int(active.sum())} active, {npit} pits"


def rebuild_merit(iso: str) -> str:
    """Use MERIT-Hydro D8 (already hydro-conditioned/acyclic), reprojected
    onto the staticmaps grid, instead of priority-flooding a flat DEM."""
    import rioxarray  # noqa
    fp = M / iso / "staticmaps.nc"
    md = M / iso / "tif" / "merit_dir_90m.tif"
    ds = xr.load_dataset(fp)
    ref = ds["wflow_dem"]
    d8 = (xr.open_dataarray(md).squeeze()
          .rio.reproject_match(ref.rio.write_crs("EPSG:4326"))
          .values).astype("float64")
    # MERIT dir: 1..128 powers of two, 0 = outlet/pit; <0 / >128 = nodata
    d8 = np.where(np.isin(d8, [1, 2, 4, 8, 16, 32, 64, 128, 0]), d8, 0)
    lat, lon = ds["lat"].values, ds["lon"].values
    xres, yres = abs(lon[1] - lon[0]), abs(lat[1] - lat[0])
    transform = from_origin(lon.min() - xres / 2, lat.max() + yres / 2,
                            xres, yres)
    flw = pyflwdir.from_array(d8.astype(np.uint8), ftype="d8",
                              transform=transform, latlon=True)
    ldd = flw.to_array(ftype="ldd").astype("float32")
    active = np.isfinite(ds["wflow_dem"].values)
    ldd = np.where(active, ldd, np.nan)
    ds["wflow_ldd"] = (("lat", "lon"), ldd)
    ds["wflow_pits"] = (("lat", "lon"),
                        np.where(ldd == 5, 1.0, 0.0).astype("float32"))
    ds["wflow_subcatch"] = (("lat", "lon"),
                            np.where(active, 1.0, np.nan).astype("float32"))
    ds.to_netcdf(fp, encoding={v: {"_FillValue": None}
                               for v in ds.data_vars})
    return f"{iso}: MERIT-D8 ldd, {int(active.sum())} active"


if __name__ == "__main__":
    if "--merit" in sys.argv:
        for iso in [a for a in sys.argv[1:] if a != "--merit"]:
            try:
                print(" ", rebuild_merit(iso), flush=True)
            except Exception as e:
                print(f"  {iso}: FAILED {type(e).__name__}: {str(e)[:140]}",
                      flush=True)
        print("Done."); sys.exit(0)
    for iso in (sys.argv[1:] or ["dji", "tza", "ken", "eth", "som"]):
        try:
            print(" ", rebuild(iso), flush=True)
        except Exception as e:
            print(f"  {iso}: FAILED {type(e).__name__}: {str(e)[:140]}",
                  flush=True)
    print("Done.")
