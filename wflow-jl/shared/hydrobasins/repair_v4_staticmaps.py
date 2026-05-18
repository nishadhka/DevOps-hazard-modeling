"""Repair v4 staticmaps so Wflow v1.0.2 can read the river network.

hazard-model-api/prepare_wflow_staticmaps.py marks `wflow_river` on more
cells than it fills with river parameters (RiverLength/Width/Depth/Slope/
N_River), so Wflow's river-parameter read hits missing values and aborts.
This fills NaN river params, on the river mask, with the per-variable
median (they are near-constant), and zero-fills any residual NaN in the
Wflow-read static vars. WRSI uses aet/pet (land column), so approximate
river routing is acceptable.

Single script, no CLI. In-place edit of each
/mnt/wflow-secondary/v4_models/<iso>/staticmaps.nc.
"""
from pathlib import Path
import numpy as np
import xarray as xr

MODELS = Path("/mnt/wflow-secondary/v4_models")
RIVER_VARS = ["RiverLength", "RiverWidth", "RiverDepth", "RiverSlope",
              "N_River"]
ISOS = ["bdi", "dji", "eri", "eth", "ken", "rwa", "sdn", "som", "ssd",
        "tza", "uga"]


def repair(iso: str) -> str:
    fp = MODELS / iso / "staticmaps.nc"
    if not fp.exists():
        return f"{iso}: no staticmaps"
    ds = xr.load_dataset(fp)  # load fully so we can rewrite in place
    riv = ds["wflow_river"].values == 1
    msg = []
    for v in RIVER_VARS:
        if v not in ds:
            continue
        a = ds[v].values.astype("float64")
        on = riv & np.isnan(a)
        if on.any():
            med = np.nanmedian(a[riv])
            if not np.isfinite(med):
                med = {"RiverLength": 1000.0, "RiverWidth": 30.0,
                       "RiverDepth": 1.0, "RiverSlope": 1e-3,
                       "N_River": 0.035}[v]
            a[on] = med
            msg.append(f"{v}+{int(on.sum())}@{med:.3g}")
        a[np.isnan(a)] = 0.0  # off-river residual
        ds[v] = (ds[v].dims, a.astype("float32"))
    # belt-and-suspenders: zero-fill NaN in every other Wflow-read static
    for v in ds.data_vars:
        if v in RIVER_VARS or v.startswith("wflow_"):
            continue
        arr = ds[v].values.astype("float64")
        bad = ~np.isfinite(arr) | (arr == 0.0)  # NaN or sentinel-0 fill
        if np.issubdtype(ds[v].values.dtype, np.floating) and bad.any():
            valid = arr[np.isfinite(arr) & (arr != 0.0)]
            med = float(np.median(valid)) if valid.size else 0.0
            arr[bad] = med            # physical median, NOT 0 (0 thetaS/
            ds[v] = (ds[v].dims, arr.astype("float32"))  # SoilThick → SBM nan
            msg.append(f"{v}~{int(bad.sum())}@{med:.3g}")
    enc = {v: {"_FillValue": None} for v in ds.data_vars}
    ds.to_netcdf(fp, encoding=enc)
    return f"{iso}: " + (", ".join(msg) if msg else "no NaN (ok)")


if __name__ == "__main__":
    import sys
    sel = sys.argv[1:] or ISOS
    for iso in sel:
        print(" ", repair(iso), flush=True)
    print("Done.")
