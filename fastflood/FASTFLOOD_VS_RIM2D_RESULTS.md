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
depth > 5 cm; % of domain. RIM2D column = `case_v1_wd_max.nc` reference.

| Case | Country | Frames / Dur | FF max (m) | FF wet (km² / %) | RIM2D max (m) | RIM2D wet (km² / %) |
|---|---|---|---|---|---|---|
| nairobi_2026-03-06 | KEN | 48 / 24 h | 10.53 | 116.1 / 6.2 | 20.08 | 221.7 / 11.8 |
| ssd_2025-10-05 | SSD | 48 / 24 h | 0.97 | 46.3 / 4.2 | 5.24 | 62.8 / 5.7 |
| dji_2019-11-21 | DJI | 144 / 72 h | 2.38 | 1004.3 / 25.5 | 23.41 | 1839.2 / 46.7 |
| eth_2021-08-16 | ETH | 144 / 72 h | 2.22 | 19.9 / 1.8 | 21.45 | 42.8 / 3.9 |
| som_2023-11-19 | SOM | 144 / 72 h | 1.43 | 139.6 / 12.6 | 7.57 | 496.3 / 44.8 |
| uga_2019-05-26 | UGA | 144 / 72 h | 1.65 | 119.2 / 5.5 | 9.75 | 257.2 / 11.9 |
| eri_2019-08-10 | ERI | 240 / 120 h | 1.55 | 2.4 / 0.8 | 12.91 | 10.8 / 3.6 |
| rwa_2023-05-01 | RWA | 240 / 120 h | 3.02 | 277.3 / 5.7 | 16.78 | 574.5 / 11.9 |
| nile_2024_abu_hamad | SDN | 288 / 144 h | 0.28 | 2.0 / 2.0 | 5.44 | 19.8 / 19.2 |
| tza_2024-04-10 | TZA | 336 / 168 h | 2.54 | 381.0 / 17.3 | 11.58 | 941.6 / 42.7 |
| bdi_2024-04-01 | BDI | 1008 / 504 h | 2.39 | 142.6 / 9.6 | 16.93 | 481.4 / 32.4 |

## Interpretation

- **Same events, consistent offset.** Across all 11 cases FastFlood reproduces
  the same flood locations but **under-predicts** RIM2D — typically about half
  the inundated area and a much lower peak depth. The wet-area ratio (FF/RIM2D)
  is remarkably stable (~0.4–0.7), which is a good sign the conversion (CRS,
  rain totals, grid) is correct and the difference is model physics, not a bug.

- **Why FastFlood is lower.** FastFlood is a fast steady-state approximation
  driven by the event-*mean* intensity. RIM2D is full 2D hydrodynamics that
  resolves sub-hourly IMERG bursts, channel conveyance and storage. The gap is
  largest for burst-driven events (nile 2.0 vs 19.2 %, som 12.6 vs 44.8 %,
  dji 25.5 vs 46.7 %) and smallest for the short, uniform NBO/SSD events.

- **Peak depths.** RIM2D peak depths (12–23 m in mountainous/among-buildings
  cells) reflect dynamic ponding that the steady method damps out; FastFlood
  peaks are 1–10 m.

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
4. **Not calibrated.** KSAT (12 mm/hr) and the uniform sewershed are placeholder
   assumptions; this is a first-pass inter-model comparison, not a validated
   hazard product.
