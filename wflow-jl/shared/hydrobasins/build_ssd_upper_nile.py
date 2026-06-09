"""Build the SSD·Upper-Nile correction case (`ssd_upper_nile`) end-to-end.

Why: the v4 SSD model used the **Bahr el Ghazal (NW)** basin, but the documented
event is **Upper Nile 2021-23 (NE South Sudan)**. This rebuilds, ALONGSIDE Bahr
el Ghazal (non-destructive), the **Sobat / Nasir** basin (eastern Upper Nile
state) over **2020-2023** so the 2021-23 drought is evaluated in the right
region against a 2020 baseline.

Selection: HydroBASINS lev-5 **unit** at seed (33.00, 9.30) → ~42,000 km²,
bbox ≈ lon 32.3-34.6 / lat 8.4-10.9 (Sobat river, E Upper Nile state).

Same 5-phase pipeline as build_tza_kagera.py (geojson → static[GEE] → repair →
forcing[EDH] → toml+run). Run: `uv run python -m
shared.hydrobasins.build_ssd_upper_nile`. Needs GEE key + EDH token.
"""
import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import xarray as xr
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[2]
HMA = REPO.parent / "hazard-model-api"
V4 = REPO / "shared" / "hydrobasins" / "outputs_v4"
OUT = Path("/mnt/wflow-secondary/v4_models/ssd_upper_nile")
VENV_PY = REPO / ".venv" / "bin" / "python"
SA_KEY = REPO / ".secrets" / "ee-service-account.json"
JULIA = Path.home() / ".juliaup/bin/julia"
JL_PROJ = REPO / "julia_env"

STEM = "08b_south_sudan_upper_nile_v4"
SEED, LVL = (33.00, 9.30), 5          # unit mode (single tile)
START, END = "2020-01-01", "2023-12-31"


def phase1_geojson():
    sys.path.insert(0, str(REPO))
    from shared.hydrobasins.download import ensure_level
    from shared.hydrobasins.select import _snap_outlet
    hb = gpd.read_file(ensure_level(LVL), engine="pyogrio")
    sid = _snap_outlet(hb, SEED[0], SEED[1])
    subset = hb[hb["HYBAS_ID"] == sid]
    area = float(subset["SUB_AREA"].sum())
    diss = subset.dissolve()
    w, s, e, n = diss.total_bounds
    print(f"[1] Upper Nile (Sobat): {len(subset)} poly, {area:,.0f} km², "
          f"bbox {w:.3f},{s:.3f},{e:.3f},{n:.3f}", flush=True)
    gpd.GeoDataFrame([{"event": "08b_South_Sudan_UpperNile", "iso": "SSD",
        "basin": "Upper Nile (Sobat/Nasir)", "west": w, "south": s, "east": e,
        "north": n, "geometry": box(w, s, e, n)}], crs="EPSG:4326").to_file(
        V4 / f"{STEM}.geojson", driver="GeoJSON")
    gpd.GeoDataFrame([{"event": "08b_South_Sudan_UpperNile", "iso": "SSD",
        "basin": "Upper Nile (Sobat/Nasir)", "level": LVL, "area_km2": area,
        "seed_lon": SEED[0], "seed_lat": SEED[1],
        "geometry": diss.geometry.iloc[0]}], crs="EPSG:4326").to_file(
        V4 / f"{STEM}_basin.geojson", driver="GeoJSON")
    return f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}"


def _hma(script, *args):
    print("    $", script, *args, flush=True)
    r = subprocess.run([str(VENV_PY), script, *args], cwd=HMA,
                       env={**os.environ, "GEE_SA_KEY": str(SA_KEY)},
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:]); raise SystemExit(f"{script} rc={r.returncode}")


def phase2_static(bb):
    OUT.mkdir(parents=True, exist_ok=True)
    print("[2] static build (GEE)", flush=True)
    _hma("download_dem.py", "--scale", "1000", "--target", "merit",
         "--bbox", bb, "--out", str(OUT))
    _hma("download_worldcover.py", "--scale", "1000", "--bbox", bb,
         "--out", str(OUT))
    _hma("download_merit_hydro.py", "--bbox", bb, "--out", str(OUT))
    _hma("download_soilgrids.py", "--scale", "1000", "--bbox", bb,
         "--out", str(OUT))
    _hma("prepare_wflow_staticmaps.py", "--bbox", bb, "--out", str(OUT),
         "--start", START, "--end", END)
    _hma("fix_ldd_pyflwdir.py", "--staticmaps", str(OUT / "staticmaps.nc"))


def phase3_repair():
    print("[3] repair + river-mask check", flush=True)
    from shared.hydrobasins.repair_v4_staticmaps import repair
    print("   ", repair("ssd_upper_nile"), flush=True)
    from shared.hydrobasins.eth_river_fix import build_succ, violations
    ds = xr.open_dataset(OUT / "staticmaps.nc")
    v = violations((ds["wflow_river"].values == 1).ravel(),
                   build_succ(ds["wflow_ldd"].values.astype("float32")))
    print(f"    river-mask cycle violations = {v}", flush=True)
    if v:
        # fresh build should be consistent; close river mask if not
        from shared.hydrobasins.eth_river_fix import downstream_closure
        print("    WARN: applying downstream-closure (eth_river_fix)",
              flush=True)
        sys.argv = ["", "--fix"]
        import importlib
        m = importlib.import_module("shared.hydrobasins.eth_river_fix")
        m.FP = OUT / "staticmaps.nc"
        m.main()


def phase4_forcing():
    print("[4] ERA5 forcing", START, "..", END, flush=True)
    from shared.hydrobasins.build_v4_forcing import open_era5, PAD
    w, s, e, n = gpd.read_file(V4 / f"{STEM}.geojson").total_bounds
    sm = xr.open_dataset(OUT / "staticmaps.nc")
    sub = open_era5()[["tp", "t2m", "pev"]].sel(
        time=slice(START, f"{END}T23:59"),
        latitude=slice(n + PAD, s - PAD), longitude=slice(w - PAD, e + PAD))
    daily = xr.Dataset()
    daily["precip"] = sub["tp"].resample(time="1D").sum() * 1000.0
    daily["temp"] = sub["t2m"].resample(time="1D").mean() - 273.15
    daily["pet"] = (-sub["pev"].resample(time="1D").sum() * 1000.0).clip(min=0)
    daily = daily.sortby("latitude").sortby("longitude").load().chunk(
        {"time": 30})
    fr = daily.interp(latitude=sm["lat"].values, longitude=sm["lon"].values,
                      method="linear").rename({"latitude": "lat",
                                               "longitude": "lon"})
    fr = fr.assign_coords(lat=sm["lat"].values, lon=sm["lon"].values)
    for v in ("precip", "temp", "pet"):
        fr[v] = fr[v].astype("float32")
    fr.attrs = {"source": "EarthDataHub ERA5 single-levels v0",
                "case": "ssd_upper_nile", "period": f"{START}/{END}"}
    fr.to_netcdf(OUT / "forcing.nc", encoding={v: {"zlib": True,
                 "complevel": 1} for v in ("precip", "temp", "pet")})
    print(f"    forcing.nc {fr['time'].size}d {fr.sizes['lat']}x"
          f"{fr.sizes['lon']} P[{float(fr.precip.mean()):.1f}] "
          f"T[{float(fr.temp.mean()):.1f}] PET[{float(fr.pet.mean()):.1f}]",
          flush=True)


def phase5_run():
    print("[5] toml + wflow run", flush=True)
    ssd = Path("/mnt/wflow-secondary/v4_models/ssd/wflow_v4.toml").read_text()
    toml = (ssd.replace("/v4_models/ssd", "/v4_models/ssd_upper_nile")
               .replace("starttime = 2021-01-01T00:00:00",
                        "starttime = 2020-01-02T00:00:00")
               .replace("output_ssd.csv", "output_ssd_upper_nile.csv"))
    (OUT / "wflow_v4.toml").write_text(toml)
    (OUT / "output").mkdir(exist_ok=True)
    r = subprocess.run([str(JULIA), "+1.10", f"--project={JL_PROJ}", "-e",
        f'using Wflow; Wflow.run("{OUT}/wflow_v4.toml")'], cwd=OUT,
        env={**os.environ, "JULIA_NUM_THREADS": "4"})
    o = OUT / "output" / "output_grid_wrsi.nc"
    print("    OK" if o.exists() and r.returncode == 0 else
          f"    FAILED rc={r.returncode}", flush=True)


if __name__ == "__main__":
    bb = phase1_geojson()
    phase2_static(bb)
    phase3_repair()
    phase4_forcing()
    phase5_run()
    print("Done. Eval/plot/upload separately (see WRSI_EVENT_EVAL.md).",
          flush=True)
