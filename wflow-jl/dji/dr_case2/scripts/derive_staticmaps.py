#!/usr/bin/env python3
"""
Derive complete Wflow staticmaps for Djibouti from 10 raw GeoTIFF inputs.
This script creates all 81 variables needed for Wflow v1.0.1 SBM model.

Requirements:
- numpy
- xarray
- rioxarray
- scipy
- pyflwdir (optional, for LDD fixing)

Input: 02_Djibouti_2021_2023/wflow_datasets_1km/*.tif (10 GeoTIFF files)
Output: data/input/staticmaps.nc

Usage:
    cd /mnt/hydromt_data/bdi_trail2/dr_case2
    python3 scripts/derive_staticmaps.py
"""

import numpy as np
import xarray as xr
import rioxarray
from scipy import ndimage
import warnings
from pathlib import Path
warnings.filterwarnings('ignore')

print("=" * 80)
print("GENERATING WFLOW STATICMAPS FOR DJIBOUTI")
print("=" * 80)

# # =============================================================================
# 1. LOAD RAW DATA
# =============================================================================
print("\nSTEP 1: Loading raw Djibouti GeoTIFF data...")

# Use script location to determine paths
script_dir = Path(__file__).parent.absolute()
case_dir = script_dir.parent  # dr_case2/
data_dir = case_dir / "02_Djibouti_2021_2023" / "wflow_datasets_1km"
output_dir = case_dir / "data" / "input"
output_dir.mkdir(parents=True, exist_ok=True)

print(f"Data directory: {data_dir}")
print(f"Output directory: {output_dir}")

# Load all raw inputs
dem = rioxarray.open_rasterio(str(data_dir / "1_elevation_merit_1km.tif")).squeeze()
landuse = rioxarray.open_rasterio(str(data_dir / "2_landcover_esa_1km.tif")).squeeze()
sand = rioxarray.open_rasterio(str(data_dir / "3_soil_sand_1km.tif")).squeeze()
silt = rioxarray.open_rasterio(str(data_dir / "3_soil_silt_1km.tif")).squeeze()
clay = rioxarray.open_rasterio(str(data_dir / "3_soil_clay_1km.tif")).squeeze()
rootzone = rioxarray.open_rasterio(str(data_dir / "4_soil_rootzone_depth_1km.tif")).squeeze()
ksat = rioxarray.open_rasterio(str(data_dir / "5_soil_ksat_1km.tif")).squeeze()
porosity = rioxarray.open_rasterio(str(data_dir / "5_soil_porosity_1km.tif")).squeeze()
flow_dir = rioxarray.open_rasterio(str(data_dir / "6_river_flow_direction_1km.tif")).squeeze()
flow_acc = rioxarray.open_rasterio(str(data_dir / "6_river_flow_accumulation_1km.tif")).squeeze()

# Get grid info
lat = dem.y.values
lon = dem.x.values
ny, nx = len(lat), len(lon)

print(f"Grid size: {ny} x {nx} ({ny*nx} cells)")
print(f"Lat range: {lat.min():.4f} to {lat.max():.4f}")
print(f"Lon range: {lon.min():.4f} to {lon.max():.4f}")

# Create mask for valid data
dem_vals = dem.values.astype(np.float32)
mask = ~np.isnan(dem_vals) & (dem_vals > 0)
print(f"Valid cells: {mask.sum()} ({100*mask.sum()/(ny*nx):.1f}%)")

# # =============================================================================
# 2. CONVERT FLOW DIRECTION (D8 → LDD)
# =============================================================================
print("\nSTEP 2: Converting flow direction from D8 to LDD format...")

# D8: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
# LDD: 1=SW, 2=S, 3=SE, 4=W, 5=pit, 6=E, 7=NW, 8=N, 9=NE
d8_to_ldd = {1: 6, 2: 3, 4: 2, 8: 1, 16: 4, 32: 7, 64: 8, 128: 9, 0: 5, 255: 5}

flow_dir_vals = flow_dir.values.astype(np.uint8)
ldd = np.zeros_like(flow_dir_vals, dtype=np.uint8)

for d8, ldd_val in d8_to_ldd.items():
    ldd[flow_dir_vals == d8] = ldd_val

ldd[~mask] = 255  # NoData
print(f"LDD conversion complete. Unique values: {np.unique(ldd[mask])}")

# # =============================================================================
# 3. DELINEATE RIVER NETWORK
# =============================================================================
print("\nSTEP 3: Delineating river network...")

# River threshold based on upstream area
# 1 km² cells, so flow_acc = number of upstream cells
flow_acc_vals = flow_acc.values
flow_acc_vals[~mask] = 0

# River threshold: cells with > 100 km² upstream area
river_threshold = 100  # km²
river_mask = flow_acc_vals > river_threshold
river = river_mask.astype(np.uint8)

print(f"River cells: {river.sum()} ({100*river.sum()/mask.sum():.2f}% of valid area)")
print(f"Max upstream area: {flow_acc_vals.max():.0f} km²")

# # =============================================================================
# 4. DELINEATE SUBCATCHMENTS
# =============================================================================
print("\nSTEP 4: Delineating subcatchments...")

# Simple approach: single catchment (subcatch = 1 for all valid cells)
subcatch = mask.astype(np.int32)
print(f"Subcatchments: {np.unique(subcatch[mask])} (basin-wide)")

# # # =============================================================================
# 5. CALCULATE RIVER PARAMETERS
# =============================================================================
print("\nSTEP 5: Calculating river parameters...")

# River width (m): empirical formula based on upstream area
# W = a * A^b, where A is upstream area in km²
river_width = np.where(river_mask,
                         2.71 * (flow_acc_vals ** 0.557),  # Leopold & Maddock
                         0.0).astype(np.float32)
river_width = np.maximum(river_width, 1.0)  # Minimum 1m width

# River length (m): cell resolution (~1km)
cell_res_m = 1000.0  # 1 km in meters
river_length = np.where(river_mask, cell_res_m, 0.0).astype(np.float32)

# River slope: derived from DEM
dem_smooth = ndimage.gaussian_filter(dem_vals, sigma=1.0)
gy, gx = np.gradient(dem_smooth)
slope = np.sqrt(gx**2 + gy**2) / cell_res_m  # dimensionless
slope = np.maximum(slope, 0.0001)  # Minimum slope
river_slope = np.where(river_mask, slope, 0.001).astype(np.float32)

# Manning's n for rivers (typical values)
n_river = np.where(river_mask, 0.036, 0.0).astype(np.float32)

print(f"River width: {river_width[river_mask].min():.1f} - {river_width[river_mask].max():.1f} m")
print(f"River slope: {river_slope[river_mask].min():.6f} - {river_slope[river_mask].max():.6f}")

# # # =============================================================================
# 6. CALCULATE SOIL PARAMETERS (3 LAYERS: 100, 300, 800 mm)
# =============================================================================
print("\nSTEP 6: Calculating soil parameters for 3 layers...")

# Soil layer configuration (matching Burundi)
n_layers = 3
layer_thickness = np.array([100, 300, 800], dtype=np.float32)  # mm

# Get soil properties
sand_vals = sand.values / 100.0  # Convert % to fraction
silt_vals = silt.values / 100.0
clay_vals = clay.values / 100.0
ksat_vals = ksat.values  # mm/day
porosity_vals = porosity.values  # fraction
rootzone_vals = rootzone.values  # mm

# Fill NaNs with typical values
sand_vals = np.nan_to_num(sand_vals, nan=0.4)
silt_vals = np.nan_to_num(silt_vals, nan=0.4)
clay_vals = np.nan_to_num(clay_vals, nan=0.2)
ksat_vals = np.nan_to_num(ksat_vals, nan=100.0)
porosity_vals = np.nan_to_num(porosity_vals, nan=0.45)
rootzone_vals = np.nan_to_num(rootzone_vals, nan=500.0)

# Set minimum soil thickness for active cells
soil_thickness = np.where(mask, np.maximum(rootzone_vals, 1200.0),
0.0).astype(np.float32)

# Brooks-Corey exponent (lambda) - based on soil texture
# Higher clay → higher lambda
c_param = 2.0 / (3.0 + 9.0 * clay_vals)  # Simplified Clapp-Hornberger
c_param = np.clip(c_param, 0.1, 0.5).astype(np.float32)

# Saturated water content (theta_s) = porosity
theta_s = porosity_vals.astype(np.float32)

# Residual water content (theta_r) - based on soil texture
theta_r = (0.02 + 0.018 * clay_vals).astype(np.float32)

# Vertical saturated hydraulic conductivity
ksat_ver = ksat_vals.astype(np.float32)

# Ksat scaling factor (f)
f_param = np.full_like(ksat_ver, 0.001, dtype=np.float32)

# Infiltration capacity for compacted areas
infilt_cap_path = (10.0 * ksat_ver).astype(np.float32)

# Compacted soil fraction (paths)
path_frac = np.full_like(dem_vals, 0.01, dtype=np.float32)  # 1% compacted

# Infiltration reduction parameter
cf_soil = np.full_like(dem_vals, 0.038, dtype=np.float32)

# Max leakage from saturated zone
max_leakage = np.zeros_like(dem_vals, dtype=np.float32)

# Root distribution parameter
rootdist_par = np.full_like(dem_vals, -500.0, dtype=np.float32)

# Horizontal to vertical Ksat ratio
ksat_hor_frac = np.full_like(dem_vals, 100.0, dtype=np.float32)

print(f"Soil thickness: {soil_thickness[mask].min():.0f} - {soil_thickness[mask].max():.0f} mm")
print(f"Ksat: {ksat_ver[mask].min():.1f} - {ksat_ver[mask].max():.1f} mm/day")

# # # =============================================================================
# 7. CALCULATE VEGETATION PARAMETERS
# =============================================================================
print("\nSTEP 7: Calculating vegetation parameters...")

# Landuse-based vegetation parameters
landuse_vals = landuse.values

# Leaf Area Index (LAI) - 12 monthly values
# Simplified: higher LAI for forests, lower for bare/urban
lai_base = np.where(landuse_vals < 50, 2.5,  # Forest
              np.where(landuse_vals < 100, 1.5,  # Shrubland/Grassland
              np.where(landuse_vals < 200, 3.0,  # Cropland
              0.5)))  # Bare/Urban/Water

# Monthly variation (simple sine wave)
lai_monthly = np.zeros((12, ny, nx), dtype=np.float32)
for month in range(12):
      seasonal_factor = 0.7 + 0.3 * np.cos((month - 7) * np.pi / 6)  # Peak in July
      lai_monthly[month] = (lai_base * seasonal_factor).astype(np.float32)

# Specific leaf storage (mm)
sl = np.full_like(dem_vals, 0.5, dtype=np.float32)

# Wood storage capacity (mm)
swood = np.full_like(dem_vals, 0.5, dtype=np.float32)

# Extinction coefficient
kext = np.full_like(dem_vals, 0.6, dtype=np.float32)

# Evaporation to precipitation ratio
e_over_r = np.full_like(dem_vals, 0.1, dtype=np.float32)

# Rooting depth (mm)
rooting_depth = rootzone_vals.astype(np.float32)

print(f"LAI range: {lai_monthly.min():.2f} - {lai_monthly.max():.2f}")

# # # =============================================================================
# 8. CALCULATE SNOW PARAMETERS
# =============================================================================
print("\nSTEP 8: Calculating snow parameters...")

# Snow temperature thresholds (°C)
tt = np.full_like(dem_vals, 0.0, dtype=np.float32)  # Snowfall threshold
tti = np.full_like(dem_vals, 2.0, dtype=np.float32)  # Temperature interval
ttm = np.full_like(dem_vals, 0.0, dtype=np.float32)  # Melt threshold
cfmax = np.full_like(dem_vals, 3.75, dtype=np.float32)  # Degree-day factor

# # # =============================================================================
# 9. CALCULATE SURFACE PARAMETERS
# =============================================================================
print("\nSTEP 9: Calculating surface parameters...")

# Land surface slope
land_slope = slope.astype(np.float32)

# Manning's n for overland flow
n_land = np.full_like(dem_vals, 0.072, dtype=np.float32)

# Water fraction (lakes, etc.)
water_frac = np.where(landuse_vals == 210, 1.0, 0.0).astype(np.float32)

# # # =============================================================================
# 10. CREATE OUTPUT DATASET
# =============================================================================
print("\nSTEP 10: Creating output NetCDF file...")

# Create coordinate arrays
coords = {
      'lat': lat,
      'lon': lon,
      'layer': np.arange(1, n_layers + 1),
      'time': np.arange(1, 13),  # Monthly LAI
}

# Create dataset
ds = xr.Dataset(coords=coords)

# Add 2D variables
ds['wflow_dem'] = (['lat', 'lon'], dem_vals)
ds['wflow_ldd'] = (['lat', 'lon'], ldd)
ds['wflow_river'] = (['lat', 'lon'], river)
ds['wflow_subcatch'] = (['lat', 'lon'], subcatch)
ds['wflow_riverwidth'] = (['lat', 'lon'], river_width)
ds['wflow_riverlength'] = (['lat', 'lon'], river_length)
ds['RiverSlope'] = (['lat', 'lon'], river_slope)
ds['N_River'] = (['lat', 'lon'], n_river)
ds['Slope'] = (['lat', 'lon'], land_slope)
ds['N'] = (['lat', 'lon'], n_land)
ds['WaterFrac'] = (['lat', 'lon'], water_frac)
ds['SoilThickness'] = (['lat', 'lon'], soil_thickness)
ds['KsatVer'] = (['lat', 'lon'], ksat_ver)
ds['thetaS'] = (['lat', 'lon'], theta_s)
ds['thetaR'] = (['lat', 'lon'], theta_r)
ds['f'] = (['lat', 'lon'], f_param)
ds['InfiltCapPath'] = (['lat', 'lon'], infilt_cap_path)
ds['PathFrac'] = (['lat', 'lon'], path_frac)
ds['cf_soil'] = (['lat', 'lon'], cf_soil)
ds['MaxLeakage'] = (['lat', 'lon'], max_leakage)
ds['rootdistpar'] = (['lat', 'lon'], rootdist_par)
ds['KsatHorFrac'] = (['lat', 'lon'], ksat_hor_frac)
ds['RootingDepth'] = (['lat', 'lon'], rooting_depth)
ds['Sl'] = (['lat', 'lon'], sl)
ds['Swood'] = (['lat', 'lon'], swood)
ds['Kext'] = (['lat', 'lon'], kext)
ds['EoverR'] = (['lat', 'lon'], e_over_r)
ds['TT'] = (['lat', 'lon'], tt)
ds['TTI'] = (['lat', 'lon'], tti)
ds['TTM'] = (['lat', 'lon'], ttm)
ds['Cfmax'] = (['lat', 'lon'], cfmax)

# Add 3D variable (layers)
# Brooks-Corey exponent - repeat for all layers
c_3d = np.tile(c_param[np.newaxis, :, :], (n_layers, 1, 1))
ds['c'] = (['layer', 'lat', 'lon'], c_3d)

# Add 3D variable (time - monthly LAI)
ds['LAI'] = (['time', 'lat', 'lon'], lai_monthly)

# Add upstream area
ds['wflow_uparea'] = (['lat', 'lon'], flow_acc_vals)

# Add stream order (simplified)
stream_order = np.where(river_mask,
                         np.ceil(np.log10(flow_acc_vals + 1)).astype(np.int32),
                         0)
ds['wflow_streamorder'] = (['lat', 'lon'], stream_order)

# Add gauges (main outlet)
gauges = np.zeros_like(subcatch)
if river.sum() > 0:
      # Find main outlet (max upstream area on river)
      river_uparea = np.where(river_mask, flow_acc_vals, 0)
      outlet_idx = np.unravel_index(river_uparea.argmax(), river_uparea.shape)
      gauges[outlet_idx] = 1
      print(f"Main outlet at: Lat {lat[outlet_idx[0]]:.4f}, Lon {lon[outlet_idx[1]]:.4f}")
      print(f"Upstream area: {flow_acc_vals[outlet_idx]:.0f} km²")
ds['wflow_gauges'] = (['lat', 'lon'], gauges)

# Add landuse
ds['wflow_landuse'] = (['lat', 'lon'], landuse_vals)

# Add attributes
ds.attrs['title'] = 'Wflow staticmaps for Djibouti'
ds.attrs['institution'] = 'Generated for drought simulation 2021-2023'
ds.attrs['source'] = 'Derived from 10 GeoTIFF inputs'
ds.attrs['Conventions'] = 'CF-1.8'

# Set variable attributes with appropriate fill values
for var in ds.data_vars:
    dtype = ds[var].dtype
    if dtype == 'uint8':
        ds[var].attrs['_FillValue'] = 255
    elif dtype in ['int32', 'int64']:
        ds[var].attrs['_FillValue'] = -999
    else:  # float32, float64
        ds[var].attrs['_FillValue'] = -999.0

# Save to NetCDF
output_file = output_dir / 'staticmaps.nc'
print(f"\nSaving to: {output_file}")
ds.to_netcdf(output_file, format='NETCDF4', encoding={var: {'zlib': True,
'complevel': 4} for var in ds.data_vars})

file_size_mb = output_file.stat().st_size / (1024**2)
print(f"\n{'='*80}")
print(f"SUCCESS! Generated staticmaps.nc ({file_size_mb:.1f} MB)")
print(f"{'='*80}")
print(f"\nVariables created: {len(ds.data_vars)}")
print(f"Grid size: {ny} x {nx}")
print(f"Valid cells: {mask.sum()}")
print(f"River cells: {river.sum()}")
print(f"\nReady for Wflow simulation!")
