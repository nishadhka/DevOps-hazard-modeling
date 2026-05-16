"""Batch WRSI for the built cases, clipped to their v3 basin polygon.

Single script, no CLI. For each case in SELECTED:
  1. derive a WRSI-minimal TOML from the case's own proven config
     (reuse its [input.static] mappings verbatim; swap only [output.*]
     for a 2-variable gridded NetCDF: aet + pet),
  2. run Wflow on the pinned toolchain (Julia 1.10 / Wflow v1.0.2),
  3. compute WRSI = 100*ΣAET/ΣPET per pixel (period + per year),
  4. clip/mask the WRSI grid to the event's v3 basin polygon,
  5. plot bbox WRSI vs v3-clipped WRSI + write a clipped NetCDF.

These are the original country-bbox builds; the v3 polygon is applied
as a post-hoc spatial mask so WRSI is reported for the v3-recommended
basin without rebuilding the model. See runs/rwa_wrsi/NEW_DIRECTION.md
for the toolchain-version rationale (pin Julia 1.10, Wflow v1.0.2).

Edit SELECTED to control which cases run. Heavy cases (ETH/KEN/TZA)
produce multi-GB NetCDFs and multi-hour runs — sequence deliberately.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rioxarray  # noqa: F401  (registers .rio accessor)
import xarray as xr
from matplotlib.colors import BoundaryNorm, ListedColormap

REPO = Path(__file__).resolve().parents[2]
JULIA = Path.home() / ".juliaup" / "bin" / "julia"
JULIA_PROJECT = REPO / "julia_env"
V3_DIR = REPO / "shared" / "hydrobasins" / "outputs_v3"
RUNS = REPO / "runs"
CASE_ROOT = Path("/mnt/wflow-data/bdi_trail2")

FAO_BOUNDS = [0, 50, 80, 150]
FAO_COLORS = ["#d7191c", "#fdae61", "#1a9641"]
FAO_LABELS = ["<50 failure", "50-79 stress", ">=80 no-stress"]

# case dir, original toml, iso, v3 geojson stem
CASES = {
    "BDI": dict(case="dr_case1",  toml="case_sbm.toml",     v3="01_burundi_bdi_v3"),
    "DJI": dict(case="dr_case2",  toml="djibouti_sbm.toml", v3="02_djibouti_dji_v3"),
    "ERI": dict(case="dr_case3",  toml="case_sbm.toml",     v3="03_eritrea_eri_v3"),
    "ETH": dict(case="dr_case4",  toml="ethiopia_sbm.toml", v3="04_ethiopia_eth_v3"),
    "KEN": dict(case="dr_case5",  toml="kenya_sbm.toml",    v3="05_kenya_ken_v3"),
    "UGA": dict(case="dr_case11", toml="case_sbm.toml",     v3="11_uganda_uga_v3"),
    "TZA": dict(case="dr_case10", toml="case_sbm.toml",     v3="10_tanzania_tza_v3"),
}

# Edit this to choose scope. Default = small/medium + ERI unblock test.
SELECTED = ["BDI", "DJI", "UGA", "ERI"]


def make_wrsi_toml(iso: str, cfg: dict) -> tuple[Path, Path]:
    """Derive a WRSI-minimal TOML from the case's own config."""
    src = CASE_ROOT / cfg["case"] / cfg["toml"]
    if not src.exists():  # some cases keep the toml under data/output
        src = CASE_ROOT / cfg["case"] / "data" / "output" / cfg["toml"]
    text = src.read_text()

    run_dir = RUNS / f"{iso.lower()}_wrsi"
    out_dir = run_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    in_abs = CASE_ROOT / cfg["case"] / "data" / "input"
    # strip dir_input/dir_output + every [output.*] block to EOF-or-next-[
    text = re.sub(r'(?m)^dir_input\s*=.*$', f'dir_input = "{in_abs}"', text)
    text = re.sub(r'(?m)^dir_output\s*=.*$', f'dir_output = "{out_dir}"', text)
    text = re.split(r'(?m)^\[output\.', text)[0].rstrip() + "\n"
    text += (
        '\n[output.netcdf_grid]\n'
        'path = "output_grid_wrsi.nc"\n'
        'compressionlevel = 1\n\n'
        '[output.netcdf_grid.variables]\n'
        'land_surface__evapotranspiration_volume_flux = "aet"\n'
        'land_surface_water__potential_evaporation_volume_flux = "pet"\n\n'
        '[output.csv]\n'
        f'path = "output_{iso.lower()}_wrsi.csv"\n\n'
        '[[output.csv.column]]\n'
        'header = "aet"\n'
        'parameter = "land_surface__evapotranspiration_volume_flux"\n'
        'reducer = "mean"\n\n'
        '[[output.csv.column]]\n'
        'header = "pet"\n'
        'parameter = "land_surface_water__potential_evaporation_volume_flux"\n'
        'reducer = "mean"\n'
    )
    toml_path = run_dir / "case_wrsi.toml"
    toml_path.write_text(text)
    return toml_path, out_dir


def run_wflow(toml_path: Path) -> None:
    env = {**os.environ, "JULIA_NUM_THREADS": "4"}
    subprocess.run(
        [str(JULIA), "+1.10", f"--project={JULIA_PROJECT}",
         "-e", f'using Wflow; Wflow.run("{toml_path.name}")'],
        cwd=toml_path.parent, check=True, env=env,
    )


def wrsi_from(ds: xr.Dataset, sel=None) -> xr.DataArray:
    a, p = ds["aet"], ds["pet"]
    if sel is not None:
        a, p = a.sel(time=sel), p.sel(time=sel)
    sp = p.sum("time", skipna=True)
    return (100.0 * a.sum("time", skipna=True) / sp.where(sp > 1e-6)).clip(0, 150)


def analyse(iso: str, cfg: dict, out_dir: Path) -> None:
    nc = out_dir / "output_grid_wrsi.nc"
    ds = xr.open_dataset(nc)
    ds = ds.rio.write_crs("EPSG:4326")
    xdim = "lon" if "lon" in ds.dims else "x"
    ydim = "lat" if "lat" in ds.dims else "y"
    ds = ds.rio.set_spatial_dims(x_dim=xdim, y_dim=ydim)

    gdf = gpd.read_file(V3_DIR / f"{cfg['v3']}.geojson").to_crs("EPSG:4326")

    wrsi_bbox = wrsi_from(ds)
    try:
        clipped_ds = ds.rio.clip(gdf.geometry, gdf.crs, drop=True, all_touched=True)
        wrsi_v3 = wrsi_from(clipped_ds)
        ok = True
    except Exception as e:  # polygon may not overlap the bbox build
        print(f"  [{iso}] clip failed ({e}); bbox-only")
        wrsi_v3, ok = wrsi_bbox, False

    res_dir = RUNS / f"{iso.lower()}_wrsi" / "wrsi"
    res_dir.mkdir(exist_ok=True)
    xr.Dataset({"wrsi_bbox": wrsi_bbox,
                "wrsi_v3": wrsi_v3}).to_netcdf(res_dir / f"{iso.lower()}_wrsi_grid.nc")

    cmap = ListedColormap(FAO_COLORS)
    norm = BoundaryNorm(FAO_BOUNDS, cmap.N)
    fig, ax = plt.subplots(1, 2, figsize=(13, 6))
    for a, g, ttl in ((ax[0], wrsi_bbox, "bbox build"),
                      (ax[1], wrsi_v3, f"v3 basin ({cfg['v3']})")):
        im = a.pcolormesh(g[xdim], g[ydim], g.values, cmap=cmap, norm=norm)
        gdf.boundary.plot(ax=a, color="black", linewidth=0.8)
        a.set_aspect("equal")
        a.set_title(f"{iso} WRSI — {ttl}\nbasin mean = {float(g.mean()):.0f}")
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal",
                        fraction=0.046, pad=0.08, ticks=[25, 65, 115])
    cbar.ax.set_xticklabels(FAO_LABELS)
    fig.suptitle(f"{iso} — WRSI = 100·ΣAET/ΣPET (Kc=1), v3 basin clip",
                 y=1.02)
    fig.savefig(res_dir / f"{iso.lower()}_wrsi_v3.png",
                dpi=150, bbox_inches="tight")
    plt.close(fig)

    v = wrsi_v3.values[np.isfinite(wrsi_v3.values)]
    if v.size:
        print(f"  [{iso}] v3-clip mean={v.mean():.1f}  "
              f"<50={100*(v<50).mean():.0f}%  "
              f"50-79={100*((v>=50)&(v<80)).mean():.0f}%  "
              f">=80={100*(v>=80).mean():.0f}%  (clip_ok={ok})")


if __name__ == "__main__":
    print(f"Selected: {SELECTED}")
    for iso in SELECTED:
        cfg = CASES[iso]
        print(f"\n=== {iso} ({cfg['case']}) ===")
        toml_path, out_dir = make_wrsi_toml(iso, cfg)
        if (out_dir / "output_grid_wrsi.nc").exists():
            print(f"  [{iso}] gridded NetCDF exists — skipping wflow run")
        else:
            print(f"  [{iso}] running wflow ({toml_path}) ...")
            try:
                run_wflow(toml_path)
            except subprocess.CalledProcessError as e:
                print(f"  [{iso}] WFLOW FAILED: {e}; skipping")
                continue
        analyse(iso, cfg, out_dir)
    print("\nDone.")
