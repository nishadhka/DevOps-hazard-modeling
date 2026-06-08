"""Evaluate each v4 WRSI output against its documented drought loss&damage event.

Reference events (icpac-igad/DevOps-hazard-modeling#drought-events):
  iso  event                         period      basin
  bdi  Burundi 2021-22               2021-2022
  dji  Djibouti 2022                 2022
  eri  Central Highlands 2021-23     2021-2023
  eth  Blue Nile Headwaters 2021-22  2021-2022
  ken  Tana / ASAL 2020-23           2020-2023
  rwa  Akagera 2016-17               2016-2017   <-- OUTSIDE sim window 2020-23
  som  South-Central 2020-23         2020-2023
  ssd  Upper Nile 2021-23            2021-2023
  sdn  Eastern States 2022           2022
  tza  Kagera 2021-22                2021-2022
  uga  Karamoja 2022                 2022

Sim window = 2020-01-02..2023-11-30 (daily). For each case we compute, clipped
to the basin polygon: full-period basin-mean WRSI (=100 ΣAET/ΣPET, FAO), and
PER-YEAR basin-mean WRSI + ΣAET (mm/yr) + ΣPET (mm/yr). A drought event should
show LOWER WRSI / lower ΣAET in its event year(s) vs non-event years — that is
the model "capturing" the event. Memory-safe (time-chunked).
"""
import json
from pathlib import Path
import numpy as np
import xarray as xr
import rioxarray  # noqa: F401
import geopandas as gpd

V4 = Path("/mnt/wflow-secondary/v4_models")
GEO = Path(__file__).resolve().parent / "outputs_v4"
EVENTS = {
    "bdi": ("Burundi 2021-22", [2021, 2022]),
    "dji": ("Djibouti 2022", [2022]),
    "eri": ("Central Highlands 2021-23", [2021, 2022, 2023]),
    "eth": ("Blue Nile Headwaters 2021-22", [2021, 2022]),
    "ken": ("Tana / ASAL 2020-23", [2020, 2021, 2022, 2023]),
    "rwa": ("Akagera 2016-17 (OUTSIDE window)", [2016, 2017]),
    "som": ("South-Central 2020-23", [2020, 2021, 2022, 2023]),
    "ssd": ("Upper Nile 2021-23", [2021, 2022, 2023]),
    "sdn": ("Eastern States 2022", [2022]),
    "tza": ("Kagera 2021-22", [2021, 2022]),
    "uga": ("Karamoja 2022", [2022]),
}


def geojson_for(iso):
    hits = sorted(GEO.glob(f"*_{iso}_v4_basin.geojson"))
    return hits[0] if hits else None


def basin_mean(da2d, gdf):
    """nanmean of a 2D (lat,lon) DataArray clipped to basin polygon."""
    d = da2d.rio.set_spatial_dims(x_dim="lon", y_dim="lat").rio.write_crs(4326)
    try:
        c = d.rio.clip(gdf.geometry.values, gdf.crs, drop=True, all_touched=True)
    except Exception:
        c = d
    v = c.values
    v = v[np.isfinite(v)]
    return float(v.mean()) if v.size else float("nan")


def analyse(iso):
    nc = V4 / iso / "output" / "output_grid_wrsi.nc"
    out = {"iso": iso, "event": EVENTS[iso][0], "event_years": EVENTS[iso][1]}
    if not nc.is_file():
        out["status"] = "MISSING output_grid_wrsi.nc"
        return out
    try:
        ds = xr.open_dataset(nc, chunks={"time": 64})
    except Exception as e:
        out["status"] = f"UNREADABLE ({type(e).__name__})"
        return out
    nt = int(ds.sizes.get("time", 0))
    if nt == 0 or "aet" not in ds or "pet" not in ds:
        out["status"] = f"EMPTY/no-vars (time={nt})"
        ds.close()
        return out
    t0, t1 = str(ds.time.values[0])[:10], str(ds.time.values[-1])[:10]
    out["status"] = "OK"
    out["time"] = f"{t0}..{t1} ({nt})"

    geo = geojson_for(iso)
    gdf = gpd.read_file(geo).to_crs(4326) if geo else None

    def wrsi_from(sa, sp):
        return (100.0 * sa / sp.where(sp > 1e-6)).clip(0, 150)

    # full period
    sa = ds["aet"].sum("time"); sp = ds["pet"].sum("time")
    out["wrsi_full"] = round(basin_mean(wrsi_from(sa, sp), gdf), 1) if gdf is not None else None

    # per-year (single grouped pass each var)
    ay = ds["aet"].groupby("time.year").sum("time").compute()
    py = ds["pet"].groupby("time.year").sum("time").compute()
    years = [int(y) for y in ay["year"].values]
    out["years"] = {}
    for y in years:
        a = ay.sel(year=y); p = py.sel(year=y)
        rec = {
            "wrsi": round(basin_mean(wrsi_from(a, p), gdf), 1) if gdf is not None else None,
            "aet_mm": round(basin_mean(a, gdf), 0) if gdf is not None else None,
            "pet_mm": round(basin_mean(p, gdf), 0) if gdf is not None else None,
            "ndays": int((ds["time.year"] == y).sum()),
        }
        out["years"][y] = rec
    ds.close()
    return out


def main():
    results = []
    for iso in EVENTS:
        print(f"--- {iso} ---", flush=True)
        r = analyse(iso)
        results.append(r)
        if r["status"] != "OK":
            print(f"  {r['status']}", flush=True)
            continue
        print(f"  event={r['event']}  years={r['event_years']}  {r['time']}",
              flush=True)
        print(f"  full-period basin WRSI = {r['wrsi_full']}", flush=True)
        for y, rec in r["years"].items():
            tag = " <EVENT>" if y in r["event_years"] else ""
            print(f"    {y}: WRSI={rec['wrsi']:5}  ΣAET={rec['aet_mm']:5} mm  "
                  f"ΣPET={rec['pet_mm']:5} mm  (n={rec['ndays']}d){tag}",
                  flush=True)
    Path(__file__).resolve().parent.joinpath("_eval_wrsi_events.json").write_text(
        json.dumps(results, indent=2))
    print("\nwrote _eval_wrsi_events.json", flush=True)


if __name__ == "__main__":
    main()
