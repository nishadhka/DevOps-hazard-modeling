#!/bin/bash
# Complete workflow: Download CHIRPS, ERA5, prepare forcing.nc, and move to dr_case4

set -e

DOWNLOAD_DIR=/data/ethiopia_downloads
SCRIPTS_DIR=/mnt/hydromt_data/bdi_trail2/dr_case4/scripts
CASE_DIR=/mnt/hydromt_data/bdi_trail2/dr_case4

cd $DOWNLOAD_DIR

echo '=== Ethiopia Complete Workflow ==='
echo ''

# Step 1: Check CHIRPS status
echo 'Step 1: Checking CHIRPS download...'
CHIRPS_COUNT=$(find data/chirps/daily -name '*.tif' 2>/dev/null | wc -l)
echo "  Current: $CHIRPS_COUNT / 1461 files"

if [ $CHIRPS_COUNT -lt 1461 ]; then
    echo '  Resuming CHIRPS download...'
    nohup python3 01_download_chirps.py >> chirps_download.log 2>&1 &
    echo "  Download started (PID: $!)"
    echo '  Monitor with: tail -f /data/ethiopia_downloads/chirps_download.log'
else
    echo '  ✓ CHIRPS download complete'
fi

# Step 2: Download ERA5 (if not done)
echo ''
echo 'Step 2: Checking ERA5 download...'
if [ ! -f "data/era5/temperature_2m_2020_2023.nc" ] || [ ! -f "data/era5/potential_evaporation_2020_2023.nc" ]; then
    echo '  Starting ERA5 download...'
    echo '  Note: Requires CDS API setup (~/.cdsapirc)'
    cd $SCRIPTS_DIR
    python3 02_download_era5_ethiopia.py || {
        echo '  ⚠️  ERA5 download failed. Please check CDS API setup.'
        exit 1
    }
    # Move ERA5 files to download directory
    mkdir -p $DOWNLOAD_DIR/data/era5
    cp -v $SCRIPTS_DIR/../data/era5/*.nc $DOWNLOAD_DIR/data/era5/ 2>/dev/null || true
else
    echo '  ✓ ERA5 files already exist'
fi

# Step 3: Prepare forcing.nc
echo ''
echo 'Step 3: Preparing forcing.nc...'
if [ ! -f "forcing/forcing.nc" ]; then
    python3 03_prepare_forcing.py
    echo '  ✓ forcing.nc created'
else
    echo '  ✓ forcing.nc already exists'
fi

# Step 4: Move to dr_case4
echo ''
echo 'Step 4: Moving forcing.nc to dr_case4...'
mkdir -p $CASE_DIR/data/input
cp -v forcing/forcing.nc $CASE_DIR/data/input/forcing.nc
echo "  ✓ forcing.nc moved to $CASE_DIR/data/input/"
echo ''
echo '=== Workflow Complete ==='
