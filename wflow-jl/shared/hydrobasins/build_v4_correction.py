"""Parameterized multi-case v4 builder for the basin/window CORRECTIONS.

Generalizes build_tza_kagera.py / build_ssd_upper_nile.py to a CONFIGS list, so
the SDN-Eastern + humid-Great-Lakes corrections build with one driver. Each case
runs the full pipeline ALONGSIDE the originals (non-destructive, new dir):
  1 geojson (select.py)  2 static (HMA/GEE)  3 repair+river-check
  4 forcing (EDH ERA5)   5 toml + wflow run (DIRECT julia binary)

Cases (2026-06-09):
  sdn_eastern   Kassala/Gash (lev-5 unit, ~73k km²) 2020-23  [event Eastern States 2022]
  uga_karamoja  Karamoja (lev-6 unit, ~6.7k km²)   2020-23  [event Karamoja 2022; fixes Kyoga dilution]
  bdi_baseline  Ruvubu (lev-6 basin, ~12k km²)     2020-23  [event Burundi 2021-22; +2020 baseline]
  rwa_baseline  Lower Akagera (lev-6 basin, ~25k)  2014-17  [event Akagera 2016-17; +2014-15 baseline]

Run: `uv run python -m shared.hydrobasins.build_v4_correction [name ...]`
(no args = all). Needs GEE key + EDH token. Uses the direct julia binary
(julia +1.10 can hang on a held juliaup config lock).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import xarray as xr
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[2]
HMA = REPO.parent / "hazard-model-api"
V4 = REPO / "shared" / "hydrobasins" / "outputs_v4"
MODELS = Path("/mnt/wflow-secondary/v4_models")
VENV_PY = REPO / ".venv" / "bin" / "python"
SA_KEY = REPO / ".secrets" / "ee-service-account.json"
JULIA = Path.home() / ".julia/juliaup/julia-1.10.11+0.x64.linux.gnu/bin/julia"
JL_PROJ = REPO / "julia_env"
TOML_TEMPLATE = MODELS / "bdi" / "wflow_v4.toml"   # generic v4 SBM config

CONFIGS = {
    "sdn_eastern": dict(stem="09b_sudan_kassala_v4", basin="Kassala/Gash (Eastern States)",
                        seed=(36.40, 15.45), level=5, mode="unit",
                        fstart="2020-01-01", fend="2023-12-31"),
    "uga_karamoja": dict(stem="11b_uganda_karamoja_v4", basin="Karamoja (NE Uganda)",
                         seed=(34.65, 2.53), level=6, mode="unit",
                         fstart="2020-01-01", fend="2023-12-31"),
    "bdi_baseline": dict(stem="01b_burundi_ruvubu_baseline_v4", basin="Ruvubu",
                         seed=(30.30, -3.10), level=6, mode="basin", target=12000,
                         fstart="2020-01-01", fend="2023-12-31"),
    "rwa_baseline": dict(stem="06b_rwanda_akagera_baseline_v4", basin="Lower Akagera",
                         seed=(30.79, -2.38), level=6, mode="basin", target=25000,
                         fstart="2014-01-01", fend="2017-12-31"),
}


def phase1_geojson(name, cfg):
    from shared.hydrobasins.download import ensure_level
    from shared.hydrobasins.select import (_build_reverse, _smart_snap,
                                            _bfs_upstream, _snap_outlet)
    hb = gpd.read_file(ensure_level(cfg["level"]), engine="pyogrio")
    if cfg["mode"] == "unit":
        sid = _snap_outlet(hb, *cfg["seed"])
        subset = hb[hb["HYBAS_ID"] == sid]
    else:
        areas = dict(zip(hb["HYBAS_ID"].astype(int),
                         hb.to_crs("ESRI:54009").geometry.area / 1e6))
        rev = _build_reverse(hb)
        sid = _smart_snap(hb, areas, rev, cfg["seed"][0], cfg["seed"][1],
                          cfg["target"])
        subset = hb[hb["HYBAS_ID"].isin(_bfs_upstream(sid, rev))]
    area = float(subset["SUB_AREA"].sum())
    diss = subset.dissolve()
    w, s, e, n = diss.total_bounds
    print(f"[1/{name}] {cfg['basin']}: {len(subset)} poly, {area:,.0f} km², "
          f"bbox {w:.3f},{s:.3f},{e:.3f},{n:.3f}", flush=True)
    gpd.GeoDataFrame([{"event": name, "basin": cfg["basin"], "west": w,
        "south": s, "east": e, "north": n, "geometry": box(w, s, e, n)}],
        crs="EPSG:4326").to_file(V4 / f"{cfg['stem']}.geojson", driver="GeoJSON")
    gpd.GeoDataFrame([{"event": name, "basin": cfg["basin"], "level": cfg["level"],
        "area_km2": area, "seed_lon": cfg["seed"][0], "seed_lat": cfg["seed"][1],
        "geometry": diss.geometry.iloc[0]}], crs="EPSG:4326").to_file(
        V4 / f"{cfg['stem']}_basin.geojson", driver="GeoJSON")
    return f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}"


def _hma(script, *args):
    r = subprocess.run([str(VENV_PY), script, *args], cwd=HMA,
                       env={**os.environ, "GEE_SA_KEY": str(SA_KEY)},
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:]); raise SystemExit(f"{script} rc={r.returncode}")


def phase2_static(name, cfg, bb):
    out = MODELS / name
    out.mkdir(parents=True, exist_ok=True)
    print(f"[2/{name}] static (GEE)", flush=True)
    _hma("download_dem.py", "--scale", "1000", "--target", "merit", "--bbox", bb, "--out", str(out))
    _hma("download_worldcover.py", "--scale", "1000", "--bbox", bb, "--out", str(out))
    _hma("download_merit_hydro.py", "--bbox", bb, "--out", str(out))
    _hma("download_soilgrids.py", "--scale", "1000", "--bbox", bb, "--out", str(out))
    _hma("prepare_wflow_staticmaps.py", "--bbox", bb, "--out", str(out),
         "--start", cfg["fstart"], "--end", cfg["fend"])
    _hma("fix_ldd_pyflwdir.py", "--staticmaps", str(out / "staticmaps.nc"))


def phase3_repair(name):
    from shared.hydrobasins.repair_v4_staticmaps import repair
    from shared.hydrobasins.eth_river_fix import build_succ, violations
    import numpy as np
    print(f"[3/{name}]", repair(name), flush=True)
    # A unit-basin in a large bbox leaves nodata-ldd (255) edge cells. Wflow's
    # NetworkLand includes them (repair strips _FillValue, so subcatch NaN is
    # not seen as `missing`) → PCR_DIR[255] BoundsError. Set ldd 255→pit(5).
    fp = MODELS / name / "staticmaps.nc"
    dd = xr.load_dataset(fp)
    ldd = dd["wflow_ldd"].values
    nbad = int((ldd == 255).sum())
    if nbad:
        ldd = np.where(ldd == 255, 5.0, ldd).astype("float32")
        dd["wflow_ldd"] = (("lat", "lon"), ldd)
        dd["wflow_pits"] = (("lat", "lon"),
                            np.where(ldd == 5, 1.0, 0.0).astype("float32"))
        dd.to_netcdf(fp, encoding={v: {"_FillValue": None} for v in dd.data_vars})
        print(f"[3/{name}] set {nbad} nodata-ldd(255) cells -> pit(5)", flush=True)
    ds = xr.open_dataset(fp)
    v = violations((ds["wflow_river"].values == 1).ravel(),
                   build_succ(ds["wflow_ldd"].values.astype("float32")))
    print(f"[3/{name}] river-mask cycle violations = {v}", flush=True)
    if v:
        import importlib
        m = importlib.import_module("shared.hydrobasins.eth_river_fix")
        m.FP = MODELS / name / "staticmaps.nc"
        sys.argv = ["", "--fix"]
        m.main()


def phase4_forcing(name, cfg):
    from shared.hydrobasins.build_v4_forcing import open_era5, PAD
    out = MODELS / name
    w, s, e, n = gpd.read_file(V4 / f"{cfg['stem']}.geojson").total_bounds
    sm = xr.open_dataset(out / "staticmaps.nc")
    sub = open_era5()[["tp", "t2m", "pev"]].sel(
        time=slice(cfg["fstart"], f"{cfg['fend']}T23:59"),
        latitude=slice(n + PAD, s - PAD), longitude=slice(w - PAD, e + PAD))
    daily = xr.Dataset()
    daily["precip"] = sub["tp"].resample(time="1D").sum() * 1000.0
    daily["temp"] = sub["t2m"].resample(time="1D").mean() - 273.15
    daily["pet"] = (-sub["pev"].resample(time="1D").sum() * 1000.0).clip(min=0)
    daily = daily.sortby("latitude").sortby("longitude").load().chunk({"time": 30})
    fr = daily.interp(latitude=sm["lat"].values, longitude=sm["lon"].values,
                      method="linear").rename({"latitude": "lat", "longitude": "lon"})
    fr = fr.assign_coords(lat=sm["lat"].values, lon=sm["lon"].values)
    for v in ("precip", "temp", "pet"):
        fr[v] = fr[v].astype("float32")
    fr.attrs = {"source": "EDH ERA5 single-levels v0", "case": name,
                "period": f"{cfg['fstart']}/{cfg['fend']}"}
    fr.to_netcdf(out / "forcing.nc", encoding={v: {"zlib": True, "complevel": 1}
                 for v in ("precip", "temp", "pet")})
    print(f"[4/{name}] forcing {fr['time'].size}d {fr.sizes['lat']}x"
          f"{fr.sizes['lon']} P[{float(fr.precip.mean()):.1f}] "
          f"T[{float(fr.temp.mean()):.1f}] PET[{float(fr.pet.mean()):.1f}]", flush=True)


def phase5_run(name, cfg):
    out = MODELS / name
    y0 = cfg["fstart"][:4]
    rstart = f"{y0}-01-02T00:00:00"
    rend = f"{cfg['fend']}T00:00:00"
    toml = TOML_TEMPLATE.read_text().replace("/v4_models/bdi", f"/v4_models/{name}")
    toml = re.sub(r"starttime = .*", f"starttime = {rstart}", toml)
    toml = re.sub(r"endtime = .*", f"endtime = {rend}", toml)
    toml = re.sub(r'output_[a-z_]+\.csv', f"output_{name}.csv", toml)
    (out / "wflow_v4.toml").write_text(toml)
    (out / "output").mkdir(exist_ok=True)
    for f in ("log.txt", "output_grid_wrsi.nc"):
        (out / "output" / f).unlink(missing_ok=True)
    print(f"[5/{name}] wflow run {rstart[:10]}..{rend[:10]}", flush=True)
    r = subprocess.run([str(JULIA), f"--project={JL_PROJ}", "-e",
        f'using Wflow; Wflow.run("{out}/wflow_v4.toml")'], cwd=out,
        env={**os.environ, "JULIA_NUM_THREADS": "4"})
    ok = (out / "output" / "output_grid_wrsi.nc").exists() and r.returncode == 0
    print(f"[5/{name}] {'OK' if ok else 'FAILED rc=%d' % r.returncode}", flush=True)


def build(name):
    cfg = CONFIGS[name]
    print(f"\n########## {name} ##########", flush=True)
    bb = phase1_geojson(name, cfg)
    phase2_static(name, cfg, bb)
    phase3_repair(name)
    phase4_forcing(name, cfg)
    phase5_run(name, cfg)


if __name__ == "__main__":
    names = sys.argv[1:] or list(CONFIGS)
    for nm in names:
        try:
            build(nm)
        except Exception as ex:
            print(f"########## {nm} FAILED: {type(ex).__name__}: "
                  f"{str(ex)[:200]} ##########", flush=True)
    print("\nALL CORRECTION BUILDS DONE", flush=True)
