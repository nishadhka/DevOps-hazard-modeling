#!/usr/bin/env bash
# Run a FastFlood pluvial simulation for one RIM2D case study.
#
# FastFlood needs only a DEM + rainfall (unlike RIM2D which needs DEM, manning,
# buildings, IMERG time-series and river hydrographs on a GPU). FastFlood
# auto-downloads its own Copernicus GLO-30 DEM for the case bounding box, so the
# RIM2D HuggingFace/compute-server inputs are NOT required for a first-pass run.
#
# Usage:
#   ./run_fastflood_case.sh <case> <lon0> <lat0> <lon1> <lat1> [rain_mm] [dur_h]
# Example (Kenya / Nairobi, from rim2d/ken/kenya_nairobi_2024/README.md):
#   ./run_fastflood_case.sh ken_nairobi 36.6 -1.402 37.1 -1.098 100 24
#
# Case extents (WGS84 lon0 lat0 lon1 lat1) from each rim2d/<c>/README.md:
#   bdi_burundi     29.2  -3.55  29.5  -3.15
#   dji_djibouti    42.5  11.4   43.3  11.8
#   eri_highlands   38.88 15.25  39.05 15.4
#   eth_akaki       38.6   8.8   38.9   9.1
#   ken_nairobi     36.6  -1.402 37.1  -1.098
#   rwa_rwanda      29.75 -2.3   30.4  -1.7
#   sdn_khartoum    32.2  15.3   32.8  15.9
#   som_south       45.15  1.9   45.45  2.2
#   ssd_upper_nile  31.45  4.7   31.75  5.0
#   tza_dar         39.05 -7.05  39.45 -6.6
#   uga_kampala     (see rim2d/uga/uganda_2019/README.md)
set -euo pipefail

CASE=${1:?case name}; LON0=${2:?lon0}; LAT0=${3:?lat0}; LON1=${4:?lon1}; LAT1=${5:?lat1}
RAIN=${6:-100}; DUR=${7:-24}

FF_ROOT=/home/sa_112625140081245282401/DevOps-hazard-modeling/fastflood
CLI="$FF_ROOT/fastflood_cli_icpac/cli"
OUT=/mnt/wflow-secondary/fastflood-data/case_runs/$CASE
export WINEPREFIX=/mnt/wflow-secondary/fastflood-data/.wineprefix
export WINEDEBUG=-all
set -a; . "$FF_ROOT/.env"; set +a
mkdir -p "$OUT"; cd "$CLI"

# WGS84 bbox -> EPSG:3857 metres, emitted in NW-then-SE corner order
# (xmin ymax xmax ymin) which is the order FastFlood's -d_dem expects.
read X0 Y1 X1 Y0 < <(python3 -c "
import math
R=20037508.34
x=lambda lon: lon*R/180.0
y=lambda lat: math.log(math.tan((90+lat)*math.pi/360.0))/(math.pi/180.0)*R/180.0
print(f'{x(min($LON0,$LON1)):.3f} {y(max($LAT0,$LAT1)):.3f} {x(max($LON0,$LON1)):.3f} {y(min($LAT0,$LAT1)):.3f}')
")

echo "[$CASE] DEM download (cop30, 20m tiles)  bbox_merc: $X0 $Y1 $X1 $Y0"
wine fastflood.exe -key "$FASTFLOOD_KEY" -d_dem cop30 20m "$X0" "$Y1" "$X1" "$Y0" \
  -dout "$OUT/${CASE}_dem.tif" 2>&1 | grep -iE "Model domain|Done$|Duration|error" || true

echo "[$CASE] flood sim  rain=${RAIN}mm dur=${DUR}h  (pluvial, uniform, no infiltration)"
wine fastflood.exe -key "$FASTFLOOD_KEY" -dem "$OUT/${CASE}_dem.tif" -sim \
  -rain "$RAIN" -dur "$DUR" -whout "$OUT/${CASE}_flood_wh.tif" 2>&1 \
  | grep -iE "Model domain|Done$|Duration|error" || true

echo "[$CASE] outputs in $OUT :"
ls -la "$OUT"
