# FastFlood case — {SLUG}

A FastFlood reproduction of the RIM2D case `{SLUG}`, using the **same published
inputs** from [`E4DRR/rim2d-simulations`](https://huggingface.co/datasets/E4DRR/rim2d-simulations)
and packaged in the same directory layout so the two methods can be compared
map-for-map.

## What FastFlood is
FastFlood (FastHazard, NL) is a **fast steady-state** flood method: DEM + rainfall
(+ optional Manning / infiltration) → maximum inundation in seconds on CPU. It
contrasts with RIM2D's GPU 2D shallow-water hydrodynamics.

## Inputs (`input/`)
Converted 1:1 from the RIM2D case NetCDFs (same 30 m grid, UTM CRS):

| File | From RIM2D | Meaning |
|---|---|---|
| `dem.tif` | `dem.nc` | Copernicus GLO-30 elevation (m), stream-burned |
| `roughness.tif` | `roughness.nc` | Manning's n |
| `infiltration.tif` | `pervious_surface.nc` × 12 | infiltration capacity (mm/hr) |
| `rain_mean_mmhr.tif` | `rain/imerg_t*.nc` | event-mean intensity (mm/hr) |
| `permanent_water.tif` | Natural Earth lakes + DEM sea | permanent-water mask (1 = lake/reservoir/sea) |

Permanent water bodies (lakes, reservoirs, ocean) pond as flat basins in FastFlood
but are not flood, so they are masked out of the depth maps/animation (rendered as
static dark water, like the RIM2D basemap). The mask is Natural Earth 10m lakes plus
DEM cells at/below 0 m connected to a domain edge (ocean); flat inland floodplains
are deliberately left unmasked. See `build_water_mask.py`.

FastFlood's `-rain` is an intensity applied as `rain × dur`, so the IMERG frames
(mm/hr, per 30 min) are reduced to an event-mean-intensity map:
`total_mm = Σ(rate·0.5)`, `mean = total_mm / duration_h`.

## Outputs (`output/`)
- `{SLUG}_wd_max.tif` — maximum water-depth envelope (compare vs RIM2D `case_v1_wd_max.nc`).
- `frames/wh_t*.tif` — inundation at successive elapsed times, produced by driving
  FastFlood with the **cumulative IMERG hyetograph** (rain accumulated so far,
  delivered over the full duration) so extent grows monotonically to the final result.
- `preview.gif` — RIM2D-style animation (dark hillshade + blue depth ramp).

## Comparison to RIM2D
FastFlood reproduces the same flood pattern but under-predicts extent/depth
(~half the wet area) — expected for a steady approximation vs full 2D
hydrodynamics. See `FASTFLOOD_VS_RIM2D_RESULTS.md` in the code repo.

## Reproduce
Code: <https://github.com/nishadhka/DevOps-hazard-modeling/tree/main/fastflood>
(`rim2d_nc_to_fastflood.py`, `run_all_cases.sh`, `make_fastflood_animation.py`,
`package_fastflood_case.sh`).

*Not calibrated — a first-pass inter-model comparison, not a validated hazard product.*
