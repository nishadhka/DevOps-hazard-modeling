# GeoSFM Climate Data Processing Workflow

Complete hydrological input data processing pipeline from raw climate data to GeoSFM model-ready zone files. This workflow integrates CHIRPS-GEFS precipitation forecasts, IMERG satellite observations, and PET evapotranspiration data for East Africa region analysis.

## Quick Start Guide

### 1. Setup Environment
```bash
# Local environment with micromamba (recommended)
micromamba create -p ./micromamba_dir python=3.11
micromamba install -p ./micromamba_dir -c conda-forge \
  xarray dask icechunk rioxarray xesmf flox geopandas rasterio pandas numpy

# Or Coiled cloud environment
coiled notebook start --name dask-thre --vm-type n2-standard-2 --software v5-geosfm-rm-x --workspace=geosfm
```

### 2. Upload Required Files
Upload these essential files to your environment:

**Required Data Files (~30MB total):**
- `zone_output.zip` (~25MB) - Pre-existing zone files with hydrological ordering headers  
- `geofsm-prod-all-zones-20240712_v2_simplfied.geojson` (~5MB) - Administrative zone boundaries
- `ea_geosfm_zones_002deg.tif` (~2MB) - Rasterized zone mask at 0.02° resolution

**Processing Scripts:**
- `01-get-regrid.py` - Downloads and regrids climate data to unified format
- `02-flox-groupby.py` - Performs spatial aggregation using flox
- `03-zone-txt.py` - Generates GeoSFM-compatible zone files

**Configuration Files:**
- `.env` - IMERG download credentials (optional)
- `flox_config.json` - Processing configuration (optional)

### 3. Complete Processing Pipeline

#### Step 1: Download and Regrid Climate Data (0.02° Resolution)
```bash
# Download and process for specific date  
python 01-get-regrid.py --date-str 20250722

# Process existing downloaded data only
python 01-get-regrid.py --date-str 20250722 --skip-download

# Custom resolution (⚠️ avoid 0.01° - causes memory issues)
python 01-get-regrid.py --date-str 20250722 --resolution 0.02
```
**What it does:** Downloads CHIRPS-GEFS, IMERG, and PET data; regrids to unified 0.02° East Africa grid; creates raw zarr and regridded icechunk datasets with temporal alignment.

**⚠️ Memory Note:** Uses 0.02° resolution by default. 0.01° resolution causes memory exhaustion and process termination.

#### Step 2: Spatial Aggregation Analysis  
```bash
# Local processing
micromamba run -p ./micromamba_dir python 02-flox-groupby.py

# Cloud processing with GCS upload (optional)
python 02-flox-groupby.py --use-dask --upload-gcs --gcs-bucket your-bucket
```
**What it does:** Converts zone boundaries to raster; loads regridded zarr data; performs spatial aggregation by zones using flox; outputs lean long table format.

#### Step 3: Generate GeoSFM Zone Files
```bash
# Generate zone-specific txt files preserving hydrological ordering
python 03-zone-txt.py \
  --lean-table flox_output/flox_results_lean_long_table_v3_20250722.csv \
  --shapefile geofsm-prod-all-zones-20240712_v2_simplfied.geojson \
  --output-dir zone_output \
  --date-str 20250722

# Process specific zones only
python 03-zone-txt.py \
  --lean-table flox_output/flox_results_lean_long_table_v3_20250722.csv \
  --shapefile geofsm-prod-all-zones-20240712_v2_simplfied.geojson \
  --output-dir zone_output \
  --date-str 20250722 \
  --zones zone1,zone3,zone5
```
**What it does:** 🚨 **CRITICAL**: Preserves existing hydrological ordering headers from zone files; maps spatial aggregation results to zone-specific positions; generates rain.txt and evap.txt files for GeoSFM model input.

### Output Structure
```
📁 Raw Data:
├── east_africa_raw_20250722.zarr/          # Raw climate data subset to East Africa
├── east_africa_regridded_20250722.zarr/    # Regridded unified dataset (0.02°)

📁 Analysis Results:
├── flox_output/
│   ├── ea_geofsm_zones_002deg.tif          # Zone raster mask
│   └── flox_results_lean_long_table_v3_20250722.csv  # Spatial aggregation results

📁 GeoSFM Model Input:
└── zone_output/lt_stable_input_20250722/
    ├── zone1/
    │   ├── rain.txt    # 86 spatial units × time steps
    │   └── evap.txt    # 86 spatial units × time steps  
    ├── zone2/ ... zone6/
    └── [Each zone with variable spatial unit counts: 86-1619 units]
```

### Key Features & Technical Details

**Resolution & Memory Management:**
- **0.02° resolution**: 1,751 x 1,601 = 2.8M grid points per layer (~11 MB per variable per time step) ✅
- **0.01° resolution**: 3,501 x 3,201 = 11.2M grid points per layer (~45 MB per variable per time step) ❌ Memory issues
- **Smart chunking**: `{'time': 3, 'lat': 500, 'lon': 500}` for memory optimization

**Hydrological Model Integration:**
- **🔒 Header Preservation**: Maintains river/stream network topology ordering from existing zone files
- **Variable Zone Sizes**: Supports zones with 86-1619 spatial units each
- **Temporal Integration**: Combines IMERG observations + CHIRPS-GEFS forecasts for rainfall
- **PET Replication**: Extends evapotranspiration data for forecast periods

**Data Processing Efficiency:**
- **Icechunk storage**: Version-controlled, cloud-optimized zarr format
- **Flox aggregation**: Memory-efficient spatial statistics using dask
- **Regional subsetting**: Early spatial cropping reduces memory footprint by ~10x
- **Lazy loading**: Processes data without loading full datasets into memory

### Troubleshooting

**Memory Issues:**
```bash
# Use 0.02° resolution (not 0.01°)
python 01-get-regrid.py --resolution 0.02

# Reduce chunk sizes if needed  
# Edit chunk_size in scripts: {"time": 1, "lat": 250, "lon": 250}
```

**Missing Files:**
- Ensure `zone_output.zip` is extracted before running step 3
- Download `geofsm-prod-all-zones-20240712_v2_simplfied.geojson` for zone boundaries
- Generate `ea_geofsm_zones_002deg.tif` using step 2 (auto-created by flox processor)

For complete documentation, see `COMPLETE_GEOSFM_INPUT_WORKFLOW_DOCUMENTATION.md`.