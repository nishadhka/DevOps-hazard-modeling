# HydroBASINS extents for the 11 ICPAC drought cases

Walks upstream from each case's outlet (defined in `region_configs.REGIONS`) through
HydroBASINS Africa polygons via the `NEXT_DOWN` field, dissolves the upstream
contributing area into a single geometry per case, and produces per-case + overview
maps for comparison with the country-extent bboxes the current wflow runs use.

## Run

```bash
# from the wflow-jl repo root, with the uv project active
uv run python -m shared.hydrobasins                 # level 8 (default)
uv run python -m shared.hydrobasins --level 7       # coarser
uv run python -m shared.hydrobasins --only ETH      # one case
```

Outputs land in `shared/hydrobasins/outputs/`:
- `case_<iso>.png` — per-case map with HydroBASINS polygon, current bbox, outlet point
- `overview_east_africa.png` — all 11 cases on one map
- `case_extents.geojson` — dissolved geometries + metadata

Inputs (auto-downloaded on first run, gitignored):
- `data/hybas_af_lev{08}_v1c.shp` — HydroSHEDS HydroBASINS Africa
- `data/ne_50m_admin_0_countries.shp` — Natural Earth country boundaries

## Selection method

For cases with an `outlet` in `region_configs.REGIONS` (BDI, DJI, ERI, ETH, KEN, RWA,
TZA, UGA), we snap the outlet point to its containing HydroBASINS polygon, then BFS
backwards through `NEXT_DOWN` edges to collect every polygon that drains to it.

For the three planned cases without outlets (SOM, SSD, SDN), we fall back to a
bbox-intersect at the chosen level — this overestimates the contributing area but
gives a placeholder until an outlet is pinned.

## Publishing outputs to HuggingFace

Heavy / generated artifacts (`outputs/*.png`, `outputs/*.geojson`, the downloaded
HydroBASINS shapefiles in `data/`) are gitignored. Push them to the
[`E4DRR/wflow.jl-simulations`](https://huggingface.co/datasets/E4DRR/wflow.jl-simulations)
dataset instead:

```bash
# .env at repo root must contain HF_TOKEN=hf_…
uv run python -m shared.hydrobasins.upload_to_hf                       # → hydrobasins/level08
uv run python -m shared.hydrobasins.upload_to_hf --dest hydrobasins/level07
uv run python -m shared.hydrobasins.upload_to_hf --dry-run             # preview only
```

Pattern adapted from
[icpac-igad/grib-index-kerchunk · upload_parquets_to_hf.py](https://github.com/icpac-igad/grib-index-kerchunk/blob/main/gefs/upload_parquets_to_hf.py).

## Why this matters

Current wflow builds use country-extent bboxes. HydroBASINS-based clipping shrinks
the active grid by 5–13× for ETH, KEN, TZA — turning multi-hour runs into
sub-hour runs and freeing tens of GB of staticmaps storage. See the storyline
versus current-cell-count comparison in the discussion linked from
`REORGANIZATION_PLAN.md`.
