#!/bin/bash
#
# Wflow-Run Directory Reorganization Script
# Reorganizes drought case folders into country-based structure using ISO codes
# Uses git mv to preserve git history
#

set -e  # Exit on error

echo "=================================================="
echo "Wflow-Run Reorganization Script"
echo "Using 3-letter ISO country codes (dr_COUNTRYISO/)"
echo "=================================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# Check if we're in the right directory
if [ ! -f "region_configs.py" ]; then
    print_error "Error: region_configs.py not found. Are you in wflow-run directory?"
    exit 1
fi

print_status "Current directory: $(pwd)"
echo ""

# Step 1: Create new country directories
echo "Step 1: Creating country directories (ISO codes)..."
mkdir -p dr_bdi dr_dji dr_eri dr_eth dr_ken dr_rwa dr_som dr_ssd dr_sdn dr_tza dr_uga shared
mkdir -p dr_eri/docs shared/docs
print_status "Created 11 country directories + shared/"
echo ""

# Step 2: Move case folders from bdi_trail2 using git mv
echo "Step 2: Moving case folders (using git mv)..."

# Burundi (BDI) - Case 1
if [ -d "bdi_trail2/dr_case1" ]; then
    git mv bdi_trail2/dr_case1 dr_bdi/
    print_status "Moved dr_case1 -> dr_bdi/"
fi

if [ -d "bdi_trail1" ]; then
    git mv bdi_trail1 dr_bdi/exploration
    print_status "Moved bdi_trail1 -> dr_bdi/exploration/"
fi

# Djibouti (DJI) - Case 2
if [ -d "bdi_trail2/dr_case2" ]; then
    git mv bdi_trail2/dr_case2 dr_dji/
    print_status "Moved dr_case2 -> dr_dji/"
fi

# Eritrea (ERI) - Case 3
if [ -d "bdi_trail2/dr_case3" ]; then
    git mv bdi_trail2/dr_case3 dr_eri/
    print_status "Moved dr_case3 -> dr_eri/"
fi

# Ethiopia (ETH) - Case 4
if [ -d "bdi_trail2/dr_case4" ]; then
    git mv bdi_trail2/dr_case4 dr_eth/
    print_status "Moved dr_case4 -> dr_eth/"
fi

if [ -d "ethiopia_downloads" ]; then
    git mv ethiopia_downloads dr_eth/downloads
    print_status "Moved ethiopia_downloads -> dr_eth/downloads/"
fi

if [ -f "complete_ethiopia_workflow.sh" ]; then
    git mv complete_ethiopia_workflow.sh dr_eth/
    print_status "Moved complete_ethiopia_workflow.sh -> dr_eth/"
fi

# Kenya (KEN) - Case 5
if [ -d "bdi_trail2/dr_case5" ]; then
    git mv bdi_trail2/dr_case5 dr_ken/
    print_status "Moved dr_case5 -> dr_ken/"
fi

if [ -d "kenya_downloads" ]; then
    git mv kenya_downloads dr_ken/downloads
    print_status "Moved kenya_downloads -> dr_ken/downloads/"
fi

if [ -f "complete_kenya_workflow.sh" ]; then
    git mv complete_kenya_workflow.sh dr_ken/
    print_status "Moved complete_kenya_workflow.sh -> dr_ken/"
fi

# Rwanda (RWA) - Case 6
if [ -d "bdi_trail2/dr_case6" ]; then
    git mv bdi_trail2/dr_case6 dr_rwa/
    print_status "Moved dr_case6 -> dr_rwa/"
fi

# Tanzania (TZA) - Case 10
if [ -d "bdi_trail2/dr_case10" ]; then
    git mv bdi_trail2/dr_case10 dr_tza/
    print_status "Moved dr_case10 -> dr_tza/"
fi

# Uganda (UGA) - Case 11
if [ -d "bdi_trail2/dr_case11" ]; then
    git mv bdi_trail2/dr_case11 dr_uga/
    print_status "Moved dr_case11 -> dr_uga/"
fi

echo ""

# Step 3: Move shared resources
echo "Step 3: Moving shared resources..."

if [ -d "bdi_trail2/wflow_tutorial" ]; then
    git mv bdi_trail2/wflow_tutorial shared/
    print_status "Moved wflow_tutorial -> shared/"
fi

if [ -d "bdi_trail2/wflow_datasets_1km" ]; then
    git mv bdi_trail2/wflow_datasets_1km shared/
    print_status "Moved wflow_datasets_1km -> shared/"
fi

echo ""

# Step 4: Move documentation files
echo "Step 4: Moving documentation files..."

if [ -f "bdi_trail2/CLAUDE.md" ]; then
    git mv bdi_trail2/CLAUDE.md shared/docs/
    print_status "Moved CLAUDE.md -> shared/docs/"
fi

if [ -f "bdi_trail2/README.md" ]; then
    git mv bdi_trail2/README.md shared/docs/BDI_TRAIL2_README.md
    print_status "Moved bdi_trail2/README.md -> shared/docs/BDI_TRAIL2_README.md"
fi

if [ -f "bdi_trail2/WFLOW_VERSION_TESTING_REPORT.md" ]; then
    git mv bdi_trail2/WFLOW_VERSION_TESTING_REPORT.md shared/docs/
    print_status "Moved WFLOW_VERSION_TESTING_REPORT.md -> shared/docs/"
fi

if [ -f "bdi_trail2/ERITREA_SIMULATION_STATUS.md" ]; then
    git mv bdi_trail2/ERITREA_SIMULATION_STATUS.md dr_eri/docs/
    print_status "Moved ERITREA_SIMULATION_STATUS.md -> dr_eri/docs/"
fi

if [ -f "bdi_trail2/TUTORIAL_VS_BURUNDI_COMPARISON.md" ]; then
    git mv bdi_trail2/TUTORIAL_VS_BURUNDI_COMPARISON.md shared/docs/
    print_status "Moved TUTORIAL_VS_BURUNDI_COMPARISON.md -> shared/docs/"
fi

# Move any other root-level scripts from bdi_trail2
if [ -f "bdi_trail2/derive_staticmaps.py" ]; then
    git mv bdi_trail2/derive_staticmaps.py shared/
    print_status "Moved derive_staticmaps.py -> shared/"
fi

if [ -f "bdi_trail2/fix_ldd_pyflwdir.py" ]; then
    git mv bdi_trail2/fix_ldd_pyflwdir.py shared/
    print_status "Moved fix_ldd_pyflwdir.py -> shared/"
fi

if [ -f "bdi_trail2/resample_forcing.py" ]; then
    git mv bdi_trail2/resample_forcing.py shared/
    print_status "Moved resample_forcing.py -> shared/"
fi

if [ -f "bdi_trail2/fix_eritrea_staticmaps.py" ]; then
    git mv bdi_trail2/fix_eritrea_staticmaps.py dr_eri/
    print_status "Moved fix_eritrea_staticmaps.py -> dr_eri/"
fi

# Move any TOML configs at root level
if [ -f "bdi_trail2/burundi_sbm.toml" ]; then
    git mv bdi_trail2/burundi_sbm.toml dr_bdi/
    print_status "Moved burundi_sbm.toml -> dr_bdi/"
fi

if [ -f "bdi_trail2/eritrea_sbm.toml" ]; then
    git mv bdi_trail2/eritrea_sbm.toml dr_eri/
    print_status "Moved eritrea_sbm.toml -> dr_eri/"
fi

echo ""

# Step 5: Check if bdi_trail2 is empty (except .git artifacts)
echo "Step 5: Checking bdi_trail2 status..."
if [ -d "bdi_trail2" ]; then
    remaining=$(find bdi_trail2 -type f ! -path "*/.*" 2>/dev/null | wc -l)
    if [ "$remaining" -eq 0 ]; then
        print_status "bdi_trail2 is empty, removing directory"
        rmdir bdi_trail2 2>/dev/null || print_warning "Could not remove bdi_trail2 (may have hidden files)"
    else
        print_warning "bdi_trail2 still contains $remaining files - please review manually"
        echo "Contents:"
        find bdi_trail2 -type f ! -path "*/.*" 2>/dev/null | head -10
    fi
fi
echo ""

# Step 6: Update region_configs.py
echo "Step 6: Updating region_configs.py case_folder paths..."

# Backup original
cp region_configs.py region_configs.py.backup
print_status "Created backup: region_configs.py.backup"

# Update paths using sed
sed -i 's|"case_folder": "bdi_trail2/dr_case1"|"case_folder": "dr_bdi/dr_case1"|g' region_configs.py
sed -i 's|"case_folder": "bdi_trail2/dr_case2"|"case_folder": "dr_dji/dr_case2"|g' region_configs.py
sed -i 's|"case_folder": "bdi_trail2/dr_case3"|"case_folder": "dr_eri/dr_case3"|g' region_configs.py
sed -i 's|"case_folder": "bdi_trail2/dr_case4"|"case_folder": "dr_eth/dr_case4"|g' region_configs.py
sed -i 's|"case_folder": "bdi_trail2/dr_case5"|"case_folder": "dr_ken/dr_case5"|g' region_configs.py
sed -i 's|"case_folder": "bdi_trail2/dr_case6"|"case_folder": "dr_rwa/dr_case6"|g' region_configs.py
sed -i 's|"case_folder": "bdi_trail2/dr_case10"|"case_folder": "dr_tza/dr_case10"|g' region_configs.py
sed -i 's|"case_folder": "bdi_trail2/dr_case11"|"case_folder": "dr_uga/dr_case11"|g' region_configs.py

print_status "Updated all case_folder paths in region_configs.py"
echo ""

# Step 7: Create placeholder READMEs for planned cases
echo "Step 7: Creating placeholder READMEs for planned cases..."

cat > dr_som/README.md << 'EOF'
# Drought Risk Case - Somalia (SOM)

**Status**: PLANNED

## Overview
- **Country ISO**: SOM
- **Region**: South-Central Somalia
- **Drought Period**: 2020-2023
- **Impact**: 2.48M affected, 1.2M displaced (Deyr drought)

## Case Details
- Multi-season rainfall failure
- Case 7 of 11 East Africa drought simulations

## Next Steps
1. Define exact bounding box
2. Download forcing data (CHIRPS + ERA5)
3. Prepare staticmaps
4. Configure Wflow SBM model
5. Run simulation

See `region_configs.py` for full configuration details.
EOF

cat > dr_ssd/README.md << 'EOF'
# Drought Risk Case - South Sudan (SSD)

**Status**: PLANNED

## Overview
- **Country ISO**: SSD
- **Region**: Upper Nile
- **Drought Period**: 2021-2023
- **Impact**: 1.4M affected (drought-flood compound events)

## Case Details
- Drought-flood compound crisis in Upper Nile region
- Case 8 of 11 East Africa drought simulations

## Next Steps
1. Define exact bounding box
2. Download forcing data (CHIRPS + ERA5)
3. Prepare staticmaps
4. Configure Wflow SBM model
5. Run simulation

See `region_configs.py` for full configuration details.
EOF

cat > dr_sdn/README.md << 'EOF'
# Drought Risk Case - Sudan (SDN)

**Status**: PLANNED

## Overview
- **Country ISO**: SDN
- **Region**: Eastern States (Kassala, Gedaref, Sennar)
- **Drought Period**: 2021-2023
- **Impact**: Drought-conflict compound crisis

## Case Details
- Drought and conflict compounding food insecurity
- Case 9 of 11 East Africa drought simulations

## Next Steps
1. Define exact bounding box
2. Download forcing data (CHIRPS + ERA5)
3. Prepare staticmaps
4. Configure Wflow SBM model
5. Run simulation

See `region_configs.py` for full configuration details.
EOF

print_status "Created READMEs for dr_som, dr_ssd, dr_sdn"
echo ""

# Step 8: Create country-level READMEs for completed cases
echo "Step 8: Creating country-level READMEs..."

# Burundi (BDI)
cat > dr_bdi/README.md << 'EOF'
# Drought Risk Case - Burundi (BDI)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case1
- **Region**: Ruzizi River Basin
- **Drought Period**: 2021-2022 (730 days)
- **Grid Size**: 245 x 212 cells (~35,000 active)
- **Impact**: Drought impact on Ruzizi basin

## Key Findings
- **22 consecutive days of zero recharge** during mid-2021 drought
- Discharge near-zero Jun-Aug 2021 (range: 2.35-1,932 m³/s)
- Recharge: 0.13-3.28 mm/day

## Simulation Details
- **Runtime**: ~12.5 minutes
- **Outlet**: Ruzizi River (29.23°E, 4.50°S), ~5,000 km² upstream
- **Role**: First successful Wflow.jl v1.0.1 simulation; baseline for all cases

## Directory Structure
- `dr_case1/` - Main case simulation
- `exploration/` - Initial HydroMT experiments (bdi_trail1)

## Quick Links
- Simulation: `dr_case1/case_sbm.toml`
- Scripts: `dr_case1/scripts/`
- Output: `dr_case1/data/output/`
EOF

# Djibouti (DJI)
cat > dr_dji/README.md << 'EOF'
# Drought Risk Case - Djibouti (DJI)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case2
- **Drought Period**: 2021-2023 (1,095 days)
- **Grid Size**: 201 x 224 cells (39,708 active)
- **Impact**: 194,000 people food insecure (Oct 2022), 6.1% inflation

## Key Findings
- Discharge: 0.46-15.30 m³/s
- Soil moisture L1: 0.023-0.101

## Simulation Details
- **Runtime**: ~6 minutes
- **Outlet**: Coastal outlet (41.60°E, 11.20°N), ~6,316 km² upstream

## Technical Fixes Applied
- Brooks-Corey 4-layer workaround
- LDD cycle resolution
- 518 cells with thetaS=0 corrected
- 6-9% forcing NaN values filled

## Quick Links
- Simulation: `dr_case2/djibouti_sbm.toml`
- Scripts: `dr_case2/scripts/`
- Output: `dr_case2/data/output/`
EOF

# Eritrea (ERI)
cat > dr_eri/README.md << 'EOF'
# Drought Risk Case - Eritrea (ERI)

**Status**: 🚫 BLOCKED

## Overview
- **Case Number**: dr_case3
- **Drought Period**: 2021-2023
- **Grid Size**: 628 x 758 cells (312,179 active) - **Largest domain** (6x Burundi)
- **Impact**: Assessment pending simulation completion

## Current Status
⚠️ Simulation fails at first timestep with:
```
BoundsError: attempt to access NTuple{4, Float64} at index [0]
```

## Data Readiness
- ✅ 95% complete
- ✅ Staticmaps (104 MB) validated
- ✅ Forcing (793 MB) prepared
- ✅ Configuration files ready

## Troubleshooting History
11+ fixes attempted (all unsuccessful):
- LDD dtype fix
- LDD cycle resolution
- 40-variable verification
- 3-layer soil config
- 4-layer Brooks-Corey workaround
- thetaS validation (875 cells)
- RootingDepth zeros (3,447 cells)
- Minimum slope enforcement
- Snow disabled
- Single thread mode

## Root Cause Hypothesis
Layer index calculation in Wflow returns 0; possibly:
- kv scaling issue (48-255 vs expected 0.07-0.25)
- Water table depth calculation anomaly

## Next Steps
1. Deep comparison with Djibouti staticmaps
2. Subset domain test
3. File Wflow bug report with minimal reproducible example

## Quick Links
- Documentation: `docs/ERITREA_SIMULATION_STATUS.md`
- Simulation configs (5 variants): `dr_case3/*.toml`
- Scripts: `dr_case3/scripts/`
EOF

# Ethiopia (ETH)
cat > dr_eth/README.md << 'EOF'
# Drought Risk Case - Ethiopia (ETH)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case4
- **Region**: Blue Nile Headwaters
- **Drought Period**: 2020-2023 (1,429 days)
- **Grid Size**: 1,671 x 1,351 cells - **Largest staticmaps** (4.4 GB)
- **Impact**: 24.1M in drought areas, 4.5M livestock deaths

## Key Findings
- Discharge: 0-53,612 m³/s (mean: 8,273)
- Recharge: 0-4.65 mm/day

## Simulation Details
- **Runtime**: ~18 hours total (3 segments due to interruptions)
  - Part 1: 2020-01-02 to 2021-10-03 (641 days)
  - Part 2: 2021-10-05 to 2022-07-11 (280 days)
  - Part 3: 2022-07-13 to 2023-11-30 (506 days)
- **Post-processing**: Segments merged with `combine_ethiopia_output.py`
- **Outlet**: Blue Nile headwaters (33.15°E, 15.12°N)

## Directory Structure
- `dr_case4/` - Main case simulation
- `downloads/` - CHIRPS/ERA5 forcing data pipeline
- `complete_ethiopia_workflow.sh` - End-to-end orchestration

## Scripts (16 total)
- Download, forcing prep, resampling (multiple approaches), output merging

## Quick Links
- Workflow: `complete_ethiopia_workflow.sh`
- Simulation: `dr_case4/ethiopia_sbm.toml`
- Scripts: `dr_case4/scripts/`
- Downloads: `downloads/`
EOF

# Kenya (KEN)
cat > dr_ken/README.md << 'EOF'
# Drought Risk Case - Kenya (KEN)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case5
- **Region**: Tana River Basin / ASAL regions
- **Drought Period**: 2020-2023 (1,429 days)
- **Grid Size**: 1,083 x 881 cells (954,123 active) - **Largest active cell count**
- **Impact**: 4.5M food shortage, 222K children malnourished

## Key Findings
- Discharge: 0-119.31 m³/s (mean: 5.14)
- Recharge: 0-8.50 mm/day

## Simulation Details
- **Runtime**: ~4.5 hours
- **Outlet**: Tana River (41.90°E, 0.66°N), 166,337 km² upstream

## Technical Fixes Applied
- LDD cycles (67,748 → 64,553 pit cells)
- 64,068 negative upstream area cells corrected
- 159,929 missing N_River cells filled

## Directory Structure
- `dr_case5/` - Main case simulation
- `downloads/` - CHIRPS/ERA5 forcing data pipeline
- `complete_kenya_workflow.sh` - End-to-end orchestration

## Quick Links
- Workflow: `complete_kenya_workflow.sh`
- Simulation: `dr_case5/kenya_sbm.toml`
- Scripts: `dr_case5/scripts/`
- Downloads: `downloads/`
EOF

# Rwanda (RWA)
cat > dr_rwa/README.md << 'EOF'
# Drought Risk Case - Rwanda (RWA)

**Status**: ✅ COMPLETE ⭐ **Reference Template**

## Overview
- **Case Number**: dr_case6
- **Region**: Akagera River Basin
- **Drought Period**: 2016-2017 (730 days)
- **Grid Size**: 212 x 234 cells (49,608 total)
- **Impact**: 250,000 people affected by food shortages (eastern province)

## Key Role
🌟 **First successful 4-layer Brooks-Corey workaround**
This case became the **reference template** for all subsequent simulations.

## Simulation Details
- **Runtime**: 25 min 17 sec
- **Outlet**: Akagera River (30.90°E, 2.08°S), 19,039 km² upstream

## Technical Fixes Applied
- LDD cycles (888 → 109 pit cells)
- 7,409 missing N_River values filled
- Grid mismatch resolved (forcing 38x42 @ 5km → 212x234 @ 1km)

## Quick Links
- Simulation: `dr_case6/case_sbm.toml`
- Scripts: `dr_case6/scripts/`
- Documentation: `dr_case6/Rwanda_simulation.md`
EOF

# Tanzania (TZA)
cat > dr_tza/README.md << 'EOF'
# Drought Risk Case - Tanzania (TZA)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case10
- **Region**: Kagera River Basin to Lake Victoria
- **Drought Period**: 2022-2023 (730 days)
- **Grid Size**: 1,198 x 1,248 cells (1,495,104 total)
- **Staticmaps Size**: 3.062 GB
- **Impact**: 2.2M affected, 70% crop failure (northern regions)

## Simulation Details
- **Outlet**: Kagera River (29.30°E, 3.36°S), 292,488 km² upstream

## Technical Fixes Applied
- 339,261 river cells identified
- 268,269 missing N_River filled
- 94,866 cycle-free pit cells

## Quick Links
- Simulation: `dr_case10/case_sbm.toml`
- Scripts: `dr_case10/scripts/`
- Documentation: `dr_case10/Tanzania_simulation.md`
EOF

# Uganda (UGA)
cat > dr_uga/README.md << 'EOF'
# Drought Risk Case - Uganda (UGA)

**Status**: ✅ COMPLETE

## Overview
- **Case Number**: dr_case11
- **Region**: Karamoja Subregion
- **Drought Period**: 2021-2022 (730 days)
- **Grid Size**: 313 x 235 cells (73,555 total)
- **Impact**: 518K emergency conditions, 900+ hunger deaths

## Simulation Details
- **Runtime**: ~2 hours
- **Outlet**: NW boundary outlet (32.80°E, 1.52°N), 34,773 km² upstream

## Technical Fixes Applied
- LDD cycles (1,092 → 118 pit cells)
- LDD uint8 conversion

## Quick Links
- Simulation: `dr_case11/case_sbm.toml`
- Scripts: `dr_case11/scripts/`
- Documentation: `dr_case11/Uganda_simulation.md`
EOF

print_status "Created country-level READMEs for all 8 completed cases + 3 planned"
echo ""

# Step 9: Git status check
echo "Step 9: Checking git status..."
echo ""
git status --short
echo ""

print_status "Migration complete!"
echo ""
echo "=================================================="
echo "Summary:"
echo "=================================================="
echo "✓ Created 11 country directories (dr_<ISO>/)"
echo "✓ Moved all case folders using git mv"
echo "✓ Moved shared resources to shared/"
echo "✓ Moved documentation files"
echo "✓ Updated region_configs.py paths"
echo "✓ Created country-level READMEs"
echo ""
echo "Next steps:"
echo "1. Review git status above"
echo "2. Test: python region_configs.py (verify paths)"
echo "3. Commit changes: git add -A && git commit -m 'Reorganize into country-based structure (ISO codes)'"
echo ""
echo "Backup created: region_configs.py.backup"
echo "=================================================="
