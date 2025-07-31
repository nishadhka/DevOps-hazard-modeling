# Flox Climate Data Processing Workflow

## Quick Start Guide

### 1. Setup Coiled Notebook Environment
```bash
coiled notebook start --name dask-thre --vm-type n2-standard-2 --software v5-geosfm-rm-x --workspace=geosfm
```

### 2. Upload Required Files
Upload these files to your notebook environment:
- `create_regridded_icechunk_memory_optimized.py` - Creates aligned zarr datasets
- `ea_geosfm_zones_002deg.tif` - Zone shapefile raster for spatial aggregation
- `env.txt` - Environment configuration
- `flox_shapefile_groupby_processor_v3.py` - Processes zarr data into lean tables

### 3. Run Processing Pipeline

#### Step 1: Create Regridded Icechunk Dataset
```bash
python create_regridded_icechunk_memory_optimized.py
```
**What it does:** Downloads climate data (CHIRPS, IMERG, PET), regrids to common resolution, aligns temporal dimensions, and creates optimized icechunk zarr format for efficient analysis.

#### Step 2: Process to Lean Long Table
```bash
python flox_shapefile_groupby_processor_v3.py --date-str 20250722
```
**What it does:** Loads zarr data, applies variable-specific NULL filtering, performs spatial aggregation by zones using flox, and outputs optimized lean long table format with encoded variables (1=imerg, 2=pet, 3=chirps).

### Output
- **Zarr Dataset:** `east_africa_regridded_YYYYMMDD.zarr`
- **Long Table:** `flox_results_lean_long_table_v3_YYYYMMDD.csv`
- **Processing Log:** `flox_processor_v3_YYYYMMDD.log`

### Key Features
- **V3 Optimization:** Variable-specific NULL filtering at xarray stage for maximum efficiency
- **Lean Format:** 5 columns vs 10+ in original format (~50% memory reduction)
- **Smart Filtering:** Eliminates sparse PET data processing (23 dates → 1 valid date)
- **Configurable:** Date-specific processing with `--date-str` parameter