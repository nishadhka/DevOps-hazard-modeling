#!/bin/bash
#
# Wflow-Run Directory Reorganization - DRY RUN
# Shows what will be moved without actually moving anything
#

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================================="
echo "Wflow-Run Reorganization - DRY RUN"
echo "No files will be moved - this is a preview only"
echo "=================================================="
echo ""

# Function to show move operation
show_move() {
    if [ -e "$1" ]; then
        echo -e "${GREEN}git mv${NC} $1 ${BLUE}->${NC} $2"
    else
        echo -e "${YELLOW}[SKIP]${NC} $1 (not found)"
    fi
}

# Function to show directory creation
show_mkdir() {
    echo -e "${GREEN}mkdir -p${NC} $1"
}

echo "Step 1: Directory Creation"
echo "-------------------------"
show_mkdir "dr_bdi dr_dji dr_eri dr_eth dr_ken dr_rwa dr_som dr_ssd dr_sdn dr_tza dr_uga shared"
show_mkdir "dr_eri/docs shared/docs"
echo ""

echo "Step 2: Case Folders (bdi_trail2 -> country dirs)"
echo "-------------------------"
show_move "bdi_trail2/dr_case1" "dr_bdi/dr_case1"
show_move "bdi_trail1" "dr_bdi/exploration"
show_move "bdi_trail2/dr_case2" "dr_dji/dr_case2"
show_move "bdi_trail2/dr_case3" "dr_eri/dr_case3"
show_move "bdi_trail2/dr_case4" "dr_eth/dr_case4"
show_move "bdi_trail2/dr_case5" "dr_ken/dr_case5"
show_move "bdi_trail2/dr_case6" "dr_rwa/dr_case6"
show_move "bdi_trail2/dr_case10" "dr_tza/dr_case10"
show_move "bdi_trail2/dr_case11" "dr_uga/dr_case11"
echo ""

echo "Step 3: Download Folders & Workflows"
echo "-------------------------"
show_move "ethiopia_downloads" "dr_eth/downloads"
show_move "complete_ethiopia_workflow.sh" "dr_eth/complete_ethiopia_workflow.sh"
show_move "kenya_downloads" "dr_ken/downloads"
show_move "complete_kenya_workflow.sh" "dr_ken/complete_kenya_workflow.sh"
echo ""

echo "Step 4: Shared Resources"
echo "-------------------------"
show_move "bdi_trail2/wflow_tutorial" "shared/wflow_tutorial"
show_move "bdi_trail2/wflow_datasets_1km" "shared/wflow_datasets_1km"
echo ""

echo "Step 5: Documentation Files"
echo "-------------------------"
show_move "bdi_trail2/CLAUDE.md" "shared/docs/CLAUDE.md"
show_move "bdi_trail2/README.md" "shared/docs/BDI_TRAIL2_README.md"
show_move "bdi_trail2/WFLOW_VERSION_TESTING_REPORT.md" "shared/docs/WFLOW_VERSION_TESTING_REPORT.md"
show_move "bdi_trail2/ERITREA_SIMULATION_STATUS.md" "dr_eri/docs/ERITREA_SIMULATION_STATUS.md"
show_move "bdi_trail2/TUTORIAL_VS_BURUNDI_COMPARISON.md" "shared/docs/TUTORIAL_VS_BURUNDI_COMPARISON.md"
echo ""

echo "Step 6: Root-Level Scripts & Configs"
echo "-------------------------"
show_move "bdi_trail2/derive_staticmaps.py" "shared/derive_staticmaps.py"
show_move "bdi_trail2/fix_ldd_pyflwdir.py" "shared/fix_ldd_pyflwdir.py"
show_move "bdi_trail2/resample_forcing.py" "shared/resample_forcing.py"
show_move "bdi_trail2/fix_eritrea_staticmaps.py" "dr_eri/fix_eritrea_staticmaps.py"
show_move "bdi_trail2/burundi_sbm.toml" "dr_bdi/burundi_sbm.toml"
show_move "bdi_trail2/eritrea_sbm.toml" "dr_eri/eritrea_sbm.toml"
echo ""

echo "Step 7: region_configs.py Updates"
echo "-------------------------"
echo -e "${BLUE}Will update paths:${NC}"
echo "  bdi_trail2/dr_case1  -> dr_bdi/dr_case1"
echo "  bdi_trail2/dr_case2  -> dr_dji/dr_case2"
echo "  bdi_trail2/dr_case3  -> dr_eri/dr_case3"
echo "  bdi_trail2/dr_case4  -> dr_eth/dr_case4"
echo "  bdi_trail2/dr_case5  -> dr_ken/dr_case5"
echo "  bdi_trail2/dr_case6  -> dr_rwa/dr_case6"
echo "  bdi_trail2/dr_case10 -> dr_tza/dr_case10"
echo "  bdi_trail2/dr_case11 -> dr_uga/dr_case11"
echo ""

echo "Step 8: New READMEs to be created"
echo "-------------------------"
echo -e "${GREEN}create${NC} dr_bdi/README.md"
echo -e "${GREEN}create${NC} dr_dji/README.md"
echo -e "${GREEN}create${NC} dr_eri/README.md"
echo -e "${GREEN}create${NC} dr_eth/README.md"
echo -e "${GREEN}create${NC} dr_ken/README.md"
echo -e "${GREEN}create${NC} dr_rwa/README.md"
echo -e "${GREEN}create${NC} dr_som/README.md (planned case)"
echo -e "${GREEN}create${NC} dr_ssd/README.md (planned case)"
echo -e "${GREEN}create${NC} dr_sdn/README.md (planned case)"
echo -e "${GREEN}create${NC} dr_tza/README.md"
echo -e "${GREEN}create${NC} dr_uga/README.md"
echo ""

echo "=================================================="
echo "Directory Structure After Reorganization:"
echo "=================================================="
cat << 'TREE'
wflow-run/
├── dr_bdi/          (Burundi - Case 1)
├── dr_dji/          (Djibouti - Case 2)
├── dr_eri/          (Eritrea - Case 3 - BLOCKED)
├── dr_eth/          (Ethiopia - Case 4)
├── dr_ken/          (Kenya - Case 5)
├── dr_rwa/          (Rwanda - Case 6 - Reference)
├── dr_som/          (Somalia - Case 7 - PLANNED)
├── dr_ssd/          (South Sudan - Case 8 - PLANNED)
├── dr_sdn/          (Sudan - Case 9 - PLANNED)
├── dr_tza/          (Tanzania - Case 10)
├── dr_uga/          (Uganda - Case 11)
├── shared/          (Common resources & docs)
├── README.md
└── region_configs.py
TREE

echo ""
echo "=================================================="
echo "To execute the actual reorganization, run:"
echo "  ./reorganize_wflow.sh"
echo "=================================================="
