# Climate Data 3x3 Grid Plotting Guide v2

## 🎯 Overview

`plot_climate_data_comprehensive_v2.py` creates **3x3 grid layouts** for comprehensive comparison of climate data, producing compact, publication-ready visualizations that show multiple samples/timesteps in a single image.

## 🆕 What's New in v2

### **Grid Layout Approach**
- **Single PNG files** with 3x3 subplots instead of individual plots
- **Raw Data Grids**: One 3x3 grid per data source (PET, IMERG, CHIRPS)
- **Icechunk Grid**: Combined 3x3 grid showing all processed variables
- **Faster rendering**: Simplified plotting without cartopy overhead
- **Compact output**: 4 PNG files instead of 10+ individual plots

### **Smart Data Sampling**
- **PET**: 9 representations of the same data (typically one file per date)
- **IMERG**: 9 random samples from available TIFF files (with cycling if needed)
- **CHIRPS**: 9 timesteps from NetCDF files across available time dimensions
- **Icechunk**: 3 samples per variable (9 total) with random timestep selection

## 🚀 Usage Examples

### Basic Usage - Create All 3x3 Grids
```bash
micromamba run -p ./micromamba_dir python plot_climate_data_comprehensive_v2.py --date 20250722
```

### Raw Data Grids Only
```bash
micromamba run -p ./micromamba_dir python plot_climate_data_comprehensive_v2.py \
  --date 20250722 \
  --skip-icechunk
```

### Icechunk Grid Only
```bash
micromamba run -p ./micromamba_dir python plot_climate_data_comprehensive_v2.py \
  --date 20250722 \
  --skip-raw
```

### Custom Output Directory
```bash
micromamba run -p ./micromamba_dir python plot_climate_data_comprehensive_v2.py \
  --date 20250722 \
  --output-dir custom_grids
```

## 📊 Output Files

### **4 High-Quality 3x3 Grid PNG Files**

1. **`raw_pet_3x3_grid_YYYYMMDD.png`**
   - 3x3 grid of PET data representations
   - Orange colormap (Potential Evapotranspiration)
   - Same data shown 9 times (single daily file)

2. **`raw_imerg_3x3_grid_YYYYMMDD.png`**
   - 3x3 grid of IMERG precipitation data
   - Blue colormap (Precipitation)
   - 9 random samples from available TIFF files

3. **`raw_chirps_3x3_grid_YYYYMMDD.png`**
   - 3x3 grid of CHIRPS-GEFS forecast data
   - Blue colormap (Precipitation)
   - 9 timesteps from NetCDF time series

4. **`icechunk_3x3_grid_YYYYMMDD.png`**
   - 3x3 grid of processed icechunk data
   - Mixed variables: ~3 PET + ~3 IMERG + ~3 CHIRPS samples
   - Different colormaps per variable type

## 🎨 Visual Features

### **Grid Layout**
- **18×15 inch** figure size for high resolution
- **Clean subplot arrangement** with minimal borders
- **Individual titles** for each subplot
- **Main title** indicating data source and date
- **Consistent color scaling** within each data type

### **Data Representation**
- **Equal aspect ratio** for proper geographic representation
- **Percentile-based scaling** (2nd to 98th percentile) for optimal contrast
- **Variable-specific colormaps**:
  - Precipitation: Blues
  - PET: Oranges
  - Custom: Viridis

### **Professional Quality**
- **300 DPI resolution** for publication use
- **18×15 inch format** suitable for reports/presentations
- **Clean axis styling** without unnecessary gridlines
- **Error handling** with informative messages for missing data

## 📈 Test Results (20250722)

### **Successful Creation**
```
✅ Raw Data Grids: 3 files
   - PET: 9 representations of et250722.bil
   - IMERG: 9 samples from 7 available TIFF files (with cycling)
   - CHIRPS: 9 timesteps from NetCDF time series

✅ Icechunk Grid: 1 file
   - 3 variables × 3 samples each = 9 subplots
   - Mixed temporal sampling across variables

📊 Total: 4 comprehensive 3x3 grid visualizations
```

### **Performance**
- **Fast execution**: ~30 seconds for all 4 grids
- **Memory efficient**: Processes data samples incrementally
- **Scalable**: Handles varying numbers of input files gracefully

## 🛠 Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--date` | Date in YYYYMMDD format | Required |
| `--geojson` | Path to GeoJSON overlay file | `ea_ghcf_simple.json` |
| `--output-dir` | Output directory for grid plots | `grid_plots_v2` |
| `--skip-icechunk` | Skip icechunk grid creation | `False` |
| `--skip-raw` | Skip raw data grid creation | `False` |
| `--zarr-path` | Custom icechunk zarr path | `east_africa_regridded_{date}.zarr` |

## 🎯 Use Cases

### 1. **Data Quality Assessment**
Compare raw vs processed data across multiple samples:
```bash
python plot_climate_data_comprehensive_v2.py --date 20250722
```

### 2. **Temporal Analysis**
Examine time series patterns in CHIRPS and IMERG data through grid sampling.

### 3. **Multi-Variable Comparison**
View all three climate variables (PET, IMERG, CHIRPS) in organized grid layouts.

### 4. **Publication Figures**
Generate high-quality 3x3 grids for reports and scientific publications.

### 5. **Batch Processing**
Process multiple dates efficiently:
```bash
for date in 20250721 20250722 20250723; do
    python plot_climate_data_comprehensive_v2.py --date $date
done
```

## 📋 Data Requirements

### **Directory Structure**
```
YYYYMMDD/
├── pet_data/
│   └── etYYMMDD.bil         # PET binary file
├── imerg_data/
│   └── *.tif                # IMERG TIFF files (multiple)
└── chirps_gefs_data/
    └── *.nc                 # CHIRPS NetCDF files
```

### **Icechunk Dataset**
```
east_africa_regridded_YYYYMMDD.zarr/
├── chunks/                  # Icechunk data chunks
├── manifests/              # Metadata
└── refs/                   # References
```

## 🔧 Technical Details

### **Grid Creation Process**
1. **Data Loading**: Load samples from each data source
2. **Sample Selection**: Random/systematic sampling for grid filling
3. **Value Scaling**: Percentile-based normalization per subplot
4. **Grid Assembly**: 3×3 matplotlib subplot arrangement
5. **Styling**: Consistent colormaps and titles
6. **Export**: High-resolution PNG output

### **Memory Optimization**
- **Sequential processing**: Load one sample at a time
- **Data cleanup**: Clear variables after plotting
- **Simplified rendering**: No cartopy overhead in subplots
- **Efficient sampling**: Smart file selection algorithms

### **Error Handling**
- **Missing files**: Graceful handling with empty subplot indicators
- **Dimension mismatches**: Automatic data reshaping attempts
- **Processing failures**: Error messages with continued execution
- **Data validation**: Range checking and NaN handling

## 📊 Comparison: v1 vs v2

| Feature | v1 (Individual) | v2 (Grid) |
|---------|----------------|-----------|
| **Output** | 10+ PNG files | 4 PNG files |
| **Layout** | Individual plots | 3×3 grids |
| **Comparison** | Side-by-side viewing | Single-view comparison |
| **File size** | Multiple smaller files | Fewer larger files |
| **Use case** | Detailed analysis | Overview comparison |
| **Processing time** | ~45 seconds | ~30 seconds |

The v2 grid approach provides **better overview visualization** while maintaining **high data density** and **professional presentation quality**!