#!/usr/bin/env python3
"""
Derive complete Wflow staticmaps for Ethiopia from 10 raw GeoTIFF inputs.
This script creates all 80+ variables needed for Wflow SBM simulation.

Adapted for Wflow v1.0.1 with 4-layer workaround for Brooks-Corey bug.
TOML uses 3 soil layers [100, 300, 800] mm, but staticmaps has 4 layers.

Drought period: 2020-01-01 to 2023-12-31
Impact: 24.1M people affected, 4.5M livestock deaths
"""

import numpy as np
import xarray as xr
import rioxarray
from scipy import ndimage
import warnings
import os
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================
REGION = "Ethiopia"
DATA_DIR = "wflow_datasets_1km"
OUTPUT_FILE = "data/input/staticmaps.nc"

# Wflow v1.0.1 WORKAROUND: Use 4 layers in NetCDF, but 3 in TOML
# This bypasses the Brooks-Corey bug
N_LAYERS_NC = 4  # Layers in NetCDF file (workaround)
N_LAYERS_TOML = 3  # Layers in TOML config
SOIL_LAYERS = [100, 300, 800]  # mm - total 1200mm (for TOML)

# =============================================================================
# 1. LOAD RAW DATA
# =============================================================================
print("=" * 80)
print(f"STEP 1: Loading raw {REGION} GeoTIFF data...")
print("=" * 80)

# Load all raw inputs
dem = rioxarray.open_rasterio(f"{DATA_DIR}/1_elevation_merit_1km.tif").squeeze()
landuse = rioxarray.open_rasterio(f"{DATA_DIR}/2_landcover_esa_1km.tif").squeeze()
sand = rioxarray.open_rasterio(f"{DATA_DIR}/3_soil_sand_1km.tif").squeeze()
silt = rioxarray.open_rasterio(f"{DATA_DIR}/3_soil_silt_1km.tif").squeeze()
clay = rioxarray.open_rasterio(f"{DATA_DIR}/3_soil_clay_1km.tif").squeeze()
rootzone = rioxarray.open_rasterio(f"{DATA_DIR}/4_soil_rootzone_depth_1km.tif").squeeze()
ksat = rioxarray.open_rasterio(f"{DATA_DIR}/5_soil_ksat_1km.tif").squeeze()
porosity = rioxarray.open_rasterio(f"{DATA_DIR}/5_soil_porosity_1km.tif").squeeze()
flow_dir = rioxarray.open_rasterio(f"{DATA_DIR}/6_river_flow_direction_1km.tif").squeeze()
flow_acc = rioxarray.open_rasterio(f"{DATA_DIR}/6_river_flow_accumulation_1km.tif").squeeze()

# Get grid info
lat = dem.y.values
lon = dem.x.values
ny, nx = len(lat), len(lon)

print(f"Grid size: {ny} x {nx} ({ny*nx:,} cells)")
print(f"Lat range: {lat.min():.4f} to {lat.max():.4f}")
print(f"Lon range: {lon.min():.4f} to {lon.max():.4f}")
print(f"Resolution: ~{abs(lat[1]-lat[0])*111:.2f} km")

# Create mask for valid data (non-NaN in DEM)
dem_vals = dem.values.astype(np.float32)
mask = ~np.isnan(dem_vals) & (dem_vals > -500)  # Ethiopia has some low areas
print(f"Valid cells: {mask.sum():,} ({100*mask.sum()/(ny*nx):.1f}%)")

# =============================================================================
# 2. CONVERT D8 FLOW DIRECTION TO LDD FORMAT
# =============================================================================
print("\n" + "=" * 80)
print("STEP 2: Converting D8 flow direction to PCRaster LDD format...")
print("=" * 80)

# D8 encoding: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
# LDD encoding: 1=SW, 2=S, 3=SE, 4=W, 5=pit, 6=E, 7=NW, 8=N, 9=NE
d8_to_ldd = {
    1: 6,    # E
    2: 3,    # SE
    4: 2,    # S
    8: 1,    # SW
    16: 4,   # W
    32: 7,   # NW
    64: 8,   # N
    128: 9,  # NE
    0: 5,    # pit/outlet
    255: 5,  # nodata -> pit
}

flow_dir_vals = flow_dir.values.astype(np.float32)
ldd = np.zeros_like(flow_dir_vals, dtype=np.float32)

for d8_val, ldd_val in d8_to_ldd.items():
    ldd[flow_dir_vals == d8_val] = ldd_val

# Handle boundary cells as pits
ldd[0, :] = 5   # Top row
ldd[-1, :] = 5  # Bottom row
ldd[:, 0] = 5   # Left column
ldd[:, -1] = 5  # Right column

# Set masked areas to NaN
ldd[~mask] = np.nan

# Convert to uint8 for Wflow (fix Missing value issue)
ldd_uint8 = np.where(np.isnan(ldd), 5, ldd).astype(np.uint8)

print(f"LDD unique values: {np.unique(ldd_uint8)}")
print(f"Pit cells: {(ldd_uint8 == 5).sum():,}")

# =============================================================================
# 3. DERIVE RIVER NETWORK AND PARAMETERS
# =============================================================================
print("\n" + "=" * 80)
print("STEP 3: Deriving river network from upstream area...")
print("=" * 80)

# Upstream area in km²
uparea = flow_acc.values.astype(np.float32)
uparea[~mask] = np.nan

# River network threshold: 10 km² (typical for 1km resolution)
river_threshold = 10.0  # km²
river_mask = (uparea >= river_threshold).astype(np.float64)
river_mask[~mask] = np.nan

# Set river values to 1 where river exists
wflow_river = np.where(uparea >= river_threshold, 1.0, np.nan)
wflow_river[~mask] = np.nan

print(f"River threshold: {river_threshold} km²")
print(f"River cells: {np.nansum(wflow_river == 1):,.0f}")

# Calculate river width using power law: W = a * A^b
a_width, b_width = 1.22, 0.557
riverwidth = a_width * (uparea ** b_width)
riverwidth = np.clip(riverwidth, 30, 500)
riverwidth[wflow_river != 1] = np.nan
riverwidth[~mask] = np.nan

print(f"River width range: {np.nanmin(riverwidth):.1f} - {np.nanmax(riverwidth):.1f} m")

# Calculate river depth using power law: D = c * A^d
c_depth, d_depth = 0.27, 0.39
riverdepth = c_depth * (uparea ** d_depth)
riverdepth = np.clip(riverdepth, 1.0, 5.0)
riverdepth[wflow_river != 1] = np.nan
riverdepth[~mask] = np.nan

print(f"River depth range: {np.nanmin(riverdepth):.2f} - {np.nanmax(riverdepth):.2f} m")

# River Z (bed elevation) - DEM minus depth
riverz = dem_vals - riverdepth
riverz[wflow_river != 1] = np.nan
riverz[~mask] = np.nan

# =============================================================================
# 4. CALCULATE SLOPES
# =============================================================================
print("\n" + "=" * 80)
print("STEP 4: Calculating surface and river slopes...")
print("=" * 80)

# Surface slope from DEM (m/m)
cell_size = abs(lat[1] - lat[0]) * 111000  # Convert degrees to meters
dy, dx = np.gradient(dem_vals, cell_size)
slope = np.sqrt(dx**2 + dy**2)
slope = np.clip(slope, 0.0001, 1.0)
slope[~mask] = np.nan

print(f"Surface slope range: {np.nanmin(slope):.6f} - {np.nanmax(slope):.4f} m/m")

# River slope
river_slope = slope.copy()
river_slope = np.clip(river_slope, 0.00001, 0.1)
river_slope[wflow_river != 1] = np.nan
river_slope[~mask] = np.nan

print(f"River slope range: {np.nanmin(river_slope):.6f} - {np.nanmax(river_slope):.4f} m/m")

# River length per cell
riverlength = np.full((ny, nx), cell_size * 1.414, dtype=np.float32)
riverlength[wflow_river != 1] = np.nan
riverlength[~mask] = np.nan

print(f"River length per cell: ~{cell_size * 1.414:.1f} m")

# =============================================================================
# 5. DERIVE STREAM ORDER AND SUBCATCHMENTS
# =============================================================================
print("\n" + "=" * 80)
print("STEP 5: Deriving stream order and subcatchments...")
print("=" * 80)

# Stream order based on upstream area thresholds
stream_order = np.zeros((ny, nx), dtype=np.float32)
stream_order[(uparea >= 10) & (uparea < 50)] = 1
stream_order[(uparea >= 50) & (uparea < 100)] = 2
stream_order[(uparea >= 100) & (uparea < 500)] = 3
stream_order[(uparea >= 500) & (uparea < 1000)] = 4
stream_order[(uparea >= 1000) & (uparea < 2000)] = 5
stream_order[(uparea >= 2000) & (uparea < 3000)] = 6
stream_order[(uparea >= 3000) & (uparea < 4000)] = 7
stream_order[uparea >= 4000] = 8
stream_order[wflow_river != 1] = np.nan
stream_order[~mask] = np.nan

print(f"Stream order range: {np.nanmin(stream_order):.0f} - {np.nanmax(stream_order):.0f}")

# Subcatchments - single catchment (ID=1)
wflow_subcatch = np.where(mask, 1.0, np.nan)

# Identify outlet (pit with max upstream area)
ldd_float = ldd.copy()
pit_mask = (ldd_float == 5) & mask
if pit_mask.sum() > 0:
    pit_uparea = np.where(pit_mask, uparea, 0)
    outlet_idx = np.unravel_index(np.argmax(pit_uparea), pit_uparea.shape)
    print(f"Main outlet at: ({lon[outlet_idx[1]]:.4f}E, {lat[outlet_idx[0]]:.4f}N)")
    print(f"Outlet upstream area: {uparea[outlet_idx]:,.1f} km²")

# Gauge locations (at outlet)
wflow_gauges = np.full((ny, nx), np.nan)
wflow_gauges[outlet_idx] = 1.0

# Pit locations
wflow_pits = np.full((ny, nx), np.nan)
wflow_pits[outlet_idx] = 1.0

# Subcatchment area
subare = np.full((ny, nx), np.nan)
subare[mask] = (cell_size / 1000) ** 2

# =============================================================================
# 6. SOIL PARAMETERS FROM TEXTURE (PEDOTRANSFER FUNCTIONS)
# =============================================================================
print("\n" + "=" * 80)
print("STEP 6: Calculating soil hydraulic parameters...")
print("=" * 80)

# Get soil texture fractions
sand_frac = sand.values.astype(np.float32) / 100.0
clay_frac = clay.values.astype(np.float32) / 100.0
silt_frac = silt.values.astype(np.float32) / 100.0

# Check units and normalize
total = sand_frac + clay_frac + silt_frac
if np.nanmean(total) > 1.5:
    pass  # Already percentage, divided by 100
elif np.nanmean(total) < 0.5:
    sand_frac = sand.values.astype(np.float32)
    clay_frac = clay.values.astype(np.float32)
    silt_frac = silt.values.astype(np.float32)

# Normalize to sum to 1
total = sand_frac + clay_frac + silt_frac
sand_frac = np.where(total > 0, sand_frac / total, 0.33)
clay_frac = np.where(total > 0, clay_frac / total, 0.33)
silt_frac = np.where(total > 0, silt_frac / total, 0.34)

# Porosity (thetaS) - Saxton & Rawls (2006)
thetaS_est = 0.332 - 0.0007251 * sand_frac * 100 + 0.1276 * np.log10(clay_frac * 100 + 1)
thetaS_est = np.clip(thetaS_est, 0.35, 0.55)

# Use provided porosity if available
porosity_vals = porosity.values.astype(np.float32)
if np.nanmax(porosity_vals) > 1:
    porosity_vals = porosity_vals / 100.0
thetaS = np.where(porosity_vals > 0.3, porosity_vals, thetaS_est)
thetaS = np.clip(thetaS, 0.35, 0.55).astype(np.float32)
thetaS[~mask] = np.nan

print(f"thetaS (porosity) range: {np.nanmin(thetaS):.3f} - {np.nanmax(thetaS):.3f}")

# Residual water content (thetaR)
thetaR = 0.01 + 0.003 * clay_frac * 100
thetaR = np.clip(thetaR, 0.05, 0.25).astype(np.float32)
thetaR[~mask] = np.nan

print(f"thetaR range: {np.nanmin(thetaR):.3f} - {np.nanmax(thetaR):.3f}")

# Brooks-Corey c parameter
lambda_bc = 0.131 + 0.00125 * sand_frac * 100 - 0.00207 * clay_frac * 100
lambda_bc = np.clip(lambda_bc, 0.1, 0.5)
c_param = 1.0 / (1.0 + lambda_bc)
c_param = np.clip(c_param, 0.05, 0.2)

# =============================================================================
# BROOKS-COREY 4-LAYER WORKAROUND (CRITICAL FOR WFLOW v1.0.1)
# =============================================================================
print("\n" + "=" * 80)
print("STEP 6b: Creating 4-layer soil variables (Brooks-Corey bug workaround)...")
print("=" * 80)

# Create c with 4 layers (workaround for Wflow v1.0.1 bug)
# Wflow reads 3 layers from TOML but the 4-layer NC file prevents the error
c_layers = np.zeros((N_LAYERS_NC, ny, nx), dtype=np.float64)
depth_factors = [1.0, 0.95, 0.90, 0.85]  # 4 layers (4th not used by Wflow)
for i, factor in enumerate(depth_factors):
    c_layers[i] = (7.5 + 6.5 * c_param * factor).astype(np.float64)
    c_layers[i][~mask] = np.nan

print(f"Brooks-Corey c layers: {N_LAYERS_NC} (workaround for v1.0.1 bug)")
print(f"Brooks-Corey c range: {np.nanmin(c_layers):.2f} - {np.nanmax(c_layers):.2f}")

# =============================================================================
# 7. KSAT PARAMETERS AT DIFFERENT DEPTHS
# =============================================================================
print("\n" + "=" * 80)
print("STEP 7: Calculating Ksat at different depths...")
print("=" * 80)

# Base Ksat
ksat_base = ksat.values.astype(np.float32)
if np.nanmean(ksat_base) < 10:
    ksat_base = ksat_base * 100
ksat_base = np.clip(ksat_base, 1, 5000)
ksat_base[~mask] = np.nan

print(f"Base KsatVer range: {np.nanmin(ksat_base):.1f} - {np.nanmax(ksat_base):.1f} mm/day")

# Ksat decay with depth
f_param = 0.001 + 0.003 * clay_frac
f_param = np.clip(f_param, 0.0003, 0.01).astype(np.float32)
f_param[~mask] = np.nan

f_alt = f_param * 0.8
f_alt[~mask] = np.nan

print(f"f parameter range: {np.nanmin(f_param):.6f} - {np.nanmax(f_param):.6f}")

# Soil thickness
soil_thick = rootzone.values.astype(np.float32)
soil_thick = soil_thick * 10  # cm to mm
soil_thick = np.clip(soil_thick, 300, 2500)
soil_thick[~mask] = np.nan

# M parameter
M_param = soil_thick / f_param
M_param = np.clip(M_param, 50, 1500).astype(np.float32)
M_param[~mask] = np.nan

M_alt = soil_thick / f_alt
M_alt = np.clip(M_alt, 50, 1500).astype(np.float32)
M_alt[~mask] = np.nan

print(f"M parameter range: {np.nanmin(M_param):.1f} - {np.nanmax(M_param):.1f}")

# Ksat at different depths
depths_cm = [0.0, 5.0, 15.0, 30.0, 60.0, 100.0, 200.0]
ksat_depths = {}
for depth in depths_cm:
    depth_mm = depth * 10
    ksat_at_depth = ksat_base * np.exp(-f_param * depth_mm)
    ksat_at_depth = np.clip(ksat_at_depth, 1, 5000)
    ksat_at_depth[~mask] = np.nan
    ksat_depths[f"KsatVer_{depth}cm"] = ksat_at_depth.astype(np.float32)

# kv layers (4 layers for workaround)
layer_depths_mm = [50, 250, 650, 1000]  # Midpoints for 4 layers
kv_layers = np.zeros((N_LAYERS_NC, ny, nx), dtype=np.float64)
for i, depth in enumerate(layer_depths_mm):
    kv_layers[i] = ksat_base * np.exp(-f_param * depth)
    kv_layers[i][~mask] = np.nan

print(f"kv layers: {N_LAYERS_NC}")

# sl layers (4 soil layer thicknesses)
sl_layers = np.zeros((N_LAYERS_NC, ny, nx), dtype=np.float64)
layer_thicknesses = [100, 300, 800, 400]  # 4th layer (not used, but needed for workaround)
for i, thickness in enumerate(layer_thicknesses):
    sl_layers[i] = thickness
    sl_layers[i][~mask] = np.nan

print(f"sl layers: {N_LAYERS_NC}")

# =============================================================================
# 8. LAND COVER LOOKUP TABLES
# =============================================================================
print("\n" + "=" * 80)
print("STEP 8: Creating land cover lookup tables...")
print("=" * 80)

landuse_vals = landuse.values.astype(np.float32)

# Manning's N for surface runoff (ESA WorldCover classes)
n_lookup = {
    10: 0.15, 20: 0.10, 30: 0.05, 40: 0.04, 50: 0.02,
    60: 0.03, 70: 0.03, 80: 0.01, 90: 0.10, 95: 0.08, 100: 0.03,
}

N_surface = np.zeros((ny, nx), dtype=np.float32)
for lc_val, n_val in n_lookup.items():
    N_surface[landuse_vals == lc_val] = n_val
N_surface[(N_surface == 0) & mask] = 0.05
N_surface[~mask] = np.nan

print(f"Manning N (surface) range: {np.nanmin(N_surface):.3f} - {np.nanmax(N_surface):.3f}")

# Manning's N for rivers
n_river_lookup = {
    10: 0.05, 20: 0.04, 30: 0.035, 40: 0.035, 50: 0.03,
    60: 0.03, 80: 0.03, 90: 0.04,
}

N_river = np.zeros((ny, nx), dtype=np.float32)
for lc_val, n_val in n_river_lookup.items():
    N_river[landuse_vals == lc_val] = n_val
N_river[(N_river == 0) & mask] = 0.035
N_river[wflow_river != 1] = np.nan
N_river[~mask] = np.nan

print(f"Manning N (river) range: {np.nanmin(N_river):.3f} - {np.nanmax(N_river):.3f}")

# Light extinction coefficient (Kext)
kext_lookup = {
    10: 0.65, 20: 0.60, 30: 0.50, 40: 0.55, 50: 0.60,
    60: 0.50, 80: 0.50, 90: 0.55,
}

Kext = np.zeros((ny, nx), dtype=np.float32)
for lc_val, k_val in kext_lookup.items():
    Kext[landuse_vals == lc_val] = k_val
Kext[(Kext == 0) & mask] = 0.55
Kext[~mask] = np.nan

# Rooting depth by land cover
root_lookup = {
    10: 2000, 20: 1000, 30: 600, 40: 800, 50: 200,
    60: 100, 80: 0, 90: 500,
}

RootingDepth = np.zeros((ny, nx), dtype=np.float64)
for lc_val, r_val in root_lookup.items():
    RootingDepth[landuse_vals == lc_val] = r_val
RootingDepth[(RootingDepth == 0) & mask] = 500
RootingDepth[~mask] = np.nan

print(f"RootingDepth range: {np.nanmin(RootingDepth):.0f} - {np.nanmax(RootingDepth):.0f} mm")

# Path fraction (impervious)
pathfrac_lookup = {
    10: 0.0, 20: 0.0, 30: 0.0, 40: 0.05, 50: 0.60,
    60: 0.1, 80: 0.0, 90: 0.0,
}

PathFrac = np.zeros((ny, nx), dtype=np.float32)
for lc_val, p_val in pathfrac_lookup.items():
    PathFrac[landuse_vals == lc_val] = p_val
PathFrac[~mask] = np.nan

# Water fraction
WaterFrac = np.zeros((ny, nx), dtype=np.float64)
WaterFrac[landuse_vals == 80] = 1.0
WaterFrac[~mask] = np.nan

# Specific leaf storage (Sl)
sl_lookup = {
    10: 0.12, 20: 0.08, 30: 0.04, 40: 0.05, 50: 0.02,
    60: 0.01, 80: 0.0, 90: 0.06,
}

Sl_veg = np.zeros((ny, nx), dtype=np.float32)
for lc_val, s_val in sl_lookup.items():
    Sl_veg[landuse_vals == lc_val] = s_val
Sl_veg[(Sl_veg == 0) & mask] = 0.04
Sl_veg[~mask] = np.nan

# Stem/wood storage (Swood)
swood_lookup = {
    10: 0.5, 20: 0.2, 30: 0.0, 40: 0.05, 50: 0.0,
    60: 0.0, 80: 0.0, 90: 0.1,
}

Swood = np.zeros((ny, nx), dtype=np.float32)
for lc_val, s_val in swood_lookup.items():
    Swood[landuse_vals == lc_val] = s_val
Swood[~mask] = np.nan

# =============================================================================
# 9. LAI (MONTHLY LEAF AREA INDEX)
# =============================================================================
print("\n" + "=" * 80)
print("STEP 9: Creating monthly LAI layers...")
print("=" * 80)

# Monthly LAI multipliers for Ethiopia (distinct wet/dry seasons)
# Ethiopia has main rainy season (June-Sept) and small rains (March-May)
monthly_lai_factor = [
    0.60, 0.55, 0.65, 0.75, 0.85, 0.95,  # Jan-Jun
    1.00, 1.00, 0.95, 0.85, 0.70, 0.60,  # Jul-Dec
]

# Base LAI by land cover
lai_base_lookup = {
    10: 5.0, 20: 2.5, 30: 1.5, 40: 2.0, 50: 0.5,
    60: 0.2, 80: 0.0, 90: 2.0,
}

LAI = np.zeros((12, ny, nx), dtype=np.float32)
for month in range(12):
    lai_month = np.zeros((ny, nx), dtype=np.float32)
    for lc_val, base_lai in lai_base_lookup.items():
        lai_month[landuse_vals == lc_val] = base_lai * monthly_lai_factor[month]
    lai_month[(lai_month == 0) & mask] = 1.0
    lai_month[~mask] = np.nan
    LAI[month] = lai_month

print(f"LAI range: {np.nanmin(LAI):.2f} - {np.nanmax(LAI):.2f}")
print(f"LAI shape: {LAI.shape}")

# =============================================================================
# 10. DEFAULT CONSTANTS
# =============================================================================
print("\n" + "=" * 80)
print("STEP 10: Setting default constants...")
print("=" * 80)

# Snow parameters (Ethiopia highlands can have frost)
Cfmax = np.full((ny, nx), 3.75653, dtype=np.float64)
Cfmax[~mask] = np.nan

G_Cfmax = np.full((ny, nx), 5.3, dtype=np.float64)
G_Cfmax[~mask] = np.nan

TT = np.full((ny, nx), 0.0, dtype=np.float64)
TT[~mask] = np.nan

TTI = np.full((ny, nx), 2.0, dtype=np.float64)
TTI[~mask] = np.nan

TTM = np.full((ny, nx), 0.0, dtype=np.float64)
TTM[~mask] = np.nan

G_TT = np.full((ny, nx), 1.3, dtype=np.float64)
G_TT[~mask] = np.nan

G_SIfrac = np.full((ny, nx), 0.002, dtype=np.float64)
G_SIfrac[~mask] = np.nan

WHC = np.full((ny, nx), 0.1, dtype=np.float64)
WHC[~mask] = np.nan

cf_soil = np.full((ny, nx), 0.038, dtype=np.float64)
cf_soil[~mask] = np.nan

# Infiltration parameters
InfiltCapPath = np.full((ny, nx), 5.0, dtype=np.float64)
InfiltCapPath[~mask] = np.nan

InfiltCapSoil = np.full((ny, nx), 600.0, dtype=np.float64)
InfiltCapSoil[~mask] = np.nan

KsatHorFrac = np.full((ny, nx), 100.0, dtype=np.float64)
KsatHorFrac[~mask] = np.nan

MaxLeakage = np.full((ny, nx), 0.0, dtype=np.float64)
MaxLeakage[~mask] = np.nan

EoverR = np.full((ny, nx), 0.11, dtype=np.float64)
EoverR[~mask] = np.nan

rootdistpar = np.full((ny, nx), -500.0, dtype=np.float64)
rootdistpar[~mask] = np.nan

# Soil thickness
SoilThickness = soil_thick.copy()
SoilMinThickness = np.full((ny, nx), 300.0, dtype=np.float32)
SoilMinThickness[~mask] = np.nan

# River boundary conditions
riverdepth_bc = np.full((ny, nx), 2.0, dtype=np.float64)
riverdepth_bc[~mask] = np.nan

riverlength_bc = np.full((ny, nx), 1000.0, dtype=np.float64)
riverlength_bc[~mask] = np.nan

print("Default constants set:")
print(f"  Cfmax: {np.nanmean(Cfmax):.2f}")
print(f"  InfiltCapSoil: {np.nanmean(InfiltCapSoil):.0f}")
print(f"  SoilThickness: {np.nanmean(SoilThickness):.0f} mm")

# =============================================================================
# 11. SUBGRID AND ADDITIONAL PARAMETERS
# =============================================================================
print("\n" + "=" * 80)
print("STEP 11: Creating subgrid and additional parameters...")
print("=" * 80)

# Subgrid outlet index
idx_out = np.arange(ny * nx).reshape(ny, nx).astype(np.float64)
idx_out[~mask] = np.nan

# Subgrid outlet coordinates
x_out = np.broadcast_to(lon, (ny, nx)).astype(np.float64).copy()
x_out[~mask] = np.nan

y_out = np.broadcast_to(lat.reshape(-1, 1), (ny, nx)).astype(np.float64).copy()
y_out[~mask] = np.nan

# Inflow placeholder
inflow = np.zeros((366, ny, nx), dtype=np.float32)
for t in range(366):
    inflow[t][~mask] = np.nan

# Floodplain placeholders
Floodplain = np.zeros((ny, nx), dtype=np.float32)
Floodplain[~mask] = np.nan

FloodplainZ = dem_vals.copy()
FloodplainZ[~mask] = np.nan

flood_depths = [0.5, 1.0, 1.5, 2.0, 3.0]
floodplain_volume = np.zeros((5, ny, nx), dtype=np.float32)
for i, depth in enumerate(flood_depths):
    floodplain_volume[i] = depth * (cell_size ** 2)
    floodplain_volume[i][~mask] = np.nan

# Reservoir placeholders
ResMaxVolume = np.full((ny, nx), 5e7, dtype=np.float32)
ResMaxVolume[~mask] = np.nan

ResDemand = np.full((ny, nx), 1.0, dtype=np.float32)
ResDemand[~mask] = np.nan

ResMaxRelease = np.full((ny, nx), 10.0, dtype=np.float32)
ResMaxRelease[~mask] = np.nan

ResSimpleArea = np.full((ny, nx), 5e6, dtype=np.float32)
ResSimpleArea[~mask] = np.nan

ResTargetFullFrac = np.full((ny, nx), 0.7, dtype=np.float32)
ResTargetFullFrac[~mask] = np.nan

ResTargetMinFrac = np.full((ny, nx), 0.2, dtype=np.float32)
ResTargetMinFrac[~mask] = np.nan

wflow_reservoirareas = np.full((ny, nx), np.nan, dtype=np.float64)
wflow_reservoirlocs = np.full((ny, nx), np.nan, dtype=np.float64)
wflow_gauges_grdc = np.full((ny, nx), np.nan, dtype=np.float64)

# Soil class
wflow_soil = np.full((ny, nx), 1.0, dtype=np.float64)
wflow_soil[~mask] = np.nan

print("Subgrid and additional parameters created")

# =============================================================================
# 12. CREATE NETCDF DATASET
# =============================================================================
print("\n" + "=" * 80)
print("STEP 12: Creating NetCDF dataset...")
print("=" * 80)

# Coordinates
time_coord = np.arange(1, 13)  # 1-12 for months
layer_coord = np.arange(1, N_LAYERS_NC + 1)  # 1-4 for layers (workaround)
flood_depth_coord = np.array(flood_depths)
time_inflow_coord = np.arange(1, 367)

# Create dataset
ds = xr.Dataset(
    coords={
        'lat': (['lat'], lat, {'units': 'degrees_north', 'axis': 'Y'}),
        'lon': (['lon'], lon, {'units': 'degrees_east', 'axis': 'X'}),
        'time': (['time'], time_coord, {'units': 'months', 'long_name': 'month of year'}),
        'layer': (['layer'], layer_coord, {'units': '-', 'long_name': 'soil layer'}),
        'flood_depth': (['flood_depth'], flood_depth_coord, {'units': 'm'}),
        'time_inflow': (['time_inflow'], time_inflow_coord, {'units': 'days'}),
    }
)

# Add spatial reference
ds['spatial_ref'] = xr.DataArray(0, attrs={
    'crs_wkt': 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
    'spatial_ref': 'EPSG:4326',
})

# =============================================================================
# ADD ALL VARIABLES TO DATASET
# =============================================================================
print("Adding variables to dataset...")

# Core DEM and flow
ds['wflow_dem'] = xr.DataArray(dem_vals, dims=['lat', 'lon'], attrs={'units': 'm', 'long_name': 'elevation'})
ds['wflow_ldd'] = xr.DataArray(ldd, dims=['lat', 'lon'], attrs={'long_name': 'ldd flow direction'})
ds['wflow_uparea'] = xr.DataArray(uparea, dims=['lat', 'lon'], attrs={'units': 'km2', 'long_name': 'upstream area'})
ds['wflow_landuse'] = xr.DataArray(landuse_vals, dims=['lat', 'lon'], attrs={'long_name': 'land cover class'})
ds['Slope'] = xr.DataArray(slope.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm.m-1', 'long_name': 'surface slope'})

# River network
ds['wflow_river'] = xr.DataArray(wflow_river, dims=['lat', 'lon'], attrs={'long_name': 'river mask'})
ds['wflow_riverwidth'] = xr.DataArray(riverwidth.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm', 'long_name': 'river width'})
ds['wflow_riverlength'] = xr.DataArray(riverlength.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm', 'long_name': 'river length'})
ds['wflow_streamorder'] = xr.DataArray(stream_order, dims=['lat', 'lon'], attrs={'long_name': 'stream order'})
ds['RiverSlope'] = xr.DataArray(river_slope.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm.m-1', 'long_name': 'river slope'})
ds['RiverDepth'] = xr.DataArray(riverdepth.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm', 'long_name': 'river depth'})
ds['RiverZ'] = xr.DataArray(riverz.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm+REF', 'long_name': 'river bed elevation'})
ds['N_River'] = xr.DataArray(N_river, dims=['lat', 'lon'], attrs={'long_name': 'Manning roughness for rivers'})

# Subcatchments and gauges
ds['wflow_subcatch'] = xr.DataArray(wflow_subcatch, dims=['lat', 'lon'], attrs={'long_name': 'subcatchment ID'})
ds['wflow_gauges'] = xr.DataArray(wflow_gauges, dims=['lat', 'lon'], attrs={'long_name': 'gauge locations'})
ds['wflow_pits'] = xr.DataArray(wflow_pits, dims=['lat', 'lon'], attrs={'long_name': 'pit locations'})
ds['subare'] = xr.DataArray(subare, dims=['lat', 'lon'], attrs={'units': 'km2', 'long_name': 'subcatchment area'})

# Soil properties (4 layers - workaround)
ds['thetaS'] = xr.DataArray(thetaS, dims=['lat', 'lon'], attrs={'long_name': 'saturated water content'})
ds['thetaR'] = xr.DataArray(thetaR, dims=['lat', 'lon'], attrs={'long_name': 'residual water content'})
ds['c'] = xr.DataArray(c_layers, dims=['layer', 'lat', 'lon'], attrs={'long_name': 'Brooks-Corey c parameter'})
ds['kv'] = xr.DataArray(kv_layers, dims=['layer', 'lat', 'lon'], attrs={'long_name': 'vertical Ksat by layer'})
ds['sl'] = xr.DataArray(sl_layers, dims=['layer', 'lat', 'lon'], attrs={'long_name': 'soil layer thickness'})
ds['M'] = xr.DataArray(M_param, dims=['lat', 'lon'], attrs={'long_name': 'Ksat decay parameter M'})
ds['M_'] = xr.DataArray(M_alt, dims=['lat', 'lon'], attrs={'long_name': 'alternative M parameter'})
ds['M_original'] = xr.DataArray(M_param, dims=['lat', 'lon'], attrs={'long_name': 'original M'})
ds['M_original_'] = xr.DataArray(M_alt, dims=['lat', 'lon'], attrs={'long_name': 'original M alternative'})
ds['f'] = xr.DataArray(f_param, dims=['lat', 'lon'], attrs={'long_name': 'Ksat exponential decay'})
ds['f_'] = xr.DataArray(f_alt, dims=['lat', 'lon'], attrs={'long_name': 'alternative f parameter'})

# Ksat at depths
ds['KsatVer'] = xr.DataArray(ksat_base, dims=['lat', 'lon'], attrs={'units': 'mm/day', 'long_name': 'saturated hydraulic conductivity'})
for depth_name, ksat_arr in ksat_depths.items():
    ds[depth_name] = xr.DataArray(ksat_arr, dims=['lat', 'lon'], attrs={'units': 'mm/day'})

# Soil thickness
ds['SoilThickness'] = xr.DataArray(SoilThickness.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'mm'})
ds['SoilMinThickness'] = xr.DataArray(SoilMinThickness, dims=['lat', 'lon'], attrs={'units': 'mm'})

# Vegetation parameters
ds['LAI'] = xr.DataArray(LAI, dims=['time', 'lat', 'lon'], attrs={'category': 'landuse', 'long_name': 'Leaf Area Index'})
ds['Kext'] = xr.DataArray(Kext, dims=['lat', 'lon'], attrs={'long_name': 'light extinction coefficient'})
ds['RootingDepth'] = xr.DataArray(RootingDepth, dims=['lat', 'lon'], attrs={'units': 'mm'})
ds['Sl'] = xr.DataArray(Sl_veg, dims=['lat', 'lon'], attrs={'long_name': 'specific leaf storage'})
ds['Swood'] = xr.DataArray(Swood, dims=['lat', 'lon'], attrs={'long_name': 'stem storage'})
ds['PathFrac'] = xr.DataArray(PathFrac, dims=['lat', 'lon'], attrs={'long_name': 'impervious fraction'})
ds['WaterFrac'] = xr.DataArray(WaterFrac, dims=['lat', 'lon'], attrs={'long_name': 'water fraction'})
ds['N'] = xr.DataArray(N_surface, dims=['lat', 'lon'], attrs={'long_name': 'Manning roughness for surface'})

# Default constants
ds['Cfmax'] = xr.DataArray(Cfmax, dims=['lat', 'lon'])
ds['G_Cfmax'] = xr.DataArray(G_Cfmax, dims=['lat', 'lon'])
ds['TT'] = xr.DataArray(TT, dims=['lat', 'lon'])
ds['TTI'] = xr.DataArray(TTI, dims=['lat', 'lon'])
ds['TTM'] = xr.DataArray(TTM, dims=['lat', 'lon'])
ds['G_TT'] = xr.DataArray(G_TT, dims=['lat', 'lon'])
ds['G_SIfrac'] = xr.DataArray(G_SIfrac, dims=['lat', 'lon'])
ds['WHC'] = xr.DataArray(WHC, dims=['lat', 'lon'])
ds['cf_soil'] = xr.DataArray(cf_soil, dims=['lat', 'lon'])
ds['InfiltCapPath'] = xr.DataArray(InfiltCapPath, dims=['lat', 'lon'])
ds['InfiltCapSoil'] = xr.DataArray(InfiltCapSoil, dims=['lat', 'lon'])
ds['KsatHorFrac'] = xr.DataArray(KsatHorFrac, dims=['lat', 'lon'])
ds['MaxLeakage'] = xr.DataArray(MaxLeakage, dims=['lat', 'lon'])
ds['EoverR'] = xr.DataArray(EoverR, dims=['lat', 'lon'])
ds['rootdistpar'] = xr.DataArray(rootdistpar, dims=['lat', 'lon'])
ds['riverdepth_bc'] = xr.DataArray(riverdepth_bc, dims=['lat', 'lon'])
ds['riverlength_bc'] = xr.DataArray(riverlength_bc, dims=['lat', 'lon'])

# Subgrid parameters
ds['idx_out'] = xr.DataArray(idx_out, dims=['lat', 'lon'], attrs={'long_name': 'subgrid outlet index'})
ds['x_out'] = xr.DataArray(x_out, dims=['lat', 'lon'], attrs={'long_name': 'subgrid outlet x coordinate'})
ds['y_out'] = xr.DataArray(y_out, dims=['lat', 'lon'], attrs={'long_name': 'subgrid outlet y coordinate'})
ds['inflow'] = xr.DataArray(inflow, dims=['time_inflow', 'lat', 'lon'])

# Floodplain
ds['Floodplain'] = xr.DataArray(Floodplain, dims=['lat', 'lon'])
ds['FloodplainZ'] = xr.DataArray(FloodplainZ, dims=['lat', 'lon'])
ds['floodplain_volume'] = xr.DataArray(floodplain_volume, dims=['flood_depth', 'lat', 'lon'])

# Reservoirs
ds['ResMaxVolume'] = xr.DataArray(ResMaxVolume, dims=['lat', 'lon'])
ds['ResDemand'] = xr.DataArray(ResDemand, dims=['lat', 'lon'])
ds['ResMaxRelease'] = xr.DataArray(ResMaxRelease, dims=['lat', 'lon'])
ds['ResSimpleArea'] = xr.DataArray(ResSimpleArea, dims=['lat', 'lon'])
ds['ResTargetFullFrac'] = xr.DataArray(ResTargetFullFrac, dims=['lat', 'lon'])
ds['ResTargetMinFrac'] = xr.DataArray(ResTargetMinFrac, dims=['lat', 'lon'])
ds['wflow_reservoirareas'] = xr.DataArray(wflow_reservoirareas, dims=['lat', 'lon'])
ds['wflow_reservoirlocs'] = xr.DataArray(wflow_reservoirlocs, dims=['lat', 'lon'])
ds['wflow_gauges_grdc'] = xr.DataArray(wflow_gauges_grdc, dims=['lat', 'lon'])
ds['wflow_soil'] = xr.DataArray(wflow_soil, dims=['lat', 'lon'])

# =============================================================================
# 13. SAVE TO NETCDF
# =============================================================================
print("\n" + "=" * 80)
print("STEP 13: Saving to NetCDF...")
print("=" * 80)

# Create output directory if needed
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

ds.to_netcdf(OUTPUT_FILE, format='NETCDF4')

print(f"\nSaved to: {OUTPUT_FILE}")
print(f"Total variables: {len(ds.data_vars)}")
print(f"Dimensions: {dict(ds.dims)}")
print(f"File size: {os.path.getsize(OUTPUT_FILE) / 1e6:.1f} MB")

# Print outlet info for TOML config
print("\n" + "=" * 80)
print("OUTLET INFORMATION FOR TOML CONFIG")
print("=" * 80)
print(f"Outlet coordinates: x={lon[outlet_idx[1]]:.4f}, y={lat[outlet_idx[0]]:.4f}")
print(f"Upstream area: {uparea[outlet_idx]:,.1f} km²")

print("\n" + "=" * 80)
print(f"DONE! staticmaps.nc created for {REGION}")
print(f"Soil layers: {N_LAYERS_NC} layers in NC (workaround for Brooks-Corey bug)")
print(f"TOML should use: soil_layer__thickness = {SOIL_LAYERS}")
print("=" * 80)
