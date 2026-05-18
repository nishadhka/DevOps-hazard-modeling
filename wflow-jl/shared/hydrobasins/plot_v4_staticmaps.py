"""Plot selected staticmaps.nc input variables for the 11 v4 case studies.

All 11 cases (bdi dji eri eth ken rwa sdn som ssd tza uga) share an identical
23-variable schema (21 2-D lat/lon; 2 3-D layer/lat/lon: c, kv); only the grid
size differs per country. Source: /mnt/wflow-secondary/v4_models/<iso>/staticmaps.nc

Usage
-----
    uv run python -m shared.hydrobasins.plot_v4_staticmaps --list
    uv run python -m shared.hydrobasins.plot_v4_staticmaps            # DEFAULT_VARS
    uv run python -m shared.hydrobasins.plot_v4_staticmaps --all
    uv run python -m shared.hydrobasins.plot_v4_staticmaps --vars wflow_dem,KsatVer
    uv run python -m shared.hydrobasins.plot_v4_staticmaps --iso bdi,rwa

PNGs land in runs/v4_staticmaps_plots/{iso}_{var}.png (layer-0 slice for the
3-D vars c / kv), ready for upload_to_hf --dest v4_staticmaps_plots.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import xarray as xr  # noqa: E402

V4 = Path("/mnt/wflow-secondary/v4_models")
OUT = Path(__file__).resolve().parents[2] / "runs" / "v4_staticmaps_plots"

# Variables chosen for input QC (the interactive selection):
DEFAULT_VARS = [
    "wflow_dem", "wflow_ldd", "wflow_subcatch",
    "wflow_river", "RiverWidth", "RiverDepth", "RiverSlope",
    "KsatVer", "SoilThickness", "thetaS", "M",
    "wflow_landuse", "RootingDepth", "N", "f",
]

# Discrete / class-like fields read better with a qualitative colormap.
CATEGORICAL = {"wflow_ldd", "wflow_subcatch", "wflow_river", "wflow_landuse",
               "wflow_gauges", "wflow_pits"}


def _isos() -> list[str]:
    return sorted(
        p.name for p in V4.iterdir()
        if p.is_dir() and (p / "staticmaps.nc").is_file()
    )


def inventory() -> None:
    isos = _isos()
    print(f"v4 staticmaps.nc inventory ({len(isos)} cases)\n")
    print(f"{'case':5s} {'#vars':>6s}  grid (lat x lon)")
    base = None
    for iso in isos:
        with xr.open_dataset(V4 / iso / "staticmaps.nc") as ds:
            vs = list(ds.data_vars)
            g = next((tuple(ds[v].shape) for v in vs if ds[v].ndim == 2), None)
            if base is None:
                base = {v: ds[v].dims for v in vs}
            print(f"{iso:5s} {len(vs):6d}  {g}")
    print(f"\n{len(base)} variables (identical set across all cases):")
    for v in sorted(base):
        print(f"  {v:16s} dims={base[v]}")


def _save(da: xr.DataArray, title: str, path: Path, cmap: str) -> None:
    fig, ax = plt.subplots(figsize=(7, 6))
    da.plot(ax=ax, robust=True, cmap=cmap)
    ax.set_title(title)
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def plot(vars_: list[str], isos: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"plotting {len(vars_)} vars x {len(isos)} cases -> {OUT}\n")
    n = 0
    for iso in isos:
        with xr.open_dataset(V4 / iso / "staticmaps.nc") as ds:
            present, missing = [], []
            for v in vars_:
                if v not in ds.data_vars:
                    missing.append(v)
                    continue
                da = ds[v]
                if "layer" in da.dims:           # 3-D c/kv -> top layer
                    da = da.isel(layer=0)
                cmap = "tab20" if v in CATEGORICAL else "viridis"
                _save(da, f"{iso} staticmaps — {v}",
                      OUT / f"{iso}_{v}.png", cmap)
                present.append(v)
                n += 1
        msg = f"  {iso}: {len(present)} plotted"
        if missing:
            msg += f"  | missing: {missing}"
        print(msg)
    print(f"\n{n} PNGs written to {OUT}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true",
                   help="Print the variable inventory and exit")
    p.add_argument("--vars", default=None,
                   help=f"Comma-separated vars (default: {','.join(DEFAULT_VARS)})")
    p.add_argument("--all", action="store_true",
                   help="Plot every variable in the file (overrides --vars)")
    p.add_argument("--iso", default=None,
                   help="Comma-separated ISO subset (default: all 11)")
    args = p.parse_args()

    if args.list:
        inventory()
        return

    isos = _isos()
    if args.iso:
        want = {s.strip() for s in args.iso.split(",")}
        isos = [i for i in isos if i in want]

    if args.all:
        with xr.open_dataset(V4 / isos[0] / "staticmaps.nc") as ds:
            vars_ = list(ds.data_vars)
    elif args.vars:
        vars_ = [s.strip() for s in args.vars.split(",") if s.strip()]
    else:
        vars_ = DEFAULT_VARS

    plot(vars_, isos)


if __name__ == "__main__":
    main()
