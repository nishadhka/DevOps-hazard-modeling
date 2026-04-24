# hazard-model-api

A flat catalog of Python download scripts that prepare the input datasets
consumed by two hazard models:

- **RIM2D** — GPU 2D hydraulic inundation model (30 m flood hazard).
  Reference case: `../rim2d/ken/nbo_2026/` (Nairobi 2026 flash flood, 6 versions).
- **Wflow.jl SBM** — distributed hydrological model (1 km drought / discharge).
  Reference case: `../wflow-jl/bdi/dr_case1/` (Burundi 2021-2022 drought).

Every script in this folder is **region-agnostic**: pass `--bbox W,S,E,N` and
date range on the command line and the same script works for Nairobi, Burundi,
or anywhere else. Nothing is hard-coded to a specific event.

---

## Why extent matters (read this first)

Input size scales with bbox area × resolution × time period. The worst
offenders are Overture Maps buildings, Overture Maps roads, and 30 m rainfall
stacks — plan bbox and period accordingly.

| Source | Size formula (rough) | Example: 55 × 34 km, 30 days | Example: country (Burundi 230 × 240 km), 2 yrs |
|--------|----------------------|------------------------------|------------------------------------------------|
| Copernicus GLO-30 DEM | ~2 MB per 1000 km² at 30 m | ~4 MB | ~110 MB |
| ESA WorldCover 2021 | ~0.5 MB per 1000 km² at 10 m (served at `scale=30`) | ~1 MB | ~30 MB |
| GHSL built-up 2020 (100 m) | ~0.2 MB per 1000 km² | ~0.4 MB | ~10 MB |
| MERIT Hydro (4 bands, 90 m) | ~4 MB per 1000 km² | ~7 MB | ~220 MB |
| **Overture buildings (GeoJSON)** | **~50 MB per 1000 km² urban, ~5 MB rural** | **~100 MB (urban Nairobi)** | **~500 MB–2 GB (cities only)** |
| **Overture roads (GeoJSON)** | **~15 MB per 1000 km²** | **~30 MB** | **~800 MB** |
| TDX-Hydro river network | <5 MB any size | ~1 MB | ~20 MB |
| **IMERG rainfall (30 min)** | **~1 KB per 30 m cell per timestep; stored per-timestep** | **~60 MB (1440 steps × 30 m grid)** | N/A (Wflow uses CHIRPS) |
| CHIRPS daily (5.5 km) | ~300 KB per day per country | N/A (RIM2D uses IMERG) | ~200 MB (730 days × ~40 tiles) |
| ERA5-Land temp + PET | ~50 KB per day per country | N/A | ~30 MB |
| SoilGrids (8 props, 250 m) | ~5 MB per 1000 km² per prop | N/A | ~450 MB |

**Rules of thumb:**

1. For Overture buildings / roads, **never request a country-scale bbox**
   unless you actually need it. Crop to the RIM2D domain (usually a city or a
   river basin, < 5000 km²). Buildings alone can pass 2 GB for a country.
2. IMERG at RIM2D 30 m grid produces one NetCDF **per 30-minute timestep**
   — 30 days = 1440 files. Keep simulation periods short (days, not months)
   for event simulations.
3. Wflow uses native 1 km grids, so DEM, landcover, soil, and forcing stay
   manageable even for country-scale domains.
4. GEE `getDownloadURL` has a **50 MB per image cap**. Any script that hits
   it tiles internally; for very large bboxes (> 20 000 km²) use the GEE
   Tasks export path instead (not implemented here).

---

## Files in this folder

### Download scripts (flat, no package)

| Script | Sources | Feeds |
|--------|---------|-------|
| [`download_dem.py`](download_dem.py) | Copernicus GLO-30 DEM + MERIT elv (GEE) | RIM2D base terrain, Wflow DEM |
| [`download_worldcover.py`](download_worldcover.py) | ESA WorldCover 2021 + GHSL built-up (GEE) | RIM2D roughness + channel mask + sealed/pervious, Wflow landuse |
| [`download_merit_hydro.py`](download_merit_hydro.py) | MERIT Hydro (elv, dir, upa, wth) (GEE) | Wflow flow direction + upstream area, RIM2D channel width |
| [`download_buildings.py`](download_buildings.py) | Overture Maps `building` type | RIM2D buildings raster, Wflow urban mask |
| [`download_roads.py`](download_roads.py) | Overture Maps `segment` type | RIM2D visualization + optional roughness override |
| [`download_river_network.py`](download_river_network.py) | TDX-Hydro v2 via TIPG API | RIM2D v5/v6 channel geometry |
| [`download_imerg.py`](download_imerg.py) | GPM IMERG V07 half-hourly (GEE) | RIM2D pluvial forcing |
| [`download_chirps.py`](download_chirps.py) | CHIRPS v2 daily (direct HTTPS) | Wflow precipitation |
| [`download_era5.py`](download_era5.py) | ERA5-Land hourly temp + PET (GEE) | Wflow temperature + PET |
| [`download_soilgrids.py`](download_soilgrids.py) | ISRIC SoilGrids (GEE mirror) | Wflow soil parameters |

### Conversion / preparation scripts

| Script | Input | Output |
|--------|-------|--------|
| [`rasterize_buildings.py`](rasterize_buildings.py) | Overture buildings GeoJSON + reference DEM | `buildings.nc` fractional cover raster (RIM2D) |
| [`compute_hand.py`](compute_hand.py) | DEM GeoTIFF | HAND + flow accumulation NetCDF (RIM2D v1 IWD) |
| [`prepare_rim2d_case.py`](prepare_rim2d_case.py) | All raw downloads | `<out>/v1/{input,output}/` + `simulation_v1.def` |
| [`prepare_wflow_staticmaps.py`](prepare_wflow_staticmaps.py) | All raw downloads | `staticmaps.nc` with 80+ Wflow variables |
| [`fix_ldd_pyflwdir.py`](fix_ldd_pyflwdir.py) | `staticmaps.nc` | Cycle-free LDD (Wflow fix) |

### Shared

| File | Purpose |
|------|---------|
| [`common.py`](common.py) | Region CLI parser, GEE auth, raster IO helpers (imported by all scripts) |
| [`manning_lookup.csv`](manning_lookup.csv) | ESA WorldCover class → Manning's n |
| [`requirements.txt`](requirements.txt) | Python dependencies |

### Examples

| File | What it runs |
|------|--------------|
| [`examples/example_region_nbo.sh`](examples/example_region_nbo.sh) | Small urban RIM2D case (Nairobi, 55 × 34 km, March 2026 event) |
| [`examples/example_region_bdi.sh`](examples/example_region_bdi.sh) | Country-scale Wflow case (Burundi, 230 × 240 km, 2021-2022) |

---

## Common CLI interface

Every download script accepts the same core arguments so you can script a
pipeline without remembering per-script flag conventions.

```
--bbox WEST,SOUTH,EAST,NORTH    lon/lat WGS84, comma-separated, REQUIRED
--out  DIR                      output directory (created if missing)
--start YYYY-MM-DD              temporal start (scripts that need it)
--end   YYYY-MM-DD              temporal end (exclusive)
--scale METRES                  target pixel size (default 30 for RIM2D, 1000 for Wflow)
--crs   EPSG:CODE               target CRS (default EPSG:4326 WGS84 lon/lat)
--sa-key PATH                   GEE service account JSON (or env GEE_SA_KEY)
--dry-run                       print estimated download size and exit without downloading
```

All scripts are idempotent — re-running skips files already on disk.

Use `--dry-run` before a large download to see size estimates:

```bash
python download_buildings.py --bbox 28.83,-4.50,30.89,-2.29 --out ./bdi --dry-run
# Estimated: 230 × 240 km ≈ 55000 km², Overture buildings ≈ 300-800 MB
```

---

## Workflow: prepare a RIM2D case for a new region

```bash
BBOX="36.60,-1.402,37.10,-1.098"           # lon/lat
OUT="./runs/nbo"
START="2026-03-06"
END="2026-03-07"

# 1. Base terrain + land cover (small, GEE)
python download_dem.py          --bbox "$BBOX" --out "$OUT" --scale 30 --crs EPSG:32737
python download_worldcover.py   --bbox "$BBOX" --out "$OUT" --scale 30 --crs EPSG:32737
python download_merit_hydro.py  --bbox "$BBOX" --out "$OUT"

# 2. Buildings + roads (WATCH SIZE for urban domains)
python download_buildings.py    --bbox "$BBOX" --out "$OUT"
python download_roads.py        --bbox "$BBOX" --out "$OUT"

# 3. River network for fluvial BCs
python download_river_network.py --bbox "$BBOX" --out "$OUT"

# 4. Event rainfall (IMERG half-hourly, one file per timestep)
python download_imerg.py --bbox "$BBOX" --out "$OUT" --start "$START" --end "$END" \
       --scale 30 --crs EPSG:32737

# 5. Build RIM2D input folder + simulation.def
python prepare_rim2d_case.py --bbox "$BBOX" --out "$OUT" --start "$START" --end "$END" \
       --version v1 --iwd worldcover

# 6. Run the model (RIM2D binary lives in ../rim2d/bin/)
cd "$OUT/v1" && ../../../rim2d/bin/RIM2D simulation_v1.def --def flex
```

## Workflow: prepare a Wflow case for a new region

```bash
BBOX="28.83,-4.50,30.89,-2.29"             # lon/lat, Burundi
OUT="./runs/bdi"
START="2021-01-01"
END="2022-12-31"

# 1. Base grids (1 km, all small)
python download_dem.py          --bbox "$BBOX" --out "$OUT" --scale 1000 --target merit
python download_worldcover.py   --bbox "$BBOX" --out "$OUT" --scale 1000
python download_merit_hydro.py  --bbox "$BBOX" --out "$OUT"
python download_soilgrids.py    --bbox "$BBOX" --out "$OUT" --scale 1000

# 2. Forcing (daily, manageable for country-scale)
python download_chirps.py --bbox "$BBOX" --out "$OUT" --start "$START" --end "$END"
python download_era5.py   --bbox "$BBOX" --out "$OUT" --start "$START" --end "$END"

# 3. Build Wflow staticmaps + config
python prepare_wflow_staticmaps.py --bbox "$BBOX" --out "$OUT"
python fix_ldd_pyflwdir.py         --staticmaps "$OUT/staticmaps.nc"

# 4. Run Wflow (julia --project= ...)
```

---

## Provenance

The scripts here are distilled from the following working code in the repo —
each has been lifted, parameterised on `--bbox`/dates, and trimmed of the
per-case specifics:

| Reference (existing) | → This folder |
|----------------------|---------------|
| `../rim2d/ken/nbo_2026/setup_v1.py` (GEE download portion) | `download_dem.py`, `download_worldcover.py`, `download_merit_hydro.py` |
| `../rim2d/ken/nbo_2026/download_imerg_v1.py` | `download_imerg.py` |
| `../rim2d/ken/nbo_2026/download_river_network_v1.py` | `download_river_network.py` |
| `../rim2d/ken/nbo_2026/download_roads_v1.py` | `download_roads.py` |
| `../rim2d/ken/nbo_2026/setup_v1.py` (rasterize_overture_buildings) | `rasterize_buildings.py` |
| `../rim2d/ken/nbo_2026/setup_v1.py` (HND computation) | `compute_hand.py` |
| `../rim2d/ken/nbo_2026/setup_v1.py` (step2 + step4) | `prepare_rim2d_case.py` |
| `../wflow-jl/*/scripts/01_download_chirps_*.py` | `download_chirps.py` |
| `../wflow-jl/*/scripts/02_download_era5_*.py` | `download_era5.py` |
| `../wflow-jl/shared/derive_staticmaps.py` | `prepare_wflow_staticmaps.py` |
| `../wflow-jl/shared/fix_ldd_pyflwdir.py` | `fix_ldd_pyflwdir.py` |

---

## Environment

Matches the existing `zarrv3` / `hydromt-wflow` micromamba envs used by the
reference cases. See [`requirements.txt`](requirements.txt).

```bash
# GEE auth — set once
export GEE_SA_KEY=/path/to/earthengine-sa-key.json

# Run a script
micromamba run -n zarrv3 python download_dem.py --bbox ... --out ...
```
