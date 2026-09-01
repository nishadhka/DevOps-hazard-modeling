# FastFlood vs RIM2D — 11 ICPAC flood cases

Running the FastFlood CLI (Windows binary under Wine, see
[`RUNNING_FASTFLOOD_CLI.md`](RUNNING_FASTFLOOD_CLI.md)) against the same 11 case
studies that RIM2D covers, using the **real event inputs** published to the
HuggingFace dataset
[`E4DRR/rim2d-simulations`](https://huggingface.co/datasets/E4DRR/rim2d-simulations),
and comparing the resulting maximum-depth envelope against RIM2D's own reference
output for each case.

## What FastFlood needs vs RIM2D

RIM2D is a GPU 2D shallow-water solver needing DEM + Manning + buildings + a
per-30-min IMERG rainfall time series + river hydrographs. FastFlood needs only
**DEM + rainfall** (optionally Manning and infiltration) and runs on CPU in
seconds. So each RIM2D case is driven into FastFlood by reusing its published
inputs:

| RIM2D input (`<case>/input/*.nc`) | FastFlood use |
|---|---|
| `dem.nc` (elevation, burned) | `-dem dem.tif` |
| `roughness.nc` (Manning's n) | `-man man.tif` |
| `pervious_surface.nc` (× KSAT) | `-inf inf.tif` (see caveat) |
| `rain/imerg_t*.nc` (mm/hr, per 30 min) | `-rain rain_mmhr.tif -dur <h>` |

The RIM2D NetCDFs carry UTM-metre coordinates but **no embedded CRS**; the
converter assigns the correct UTM EPSG per case from the domain centroid.

### Rain handling (important)
FastFlood's `-rain` is an **intensity in mm/hr**, and it applies `rain × dur` as
the event total. The IMERG frames are per-30-min mm/hr rates, so the converter
builds a spatial **event-mean intensity** map:

```
event_total_mm  = Σ(frame_mm_hr) × 0.5
duration_h      = n_frames × 0.5
mean_intensity  = event_total_mm / duration_h      → rain_mmhr.tif
```

Passing `-rain rain_mmhr.tif -dur duration_h` then reproduces the true spatial
event totals.

## Reproduce

```bash
# convert one case's HF NetCDFs to FastFlood GeoTIFFs
micromamba run -n aifs-etl python rim2d_nc_to_fastflood.py \
    <case>/input <out_dir> <lon_centroid> <lat_centroid> [ksat_mmhr]

# run all 11 (downloads HF inputs, converts, runs, compares → results.csv)
./run_all_cases.sh
```

Outputs per case land in
`/mnt/wflow-secondary/fastflood-data/case_runs/<slug>/`
(`dem/man/inf/rain_mmhr.tif`, `<slug>_ff_wh.tif`, `rim2d_wd_max.nc`).

## Results

Real event rain, DEM + Manning, no channel routing. Wet area = cells with
depth > 5 cm; % of the whole domain. **Permanent water bodies (lakes / reservoirs
/ ocean) are excluded from both columns** using the same `permanent_water.tif`
mask per case (Natural Earth lakes + DEM sea; see `build_water_mask.py`), so the
figures are flood-on-land for both models. RIM2D column = `case_v1_wd_max.nc`.

| Case | Country | Frames / Dur | Water masked | FF max (m) | FF wet (km² / %) | RIM2D max (m) | RIM2D wet (km² / %) |
|---|---|---|---|---|---|---|---|
| nairobi_2026-03-06 | KEN | 48 / 24 h | 0.0 % | 10.53 | 116.1 / 6.2 | 20.08 | 221.7 / 11.8 |
| ssd_2025-10-05 | SSD | 48 / 24 h | 0.0 % | 0.97 | 46.3 / 4.2 | 5.24 | 62.8 / 5.7 |
| dji_2019-11-21 | DJI | 144 / 72 h | 43.7 % | 2.38 | 22.4 / 0.6 | 23.41 | 1216.9 / 30.9 |
| eth_2021-08-16 | ETH | 144 / 72 h | 0.0 % | 2.22 | 19.9 / 1.8 | 21.45 | 42.8 / 3.9 |
| som_2023-11-19 | SOM | 144 / 72 h | 36.5 % | 1.43 | 34.7 / 3.1 | 7.57 | 409.8 / 37.0 |
| uga_2019-05-26 | UGA | 144 / 72 h | 2.0 % | 1.65 | 98.7 / 4.6 | 9.75 | 252.7 / 11.7 |
| eri_2019-08-10 | ERI | 240 / 120 h | 0.0 % | 1.55 | 2.4 / 0.8 | 12.91 | 10.8 / 3.6 |
| rwa_2023-05-01 | RWA | 240 / 120 h | 5.3 % | 3.02 | 250.2 / 5.2 | 16.78 | 564.7 / 11.7 |
| nile_2024_abu_hamad | SDN | 288 / 144 h | 0.0 % | 0.28 | 2.0 / 2.0 | 5.44 | 19.8 / 19.2 |
| tza_2024-04-10 | TZA | 336 / 168 h | 28.4 % | 2.54 | 89.1 / 4.0 | 11.58 | 718.7 / 32.6 |
| bdi_2024-04-01 | BDI | 1008 / 504 h | 24.5 % | 2.14 | 22.9 / 1.5 | 16.93 | 411.3 / 27.7 |

> Earlier (unmasked) figures counted permanent-water ponding as flood and were
> inflated, especially for FastFlood in coastal/lake cases — e.g. dji FF 25.5 % →
> 0.6 %, som 12.6 % → 3.1 %, tza 17.3 % → 4.0 %, bdi 9.6 % → 1.5 % once the sea /
> lake is removed.

## Interpretation

Two regimes emerge once permanent water is excluded:

- **Inland cases** (water ≈ 0 %: nairobi, ssd, eth, eri, nile, uga, rwa).
  FastFlood reproduces the same flood locations but **under-predicts** RIM2D by
  roughly half (FF/RIM2D wet-area ratio ~0.4–0.7; nile the outlier at ~0.1).
  The stable ratio is a good sign the conversion (CRS, rain totals, grid) is
  correct and the difference is model physics, not a bug.

- **Coastal / lake cases** (dji, som, tza, bdi). After masking the sea/lake,
  FastFlood's on-land flood is very small (0.6–4 %) while RIM2D still inundates
  extensive low-lying coastal **land** (28–37 %). Here FastFlood's steady
  pluvial method barely wets the near-sea-level plains that RIM2D's dynamic
  solver floods, so the gap is much wider than inland.

- **Why FastFlood is lower.** It is a fast steady-state approximation driven by
  the event-*mean* intensity; RIM2D is full 2D hydrodynamics resolving sub-hourly
  IMERG bursts, channel conveyance and storage. Peak depths follow the same
  pattern — RIM2D 5–23 m of dynamic ponding vs FastFlood's damped 0.3–10.5 m.

## Caveats / next steps

1. **Infiltration ignored.** Runs with and without `-inf inf.tif` were
   bit-identical → FastFlood's raster-rain path appears not to apply `-inf`.
   To confirm with FastHazard.
2. **Event-mean intensity underestimates burst floods.** Using a **peak-window
   intensity** (e.g. max rolling 3–6 h) with a matched short duration would
   raise FastFlood toward RIM2D for the flashy cases.
3. **No fluvial routing.** These are pluvial-only; enabling FastFlood's
   `-channel` (1D–2D coupled) would add river conveyance, closing part of the
   gap on river-driven cases (eth, nile, ssd).
4. **Coastal cases need more than pluvial.** For dji/som/tza the large RIM2D
   on-land inundation near sea level is driven by processes FastFlood's steady
   pluvial run does not capture (dynamic routing across flat coastal land, and
   any tidal/backwater effect). These cases are where the two models diverge most.
5. **Permanent-water mask is heuristic.** Natural Earth lakes + DEM-sea (≤ 0 m
   connected to a domain edge). It can miss small reservoirs (Nairobi Dam stays
   unmasked, ~0.1 %) and, on a very low coast, the 0 m cut is approximate. Both
   models use the identical mask, so the comparison stays fair.
6. **Not calibrated.** KSAT (12 mm/hr) and the uniform sewershed are placeholder
   assumptions; this is a first-pass inter-model comparison, not a validated
   hazard product.
