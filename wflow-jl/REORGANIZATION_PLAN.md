# Wflow-Run Directory Reorganization Plan

## Goal
Reorganize the current structure to country-based folders (`dr_COUNTRYNAME/`) to better organize scripts, documentation, and the 11 drought simulation cases.

## Current Structure Issues
- All 11 cases buried inside `bdi_trail2/` folder
- Country-specific downloads scattered (`ethiopia_downloads/`, `kenya_downloads/`)
- Initial exploration (`bdi_trail1/`) separate from production (`bdi_trail2/`)
- Hard to find country-specific scripts and documentation

## Proposed New Structure

Using **3-letter ISO country codes** (from region_configs.py):

```
wflow-run/
├── README.md                           # Updated project overview
├── region_configs.py                   # Master configuration (11 cases)
├── complete_workflow_template.sh       # Generic workflow template
│
├── dr_bdi/                             # BURUNDI (BDI) - Case 1
│   ├── README.md                       # Country-specific overview
│   ├── dr_case1/                       # From: bdi_trail2/dr_case1
│   │   ├── case_sbm.toml
│   │   ├── scripts/
│   │   └── data/
│   ├── exploration/                    # From: bdi_trail1 (historical)
│   │   ├── download_all_datasets.sh
│   │   ├── wflow_build_*.yml
│   │   └── burundi_*/
│   └── docs/
│       └── SIMULATION_NOTES.md
│
├── dr_dji/                             # DJIBOUTI (DJI) - Case 2
│   ├── README.md
│   ├── dr_case2/                       # From: bdi_trail2/dr_case2
│   │   ├── djibouti_sbm.toml
│   │   ├── scripts/
│   │   └── data/
│   └── docs/
│
├── dr_eri/                             # ERITREA (ERI) - Case 3 (BLOCKED)
│   ├── README.md
│   ├── dr_case3/                       # From: bdi_trail2/dr_case3
│   │   ├── case_sbm.toml
│   │   ├── scripts/
│   │   └── data/
│   └── docs/
│       ├── ERITREA_SIMULATION_STATUS.md
│       └── Eritrea_simulation.md
│
├── dr_eth/                             # ETHIOPIA (ETH) - Case 4
│   ├── README.md
│   ├── complete_ethiopia_workflow.sh   # From: root level
│   ├── dr_case4/                       # From: bdi_trail2/dr_case4
│   │   ├── ethiopia_sbm.toml
│   │   ├── scripts/
│   │   └── data/
│   ├── downloads/                      # From: ethiopia_downloads
│   │   ├── 01_download_chirps.py
│   │   ├── 03_prepare_forcing.py
│   │   └── data/
│   └── docs/
│
├── dr_ken/                             # KENYA (KEN) - Case 5
│   ├── README.md
│   ├── complete_kenya_workflow.sh      # From: root level
│   ├── dr_case5/                       # From: bdi_trail2/dr_case5
│   │   ├── kenya_sbm.toml
│   │   ├── scripts/
│   │   └── data/
│   ├── downloads/                      # From: kenya_downloads
│   │   ├── 01_download_chirps.py
│   │   ├── 03_prepare_forcing.py
│   │   └── data/
│   └── docs/
│
├── dr_rwa/                             # RWANDA (RWA) - Case 6 (Reference Template)
│   ├── README.md
│   ├── dr_case6/                       # From: bdi_trail2/dr_case6
│   │   ├── case_sbm.toml
│   │   ├── scripts/
│   │   └── data/
│   └── docs/
│       └── Rwanda_simulation.md
│
├── dr_som/                             # SOMALIA (SOM) - Case 7 (PLANNED)
│   ├── README.md
│   └── docs/
│       └── PLANNING_NOTES.md
│
├── dr_ssd/                             # SOUTH SUDAN (SSD) - Case 8 (PLANNED)
│   ├── README.md
│   └── docs/
│       └── PLANNING_NOTES.md
│
├── dr_sdn/                             # SUDAN (SDN) - Case 9 (PLANNED)
│   ├── README.md
│   └── docs/
│       └── PLANNING_NOTES.md
│
├── dr_tza/                             # TANZANIA (TZA) - Case 10
│   ├── README.md
│   ├── dr_case10/                      # From: bdi_trail2/dr_case10
│   │   ├── case_sbm.toml
│   │   ├── scripts/
│   │   └── data/
│   └── docs/
│       └── Tanzania_simulation.md
│
├── dr_uga/                             # UGANDA (UGA) - Case 11
│   ├── README.md
│   ├── dr_case11/                      # From: bdi_trail2/dr_case11
│   │   ├── case_sbm.toml
│   │   ├── scripts/
│   │   └── data/
│   └── docs/
│       └── Uganda_simulation.md
│
└── shared/                             # Shared resources
    ├── wflow_tutorial/                 # From: bdi_trail2/wflow_tutorial
    │   ├── sbm_config.toml
    │   └── data/
    ├── wflow_datasets_1km/             # From: bdi_trail2/wflow_datasets_1km
    │   └── download_summary.json
    └── templates/
        ├── derive_staticmaps_template.py
        ├── fix_ldd_pyflwdir_template.py
        └── sbm_config_template.toml
```

## Benefits of New Structure

1. **Country-centric organization**: Easy to find all materials for a specific country
2. **Clear case numbering**: Each country folder contains its dr_case* subfolder
3. **Consolidated downloads**: Country-specific download folders alongside case folders
4. **Documentation co-located**: Country-specific docs with relevant cases
5. **Scalability**: Easy to add 3 planned cases (Somalia, South Sudan, Sudan)
6. **Historical preservation**: `dr_burundi/exploration/` keeps initial work
7. **Shared resources**: Common utilities and reference data in `shared/`

## Migration Steps

### Step 1: Create new country directories (using ISO codes)
```bash
mkdir -p dr_bdi dr_dji dr_eri dr_eth dr_ken dr_rwa dr_som dr_ssd dr_sdn dr_tza dr_uga shared
```

### Step 2: Move case folders from bdi_trail2
```bash
# Burundi (BDI)
mv bdi_trail2/dr_case1 dr_bdi/
mv bdi_trail1 dr_bdi/exploration

# Djibouti (DJI)
mv bdi_trail2/dr_case2 dr_dji/

# Eritrea (ERI)
mv bdi_trail2/dr_case3 dr_eri/

# Ethiopia (ETH)
mv bdi_trail2/dr_case4 dr_eth/
mv ethiopia_downloads dr_eth/downloads
mv complete_ethiopia_workflow.sh dr_eth/

# Kenya (KEN)
mv bdi_trail2/dr_case5 dr_ken/
mv kenya_downloads dr_ken/downloads
mv complete_kenya_workflow.sh dr_ken/

# Rwanda (RWA)
mv bdi_trail2/dr_case6 dr_rwa/

# Tanzania (TZA)
mv bdi_trail2/dr_case10 dr_tza/

# Uganda (UGA)
mv bdi_trail2/dr_case11 dr_uga/
```

### Step 3: Move shared resources
```bash
mv bdi_trail2/wflow_tutorial shared/
mv bdi_trail2/wflow_datasets_1km shared/
```

### Step 4: Move documentation files
```bash
# Create docs directories
mkdir -p shared/docs dr_eri/docs

# Top-level bdi_trail2 docs
mv bdi_trail2/CLAUDE.md shared/docs/
mv bdi_trail2/WFLOW_VERSION_TESTING_REPORT.md shared/docs/
mv bdi_trail2/ERITREA_SIMULATION_STATUS.md dr_eri/docs/
mv bdi_trail2/TUTORIAL_VS_BURUNDI_COMPARISON.md shared/docs/

# Country-specific simulation docs (already in case folders)
# dr_case3/Eritrea_simulation.md -> stays in dr_eri/dr_case3/
# dr_case6/Rwanda_simulation.md -> stays in dr_rwa/dr_case6/
# dr_case10/Tanzania_simulation.md -> stays in dr_tza/dr_case10/
# dr_case11/Uganda_simulation.md -> stays in dr_uga/dr_case11/
```

### Step 5: Create country-level READMEs
Generate README.md for each dr_* folder with:
- Country overview
- Drought event context
- Case summary
- Simulation status
- Key findings
- Quick links to scripts/data

### Step 6: Update root README.md
Update navigation to point to country folders instead of bdi_trail2 structure.

### Step 7: Update region_configs.py
Update `case_folder` paths to use ISO codes:
```python
# Old: "case_folder": "bdi_trail2/dr_case1"
# New: "case_folder": "dr_bdi/dr_case1"
```

### Step 8: Create placeholder folders for planned cases
```bash
# Somalia (SOM), South Sudan (SSD), Sudan (SDN)
for iso in som ssd sdn; do
    mkdir -p dr_${iso}/docs
    echo "# Drought Risk Case - ${iso^^}" > dr_${iso}/README.md
done
```

### Step 9: Remove empty bdi_trail2 folder
```bash
rmdir bdi_trail2  # Should be empty after all moves
```

### Step 10: Verify and test
- Check all paths in workflow scripts
- Verify region_configs.py case_folder paths
- Test one simulation (e.g., Rwanda) with new structure
- Update git tracking if needed

## Path Updates Required

After reorganization, update these references:

1. **region_configs.py**: All `case_folder` entries
2. **complete_*_workflow.sh**: Update relative paths
3. **Any symlinks**: Re-create if broken
4. **Documentation cross-references**: Update internal links

## Rollback Plan

If issues arise, the reorganization can be reversed:
```bash
# Restore bdi_trail2
mkdir bdi_trail2
mv dr_bdi/dr_case1 bdi_trail2/
mv dr_dji/dr_case2 bdi_trail2/
# ... etc
```

## Timeline Estimate

- Manual execution: ~30 minutes
- Automated script: ~5 minutes
- Testing and validation: ~20 minutes
- **Total: ~1 hour**
