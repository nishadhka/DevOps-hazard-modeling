#!/usr/bin/env bash
# Assemble a FastFlood case into a directory that mirrors the RIM2D HF case
# layout (E4DRR/rim2d-simulations), so the FastFlood method + inputs + outputs
# can be published to HuggingFace alongside the RIM2D cases.
#
#   <case>_fastflood/
#   ├── input/    dem.tif  roughness.tif  infiltration.tif  rain_mean_mmhr.tif
#   ├── output/   <case>_wd_max.tif   frames/wh_t*.tif   preview.gif
#   ├── run_command.txt         the exact FastFlood invocation (≈ RIM2D .def)
#   └── METHOD.md               how the maps were produced
#
# Usage: ./package_fastflood_case.sh <slug>
# (expects run_all_cases.sh + make_fastflood_animation.py to have been run)
set -euo pipefail
slug=${1:?case slug}
RUNS=/mnt/wflow-secondary/fastflood-data/case_runs
SRC="$RUNS/$slug"; ANIM="$SRC/anim"
PKG=/mnt/wflow-secondary/fastflood-data/hf_fastflood/$slug
mkdir -p "$PKG/input" "$PKG/output/frames"

# inputs (RIM2D-style names)
cp "$SRC/dem.tif"       "$PKG/input/dem.tif"
cp "$SRC/man.tif"       "$PKG/input/roughness.tif"
cp "$SRC/inf.tif"       "$PKG/input/infiltration.tif"
cp "$SRC/rain_mmhr.tif" "$PKG/input/rain_mean_mmhr.tif"

# outputs
cp "$SRC/${slug}_ff_wh.tif" "$PKG/output/${slug}_wd_max.tif"
[ -d "$ANIM/frames" ] && cp "$ANIM/frames"/wh_*.tif "$PKG/output/frames/" 2>/dev/null || true
[ -f "$ANIM/preview.gif" ] && cp "$ANIM/preview.gif" "$PKG/output/preview.gif"

# the FastFlood "definition" — the exact command line
cat > "$PKG/run_command.txt" <<EOF
# FastFlood v0.1 pluvial run for $slug (Windows CLI under Wine)
# max-depth envelope:
wine fastflood.exe -key \$FASTFLOOD_KEY -dem input/dem.tif -sim \\
    -man input/roughness.tif -rain input/rain_mean_mmhr.tif -dur <event_hours> \\
    -whout output/${slug}_wd_max.tif
# animation frames driven by the cumulative IMERG hyetograph:
#   see make_fastflood_animation.py
EOF

echo "packaged $slug -> $PKG"
du -sh "$PKG"; find "$PKG" -maxdepth 2 -type f | sed "s|$PKG/||" | sort | head -20
