#!/usr/bin/env python3
"""
Bresenham 4-connected rasterization — diagnostic & demonstration
=================================================================

Background
----------
RIM2D uses 4-directional (N/S/E/W) flow routing: flux is computed only
between cells that share an edge.  Channel burns produced by the standard
Bresenham algorithm often step *diagonally*, creating cell pairs that share
only a corner.  From RIM2D's perspective these cells are disconnected:

    Standard Bresenham diagonal step:
        (212, 312)  ←──── only corner-connected ────→  (211, 311)
        No shared face → no 4-directional flux.

Pysheds `fill_depressions` uses 8-directional connectivity, so it accepts
diagonal exits as valid drainage paths and does NOT raise diagonal-pit cells.
The depression-fill diagnostic therefore passes, but the RIM2D simulation
ponds because the diagonal exit is invisible to its 4-directional kernel.

    Concrete pit from v23 DEM at (row=158, col=250), elev=306.44 m:
        N (159,250)=320.87  S (157,250)=314.30
        E (158,251)=309.11  W (158,249)=314.14
        ── all 4 orthogonal neighbours HIGHER → 4-directional PIT ──
        SW diagonal (157,249)=302.79  ← pysheds routes here, RIM2D cannot

Fix: 4-connected Bresenham
---------------------------
At every diagonal step, insert an intermediate orthogonal cell so that
consecutive cells always share an edge:

    4-connected step (dr ≥ dc, row-first):
        (212, 312) → (211, 312) → (211, 311) → ...
                     ↑ edge         ↑ edge

This script:
  1. Demonstrates the difference between standard and 4-connected Bresenham.
  2. Applies both to the cor1, cor2, and corr3 KML paths and compares cells.
  3. Runs the v24 DEM connectivity diagnostic (4-directional flood-fill).
  4. Shows the pit at (158, 250) from the v23 DEM.

Usage:
    micromamba run -n zarrv3 python v24/analysis/bresenham_4connected_demo.py
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import netCDF4
from collections import deque
from pyproj import Transformer

# ---------------------------------------------------------------------------
WORK_DIR  = Path("/data/rim2d/nile_highres")
V10_INPUT = WORK_DIR / "v10" / "input"
V23_INPUT = WORK_DIR / "v23" / "input"
V24_INPUT = WORK_DIR / "v24" / "input"
V23_DIR   = WORK_DIR / "v23"
KML_NS    = {"kml": "http://www.opengis.net/kml/2.2"}


# ---------------------------------------------------------------------------
# Core algorithms
# ---------------------------------------------------------------------------

def bresenham_standard(r0, c0, r1, c1):
    """Standard Bresenham — may produce diagonal (corner-only) steps."""
    pts = []
    dr = abs(r1-r0); dc = abs(c1-c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dr - dc
    r, c = r0, c0
    while True:
        pts.append((r, c))
        if r == r1 and c == c1:
            break
        e2 = 2 * err
        if e2 > -dc:
            err -= dc; r += sr
        if e2 <  dr:
            err += dr; c += sc
    return pts


def bresenham_4connected(r0, c0, r1, c1):
    """4-connected Bresenham — intermediate orthogonal cell at each diagonal step.

    At every point where the standard algorithm would step both row and col
    simultaneously (diagonal), this variant inserts one extra cell to break
    the diagonal into two orthogonal steps:

        if dr >= dc:  row step first  →  (r+sr, c)  then  (r+sr, c+sc)
        else:         col step first  →  (r, c+sc)  then  (r+sr, c+sc)

    Every consecutive pair of output cells therefore shares an edge, making
    the path traversable by 4-directional flow models (RIM2D, LISFLOOD-FP, …).
    """
    pts = []
    dr = abs(r1-r0); dc = abs(c1-c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dr - dc
    r, c = r0, c0
    while True:
        pts.append((r, c))
        if r == r1 and c == c1:
            break
        e2 = 2 * err
        step_r = e2 > -dc
        step_c = e2 <  dr
        if step_r and step_c:
            # Diagonal step — insert intermediate orthogonal cell
            if dr >= dc:
                pts.append((r + sr, c))   # row-first
            else:
                pts.append((r, c + sc))   # col-first
            err -= dc; r += sr
            err += dr; c += sc
        elif step_r:
            err -= dc; r += sr
        else:
            err += dr; c += sc
    return pts


def count_diagonal_steps(pts):
    """Count how many consecutive pairs are only diagonally connected."""
    diag = 0
    for i in range(len(pts) - 1):
        dr = abs(pts[i+1][0] - pts[i][0])
        dc = abs(pts[i+1][1] - pts[i][1])
        if dr == 1 and dc == 1:
            diag += 1
    return diag


# ---------------------------------------------------------------------------
# KML helper
# ---------------------------------------------------------------------------

def kml_to_raw_points(kml_path, x, y, tr):
    """Parse KML coordinates → list of (row, col) grid points (no interpolation)."""
    tree = ET.parse(str(kml_path))
    root = tree.getroot()
    raw = []
    for coords_el in root.findall(".//kml:coordinates", KML_NS):
        for pt in coords_el.text.strip().split():
            parts = pt.strip().split(",")
            if len(parts) < 2:
                continue
            lon, lat = float(parts[0]), float(parts[1])
            ex, ey = tr.transform(lon, lat)
            c = int(round((ex - x[0]) / (x[1] - x[0])))
            r = int(round((ey - y[0]) / (y[1] - y[0])))
            raw.append((r, c))
    return raw


def rasterize_path(raw_pts, nrows, ncols, algo):
    """Apply bresenham algo between consecutive raw_pts, clipped to grid."""
    cells = []
    for i in range(len(raw_pts) - 1):
        for r, c in algo(raw_pts[i][0], raw_pts[i][1],
                         raw_pts[i+1][0], raw_pts[i+1][1]):
            if 0 <= r < nrows and 0 <= c < ncols:
                cells.append((r, c))
    if raw_pts:
        r, c = raw_pts[-1]
        if 0 <= r < nrows and 0 <= c < ncols:
            cells.append((r, c))
    return cells


# ---------------------------------------------------------------------------
# Section 1: Algorithm demonstration
# ---------------------------------------------------------------------------

def demo_algorithm():
    print("=" * 60)
    print("SECTION 1: Algorithm comparison on a short diagonal segment")
    print("=" * 60)
    # A ~45-degree segment like cor2 makes diagonally
    r0, c0, r1, c1 = 10, 10, 3, 3

    std  = bresenham_standard(r0, c0, r1, c1)
    conn = bresenham_4connected(r0, c0, r1, c1)

    print(f"\nSegment: ({r0},{c0}) → ({r1},{c1})  (45° diagonal)")
    print(f"\n  Standard Bresenham  — {len(std)} cells, "
          f"{count_diagonal_steps(std)} diagonal pairs:")
    for i, (r, c) in enumerate(std):
        nxt = std[i+1] if i+1 < len(std) else None
        mark = ""
        if nxt:
            dr = abs(nxt[0]-r); dc = abs(nxt[1]-c)
            if dr == 1 and dc == 1:
                mark = "  ← diagonal (corner only)"
        print(f"    ({r:3d},{c:3d}){mark}")

    print(f"\n  4-connected Bresenham — {len(conn)} cells, "
          f"{count_diagonal_steps(conn)} diagonal pairs:")
    for i, (r, c) in enumerate(conn):
        nxt = conn[i+1] if i+1 < len(conn) else None
        mark = ""
        if nxt:
            dr = abs(nxt[0]-r); dc = abs(nxt[1]-c)
            if dr == 1 and dc == 1:
                mark = "  ← STILL DIAGONAL (bug)"
            elif dr == 0 and dc == 1:
                mark = "  → col step"
            elif dr == 1 and dc == 0:
                mark = "  → row step"
        print(f"    ({r:3d},{c:3d}){mark}")


# ---------------------------------------------------------------------------
# Section 2: KML path comparison
# ---------------------------------------------------------------------------

def demo_kml_paths():
    print("\n" + "=" * 60)
    print("SECTION 2: KML path rasterization — standard vs 4-connected")
    print("=" * 60)

    ds = netCDF4.Dataset(str(V10_INPUT / "dem.nc"))
    x  = np.array(ds["x"][:])
    y  = np.array(ds["y"][:])
    ds.close()
    nrows, ncols = 297, 386
    tr = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)

    for name, kml in [("cor1", V23_DIR / "cor1.kml"),
                       ("cor2", V23_DIR / "cor2.kml"),
                       ("corr3", V23_DIR / "corr3.kml")]:
        raw = kml_to_raw_points(kml, x, y, tr)
        std  = rasterize_path(raw, nrows, ncols, bresenham_standard)
        conn = rasterize_path(raw, nrows, ncols, bresenham_4connected)
        diag_std  = count_diagonal_steps(std)
        diag_conn = count_diagonal_steps(conn)
        rs = [r for r,c in conn]; cs = [c for r,c in conn]
        print(f"\n  {name}.kml ({len(raw)} GPS points)")
        print(f"    Standard  : {len(std):3d} cells, "
              f"{diag_std:3d} diagonal pairs ({100*diag_std/max(len(std)-1,1):.0f}%)")
        print(f"    4-connected: {len(conn):3d} cells, "
              f"{diag_conn:3d} diagonal pairs (should be 0)")
        print(f"    Extent: rows {min(rs)}-{max(rs)}, cols {min(cs)}-{max(cs)}")


# ---------------------------------------------------------------------------
# Section 3: Show the v23 pit at (158, 250)
# ---------------------------------------------------------------------------

def show_v23_pit():
    print("\n" + "=" * 60)
    print("SECTION 3: The 4-directional pit in v23 DEM at (158, 250)")
    print("=" * 60)

    ds = netCDF4.Dataset(str(V23_INPUT / "dem_v23.nc"))
    var = [v for v in ds.variables if v not in ("x","y")][0]
    dem23 = np.array(ds[var][:]).squeeze()
    ds.close()

    pr, pc = 158, 250
    e = dem23[pr, pc]
    print(f"\n  Cell ({pr}, {pc}): elevation = {e:.2f} m  (burned by cor2.kml)")
    print()
    print("  4-directional neighbours:")
    for dr, dc, label in [(-1,0,"N"),(1,0,"S"),(0,-1,"W"),(0,1,"E")]:
        nr, nc = pr+dr, pc+dc
        ne = dem23[nr, nc]
        delta = ne - e
        note = "HIGHER → blocks" if delta > 0 else "LOWER → exit"
        print(f"    {label}  ({nr:3d},{nc:3d}) = {ne:.2f} m  Δ={delta:+.2f}  {note}")

    print()
    print("  8-directional neighbours (diagonals):")
    for dr, dc, label in [(-1,-1,"SW"),(-1,1,"SE"),(1,-1,"NW"),(1,1,"NE")]:
        nr, nc = pr+dr, pc+dc
        ne = dem23[nr, nc]
        delta = ne - e
        note = "LOWER → pysheds exit" if delta < 0 else "higher"
        print(f"    {label} ({nr:3d},{nc:3d}) = {ne:.2f} m  Δ={delta:+.2f}  {note}")

    print()
    print("  → In 4-directional flow: PIT — water cannot escape.")
    print("  → In 8-directional flow: valid exit via SW diagonal (157,249).")
    print("  → Pysheds leaves cell unfilled; RIM2D ponds here indefinitely.")


# ---------------------------------------------------------------------------
# Section 4: v24 connectivity flood-fill
# ---------------------------------------------------------------------------

def show_v24_connectivity():
    print("\n" + "=" * 60)
    print("SECTION 4: v24 DEM — 4-directional pool analysis from Culvert2")
    print("=" * 60)

    ds = netCDF4.Dataset(str(V24_INPUT / "dem_v24.nc"))
    var = [v for v in ds.variables if v not in ("x","y")][0]
    dem24 = np.array(ds[var][:]).squeeze()
    ds.close()
    nrows, ncols = dem24.shape

    start = (222, 266)
    POOL_THRESH = 312.5

    visited = set(); pool = set()
    q = deque([start]); visited.add(start)
    while q:
        r, c = q.popleft()
        if dem24[r, c] <= POOL_THRESH:
            pool.add((r, c))
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = r+dr, c+dc
            if 0<=nr<nrows and 0<=nc<ncols and (nr,nc) not in visited:
                if dem24[nr,nc] <= POOL_THRESH:
                    visited.add((nr,nc))
                    q.append((nr,nc))

    pool_rows = [r for r,c in pool]
    pool_cols = [c for r,c in pool]
    min_elev  = min(dem24[r,c] for r,c in pool)
    at_nile   = sum(1 for r,c in pool if dem24[r,c] <= 295.0)

    print(f"\n  Start: Culvert2 ({start[0]},{start[1]}) "
          f"= {dem24[start[0],start[1]]:.2f} m")
    print(f"  Threshold: {POOL_THRESH} m")
    print(f"  Pool size:  {len(pool):,} cells")
    print(f"  Pool rows:  {min(pool_rows)} – {max(pool_rows)}")
    print(f"  Pool cols:  {min(pool_cols)} – {max(pool_cols)}")
    print(f"  Min elev in pool: {min_elev:.4f} m")
    print(f"  Cells at Nile floor (≤295 m): {at_nile:,}")

    if min_elev <= 295.0:
        print("\n  ✓ Culvert2 IS 4-directionally connected to the Nile zone.")
    else:
        print("\n  ✗ Culvert2 is NOT connected to the Nile zone at 4-dir topology.")

    # Lowest spill points outside pool
    spill = []
    for r, c in pool:
        for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
            nr, nc = r+dr, c+dc
            if 0<=nr<nrows and 0<=nc<ncols and (nr,nc) not in pool:
                spill.append((dem24[nr,nc], nr, nc, r, c))
    spill.sort()
    print(f"\n  3 lowest orthogonal spill points outside pool:")
    for e, nr, nc, fr, fc in spill[:3]:
        print(f"    ({nr},{nc})={e:.2f} m  from pool cell ({fr},{fc})={dem24[fr,fc]:.4f} m")


# ---------------------------------------------------------------------------
# Section 5: Steepest-descent trace comparison v23 vs v24
# ---------------------------------------------------------------------------

def compare_steepest_descent():
    print("\n" + "=" * 60)
    print("SECTION 5: Steepest-descent path trace — v23 vs v24")
    print("(uses micro-gradients from resolve_flats; stops at local min)")
    print("=" * 60)

    sites = [
        ("Culvert1",    212, 312),
        ("Culvert2",    222, 266),
        ("WesternWadi", 222, 175),
        ("HospitalWadi",183, 281),
    ]
    NILE_ELEV = 296.0

    for version, nc_path in [("v23", V23_INPUT / "dem_v23.nc"),
                               ("v24", V24_INPUT / "dem_v24.nc")]:
        ds = netCDF4.Dataset(str(nc_path))
        var = [v for v in ds.variables if v not in ("x","y")][0]
        dem = np.array(ds[var][:]).squeeze()
        ds.close()
        nrows, ncols = dem.shape
        print(f"\n  {version}:")
        for name, sr, sc in sites:
            r, c = sr, sc
            visited = set(); visited.add((r, c))
            for _ in range(10000):
                neighbors = [(dem[r+dr, c+dc], r+dr, c+dc)
                             for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]
                             if 0<=r+dr<nrows and 0<=c+dc<ncols
                             and (r+dr,c+dc) not in visited
                             and not np.isnan(dem[r+dr,c+dc])]
                if not neighbors:
                    break
                best_e, nr, nc2 = min(neighbors)
                if best_e >= dem[r, c]:
                    break
                visited.add((nr, nc2))
                r, c = nr, nc2
            end_e = dem[r, c]
            ok = "REACHES NILE ✓" if end_e <= NILE_ELEV else \
                 f"stalls row={r} col={c} elev={end_e:.2f}m"
            print(f"    {name:<18} steps={len(visited):4d}  "
                  f"end={end_e:.2f}m  {ok}")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    demo_algorithm()
    demo_kml_paths()
    show_v23_pit()
    show_v24_connectivity()
    compare_steepest_descent()
    print("\nDone.")
