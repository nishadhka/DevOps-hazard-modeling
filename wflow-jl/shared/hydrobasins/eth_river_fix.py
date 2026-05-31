"""Fix ETH Wflow river-network cycles WITHOUT regridding.

Root cause (verified against Wflow v1.0.2 src/routing/routing_process.jl:flowgraph
+ src/network.jl:NetworkRiver): the river network is built over `wflow_river`
cells only, and `flowgraph` resolves each cell's downstream node with
`searchsortedfirst(indices, to_index)` — which does NOT check membership. So a
river cell whose ldd points to an IN-GRID cell that is NOT itself a river cell
gets wired to an arbitrary nearby river node → spurious edges → cycles. The
prior fixes rebuilt `wflow_ldd` but left the stale `wflow_river`, so the mask no
longer matched the ldd's drainage lines.

(Off-grid ldd pointers are harmless: `searchsortedfirst` returns len+1, and
Julia `add_edge!` to an out-of-range vertex is silently dropped → effective
outlet. That is why the LAND network — full rectangle with boundary pits —
passes while the RIVER network fails.)

Fix: enforce the closure property Wflow needs — every river cell is either a pit
(ldd==5) or its in-grid downstream is ALSO a river cell. We take the existing
river cells and add their downstream closure (follow ldd to each outlet),
then median-fill river params on the newly added cells. No grid change → no
forcing/staticmaps regrid, no IHU upscale.

Usage:
  python eth_river_fix.py            # verify + report only
  python eth_river_fix.py --fix      # apply, back up, write in place
"""
import sys
from pathlib import Path
import numpy as np
import xarray as xr

FP = Path("/mnt/wflow-secondary/v4_models/eth/staticmaps.nc")
RIVER_VARS = ["RiverLength", "RiverWidth", "RiverDepth", "RiverSlope", "N_River"]
OFF = {1: (1, -1), 2: (1, 0), 3: (1, 1), 4: (0, -1), 6: (0, 1),
       7: (-1, -1), 8: (-1, 0), 9: (-1, 1)}  # 5 = pit (no successor)


def build_succ(ldd):
    """succ[i] = downstream linear index, or -1 for pit(5)/off-grid/invalid."""
    ny, nx = ldd.shape
    N = ny * nx
    succ = np.full(N, -1, dtype=np.int64)
    code = np.where(np.isfinite(ldd), ldd, 0).astype(np.int64).ravel()
    rows, cols = np.divmod(np.arange(N), nx)
    for c, (dr, dc) in OFF.items():
        m = code == c
        if not m.any():
            continue
        idx = np.nonzero(m)[0]
        nr, nc = rows[idx] + dr, cols[idx] + dc
        ok = (nr >= 0) & (nr < ny) & (nc >= 0) & (nc < nx)
        tgt = np.full(idx.shape, -1, dtype=np.int64)
        tgt[ok] = nr[ok] * nx + nc[ok]
        succ[idx] = tgt
    return succ


def downstream_closure(river0, succ):
    """Return boolean river mask = river0 plus every in-grid downstream cell
    reachable by following succ from any river0 cell, until a pit/off-grid
    (-1). Iterative with memoised colouring; O(N)."""
    N = succ.size
    river = river0.copy()
    # 0 = not yet decided this pass, we just walk each seed once
    seen = np.zeros(N, dtype=bool)
    seeds = np.flatnonzero(river0)
    for s in seeds:
        u = s
        path = []
        while u != -1 and not seen[u]:
            seen[u] = True
            path.append(u)
            river[u] = True
            u = succ[u]
        # if we stopped because u already seen, it (and its downstream) are
        # already river/closed from a previous walk — nothing more to do
    return river


def violations(river, succ):
    """Count river cells whose in-grid downstream is NOT a river cell (these are
    exactly the cells that make Wflow's flowgraph cyclic)."""
    ridx = np.flatnonzero(river)
    d = succ[ridx]
    ingrid = d != -1
    bad = np.zeros(ridx.shape, dtype=bool)
    bad[ingrid] = ~river[d[ingrid]]
    return int(bad.sum())


def main():
    ds = xr.load_dataset(FP)
    ldd = ds["wflow_ldd"].values.astype("float32")
    ny, nx = ldd.shape
    river0 = (ds["wflow_river"].values == 1)
    succ = build_succ(ldd)

    n0 = int(river0.sum())
    v0 = violations(river0.ravel(), succ)
    print(f"grid {ny}x{nx}  river cells={n0}  pits(ldd5)={int((ldd==5).sum())}",
          flush=True)
    print(f"river cells whose in-grid downstream is NOT river (Wflow cycle "
          f"source) = {v0}", flush=True)

    river1 = downstream_closure(river0.ravel(), succ)
    n1 = int(river1.sum())
    v1 = violations(river1, succ)
    print(f"after downstream-closure: river cells={n1} (+{n1-n0})  "
          f"violations now={v1}", flush=True)
    assert v1 == 0, "closure failed to make river mask self-consistent"

    if "--fix" not in sys.argv:
        print("(verify-only; pass --fix to write)", flush=True)
        return

    river1_2d = river1.reshape(ny, nx)
    added = river1_2d & ~river0
    rv_dtype = ds["wflow_river"].dtype
    ds["wflow_river"] = (("lat", "lon"),
                         river1_2d.astype(rv_dtype))

    # median-fill river params on the new river mask so added cells are valid
    for v in RIVER_VARS:
        if v not in ds:
            continue
        a = ds[v].values.astype("float64")
        on_riv = river1_2d
        med = np.nanmedian(np.where(np.isfinite(a) & (a != 0.0) & on_riv,
                                    a, np.nan))
        if not np.isfinite(med):
            med = {"RiverLength": 1000.0, "RiverWidth": 30.0, "RiverDepth": 1.0,
                   "RiverSlope": 1e-3, "N_River": 0.035}[v]
        need = on_riv & (~np.isfinite(a) | (a == 0.0))
        a[need] = med
        a[~np.isfinite(a)] = 0.0
        ds[v] = (ds[v].dims, a.astype("float32"))
        print(f"  {v}: filled {int(need.sum())} river cells @ {med:.4g}",
              flush=True)

    bak = FP.with_suffix(".nc.preriverfix")
    if not bak.exists():
        import shutil
        shutil.copy2(FP, bak)
        print(f"backup -> {bak}", flush=True)
    enc = {v: {"_FillValue": None} for v in ds.data_vars}
    ds.to_netcdf(FP, encoding=enc)
    print(f"wrote consistent wflow_river ({n1} cells, +{int(added.sum())}) "
          f"-> {FP}", flush=True)


if __name__ == "__main__":
    main()
