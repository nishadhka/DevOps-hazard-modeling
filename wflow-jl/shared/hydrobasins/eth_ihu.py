"""ETH IHU rework: acyclic ldd via pyflwdir IHU upscale of native MERIT D8,
regenerate staticmaps+forcing on the upscaled grid, run Wflow.

merit_dir_90m (3 arcsec, hydro-conditioned) -> from_array(d8) ->
upscale(ihu) to ~1 km (acyclic by construction) -> that grid becomes the
new ETH model grid; existing 1 km staticmaps vars + forcing are
reprojected onto it. Output -> /mnt/wflow-secondary/v4_models/eth_ihu/.
"""
import os, subprocess
from pathlib import Path
import numpy as np, xarray as xr, rioxarray, pyflwdir

SRC = Path("/mnt/wflow-secondary/v4_models/eth")
DST = Path("/mnt/wflow-secondary/v4_models/eth_ihu")
(DST/"output").mkdir(parents=True, exist_ok=True)

# 1. native MERIT D8 -> pyflwdir, IHU upscale ~x10 -> ~1 km, acyclic
d = rioxarray.open_rasterio(SRC/"tif/merit_dir_90m.tif").squeeze()
upa = rioxarray.open_rasterio(SRC/"tif/merit_upa_90m.tif").squeeze().values.astype("float32")
d8 = d.values
d8 = np.where(np.isin(d8,[1,2,4,8,16,32,64,128,0]), d8, 0).astype(np.uint8)
tr90 = d.rio.transform()
# full-native (~80M cells) IHU is unviable on this VM; decimate the
# MERIT D8 by K (→ ~K^2 fewer cells) then IHU-upscale to ~1 km.
from rasterio import Affine
K = 3
d8 = d8[::K, ::K]
tr90 = Affine(tr90.a * K, tr90.b, tr90.c, tr90.d, tr90.e * K, tr90.f)
flw = pyflwdir.from_array(d8, ftype="d8", transform=tr90, latlon=True)
flw1, idx = flw.upscale(4, method="ihu")   # ~270 m → ~1 km
ldd = flw1.to_array(ftype="ldd").astype("float32")
ny, nx = flw1.shape
a,b,c,e,f,g = flw1.transform[:6]
lon = c + (np.arange(nx)+0.5)*a
lat = f + (np.arange(ny)+0.5)*e          # e negative -> descending
print(f"IHU grid {ny}x{nx}  pits={int((ldd==5).sum())}", flush=True)

# 2. reproject existing 1km staticmaps vars onto the IHU grid
sm = xr.open_dataset(SRC/"staticmaps.nc").rio.write_crs(4326)
sm = sm.rio.set_spatial_dims(x_dim="lon", y_dim="lat")
tgt = xr.DataArray(np.zeros((ny,nx),"float32"),
        coords={"lat":lat,"lon":lon}, dims=("lat","lon")).rio.write_crs(4326)
out = xr.Dataset()
for v in sm.data_vars:
    if "lat" in sm[v].dims and "lon" in sm[v].dims and v not in ("wflow_ldd","wflow_pits","wflow_subcatch"):
        out[v] = sm[v].rio.reproject_match(tgt).astype("float32")
out = out.assign_coords(lat=lat, lon=lon)
out["wflow_ldd"]=(("lat","lon"),ldd)
fin = np.isfinite(out["wflow_dem"].values)
out["wflow_ldd"]=(("lat","lon"),np.where(fin,ldd,np.nan).astype("float32"))
out["wflow_pits"]=(("lat","lon"),np.where(ldd==5,1.,0.).astype("float32"))
out["wflow_subcatch"]=(("lat","lon"),np.where(fin,1.,np.nan).astype("float32"))
out.to_netcdf(DST/"staticmaps.nc", encoding={v:{"_FillValue":None} for v in out.data_vars})

# 3. reproject forcing onto the IHU grid
fc = xr.open_dataset(SRC/"forcing.nc").rio.write_crs(4326).rio.set_spatial_dims(x_dim="lon",y_dim="lat")
fr = xr.Dataset({k: fc[k].rio.reproject_match(tgt).astype("float32") for k in ("precip","temp","pet")})
fr = fr.assign_coords(lat=lat, lon=lon)
fr.to_netcdf(DST/"forcing.nc")
print("staticmaps+forcing written", flush=True)

# 4. toml + run
t=(SRC/"wflow_v4.toml").read_text().replace(str(SRC),str(DST))
(DST/"wflow_v4.toml").write_text(t)
j=str(Path.home()/".juliaup/bin/julia")
jp="/home/sa_112625140081245282401/DevOps-hazard-modeling/wflow-jl/julia_env"
r=subprocess.run([j,"+1.10",f"--project={jp}","-e",
   f'using Wflow; Wflow.run("{DST}/wflow_v4.toml")'],cwd=DST,
   env={**os.environ,"JULIA_NUM_THREADS":"4"},capture_output=True,text=True)
o=DST/"output"/"output_grid_wrsi.nc"
print(("OK %dMB"%(o.stat().st_size//1e6)) if o.exists()
      else "FAILED rc=%d\n%s"%(r.returncode,(r.stderr or r.stdout)[-700:]),flush=True)
