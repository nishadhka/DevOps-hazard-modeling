"""Locate (and optionally break) cycles in the ETH wflow_ldd on its EXISTING
grid — no IHU upscale, no forcing/staticmaps regrid.

Wflow rejects ETH with "One or more cycles detected in flow graph". Every
prior fix re-derived an ldd and threw it at Wflow without ever verifying the
exact written array is acyclic. This builds the functional flow graph from the
on-disk PCRaster ldd, finds the cycles in O(N), and (with --fix) breaks each
cycle deterministically by turning its highest-DEM member into a pit, then
re-verifies until acyclic. WRSI uses the AET/PET land column, so a handful of
extra internal sinks is acceptable (routing is already approximate).

PCRaster ldd codes (numeric keypad), downstream offset (row,col); row+1 = south
because lat is descending:
  1 SW (+1,-1)  2 S (+1,0)  3 SE (+1,+1)
  4 W  ( 0,-1)  5 PIT       6 E  ( 0,+1)
  7 NW (-1,-1)  8 N (-1,0)  9 NE (-1,+1)

Usage:
  python eth_cycle_fix.py            # detect + report only
  python eth_cycle_fix.py --fix      # break cycles, back up, write in place
"""
import sys
from pathlib import Path
import numpy as np
import xarray as xr

FP = Path("/mnt/wflow-secondary/v4_models/eth/staticmaps.nc")
OFF = {1: (1, -1), 2: (1, 0), 3: (1, 1), 4: (0, -1), 5: (0, 0),
       6: (0, 1), 7: (-1, -1), 8: (-1, 0), 9: (-1, 1)}


def build_succ(ldd):
    """Return succ[i] = downstream linear index, or -1 for pit / off-grid /
    nodata-target / invalid. Active = finite ldd in 1..9."""
    ny, nx = ldd.shape
    N = ny * nx
    succ = np.full(N, -1, dtype=np.int64)
    code = np.where(np.isfinite(ldd), ldd, 0).astype(np.int64)
    rows, cols = np.divmod(np.arange(N), nx)
    for c, (dr, dc) in OFF.items():
        if c == 5:
            continue
        m = code.ravel() == c
        if not m.any():
            continue
        nr = rows[m] + dr
        nc = cols[m] + dc
        ok = (nr >= 0) & (nr < ny) & (nc >= 0) & (nc < nx)
        idx = np.nonzero(m)[0]
        tgt = np.full(idx.shape, -1, dtype=np.int64)
        tgt[ok] = nr[ok] * nx + nc[ok]
        succ[idx] = tgt
    # cells with code 5 or 0 stay -1 (pit / inactive)
    return succ


def find_cycles(succ):
    """Functional-graph cycle detection via 3-colour iterative DFS.
    Returns list of cycles (each a list of linear indices)."""
    N = succ.size
    WHITE, GRAY, BLACK = 0, 1, 2
    color = np.zeros(N, dtype=np.int8)
    cycles = []
    for s in range(N):
        if color[s] != WHITE:
            continue
        path = []
        pos = {}
        u = s
        while u != -1 and color[u] == WHITE:
            color[u] = GRAY
            pos[u] = len(path)
            path.append(u)
            u = succ[u]
        if u != -1 and color[u] == GRAY:
            cycles.append(path[pos[u]:])  # back-edge into current path
        for v in path:
            color[v] = BLACK
    return cycles


def main():
    ds = xr.load_dataset(FP)
    ldd = ds["wflow_ldd"].values.astype("float32")
    dem = ds["wflow_dem"].values.astype("float64")
    ny, nx = ldd.shape
    print(f"grid {ny}x{nx}  active(ldd 1..9)="
          f"{int(np.isin(ldd,[1,2,3,4,5,6,7,8,9]).sum())}  "
          f"pits(5)={int((ldd==5).sum())}", flush=True)

    succ = build_succ(ldd)
    cycles = find_cycles(succ)
    ncyc = len(cycles)
    sizes = sorted((len(c) for c in cycles), reverse=True)
    print(f"CYCLES: {ncyc}  sizes(top12)={sizes[:12]}  "
          f"cells_in_cycles={sum(sizes)}", flush=True)
    for c in cycles[:8]:
        locs = [(int(i // nx), int(i % nx)) for i in c[:6]]
        print("  cycle@", locs, "..." if len(c) > 6 else "", flush=True)

    if "--fix" not in sys.argv:
        print("(detect-only; pass --fix to break cycles)", flush=True)
        return

    if ncyc == 0:
        print("already acyclic — nothing to fix", flush=True)
        return

    # break: highest-DEM member of each cycle -> pit (5). iterate until clean.
    ldd2 = ldd.copy()
    demf = dem.ravel()
    rounds, broken = 0, 0
    while cycles:
        for c in cycles:
            hi = max(c, key=lambda i: demf[i])
            r, col = divmod(hi, nx)
            ldd2[r, col] = 5
            broken += 1
        rounds += 1
        succ = build_succ(ldd2)
        cycles = find_cycles(succ)
        print(f"  round {rounds}: remaining cycles={len(cycles)}", flush=True)
        if rounds > 50:
            print("  ABORT: too many rounds", flush=True)
            sys.exit(1)
    print(f"broke {broken} cells into pits over {rounds} rounds -> acyclic",
          flush=True)

    bak = FP.with_suffix(".nc.precyclefix")
    if not bak.exists():
        import shutil
        shutil.copy2(FP, bak)
        print(f"backup -> {bak}", flush=True)
    ds["wflow_ldd"] = (("lat", "lon"), ldd2)
    ds["wflow_pits"] = (("lat", "lon"),
                        np.where(ldd2 == 5, 1.0, 0.0).astype("float32"))
    enc = {v: {"_FillValue": None} for v in ds.data_vars}
    ds.to_netcdf(FP, encoding=enc)
    print(f"wrote acyclic ldd -> {FP}  pits now={int((ldd2==5).sum())}",
          flush=True)


if __name__ == "__main__":
    main()
