#!/usr/bin/env bash
# Example: small urban RIM2D case (Nairobi, 55 × 34 km, March 2026 flood event).
#
# Expected downloads (estimate for this bbox):
#   DEM ............. ~4 MB     (Copernicus GLO-30)
#   WorldCover ...... ~1 MB     (raw classes + roughness)
#   GHSL ............ ~0.5 MB   (sealed + pervious at 100 m)
#   MERIT Hydro ..... ~7 MB     (4 bands @ 90 m)
#   Buildings ....... ~100 MB   (Overture, urban — the heavy one)
#   Roads ........... ~30 MB    (Overture segments)
#   TDX-Hydro ....... ~0.5 MB   (vector network)
#   IMERG ........... ~2 MB     (1 day × 48 timesteps)
#
# Total: ~150 MB. Run time (serial): ~5 min + Overture download time.

set -e

BBOX="36.60,-1.402,37.10,-1.098"
OUT="./runs/nbo"
START="2026-03-06"
END="2026-03-07"
SCALE=30
CRS="EPSG:32737"

cd "$(dirname "$0")/.."

echo "=== dry-run size preview ==="
python download_buildings.py --bbox "$BBOX" --out "$OUT" --dry-run
python download_imerg.py     --bbox "$BBOX" --out "$OUT" \
                             --start "$START" --end "$END" \
                             --scale "$SCALE" --crs "$CRS" --dry-run

echo "=== 1. Terrain + land cover ==="
python download_dem.py         --bbox "$BBOX" --out "$OUT" --scale "$SCALE" --crs "$CRS"
python download_worldcover.py  --bbox "$BBOX" --out "$OUT" --scale "$SCALE" --crs "$CRS"
python download_merit_hydro.py --bbox "$BBOX" --out "$OUT" --crs "$CRS"

echo "=== 2. Buildings (watch size!) ==="
python download_buildings.py --bbox "$BBOX" --out "$OUT"
python rasterize_buildings.py --out "$OUT" --mode fraction

echo "=== 3. Roads (optional) ==="
python download_roads.py --bbox "$BBOX" --out "$OUT"

echo "=== 4. River network ==="
python download_river_network.py --bbox "$BBOX" --out "$OUT"

echo "=== 5. Rainfall ==="
python download_imerg.py --bbox "$BBOX" --out "$OUT" \
                         --start "$START" --end "$END" \
                         --scale "$SCALE" --crs "$CRS"

echo "=== 6. Build RIM2D case ==="
python prepare_rim2d_case.py --bbox "$BBOX" --out "$OUT" \
                             --start "$START" --end "$END" \
                             --scale "$SCALE" --crs "$CRS" \
                             --version v1 --iwd worldcover

echo ""
echo "Done. Run:"
echo "  cd $OUT/v1"
echo "  ../../../rim2d/bin/RIM2D simulation_v1.def --def flex"
