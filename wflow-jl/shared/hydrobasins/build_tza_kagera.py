"""Build the TZA·Kagera correction case (`tza_kagera`) end-to-end.

Why: the v4 TZA model used the **Pangani (NE)** basin, but the documented event
is **Kagera 2021-22 (NW Tanzania)** — wrong basin, and the run window (2022-23)
missed 2021. This rebuilds, ALONGSIDE Pangani (non-destructive), the **Kagera NW**
basin over **2020-2023** so the 2021-22 drought is captured against a 2020
baseline. Result: WRSI 75→56→53→61 — a clear event-year dip (see
WRSI_EVENT_EVAL.md). All artifacts under /mnt/wflow-secondary/v4_models/tza_kagera/.

Phases (each idempotent-ish; safe to re-run):
  1 geojson  : resolve Kagera NW (lev-6, seed 31.30,-1.60, ~6.7k km², basin mode)
               -> outputs_v4/10b_tanzania_kagera_v4{,_basin}.geojson
  2 static   : hazard-model-api dem/worldcover/merit/soilgrids + prepare + fix_ldd
  3 repair   : repair_v4_staticmaps median-fill (river mask already ldd-consistent
               on a fresh build — 0 cycle violations, so no eth_river_fix needed)
  4 forcing  : EDH ERA5 tp/t2m/pev 2020-23 -> daily -> interp to grid -> forcing.nc
  5 toml+run : wflow_v4.toml (2020-01-02..2023-12-31), Wflow v1.0.2 (julia +1.10)

Run: `uv run python -m shared.hydrobasins.build_tza_kagera`
Needs: GEE key (.secrets/ee-service-account.json), EDH token (~/.netrc + .env).
"""
import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import xarray as xr
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO.parent
HMA = ROOT / "hazard-model-api"
V4 = REPO / "shared" / "hydrobasins" / "outputs_v4"
OUT = Path("/mnt/wflow-secondary/v4_models/tza_kagera")
VENV_PY = REPO / ".venv" / "bin" / "python"
SA_KEY = REPO / ".secrets" / "ee-service-account.json"
JULIA = Path.home() / ".juliaup/bin/julia"
JL_PROJ = REPO / "julia_env"

STEM = "10b_tanzania_kagera_v4"
SEED, TARGET, LVL = (31.30, -1.60), 12000, 6   # v3 "Kagera NW (IBF)"
START, END = "2020-01-01", "2023-12-31"


def phase1_geojson():
    sys.path.insert(0, str(REPO))
    from shared.hydrobasins.download import ensure_level
    from shared.hydrobasins.select import (_build_reverse, _smart_snap,
                                            _bfs_upstream)
    hb = gpd.read_file(ensure_level(LVL), engine="pyogrio")
    areas = dict(zip(hb["HYBAS_ID"].astype(int),
                     hb.to_crs("ESRI:54009").geometry.area / 1e6))
    reverse = _build_reverse(hb)
    sid = _smart_snap(hb, areas, reverse, SEED[0], SEED[1], TARGET)
    subset = hb[hb["HYBAS_ID"].isin(_bfs_upstream(sid, reverse))]
    area = float(subset["SUB_AREA"].sum())
    diss = subset.dissolve()
    w, s, e, n = diss.total_bounds
    print(f"[1] Kagera NW: {len(subset)} poly, {area:,.0f} km², "
          f"bbox {w:.3f},{s:.3f},{e:.3f},{n:.3f}")
    gpd.GeoDataFrame([{"event": "10b_Tanzania_Kagera", "iso": "TZA",
        "basin": "Kagera NW (IBF)", "west": w, "south": s, "east": e,
        "north": n, "geometry": box(w, s, e, n)}], crs="EPSG:4326").to_file(
        V4 / f"{STEM}.geojson", driver="GeoJSON")
    gpd.GeoDataFrame([{"event": "10b_Tanzania_Kagera", "iso": "TZA",
        "basin": "Kagera NW (IBF)", "level": LVL, "area_km2": area,
        "seed_lon": SEED[0], "seed_lat": SEED[1],
        "geometry": diss.geometry.iloc[0]}], crs="EPSG:4326").to_file(
        V4 / f"{STEM}_basin.geojson", driver="GeoJSON")
    return f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}"


def _hma(script, *args):
    cmd = [str(VENV_PY), script, *args]
    print("    $", " ".join(cmd[1:]))
    r = subprocess.run(cmd, cwd=HMA,
                       env={**os.environ, "GEE_SA_KEY": str(SA_KEY)},
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-2000:])
        raise SystemExit(f"{script} failed rc={r.returncode}")


def phase2_static(bb):
    OUT.mkdir(parents=True, exist_ok=True)
    print("[2] static build (GEE)")
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
    print("[3] repair + river-mask check")
    from shared.hydrobasins.repair_v4_staticmaps import repair
    print("   ", repair("tza_kagera"))
    from shared.hydrobasins.eth_river_fix import build_succ, violations
    ds = xr.open_dataset(OUT / "staticmaps.nc")
    v = violations((ds["wflow_river"].values == 1).ravel(),
                   build_succ(ds["wflow_ldd"].values.astype("float32")))
    print(f"    river-mask cycle violations = {v} "
          f"({'ok' if v == 0 else 'NEEDS eth_river_fix-style closure'})")


def phase4_forcing():
    print("[4] ERA5 forcing", START, "..", END)
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
                "case": "tza_kagera", "period": f"{START}/{END}"}
    fr.to_netcdf(OUT / "forcing.nc", encoding={v: {"zlib": True,
                 "complevel": 1} for v in ("precip", "temp", "pet")})
    print(f"    forcing.nc {fr['time'].size}d {fr.sizes['lat']}x"
          f"{fr.sizes['lon']} P[{float(fr.precip.mean()):.1f}] "
          f"T[{float(fr.temp.mean()):.1f}] PET[{float(fr.pet.mean()):.1f}]")


def phase5_run():
    print("[5] toml + wflow run")
    tza = Path("/mnt/wflow-secondary/v4_models/tza/wflow_v4.toml").read_text()
    toml = (tza.replace("/v4_models/tza", "/v4_models/tza_kagera")
               .replace("starttime = 2022-01-01T00:00:00",
                        "starttime = 2020-01-02T00:00:00")
               .replace("output_tza.csv", "output_tza_kagera.csv"))
    (OUT / "wflow_v4.toml").write_text(toml)
    (OUT / "output").mkdir(exist_ok=True)
    r = subprocess.run([str(JULIA), "+1.10", f"--project={JL_PROJ}", "-e",
        f'using Wflow; Wflow.run("{OUT}/wflow_v4.toml")'], cwd=OUT,
        env={**os.environ, "JULIA_NUM_THREADS": "4"})
    o = OUT / "output" / "output_grid_wrsi.nc"
    print("    OK" if o.exists() and r.returncode == 0 else
          f"    FAILED rc={r.returncode}")


if __name__ == "__main__":
    bb = phase1_geojson()
    phase2_static(bb)
    phase3_repair()
    phase4_forcing()
    phase5_run()
    print("Done. Eval/plot/upload separately (see WRSI_EVENT_EVAL.md).")
