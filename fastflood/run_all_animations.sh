#!/usr/bin/env bash
# Build a RIM2D-style animation + HF-ready package for all 11 FastFlood cases.
# Requires run_all_cases.sh to have run (dem.tif/man.tif + cached rain frames).
set -uo pipefail
FF=/home/sa_112625140081245282401/DevOps-hazard-modeling/fastflood
RUNS=/mnt/wflow-secondary/fastflood-data/case_runs
RAINROOT=/mnt/wflow-secondary/fastflood-data/rim2d_hf
PY="micromamba run -n aifs-etl python"
N=${1:-20}; MS=${2:-450}       # moments, ms/frame

# slug | start_iso | event_h | tz | title
CASES=(
 "nairobi_2026-03-06|2026-03-06T00:00|24|EAT|Nairobi flash flood  ·  FastFlood"
 "ssd_2025-10-05|2025-10-05T00:00|24|CAT|Upper Nile / Renk flood  ·  FastFlood"
 "dji_2019-11-21|2019-11-21T00:00|72|EAT|Djibouti City flash flood  ·  FastFlood"
 "eth_2021-08-16|2021-08-16T00:00|72|EAT|Addis Akaki river flood  ·  FastFlood"
 "som_2023-11-19|2023-11-19T00:00|72|EAT|Lower Shabelle flood  ·  FastFlood"
 "uga_2019-05-26|2019-05-26T00:00|72|EAT|Central Uganda flood  ·  FastFlood"
 "eri_2019-08-10|2019-08-10T00:00|120|EAT|Eritrea highlands flood  ·  FastFlood"
 "rwa_2023-05-01|2023-05-01T00:00|120|CAT|Rwanda W/N flood  ·  FastFlood"
 "nile_2024_abu_hamad|2024-08-25T00:00|144|CAT|Abu Hamad (Nile) flood  ·  FastFlood"
 "tza_2024-04-10|2024-04-10T00:00|168|EAT|Dar es Salaam flood  ·  FastFlood"
 "bdi_2024-04-01|2024-04-01T00:00|504|CAT|Burundi floods  ·  FastFlood"
)

for row in "${CASES[@]}"; do
  IFS='|' read slug start eh tz title <<< "$row"
  echo "======== ANIM $slug (dur=${eh}h, N=$N) ========"
  RUN="$RUNS/$slug"; RAIN="$RAINROOT/$slug/input/rain"; ANIM="$RUN/anim"
  [ -s "$RUN/dem.tif" ] || { echo "  no dem.tif, skip"; continue; }
  rm -rf "$ANIM"
  $PY "$FF/make_fastflood_animation.py" "$RUN" "$RAIN" "$ANIM" \
      "$title" "$start" "$eh" "$N" "$MS" "$tz" 2>&1 \
      | grep -viE "FutureWarning|warnings.warn|Glyph|glyph" \
      | grep -E "moment|wrote|fail|Error|Traceback" | tail -4
  # package into RIM2D-style HF layout + METHOD.md
  "$FF/package_fastflood_case.sh" "$slug" >/dev/null 2>&1
  PKG=/mnt/wflow-secondary/fastflood-data/hf_fastflood/$slug
  sed "s/{SLUG}/$slug/g" "$FF/hf_case_METHOD_template.md" > "$PKG/METHOD.md"
  echo "  packaged -> $PKG ($(du -sh "$PKG"|cut -f1))"
done
echo "======== ALL ANIMATIONS DONE ========"
