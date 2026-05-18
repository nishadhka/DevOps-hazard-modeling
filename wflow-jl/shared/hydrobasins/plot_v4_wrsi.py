"""Build v4 staticmaps + WRSI plots for the 11 case studies, for HF upload.

Source models live at /mnt/wflow-secondary/v4_models/<iso>/ ; basin polygons at
shared/hydrobasins/outputs_v4/*_<iso>_v4_basin.geojson (EPSG:4326).

For each ISO case study:
  0. staticmaps.nc  -> 5 key model-setup variables as PNGs  ({iso}_static_<v>.png)
  1. output/output_grid_wrsi.nc -> per-variable time-mean field PNGs
     ({iso}_<v>.png for v in ds.data_vars, i.e. aet, pet)
  2. derived WRSI = 100 * ΣAET / ΣPET (Kc=1, water-balance form — same
     `wrsi_grid` logic as wrsi_analysis.py), clipped to the case's
     _v4_basin.geojson, drawn with the FAO interpretation classes
     ({iso}_wrsi.png).

All PNGs land in runs/v4_wrsi_plots/ , ready for:
    uv run python -m shared.hydrobasins.upload_to_hf \
        --folder runs/v4_wrsi_plots --dest v4_wrsi_plots

Steps 1-2 only run where a Wflow run produced output_grid_wrsi.nc (6 of 11);
step 0 runs for all 11. No CLI — just `uv run python -m shared.hydrobasins.plot_v4_wrsi`.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rioxarray  # noqa: E402,F401  (registers .rio accessor)
import xarray as xr  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402

V4 = Path("/mnt/wflow-secondary/v4_models")
HERE = Path(__file__).resolve().parent
GEOJSON_DIR = HERE / "outputs_v4"
OUT = HERE.parents[1] / "runs" / "v4_wrsi_plots"
OUT.mkdir(parents=True, exist_ok=True)

# Priority order of "super important" staticmap variables; first 5 present win.
STATIC_PRIORITY = [
    "wflow_dem",        # elevation — drives routing
    "wflow_subcatch",   # delineated catchments
    "wflow_river",      # river network mask
    "wflow_landuse",    # land use / land cover
    "SoilThickness",    # soil column depth
    "RootingDepth",     # vegetation root depth (WRSI-relevant)
    "KsatVer",          # vertical saturated conductivity
]

# FAO WRSI interpretation classes (identical to wrsi_analysis.py).
FAO_BOUNDS = [0, 50, 80, 150]
FAO_COLORS = ["#d7191c", "#fdae61", "#1a9641"]  # failure / stress / no-stress
FAO_LABELS = ["<50 crop-failure", "50-79 water stress", ">=80 no/min stress"]


def wrsi_grid(aet: xr.DataArray, pet: xr.DataArray) -> xr.DataArray:
    """100 * ΣAET/ΣPET over time, masked where ΣPET~0 (wrsi_analysis.py logic)."""
    sa = aet.sum("time", skipna=True)
    sp = pet.sum("time", skipna=True)
    w = 100.0 * sa / sp.where(sp > 1e-6)
    return w.clip(0, 150)


def _isos() -> list[str]:
    return sorted(
        p.name for p in V4.iterdir()
        if p.is_dir() and (p / "staticmaps.nc").is_file()
    )


def _geojson_for(iso: str) -> Path | None:
    hits = sorted(GEOJSON_DIR.glob(f"*_{iso}_v4_basin.geojson"))
    return hits[0] if hits else None


def _save_field(da: xr.DataArray, title: str, path: Path, **kw) -> None:
    fig, ax = plt.subplots(figsize=(7, 6))
    da.plot(ax=ax, **kw)
    ax.set_title(title)
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def step0_staticmaps(iso: str) -> list[str]:
    ds = xr.open_dataset(V4 / iso / "staticmaps.nc")
    chosen = [v for v in STATIC_PRIORITY if v in ds.data_vars][:5]
    for v in chosen:
        da = ds[v]
        if "layer" in da.dims:           # collapse soil-layer vars to top layer
            da = da.isel(layer=0)
        _save_field(da, f"{iso} staticmaps — {v}",
                    OUT / f"{iso}_static_{v}.png", robust=True)
    ds.close()
    return chosen


def _open_output(nc: Path) -> xr.Dataset | None:
    """Open output_grid_wrsi.nc, tolerating partial/corrupt files written by a
    concurrent Wflow batch. Returns None if unreadable or has no timesteps."""
    try:
        ds = xr.open_dataset(nc)
    except (OSError, RuntimeError, ValueError):
        return None
    if int(ds.sizes.get("time", 0)) == 0:
        ds.close()
        return None
    return ds


def step1_timemean(iso: str, ds: xr.Dataset) -> list[str]:
    done = []
    for v in ds.data_vars:
        _save_field(ds[v].mean("time"),
                    f"{iso} — time-mean {v} (mm)",
                    OUT / f"{iso}_{v}.png", robust=True, cmap="viridis")
        done.append(str(v))
    return done


def step2_wrsi(iso: str, ds: xr.Dataset, geo: Path) -> dict:
    w = wrsi_grid(ds["aet"], ds["pet"])
    gdf = gpd.read_file(geo).to_crs("EPSG:4326")
    w = (w.rio.set_spatial_dims(x_dim="lon", y_dim="lat")
          .rio.write_crs("EPSG:4326"))
    wc = w.rio.clip(gdf.geometry.values, gdf.crs, drop=True, all_touched=True)

    cmap = ListedColormap(FAO_COLORS)
    norm = BoundaryNorm(FAO_BOUNDS, cmap.N)
    fig, ax = plt.subplots(figsize=(7.5, 7))
    im = ax.pcolormesh(wc["lon"], wc["lat"], wc.values, cmap=cmap, norm=norm)
    gdf.boundary.plot(ax=ax, color="black", linewidth=0.6)
    ax.set_aspect("equal")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    v = wc.values[np.isfinite(wc.values)]
    ax.set_title(f"{iso} WRSI = 100·ΣAET/ΣPET (Kc=1) — basin mean "
                 f"= {v.mean():.0f}")
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal",
                        fraction=0.046, pad=0.09, ticks=[25, 65, 115])
    cbar.ax.set_xticklabels(FAO_LABELS)
    fig.tight_layout()
    fig.savefig(OUT / f"{iso}_wrsi.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {
        "mean": float(v.mean()),
        "fail_pct": float(100 * (v < 50).mean()),
        "stress_pct": float(100 * ((v >= 50) & (v < 80)).mean()),
        "ok_pct": float(100 * (v >= 80).mean()),
    }


def main() -> None:
    isos = _isos()
    print(f"v4 case studies ({len(isos)}): {', '.join(isos)}")
    print(f"output dir: {OUT}\n")
    for iso in isos:
        chosen = step0_staticmaps(iso)
        nc = V4 / iso / "output" / "output_grid_wrsi.nc"
        if not nc.is_file():
            print(f"  {iso}: static {chosen}  | no output_grid_wrsi.nc — "
                  f"skip WRSI")
            continue
        ds = _open_output(nc)
        if ds is None:
            print(f"  {iso}: static {chosen}  | output_grid_wrsi.nc "
                  f"unreadable/empty (partial or degenerate run) — skip WRSI")
            continue
        try:
            vars_ = step1_timemean(iso, ds)
            geo = _geojson_for(iso)
            if geo is None:
                print(f"  {iso}: static {chosen}  time-mean {vars_}  | "
                      f"no basin geojson — skip clipped WRSI")
                continue
            s = step2_wrsi(iso, ds, geo)
        except (OSError, RuntimeError, ValueError) as e:
            print(f"  {iso}: static {chosen}  | WRSI read failed "
                  f"({type(e).__name__}: partial/corrupt nc) — skip WRSI")
            continue
        finally:
            ds.close()
        print(f"  {iso}: static {chosen}  time-mean {vars_}  | "
              f"WRSI mean={s['mean']:.0f}  <50={s['fail_pct']:.0f}%  "
              f"50-79={s['stress_pct']:.0f}%  >=80={s['ok_pct']:.0f}%  "
              f"[{geo.name}]")

    pngs = sorted(p.name for p in OUT.glob("*.png"))
    print(f"\n{len(pngs)} PNGs written to {OUT}")


if __name__ == "__main__":
    main()
