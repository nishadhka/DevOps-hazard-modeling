"""v4 WRSI: subset existing inputs to the v4 basin bbox, run, clip.

Single script, no CLI. Per event in SELECTED:
  1. read the v4 basin polygon -> its bounding box (+ small pad),
  2. subset the case's existing staticmaps.nc + forcing.nc to that bbox
     (massively smaller domain than the original country build),
  3. derive a WRSI-minimal TOML (reuse the case's [input.static] verbatim,
     2-var aet+pet gridded output),
  4. run Wflow on the pinned toolchain (Julia 1.10 / Wflow v1.0.2),
  5. WRSI = 100*ΣAET/ΣPET, clipped to the v4 polygon, plot + NetCDF.

Big subset inputs + gridded NetCDFs go to /mnt/wflow-secondary (280 GB);
small WRSI result grids/plots to repo runs/ (-> git/HF).

CAVEAT: clipping a hydrological domain to a bbox breaks lateral routing
at the cut edges, so discharge near edges is unreliable. WRSI uses the
vertical water balance (aet, pet) which is column-local, so it is robust
to the clip — this is why bbox-subsetting is valid here.

Only the 8 cases with built inputs are runnable. SOM/SSD/SDN are
"planned" (no staticmaps/forcing) and are skipped — they need a full
HydroMT build first. ERI carries the documented dr_case3 BoundsError
(a staticmaps data bug, not version-related); it is attempted but may
fail and the batch continues.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rioxarray  # noqa: F401
import xarray as xr
from matplotlib.colors import BoundaryNorm, ListedColormap

REPO = Path(__file__).resolve().parents[2]
JULIA = Path.home() / ".juliaup" / "bin" / "julia"
JPROJ = REPO / "julia_env"
V4 = REPO / "shared" / "hydrobasins" / "outputs_v4"
RUNS = REPO / "runs"
HEAVY = Path("/mnt/wflow-secondary/wrsi_v4")
CASE_ROOT = Path("/mnt/wflow-data/bdi_trail2")
BBOX_PAD_DEG = 0.05

FAO_BOUNDS = [0, 50, 80, 150]
FAO_COLORS = ["#d7191c", "#fdae61", "#1a9641"]
FAO_LABELS = ["<50 failure", "50-79 stress", ">=80 no-stress"]

# iso -> built case dir, its toml, v4 geojson stem. Only cases with inputs.
CASES = {
    "BDI": dict(case="dr_case1",  toml="case_sbm.toml",     v4="01_burundi_bdi_v4"),
    "DJI": dict(case="dr_case2",  toml="djibouti_sbm.toml", v4="02_djibouti_dji_v4"),
    "ERI": dict(case="dr_case3",  toml="case_sbm.toml",     v4="03_eritrea_eri_v4"),
    "RWA": dict(case="dr_case6",  toml="case_sbm.toml",     v4="06_rwanda_rwa_v4"),
    "TZA": dict(case="dr_case10", toml="case_sbm.toml",     v4="10_tanzania_tza_v4"),
    "UGA": dict(case="dr_case11", toml="case_sbm.toml",     v4="11_uganda_uga_v4"),
    "KEN": dict(case="dr_case5",  toml="kenya_sbm.toml",    v4="05_kenya_ken_v4"),
    "ETH": dict(case="dr_case4",  toml="ethiopia_sbm.toml", v4="04_ethiopia_eth_v4"),
}
# small -> large so tractable results land first; ETH last.
SELECTED = ["BDI", "DJI", "ERI", "RWA", "UGA", "TZA", "KEN", "ETH"]
UNRUNNABLE = ["SOM", "SSD", "SDN"]  # planned, no built inputs


def _slice_dim(ds, name, lo, hi):
    """sel a coord range handling ascending or descending order."""
    v = ds[name].values
    if v[0] > v[-1]:
        return ds.sel({name: slice(hi, lo)})
    return ds.sel({name: slice(lo, hi)})


def subset_inputs(iso, cfg, bounds) -> Path:
    """Clip staticmaps.nc + forcing.nc to the v4 bbox; return new input dir."""
    mnx, mny, mxx, mxy = bounds
    mnx -= BBOX_PAD_DEG; mny -= BBOX_PAD_DEG
    mxx += BBOX_PAD_DEG; mxy += BBOX_PAD_DEG
    src = CASE_ROOT / cfg["case"] / "data" / "input"
    dst = HEAVY / f"{iso.lower()}_v4" / "input"
    dst.mkdir(parents=True, exist_ok=True)
    for fn in ("staticmaps.nc", "forcing.nc"):
        out = dst / fn
        if out.exists():
            continue
        ds = xr.open_dataset(src / fn)
        xn = "lon" if "lon" in ds.dims else ("x" if "x" in ds.dims else "longitude")
        yn = "lat" if "lat" in ds.dims else ("y" if "y" in ds.dims else "latitude")
        ds = _slice_dim(_slice_dim(ds, xn, mnx, mxx), yn, mny, mxy)
        ds.to_netcdf(out)
        ds.close()
    return dst


def make_toml(iso, cfg, in_dir: Path) -> tuple[Path, Path]:
    src = CASE_ROOT / cfg["case"] / cfg["toml"]
    if not src.exists():
        src = CASE_ROOT / cfg["case"] / "data" / "output" / cfg["toml"]
    text = src.read_text()
    out_dir = HEAVY / f"{iso.lower()}_v4" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    run_dir = RUNS / f"{iso.lower()}_v4_wrsi"
    run_dir.mkdir(parents=True, exist_ok=True)
    text = re.sub(r'(?m)^dir_input\s*=.*$',  f'dir_input = "{in_dir}"', text)
    text = re.sub(r'(?m)^dir_output\s*=.*$', f'dir_output = "{out_dir}"', text)
    text = re.split(r'(?m)^\[output\.', text)[0].rstrip() + "\n"
    text += (
        '\n[output.netcdf_grid]\n'
        'path = "output_grid_wrsi.nc"\ncompressionlevel = 1\n\n'
        '[output.netcdf_grid.variables]\n'
        'land_surface__evapotranspiration_volume_flux = "aet"\n'
        'land_surface_water__potential_evaporation_volume_flux = "pet"\n\n'
        '[output.csv]\n'
        f'path = "output_{iso.lower()}_wrsi.csv"\n\n'
        '[[output.csv.column]]\nheader = "aet"\n'
        'parameter = "land_surface__evapotranspiration_volume_flux"\n'
        'reducer = "mean"\n\n'
        '[[output.csv.column]]\nheader = "pet"\n'
        'parameter = "land_surface_water__potential_evaporation_volume_flux"\n'
        'reducer = "mean"\n'
    )
    tp = run_dir / "case_v4_wrsi.toml"
    tp.write_text(text)
    return tp, out_dir


def run_wflow(tp: Path) -> None:
    subprocess.run(
        [str(JULIA), "+1.10", f"--project={JPROJ}",
         "-e", f'using Wflow; Wflow.run("{tp.name}")'],
        cwd=tp.parent, check=True,
        env={**os.environ, "JULIA_NUM_THREADS": "4"},
    )


def wrsi(ds, sel=None):
    a, p = ds["aet"], ds["pet"]
    if sel is not None:
        a, p = a.sel(time=sel), p.sel(time=sel)
    sp = p.sum("time", skipna=True)
    return (100.0 * a.sum("time", skipna=True) / sp.where(sp > 1e-6)).clip(0, 150)


def analyse(iso, cfg, out_dir: Path) -> None:
    ds = xr.open_dataset(out_dir / "output_grid_wrsi.nc")
    xn = "lon" if "lon" in ds.dims else "x"
    yn = "lat" if "lat" in ds.dims else "y"
    ds = ds.rio.write_crs("EPSG:4326").rio.set_spatial_dims(x_dim=xn, y_dim=yn)
    # clip to the actual basin polygon (companion file), not the bbox
    basin_fp = V4 / f"{cfg['v4']}_basin.geojson"
    if not basin_fp.exists():
        basin_fp = V4 / f"{cfg['v4']}.geojson"
    gdf = gpd.read_file(basin_fp).to_crs("EPSG:4326")
    w_bbox = wrsi(ds)
    try:
        w_v4 = wrsi(ds.rio.clip(gdf.geometry, gdf.crs, drop=True, all_touched=True))
    except Exception as e:
        print(f"  [{iso}] clip failed ({e}); bbox only"); w_v4 = w_bbox

    res = RUNS / f"{iso.lower()}_v4_wrsi" / "wrsi"
    res.mkdir(exist_ok=True)
    xr.Dataset({"wrsi_bbox": w_bbox, "wrsi_v4": w_v4}).to_netcdf(
        res / f"{iso.lower()}_wrsi_grid.nc")

    cmap = ListedColormap(FAO_COLORS); norm = BoundaryNorm(FAO_BOUNDS, cmap.N)
    fig, ax = plt.subplots(1, 2, figsize=(13, 6))
    for a_, g, t in ((ax[0], w_bbox, "v4 basin bbox"),
                     (ax[1], w_v4, "v4 basin (clipped)")):
        im = a_.pcolormesh(g[xn], g[yn], g.values, cmap=cmap, norm=norm)
        gdf.boundary.plot(ax=a_, color="black", linewidth=0.8)
        a_.set_aspect("equal")
        a_.set_title(f"{iso} WRSI — {t}\nmean = {float(g.mean()):.0f}")
    cb = fig.colorbar(im, ax=ax, orientation="horizontal", fraction=0.046,
                      pad=0.08, ticks=[25, 65, 115])
    cb.ax.set_xticklabels(FAO_LABELS)
    fig.suptitle(f"{iso} v4 — WRSI = 100·ΣAET/ΣPET (Kc=1)", y=1.02)
    fig.savefig(res / f"{iso.lower()}_wrsi_v4.png", dpi=150,
                bbox_inches="tight")
    plt.close(fig)
    v = w_v4.values[np.isfinite(w_v4.values)]
    if v.size:
        print(f"  [{iso}] WRSI v4-clip mean={v.mean():.1f}  "
              f"<50={100*(v<50).mean():.0f}%  "
              f"50-79={100*((v>=50)&(v<80)).mean():.0f}%  "
              f">=80={100*(v>=80).mean():.0f}%")


if __name__ == "__main__":
    print(f"Runnable: {SELECTED}")
    print(f"Skipped (no built inputs — need HydroMT): {UNRUNNABLE}")
    for iso in SELECTED:
        cfg = CASES[iso]
        print(f"\n=== {iso} ({cfg['case']}) ===")
        g = gpd.read_file(V4 / f"{cfg['v4']}.geojson")
        in_dir = subset_inputs(iso, cfg, g.total_bounds)
        tp, out_dir = make_toml(iso, cfg, in_dir)
        if (out_dir / "output_grid_wrsi.nc").exists():
            print(f"  [{iso}] gridded NetCDF exists — skip run")
        else:
            try:
                run_wflow(tp)
            except subprocess.CalledProcessError as e:
                print(f"  [{iso}] WFLOW FAILED: {e}; skipping")
                continue
        analyse(iso, cfg, out_dir)
    print("\nDone.")
