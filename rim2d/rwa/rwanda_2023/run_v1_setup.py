#!/usr/bin/env python3
"""
RIM2D v1 setup — Rwanda National
=======================================================
Event:   2023-05-01 to 2023-05-06
Country: RWA
Bbox:    lon [29.75, 30.4]  lat [-2.3, -1.7]
Desc:    Seasonal floods, central Rwanda

Pipeline
--------
  Step 1: Download/clip MERIT DEM to domain
  Step 2: Download IMERG v7 rainfall for event period
  Step 3: Condition DEM (Nile/stream burns, depression fill)
  Step 4: Build inflowlocs from GEOGlows v2 river discharge
  Step 5: Write simulation_v1.def

Usage:
    micromamba run -n zarrv3 python run_v1_setup.py
    export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
    /data/rim2d/bin/RIM2D simulation_v1.def --def flex
"""

from pathlib import Path
import numpy as np

# ── Domain ───────────────────────────────────────────────────────────────────
CASE_DIR  = Path(__file__).parent
INPUT_DIR = CASE_DIR / "input"
OUT_DIR   = CASE_DIR / "output"
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

BBOX = {"lon_min": 29.75, "lat_min": -2.3,
         "lon_max": 30.4, "lat_max": -1.7}

EVENT_START = "2023-05-01"
EVENT_END   = "2023-05-06"

SIM_DUR   = 518_400   # 6 days in seconds — adjust to event duration
DT_OUTPUT = 21_600    # 6-hourly snapshots

# ── Step 1: DEM ───────────────────────────────────────────────────────────────
def download_dem():
    """Download and clip MERIT DEM (30 m) to domain bbox.
    Source: MERIT Hydro or Copernicus DEM GLO-30.
    Output: input/dem_v1.nc  (EPSG:32636 or local UTM zone)
    """
    # TODO: implement DEM download/clip
    # Suggested: use rioxarray or gdal_translate with bbox
    print("Step 1: DEM download — TODO")


# ── Step 2: Rainfall ─────────────────────────────────────────────────────────
def download_imerg():
    """Download IMERG v7 half-hourly rainfall for event period.
    Output: input/rain/imerg_v1_tNNN.nc  (one file per 30-min timestep)
    See: v11/download_geoglows_rivers.py for S3/Zarr access pattern.
    """
    # TODO: implement IMERG download (GPM IMERG Final v07 via NASA GES DISC)
    print("Step 2: IMERG download — TODO")


# ── Step 3: DEM conditioning ──────────────────────────────────────────────────
def condition_dem():
    """Apply stream burns and pysheds 2-pass depression fill.
    See nile_2024/v24/run_v24_setup.py for full reference implementation.
    Key steps:
      - Fix A: channel/floodplain burn (dem < thresh → target_elev)
      - Fix B: TDX-Hydro GeoJSON stream burns (4-connected Bresenham)
      - Fix C: KML-corrected channel burns if GeoJSON mispositioned
      - Fix F: pysheds fill_depressions + resolve_flats (float64)
    """
    # TODO: implement DEM conditioning
    print("Step 3: DEM conditioning — TODO")


# ── Step 4: Inflowlocs ────────────────────────────────────────────────────────
def build_inflowlocs():
    """Build fluvial boundary conditions from GEOGlows v2 discharge.
    See nile_2024/v11/download_geoglows_rivers.py for Zarr access.
    Output: input/inflowlocs_v1.txt
    """
    # TODO: query GEOGlows v2 for rivers intersecting domain bbox
    # TODO: convert discharge to WSE boundary condition
    print("Step 4: Inflowlocs — TODO")


# ── Step 5: Write def file ────────────────────────────────────────────────────
def write_def():
    """Write simulation_v1.def (RIM2D flex format)."""
    n_rain    = SIM_DUR // 1800
    out_times = " ".join(str(t) for t in range(DT_OUTPUT, SIM_DUR + 1, DT_OUTPUT))
    content = f"""# RIM2D v1 — {c["region"].replace("_"," ")}
# Event: {c["event"]}
# Country: {c["country"].upper()}

###### INPUT RASTERS ######
**DEM**
input/dem_v1.nc
**buildings**
input/buildings.nc
**IWD**
file
input/iwd.nc
**roughness**
file
input/roughness.nc
**pervious_surface**
input/pervious_surface.nc
**sealed_surface**
input/sealed_surface.nc
**sewershed**
input/sewershed.nc

###### BOUNDARIES ######
**fluvial_boundary**
input/inflowlocs_v1.txt

**pluvial_raster_nr**
{n_rain}
**pluvial_dt**
1800
**pluvial_start**
0
**pluvial_base_fn**
input/rain/imerg_v1_t

###### OUTPUT ######
**output_base_fn**
output/v1_
**out_cells**
input/outflowlocs.txt
**out_timing_nr**
{SIM_DUR // DT_OUTPUT}
**out_timing**
{out_times}

###### MODEL PARAMETERS ######
**dt**
1
**sim_dur**
{SIM_DUR}
**inf_rate**
0
**sewer_cap**
0
**sewer_threshold**
0.002
**alpha**
0.4
**theta**
0.8

###### FLAGS ######
**verbose**
.TRUE.
**routing**
.TRUE.
**superverbose**
.FALSE.
**neg_wd_corr**
.TRUE.
**sew_sub**
.FALSE.
none
**fluv_bound**
.TRUE.
input/fluvbound_mask_v1.nc
**full_out**
.FALSE.
**closed_boundaries**
.FALSE.
**sheetflow_roughness**
.TRUE.

# end
"""
    (CASE_DIR / "simulation_v1.def").write_text(content)
    print("  Saved: simulation_v1.def")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"RIM2D v1 setup — Rwanda National")
    print(f"  Bbox: {BBOX}")
    print(f"  Event: {EVENT_START} → {EVENT_END}")
    download_dem()
    download_imerg()
    condition_dem()
    build_inflowlocs()
    write_def()
    print("Setup skeleton complete — fill in TODO steps.")
