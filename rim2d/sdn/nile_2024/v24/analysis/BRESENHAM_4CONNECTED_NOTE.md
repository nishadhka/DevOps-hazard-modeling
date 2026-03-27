# Bresenham Rasterization & 4-Directional Flow Connectivity
## RIM2D Channel Burn Diagnostics — v23→v24

---

## 1. The Problem: Pysheds Thinks Water Drains; RIM2D Disagrees

After v23 DEM conditioning, the depression-fill diagnostic (pysheds) reported that all
4 inflow sites **reach the Nile**.  Yet the simulation showed high ponding at Culvert1 and
Culvert2, and the user observed that stream flow was not visibly connecting to the Nile.

The root cause is a **dimensionality mismatch** between two tools in the pipeline:

| Tool | Connectivity | Consequence |
|------|-------------|-------------|
| pysheds `fill_depressions` | **8-directional** (incl. diagonals) | Sees a valid outlet diagonally |
| RIM2D flow kernel | **4-directional** (N/S/E/W only) | Cannot use the diagonal outlet |

### Concrete example from v23 DEM (col=250, row=158)

```
Cell (158, 250) — burned by cor2.kml — elevation 306.44 m

4-directional neighbours:
  N  (159, 250) = 320.87 m   ↑ uphill
  S  (157, 250) = 314.30 m   ↑ uphill
  E  (158, 251) = 309.11 m   ↑ uphill
  W  (158, 249) = 314.14 m   ↑ uphill

→ ALL four neighbours are HIGHER than 306.44 m.
→ In RIM2D 4-directional routing, this cell is a PIT.
  Water fills it and cannot escape.
```

However, looking at the 8-directional (diagonal) neighbourhood:

```
  SW diagonal (157, 249) = 302.79 m   ↓ LOWER — pysheds routes here
```

Pysheds `fill_depressions` uses 8-directional connectivity, so it classifies
`(158, 250)` as *not* a depression (because the SW diagonal exits at 302.79 m).
The cell is left unfilled, and `resolve_flats` adds a tiny micro-gradient pointing
SW.  From pysheds' point of view, the path to the Nile is valid.

RIM2D only computes fluxes between the four orthogonal face-adjacent cells.
The SW diagonal is never checked.  Water accumulates at `(158, 250)` until the
water surface elevation is high enough to overflow one of the orthogonal walls —
a process that is very slow and leads to the observed ponding.

---

## 2. Why Did the Diagonal Pit Form?

The cor2.kml channel was rasterized using a **standard Bresenham line algorithm**.
For a path with roughly equal row and column increments (≈45° diagonal), the algorithm
steps both `row` and `col` simultaneously, producing a *diagonal staircase*:

```
Standard Bresenham (diagonal step):
  (212, 312) ──→ (211, 311) ──→ (210, 310) ──→ ...
                  ↖diagonal     ↖diagonal

Consecutive cell pairs share only a CORNER, not an EDGE.
In 4-directional flow there is no face between them.
```

Each pair of consecutive burned cells is only **8-connected** (corner-sharing),
not **4-connected** (edge-sharing).  So the burned channel, when viewed by RIM2D's
4-directional kernel, is a series of isolated pits connected only diagonally.

---

## 3. The Fix: 4-Connected Bresenham

A 4-connected (Manhattan-path) variant of Bresenham inserts an **intermediate
orthogonal cell** at every diagonal step, ensuring every consecutive pair of cells
shares an edge:

```
4-connected Bresenham (diagonal step → insert intermediate):
  (212, 312) → (211, 312) → (211, 311) → (210, 311) → ...
               ↑ row-step    ↑ col-step   ↑ row-step

Every consecutive pair shares a FACE → 4-directional flow is possible.
```

The rule for choosing which intermediate cell to insert:
- If `dr ≥ dc` (path is more vertical): step **row first**, then col.
- If `dc > dr` (path is more horizontal): step **col first**, then row.

This guarantees a connected, monotonically progressing path along the dominant axis.

### Implementation (Python)

```python
def bresenham_4connected(r0, c0, r1, c1):
    """
    All grid cells on the line (r0,c0)→(r1,c1), 4-connected.

    At each diagonal step, an intermediate orthogonal cell is inserted so
    that every consecutive pair of output cells shares an edge (not just a
    corner).  Essential for RIM2D 4-directional flow routing.
    """
    pts = []
    dr = abs(r1 - r0); dc = abs(c1 - c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dr - dc
    r, c = r0, c0

    while True:
        pts.append((r, c))
        if r == r1 and c == c1:
            break
        e2 = 2 * err
        step_r = e2 > -dc   # would standard Bresenham step row?
        step_c = e2 <  dr   # would standard Bresenham step col?

        if step_r and step_c:
            # Diagonal — insert intermediate orthogonal cell
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
```

### Effect on burn cell counts (v23 → v24)

| KML file | v23 cells (8-connected) | v24 cells (4-connected) | Extra cells |
|----------|------------------------|------------------------|-------------|
| cor1.kml | 131 | 159 | +28 |
| cor2.kml | 134 | 197 | +63 |
| corr3.kml | — | 6 | new in v24 |

The extra cells are the intermediate orthogonal steps inserted at diagonal
transitions.  They do not deepen the channel — they inherit the same burn depth
as the adjacent principal cell.

---

## 4. Additional Fix: corr3.kml Shallow Channel (dem − 1 m)

`corr3.kml` (15 GPS points, rows 158–176, cols 251–254) traces the actual drainage
path through the railway-side stagnation zone identified by the user via Google Earth.
It is burned at **dem_orig − 1 m** (a shallow, 1 m-deep channel).

Purpose:
- Fills topographic gaps left between the cor2.kml burn and the Nile zone.
- Provides an additional 4-directional pathway through the 311–314 m ridge at
  rows 157–158 that was otherwise only reachable diagonally.
- Does not distort inundation depths (1 m burn ≪ 8 m burn for cor1/cor2).

---

## 5. Hydraulic Pool Analysis

After all burns, a 4-directional flood-fill from Culvert2 (row=222, col=266) was
performed to verify true connectivity at the 312.5 m threshold:

```
Pool size:   13,224 cells
Pool extent: rows 0–222, cols 0–358
Pool min elevation: 294.00 m  ← Nile channel floor
```

This confirms the entire channel network — from all 4 inflow sites through the
cor1/cor2/corr3 burned paths — is **4-directionally connected to the Nile zone**
after the v24 DEM conditioning.

The residual ponding at Culvert1/Culvert2 (true flood depth ~1.1–1.3 m) is therefore
a **hydraulic capacity effect** (narrow channel cannot carry peak discharge fast enough),
not a topological connectivity failure.  The 1.1–1.3 m above-ground inundation is
physically consistent with the Aug 2024 Abu Hamad event.

---

## 6. Files

| File | Description |
|------|-------------|
| `v24/run_v24_setup.py` | Full DEM conditioning pipeline with 4-connected Bresenham |
| `v24/analysis/bresenham_4connected_demo.py` | Standalone demo & diagnostic script |
| `v24/input/dem_v24.nc` | Final conditioned DEM (float64, 297×386) |
| `v24/analysis/visualizations/v24_max_depth_map.png` | Peak inundation map (raw WD + true flood depth) |
| `v24/analysis/visualizations/v24_timeseries.png` | Flood evolution time series |

---

## 7. Key Lesson

> **Always match the rasterization connectivity to the model's flow connectivity.**
>
> If RIM2D uses 4-directional flow, channel burns must use a 4-connected
> rasterization algorithm.  Using the standard 8-connected Bresenham for diagonal
> channels will create isolated pits that pysheds cannot detect (because pysheds
> is 8-directional) but RIM2D cannot drain (because RIM2D is 4-directional).
> This mismatch is silent — the depression-fill diagnostic passes, but the
> simulation ponds.
