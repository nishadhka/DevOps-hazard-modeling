# Wflow SBM Hydrological Model for Burundi

A complete Wflow SBM (Soil-Based Model) simulation for Burundi covering the 2021-2022 drought period.

## Project Overview

This project derives 81 hydrological variables from 10 raw GeoTIFF inputs to create a complete Wflow model for Burundi. The model simulates daily discharge, groundwater recharge, and soil moisture for the period 2021-01-01 to 2022-12-31.

## Directory Structure

```
bdi_trail2/
├── data/
│   ├── input/
│   │   ├── staticmaps.nc      # 81 derived spatial variables (106 MB)
│   │   └── forcing.nc         # Climate forcing data (416 MB)
│   └── output/
│       └── output_burundi.csv # Simulation results (729 days)
├── wflow_datasets_1km/        # Raw input GeoTIFFs (10 files)
├── burundi_sbm.toml           # Wflow configuration file
├── derive_staticmaps.py       # Main script to derive all variables
├── fix_ldd_pyflwdir.py        # Fix LDD cycles using pyflwdir
├── resample_forcing.py        # Resample forcing to match staticmaps grid
├── staticmaps-burundi.nc      # Backup of derived static maps
└── README.md                  # This documentation
```

## Raw Input Data

The following 10 GeoTIFF files in `wflow_datasets_1km/` were used:

| File | Description |
|------|-------------|
| `1_elevation_merit_1km.tif` | MERIT DEM elevation (m) |
| `2_landcover_esa_1km.tif` | ESA WorldCover land use classes |
| `3_soil_sand_1km.tif` | Soil sand fraction (%) |
| `3_soil_silt_1km.tif` | Soil silt fraction (%) |
| `3_soil_clay_1km.tif` | Soil clay fraction (%) |
| `4_soil_rootzone_depth_1km.tif` | Root zone depth (cm) |
| `5_soil_ksat_1km.tif` | Saturated hydraulic conductivity |
| `5_soil_porosity_1km.tif` | Soil porosity |
| `6_river_flow_direction_1km.tif` | D8 flow direction |
| `6_river_flow_accumulation_1km.tif` | Upstream area (km²) |

## Derived Variables

The `derive_staticmaps.py` script generates 81 variables organized into categories:

### Flow Direction & River Network
- `wflow_ldd` - PCRaster LDD flow direction (converted from D8)
- `wflow_river` - River mask (upstream area >= 10 km²)
- `wflow_riverwidth` - River width from power law: W = 1.22 × A^0.557
- `wflow_riverlength` - River length per cell (~1.4 km diagonal)
- `wflow_streamorder` - Stream order based on upstream area thresholds
- `RiverSlope` - River bed slope (m/m)
- `RiverDepth` - River depth from power law: D = 0.27 × A^0.39
- `RiverZ` - River bed elevation (DEM - depth)

### Soil Hydraulic Parameters
- `thetaS` - Saturated water content (porosity) using Saxton & Rawls pedotransfer
- `thetaR` - Residual water content
- `KsatVer` - Vertical saturated hydraulic conductivity (mm/day)
- `f` - Ksat exponential decay parameter
- `c` - Brooks-Corey pore size distribution (4 layers)
- `SoilThickness` - Total soil thickness (mm)

### Vegetation Parameters (Land Cover Lookup Tables)
- `LAI` - Monthly Leaf Area Index (12 months, varies by land cover)
- `RootingDepth` - Rooting depth by land cover (mm)
- `N` - Manning's roughness for surface runoff
- `N_River` - Manning's roughness for river flow
- `Kext` - Light extinction coefficient
- `Sl` - Specific leaf storage
- `Swood` - Stem/wood water storage
- `PathFrac` - Impervious/compacted soil fraction
- `WaterFrac` - Open water fraction

### Snow Parameters (included for completeness)
- `Cfmax` - Degree-day factor
- `TT` - Snowfall temperature threshold
- `TTI` - Snowfall temperature interval
- `TTM` - Snowmelt temperature threshold

## Key Algorithms

### Flow Direction Conversion (D8 to LDD)
```
D8: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
LDD: 1=SW, 2=S, 3=SE, 4=W, 5=pit, 6=E, 7=NW, 8=N, 9=NE
```

### Pedotransfer Functions (Saxton & Rawls 2006)
```python
thetaS = 0.332 - 0.0007251×sand + 0.1276×log10(clay+1)
thetaR = 0.01 + 0.003×clay
```

### River Width/Depth Power Laws
```python
Width = 1.22 × UpstreamArea^0.557  (Andreadis et al. 2013)
Depth = 0.27 × UpstreamArea^0.39   (Leopold & Maddock)
```

### Ksat Depth Decay
```python
K(z) = K0 × exp(-f × z)
where f = 0.001 + 0.003×clay_fraction
```

## Model Configuration

The `burundi_sbm.toml` configuration includes:

- **Model Type**: SBM (Soil-Based Model)
- **Time Period**: 2021-01-01 to 2022-12-31
- **Soil Layers**: 3 layers [100, 300, 800 mm]
- **Snow Module**: Enabled
- **Reservoirs**: Disabled

### Output Variables
| Header | Parameter | Description |
|--------|-----------|-------------|
| `Q` | `river_water__volume_flow_rate` | Discharge at outlet (m³/s) |
| `recharge` | `soil_water_saturated_zone_top__recharge_volume_flux` | Basin-avg recharge (mm/day) |
| `soil_moisture_L1` | `soil_layer_water__volume_fraction` (layer 1) | Top 100mm soil moisture |
| `soil_moisture_L2` | `soil_layer_water__volume_fraction` (layer 2) | 100-400mm soil moisture |

## Output Data

The simulation produces daily output for 729 days (2021-01-02 to 2022-12-31):

```csv
time,Q,recharge,soil_moisture_L1,soil_moisture_L2
2021-01-02T00:00:00,2.35,0.96,0.374,0.520
...
2022-12-31T00:00:00,1375.51,1.23,0.464,0.511
```

### Variable Ranges
- **Q (Discharge)**: 2.35 - 1932 m³/s
- **Recharge**: 0.13 - 3.28 mm/day
- **Soil Moisture L1**: 0.32 - 0.49 (volumetric fraction)
- **Soil Moisture L2**: ~0.51 (volumetric fraction)

## Python Scripts

### 1. `derive_staticmaps.py` (875 lines)
Main script that derives all 81 Wflow variables from 10 raw GeoTIFFs.

**What it does:**
- Loads raw data (DEM, land cover, soil texture, flow direction, etc.)
- Converts D8 flow direction to PCRaster LDD format
- Derives river network from upstream area threshold
- Calculates soil hydraulic parameters using pedotransfer functions
- Creates monthly LAI lookup by land cover type
- Generates Manning's roughness, rooting depth, and other vegetation parameters
- Outputs `staticmaps-burundi.nc`

**Usage:**
```bash
python derive_staticmaps.py
```

### 2. `fix_ldd_pyflwdir.py` (230 lines)
Fixes LDD cycles that can crash Wflow by re-deriving flow direction from DEM.

**What it does:**
- Uses pyflwdir.from_dem() to derive cycle-free flow direction
- Recalculates upstream area, river network, and river parameters
- Updates staticmaps.nc with corrected values
- Creates a backup before modifying

**When to use:**
Run this if Wflow throws "LDD cycles detected" error.

**Usage:**
```bash
python fix_ldd_pyflwdir.py
```

### 3. `resample_forcing.py` (220 lines)
Resamples coarse-resolution forcing data to match the staticmaps grid.

**What it does:**
- Loads target grid from staticmaps.nc
- Resamples precipitation, temperature, and PET using bilinear interpolation
- Applies domain mask
- Outputs forcing.nc with matching resolution

**When to use:**
Run this if your forcing data has different resolution than staticmaps.

**Usage:**
```bash
python resample_forcing.py
```

## Running the Simulation

### Prerequisites
- Julia with Wflow.jl v1.0.1
- Python 3.x with: numpy, xarray, rioxarray, scipy, pyflwdir

### Complete Workflow
```bash
cd /mnt/hydromt_data/bdi_trail2

# Step 1: Generate static maps from raw GeoTIFFs
python derive_staticmaps.py

# Step 2: Fix LDD if cycles are detected (optional)
python fix_ldd_pyflwdir.py

# Step 3: Resample forcing data if needed (optional)
python resample_forcing.py

# Step 4: Run Wflow simulation
julia -e 'using Wflow; Wflow.run("burundi_sbm.toml")'
```

### Run Wflow Simulation Only
```bash
cd /mnt/hydromt_data/bdi_trail2
julia -e 'using Wflow; Wflow.run("burundi_sbm.toml")'
```

## Grid Specifications

- **Resolution**: ~1 km (0.00833° × 0.00833°)
- **Grid Size**: 245 × 212 cells
- **Valid Cells**: ~35,000 cells
- **Coordinate System**: WGS 84 (EPSG:4326)
- **Latitude Range**: -4.50° to -2.29°
- **Longitude Range**: 28.83° to 30.89°

## Main Basin Outlet

- **Coordinates**: (29.2267°E, -4.4961°S)
- **Upstream Area**: Maximum in domain
- **Location**: Southern edge of Burundi (Ruzizi River outlet)

## References

1. Wflow.jl Documentation: https://deltares.github.io/Wflow.jl/dev/
2. Saxton, K.E. & Rawls, W.J. (2006). Soil Water Characteristic Estimates by Texture and Organic Matter for Hydrologic Solutions. Soil Science Society of America Journal.
3. Andreadis, K.M. et al. (2013). A simple global river bankfull width and depth database. Water Resources Research.
4. Leopold, L.B. & Maddock, T. (1953). The hydraulic geometry of stream channels and some physiographic implications. USGS Professional Paper 252.

## File Sizes

| File | Size |
|------|------|
| `data/input/staticmaps.nc` | 106 MB |
| `data/input/forcing.nc` | 416 MB |
| `data/output/output_burundi.csv` | ~50 KB |
| `derive_staticmaps.py` | 33 KB |

## Author

Generated using Claude Code (Anthropic)

## Date

January 2026
