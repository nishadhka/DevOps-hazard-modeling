#!/usr/bin/env bash
# Example: country-scale Wflow case (Burundi, 230 × 240 km, 2021-2022 drought).
#
# Expected downloads (estimate for this bbox):
#   DEM (MERIT 1 km) ........ ~20 MB
#   WorldCover @ 1 km ....... ~3 MB
#   MERIT Hydro (3 bands) ... ~150 MB  (elv, dir, upa @ 90 m)
#   SoilGrids (4 props) ..... ~250 MB  (sand, silt, clay, bdod @ 250 m)
#   CHIRPS (730 days) ....... ~3 GB   *** heaviest piece ***
#   ERA5 (730 days × 2) ..... ~30 MB
#
# Total: ~3.5 GB. CHIRPS download dominates — run with good bandwidth.
# Wflow itself runs in ~12 minutes on this grid.
#
# Skip buildings / roads — at 1 km Wflow only needs the landuse class,
# not vector footprints.

set -e

BBOX="28.83,-4.50,30.89,-2.29"
OUT="./runs/bdi"
START="2021-01-01"
END="2023-01-01"

cd "$(dirname "$0")/.."

echo "=== dry-run size preview ==="
python download_chirps.py --bbox "$BBOX" --out "$OUT" --start "$START" --end "$END" --dry-run
python download_soilgrids.py --bbox "$BBOX" --out "$OUT" --dry-run

echo "=== 1. Base grids at 1 km ==="
python download_dem.py         --bbox "$BBOX" --out "$OUT" --scale 1000 --target merit
# Copy merit_elv to dem.tif slot so subsequent scripts find it
cp "$OUT/tif/merit_elv_90m.tif" "$OUT/tif/dem.tif" 2>/dev/null || true
python download_worldcover.py  --bbox "$BBOX" --out "$OUT" --scale 1000 --no-ghsl
python download_merit_hydro.py --bbox "$BBOX" --out "$OUT" --bands elv,dir,upa
python download_soilgrids.py   --bbox "$BBOX" --out "$OUT" --depth

echo "=== 2. Forcing (CHIRPS + ERA5) ==="
python download_chirps.py --bbox "$BBOX" --out "$OUT" --start "$START" --end "$END"
python download_era5.py   --bbox "$BBOX" --out "$OUT" --start "$START" --end "$END"

echo "=== 3. Build staticmaps ==="
python prepare_wflow_staticmaps.py --bbox "$BBOX" --out "$OUT" \
                                    --start "$START" --end "$END" --write-toml
python fix_ldd_pyflwdir.py --staticmaps "$OUT/staticmaps.nc"

echo ""
echo "Done. Next: stack forcing into forcing.nc and run:"
echo "  cd $OUT && julia --project=. -e 'using Wflow; Wflow.run(\"config.toml\")'"
