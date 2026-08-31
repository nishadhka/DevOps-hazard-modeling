#!/usr/bin/env bash
# Batch: for each of the 11 RIM2D cases on HF E4DRR/rim2d-simulations, pull the
# real inputs (DEM, roughness, pervious, IMERG rain frames), convert to fastflood
# GeoTIFFs, run a fastflood pluvial sim with the real event rain, and compare the
# max-depth envelope against the RIM2D reference output.
#
# Cases processed smallest-event first. Rain frames downloaded by index (robust
# to the HF tree API's 1000-item page cap). Results appended to results.csv.
set -uo pipefail

FF_ROOT=/home/sa_112625140081245282401/DevOps-hazard-modeling/fastflood
CLI="$FF_ROOT/fastflood_cli_icpac/cli"
HF=/mnt/wflow-secondary/fastflood-data/rim2d_hf
RUNS=/mnt/wflow-secondary/fastflood-data/case_runs
BASE="https://huggingface.co/datasets/E4DRR/rim2d-simulations/resolve/main"
CSV="$RUNS/results.csv"
export WINEPREFIX=/mnt/wflow-secondary/fastflood-data/.wineprefix WINEDEBUG=-all
set -a; . "$FF_ROOT/.env"; set +a
PY="micromamba run -n aifs-etl python"
mkdir -p "$RUNS"
[ -f "$CSV" ] || echo "case,epsg,frames,dur_h,ff_max_m,ff_wet_km2,ff_wet_pct,rim2d_max_m,rim2d_wet_km2,rim2d_wet_pct" > "$CSV"

# slug  centroid_lon  centroid_lat  n_frames  (smallest first)
CASES=(
 "nairobi_2026-03-06 36.85 -1.25 48"
 "ssd_2025-10-05 31.6 4.85 48"
 "dji_2019-11-21 42.9 11.6 144"
 "eth_2021-08-16 38.75 8.95 144"
 "som_2023-11-19 45.3 2.05 144"
 "uga_2019-05-26 32.5 0.35 144"
 "eri_2019-08-10 38.965 15.325 240"
 "rwa_2023-05-01 30.075 -2.0 240"
 "nile_2024_abu_hamad 33.3 19.5 288"
 "tza_2024-04-10 39.25 -6.825 336"
 "bdi_2024-04-01 29.35 -3.35 1008"
)

for entry in "${CASES[@]}"; do
  read slug lon lat n <<< "$entry"
  echo "======== $slug (lon=$lon lat=$lat frames=$n) ========"
  IN="$HF/$slug/input"; OUT="$RUNS/$slug"; mkdir -p "$IN/rain" "$OUT"

  # 1. static inputs
  for f in dem.nc roughness.nc pervious_surface.nc; do
    [ -s "$IN/$f" ] || curl -sL "$BASE/$slug/input/$f" -o "$IN/$f"
  done
  # 2. rain frames by index (skip already-present)
  echo "  downloading $n rain frames..."
  seq 1 "$n" | xargs -P 10 -I {} sh -c '
    o="'"$IN"'/rain/imerg_t{}.nc"
    [ -s "$o" ] || curl -sL "'"$BASE/$slug"'/input/rain/imerg_t{}.nc" -o "$o"'
  got=$(ls "$IN"/rain/imerg_t*.nc 2>/dev/null | wc -l)
  echo "  rain frames present: $got"

  # 3. convert -> geotiffs
  DUR=$($PY "$FF_ROOT/rim2d_nc_to_fastflood.py" "$IN" "$OUT" "$lon" "$lat" 12 2>/dev/null | grep DUR_H | cut -d= -f2)
  [ -z "$DUR" ] && { echo "  CONVERT FAILED, skipping"; continue; }
  echo "  converted; duration=${DUR}h"

  # 4. fastflood run (DEM + manning + real spatial rain)
  ( cd "$CLI" && timeout 900 wine fastflood.exe -key "$FASTFLOOD_KEY" \
      -dem "$OUT/dem.tif" -sim -man "$OUT/man.tif" -rain "$OUT/rain_mmhr.tif" \
      -dur "$DUR" -whout "$OUT/${slug}_ff_wh.tif" 2>&1 | grep -iE "Duration:|error" | tail -2 )
  [ -s "$OUT/${slug}_ff_wh.tif" ] || { echo "  FASTFLOOD FAILED, skipping"; continue; }

  # 5. RIM2D reference
  curl -sL "$BASE/$slug/output/case_v1_wd_max.nc" -o "$OUT/rim2d_wd_max.nc" 2>/dev/null

  # 6. compare + append CSV
  EPSG=$($PY -c "lon,lat=$lon,$lat; z=int((lon+180)/6)+1; print((32700 if lat<0 else 32600)+z)")
  $PY - "$OUT" "$slug" "$EPSG" "$n" "$DUR" "$CSV" <<'PYEOF'
import sys, numpy as np, rasterio, xarray as xr, os
OUT,slug,epsg,n,dur,csv=sys.argv[1:7]
cell=0.03*0.03
def st(a):
    a=a[np.isfinite(a)]; w=(a>0.05).sum()
    return a.max(), w*cell, 100*w/a.size
with rasterio.open(f"{OUT}/{slug}_ff_wh.tif") as s: fmx,fkm,fp=st(s.read(1).astype("float64"))
rmx=rkm=rp=float("nan")
rp_path=f"{OUT}/rim2d_wd_max.nc"
if os.path.exists(rp_path) and os.path.getsize(rp_path)>1000:
    ds=xr.open_dataset(rp_path); v=list(ds.data_vars)[0]; rmx,rkm,rp=st(ds[v].values.astype("float64"))
with open(csv,"a") as fh:
    fh.write(f"{slug},{epsg},{n},{dur},{fmx:.2f},{fkm:.1f},{fp:.2f},{rmx:.2f},{rkm:.1f},{rp:.2f}\n")
print(f"  FF max={fmx:.2f}m wet={fkm:.0f}km2({fp:.1f}%) | RIM2D max={rmx:.2f}m wet={rkm:.0f}km2({rp:.1f}%)")
PYEOF
done
echo "======== ALL DONE ========"; column -t -s, "$CSV"
