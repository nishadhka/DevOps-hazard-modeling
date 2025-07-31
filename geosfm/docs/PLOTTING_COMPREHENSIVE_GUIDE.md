# Comprehensive Climate Data Plotting Guide

## 🎯 Overview

This guide covers two powerful plotting scripts for visualizing climate data:

1. **`plot_icechunk_results.py`** - Specialized for processed icechunk datasets
2. **`plot_climate_data_comprehensive.py`** - Flexible plotting for both raw and processed data

## 📊 Script Features

### plot_icechunk_results.py
- Plots processed icechunk zarr datasets
- Handles multiple time dimensions per variable
- Creates publication-quality cartopy visualizations
- GeoJSON overlay support

### plot_climate_data_comprehensive.py  
- **Raw data plotting**: Direct from downloaded TIFF/NC/BIL files
- **Icechunk plotting**: From processed zarr datasets
- **Random sampling**: Selects random files/timesteps for comparison
- **Flexible switching**: Enable/disable raw or icechunk plotting
- **Command-line interface**: Easy configuration

## 🚀 Usage Examples

### Basic Usage - Both Raw and Icechunk
```bash
micromamba run -p ./micromamba_dir python plot_climate_data_comprehensive.py --date 20250722
```

### Raw Data Only
```bash
micromamba run -p ./micromamba_dir python plot_climate_data_comprehensive.py \
  --date 20250722 \
  --skip-icechunk \
  --raw-samples 3
```

### Icechunk Data Only  
```bash
micromamba run -p ./micromamba_dir python plot_climate_data_comprehensive.py \
  --date 20250722 \
  --skip-raw \
  --icechunk-samples 3
```

### Custom Configuration
```bash
micromamba run -p ./micromamba_dir python plot_climate_data_comprehensive.py \
  --date 20250722 \
  --geojson ea_ghcf_simple.json \
  --output-dir my_plots \
  --raw-samples 2 \
  --icechunk-samples 2 \
  --zarr-path "custom_path_{date}.zarr"
```

### Icechunk Only (Original Script)
```bash
micromamba run -p ./micromamba_dir python plot_icechunk_results.py
```

## 📁 Expected Directory Structure

```
/workspace/
├── YYYYMMDD/                    # Date folder (e.g., 20250722/)
│   ├── pet_data/
│   │   ├── etYYMMDD.bil         # PET binary files
│   │   └── etYYMMDD.hdr
│   ├── imerg_data/
│   │   └── *.tif                # IMERG TIFF files
│   └── chirps_gefs_data/
│       └── *.nc                 # CHIRPS NetCDF files
├── east_africa_regridded_YYYYMMDD.zarr/  # Icechunk dataset
├── ea_ghcf_simple.json          # GeoJSON overlay
└── plot_climate_data_comprehensive.py
```

## 🎨 Plot Types Generated

### Raw Data Plots
- **PET**: `raw_pet_YYYYMMDD_fileXX.png`
- **IMERG**: `raw_imerg_YYYYMMDD_fileXX.png`  
- **CHIRPS**: `raw_chirps_YYYYMMDD_fileXX.png`

### Icechunk Plots
- **IMERG**: `icechunk_imerg-precipitation_sampleXX.png`
- **CHIRPS**: `icechunk_chirps-precipitation_sampleXX.png`
- **PET**: `icechunk_pet-data_sampleXX.png`

## 🗺 Features

### Cartopy Visualization
- East Africa geographic projection
- Coastlines, borders, and geographic features
- Proper coordinate grids with lat/lon labels
- Professional map styling

### GeoJSON Overlay
- Red boundary overlays from `ea_ghcf_simple.json`
- 11 geographic features (zones/regions)
- Supports both Polygon and MultiPolygon geometries

### Data Handling
- **PET**: Binary (.bil) files with automatic dimension detection
- **IMERG**: GeoTIFF files with coordinate standardization
- **CHIRPS**: NetCDF files with variable auto-detection
- **Icechunk**: Multi-dimensional zarr with separate time dimensions

### Smart Sampling
- Random file selection for raw data
- Random timestep selection for time series
- Configurable number of samples per data source

## 📊 Recent Test Results

### Successful Test Run (20250722)
```
✅ Raw Data: 10 plots created
   - PET: 1 file (et250722.bil)
   - IMERG: 7 TIFF files (2 samples plotted)
   - CHIRPS: 2 NC files (2 samples plotted)

✅ Icechunk Data: 5 plots created  
   - IMERG: 3 time steps (2 samples)
   - CHIRPS: 16 time steps (2 samples)
   - PET: Static data (1 plot)

📊 Total: 10 publication-quality plots with GeoJSON overlays
```

## 🛠 Command Line Options

### plot_climate_data_comprehensive.py Options

| Option | Description | Default |
|--------|-------------|---------|
| `--date` | Date in YYYYMMDD format | Required |
| `--geojson` | Path to GeoJSON overlay file | `ea_ghcf_simple.json` |
| `--output-dir` | Output directory for plots | `comprehensive_plots` |
| `--raw-samples` | Number of samples per raw data source | `2` |
| `--icechunk-samples` | Number of samples per icechunk variable | `2` |
| `--skip-icechunk` | Skip icechunk plotting | `False` |
| `--skip-raw` | Skip raw data plotting | `False` |
| `--zarr-path` | Custom icechunk zarr path | `east_africa_regridded_{date}.zarr` |

## 🎯 Use Cases

### 1. Data Quality Validation
Compare raw downloaded data vs processed icechunk results:
```bash
python plot_climate_data_comprehensive.py --date 20250722 --raw-samples 3 --icechunk-samples 3
```

### 2. Raw Data Exploration
Explore multiple files from a download session:
```bash
python plot_climate_data_comprehensive.py --date 20250722 --skip-icechunk --raw-samples 5
```

### 3. Publication Plots
Generate high-quality plots from processed icechunk data:
```bash
python plot_climate_data_comprehensive.py --date 20250722 --skip-raw --icechunk-samples 1
```

### 4. Different Dates
Process multiple dates:
```bash
for date in 20250721 20250722 20250723; do
    python plot_climate_data_comprehensive.py --date $date --output-dir plots_$date
done
```

## 📈 Plot Quality

- **Resolution**: 300 DPI for publication quality
- **Format**: PNG with white background  
- **Size**: 16x12 inches (high resolution)
- **Color schemes**: 
  - Precipitation: Blues colormap
  - PET: Oranges colormap  
  - Custom: Viridis colormap
- **Statistics**: Mean, standard deviation in subtitles
- **Geographic context**: East Africa focused with proper projections

The comprehensive plotting system provides flexible, high-quality visualization for both raw climate data and processed icechunk datasets with professional cartographic presentation!