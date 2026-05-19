"""Cheap ETH fix attempt: clip out the Lake Tana flat, rebuild ldd, run.

Clips the existing ETH staticmaps.nc + forcing.nc to lat <= 11.4 (drops
the Lake Tana / far-north flat that keeps the ldd cyclic), rebuilds a
cycle-free ldd via pyflwdir.from_dem on the smaller domain, writes the
v1.0.2 TOML, runs Wflow. Output → /mnt/wflow-secondary/v4_models/eth_clip/.
"""
import os, shutil, subprocess
from pathlib import Path
import numpy as np, xarray as xr, pyflwdir
from rasterio.transform import from_origin

SRC = Path("/mnt/wflow-secondary/v4_models/eth")
DST = Path("/mnt/wflow-secondary/v4_models/eth_clip")
LAT_MAX = 11.4  # keep lat <= this (lat is descending; Lake Tana ~12.0N)
(DST / "output").mkdir(parents=True, exist_ok=True)

# 1. clip staticmaps + forcing (lat descending → south slice = lat <= LAT_MAX)
sm = xr.load_dataset(SRC / "staticmaps.nc")
sm = sm.sel(lat=sm.lat[sm.lat <= LAT_MAX])
fc = xr.open_dataset(SRC / "forcing.nc")
fc = fc.sel(lat=fc.lat[fc.lat <= LAT_MAX])

# 2. rebuild ldd from clipped DEM
dem = sm["wflow_dem"].values.astype("float32")
lat, lon = sm["lat"].values, sm["lon"].values
xr_, yr_ = abs(lon[1]-lon[0]), abs(lat[1]-lat[0])
tr = from_origin(lon.min()-xr_/2, lat.max()+yr_/2, xr_, yr_)
nod = float(np.nanmin(dem)-1e4)
demf = np.where(np.isfinite(dem), dem, nod).astype("float32")
flw = pyflwdir.from_dem(data=demf, nodata=nod, transform=tr, latlon=True)
ldd = np.where(np.isfinite(dem), flw.to_array(ftype="ldd"), np.nan).astype("float32")
sm["wflow_ldd"] = (("lat","lon"), ldd)
sm["wflow_pits"] = (("lat","lon"), np.where(ldd==5,1.,0.).astype("float32"))
sm["wflow_subcatch"] = (("lat","lon"), np.where(np.isfinite(dem),1.,np.nan).astype("float32"))
enc={v:{"_FillValue":None} for v in sm.data_vars}
sm.to_netcdf(DST/"staticmaps.nc", encoding=enc)
fc.to_netcdf(DST/"forcing.nc")
print(f"clipped grid {sm.sizes['lat']}x{sm.sizes['lon']}, {int(np.isfinite(dem).sum())} active, {int((ldd==5).sum())} pits", flush=True)

# 3. toml from the existing ETH one, repathed
t = (SRC/"wflow_v4.toml").read_text().replace(str(SRC), str(DST))
(DST/"wflow_v4.toml").write_text(t)

# 4. run
j = str(Path.home()/".juliaup/bin/julia")
jp = "/home/sa_112625140081245282401/DevOps-hazard-modeling/wflow-jl/julia_env"
r = subprocess.run([j,"+1.10",f"--project={jp}","-e",
     f'using Wflow; Wflow.run("{DST}/wflow_v4.toml")'], cwd=DST,
     env={**os.environ,"JULIA_NUM_THREADS":"4"}, capture_output=True, text=True)
o = DST/"output"/"output_grid_wrsi.nc"
print("OK "+str(o.stat().st_size//1e6)+"MB" if o.exists() else
      "FAILED rc=%d\n%s"%(r.returncode,(r.stderr or r.stdout)[-800:]), flush=True)
