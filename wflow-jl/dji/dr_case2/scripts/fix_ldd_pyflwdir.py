#!/usr/bin/env python3
"""
Fix LDD (Local Drain Direction) using pyflwdir for Djibouti.

This script derives a cycle-free LDD directly from the DEM using pyflwdir,
which properly handles flow routing to avoid cycles that can crash Wflow.

The original D8→LDD conversion in derive_staticmaps.py can create cycles.
This script fixes that by:
1. Loading the DEM from staticmaps.nc
2. Using pyflwdir.from_dem() to derive proper flow direction
3. Recalculating river network and related parameters
4. Updating staticmaps.nc with corrected values

Input: data/input/staticmaps.nc with potentially cyclic LDD
Output: data/input/staticmaps.nc with corrected LDD and river parameters

Usage:
    cd /mnt/hydromt_data/bdi_trail2/dr_case2
    python3 scripts/fix_ldd_pyflwdir.py
"""

import numpy as np
import xarray as xr
import pyflwdir
import warnings
from pathlib import Path
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURATION
# =============================================================================

# Use script location to determine paths
script_dir = Path(__file__).parent.absolute()
case_dir = script_dir.parent  # dr_case2/
STATICMAPS_FILE = case_dir / "data" / "input" / "staticmaps.nc"
RIVER_THRESHOLD = 10.0  # km² upstream area for river network

# =============================================================================
# LOAD STATICMAPS
# =============================================================================
print("=" * 80)
print("STEP 1: Loading staticmaps...")
print("=" * 80)

ds = xr.open_dataset(STATICMAPS_FILE)

dem = ds['wflow_dem'].values
lat = ds['lat'].values
lon = ds['lon'].values
ny, nx = len(lat), len(lon)

# Create mask
mask = ~np.isnan(dem)
print(f"Grid size: {ny} x {nx}")
print(f"Valid cells: {mask.sum()}")

# Fill NaN in DEM for pyflwdir (it doesn't handle NaN well)
dem_filled = np.where(np.isnan(dem), -9999, dem)

# =============================================================================
# DERIVE LDD USING PYFLWDIR
# =============================================================================
print("\n" + "=" * 80)
print("STEP 2: Deriving flow direction from DEM using pyflwdir...")
print("=" * 80)

# Calculate cell size in meters
cell_size_deg = abs(lat[1] - lat[0])
cell_size_m = cell_size_deg * 111000  # Approximate meters per degree

# Check if latitude is descending (common for rasters)
if lat[0] > lat[-1]:
    latlon = True  # Latitude decreasing (north to south)
    transform = None
else:
    latlon = False
    transform = None

print(f"Cell size: {cell_size_m:.1f} m")
print(f"Latitude direction: {'descending' if lat[0] > lat[-1] else 'ascending'}")

# Derive flow direction from DEM
# pyflwdir.from_dem returns a FlwdirRaster object
flw = pyflwdir.from_dem(
    dem_filled,
    nodata=-9999,
    outlets='edge',  # Allow flow to edges
    latlon=True,     # Geographic coordinates
)

print(f"Flow direction derived successfully")
print(f"Number of pits: {flw.idxs_pit.size}")

# Get LDD in PCRaster format
ldd = flw.to_ldd()
ldd = ldd.astype(np.float32)
ldd[~mask] = np.nan

# Verify LDD values
ldd_valid = ldd[~np.isnan(ldd)]
print(f"LDD unique values: {np.unique(ldd_valid).astype(int)}")
print(f"Pit cells (value=5): {(ldd == 5).sum()}")

# =============================================================================
# RECALCULATE UPSTREAM AREA
# =============================================================================
print("\n" + "=" * 80)
print("STEP 3: Calculating upstream area...")
print("=" * 80)

# Calculate upstream area in number of cells
uparea_cells = flw.upstream_area()

# Convert to km²
cell_area_km2 = (cell_size_m / 1000) ** 2
uparea = uparea_cells * cell_area_km2
uparea = uparea.astype(np.float32)
uparea[~mask] = np.nan

print(f"Upstream area range: {np.nanmin(uparea):.1f} - {np.nanmax(uparea):.1f} km²")

# =============================================================================
# DERIVE NEW RIVER NETWORK
# =============================================================================
print("\n" + "=" * 80)
print("STEP 4: Deriving river network...")
print("=" * 80)

# River mask based on upstream area threshold
wflow_river = np.where(uparea >= RIVER_THRESHOLD, 1.0, np.nan)
wflow_river[~mask] = np.nan

river_cells = np.nansum(wflow_river == 1)
print(f"River threshold: {RIVER_THRESHOLD} km²")
print(f"River cells: {river_cells:.0f}")

# =============================================================================
# RECALCULATE RIVER PARAMETERS
# =============================================================================
print("\n" + "=" * 80)
print("STEP 5: Calculating river parameters...")
print("=" * 80)

# River width: W = 1.22 * A^0.557
a_width, b_width = 1.22, 0.557
riverwidth = a_width * (uparea ** b_width)
riverwidth = np.clip(riverwidth, 30, 500)
riverwidth[wflow_river != 1] = np.nan
riverwidth[~mask] = np.nan
print(f"River width range: {np.nanmin(riverwidth):.1f} - {np.nanmax(riverwidth):.1f} m")

# River depth: D = 0.27 * A^0.39
c_depth, d_depth = 0.27, 0.39
riverdepth = c_depth * (uparea ** d_depth)
riverdepth = np.clip(riverdepth, 1.0, 5.0)
riverdepth[wflow_river != 1] = np.nan
riverdepth[~mask] = np.nan
print(f"River depth range: {np.nanmin(riverdepth):.2f} - {np.nanmax(riverdepth):.2f} m")

# River Z (bed elevation)
riverz = dem - riverdepth
riverz[wflow_river != 1] = np.nan
riverz[~mask] = np.nan

# River length per cell (diagonal)
riverlength = np.full((ny, nx), cell_size_m * 1.414, dtype=np.float32)
riverlength[wflow_river != 1] = np.nan
riverlength[~mask] = np.nan
print(f"River length per cell: ~{cell_size_m * 1.414:.1f} m")

# River slope (from surface slope at river cells)
dy, dx = np.gradient(dem, cell_size_m)
slope = np.sqrt(dx**2 + dy**2)
slope = np.clip(slope, 0.0001, 1.0)

river_slope = slope.copy()
river_slope = np.clip(river_slope, 0.00001, 0.1)
river_slope[wflow_river != 1] = np.nan
river_slope[~mask] = np.nan
print(f"River slope range: {np.nanmin(river_slope):.6f} - {np.nanmax(river_slope):.4f}")

# Stream order based on upstream area
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

# =============================================================================
# FIND MAIN OUTLET
# =============================================================================
print("\n" + "=" * 80)
print("STEP 6: Identifying main outlet...")
print("=" * 80)

pit_mask = (ldd == 5) & mask
if pit_mask.sum() > 0:
    pit_uparea = np.where(pit_mask, uparea, 0)
    outlet_idx = np.unravel_index(np.argmax(pit_uparea), pit_uparea.shape)
    outlet_lat = lat[outlet_idx[0]]
    outlet_lon = lon[outlet_idx[1]]
    outlet_uparea = uparea[outlet_idx]
    print(f"Main outlet at: ({outlet_lon:.4f}°E, {outlet_lat:.4f}°N)")
    print(f"Outlet upstream area: {outlet_uparea:.1f} km²")

    # Update gauges
    wflow_gauges = np.full((ny, nx), np.nan)
    wflow_gauges[outlet_idx] = 1.0

    wflow_pits = np.full((ny, nx), np.nan)
    wflow_pits[outlet_idx] = 1.0
else:
    print("WARNING: No pit cells found!")
    wflow_gauges = ds['wflow_gauges'].values
    wflow_pits = ds['wflow_pits'].values if 'wflow_pits' in ds else np.full((ny, nx), np.nan)

# =============================================================================
# UPDATE DATASET
# =============================================================================
print("\n" + "=" * 80)
print("STEP 7: Updating staticmaps dataset...")
print("=" * 80)

# Update variables
ds['wflow_ldd'] = xr.DataArray(ldd, dims=['lat', 'lon'], attrs={'long_name': 'ldd flow direction'})
ds['wflow_uparea'] = xr.DataArray(uparea, dims=['lat', 'lon'], attrs={'units': 'km2', 'long_name': 'upstream area'})
ds['wflow_river'] = xr.DataArray(wflow_river, dims=['lat', 'lon'], attrs={'long_name': 'river mask'})
ds['wflow_riverwidth'] = xr.DataArray(riverwidth, dims=['lat', 'lon'], attrs={'units': 'm', 'long_name': 'river width'})
ds['wflow_riverlength'] = xr.DataArray(riverlength, dims=['lat', 'lon'], attrs={'units': 'm', 'long_name': 'river length'})
ds['wflow_streamorder'] = xr.DataArray(stream_order, dims=['lat', 'lon'], attrs={'long_name': 'stream order'})
ds['RiverSlope'] = xr.DataArray(river_slope.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm.m-1', 'long_name': 'river slope'})
ds['RiverDepth'] = xr.DataArray(riverdepth.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm', 'long_name': 'river depth'})
ds['RiverZ'] = xr.DataArray(riverz.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm+REF', 'long_name': 'river bed elevation'})
ds['wflow_gauges'] = xr.DataArray(wflow_gauges, dims=['lat', 'lon'], attrs={'long_name': 'gauge locations'})
ds['wflow_pits'] = xr.DataArray(wflow_pits, dims=['lat', 'lon'], attrs={'long_name': 'pit locations'})

# Also update surface slope
ds['Slope'] = xr.DataArray(slope.astype(np.float32), dims=['lat', 'lon'], attrs={'units': 'm.m-1', 'long_name': 'surface slope'})

print("Variables updated:")
print("  - wflow_ldd (cycle-free)")
print("  - wflow_uparea")
print("  - wflow_river")
print("  - wflow_riverwidth")
print("  - wflow_riverlength")
print("  - wflow_streamorder")
print("  - RiverSlope")
print("  - RiverDepth")
print("  - RiverZ")
print("  - wflow_gauges")
print("  - wflow_pits")
print("  - Slope")

# =============================================================================
# SAVE UPDATED STATICMAPS
# =============================================================================
print("\n" + "=" * 80)
print("STEP 8: Saving updated staticmaps...")
print("=" * 80)

# Create backup
import shutil
backup_file = str(STATICMAPS_FILE).replace('.nc', '_backup.nc')
if not Path(backup_file).exists():
    shutil.copy(STATICMAPS_FILE, backup_file)
    print(f"Backup created: {backup_file}")

# Save updated file
ds.to_netcdf(STATICMAPS_FILE, format='NETCDF4')
print(f"Saved to: {STATICMAPS_FILE}")
print(f"File size: {STATICMAPS_FILE.stat().st_size / 1e6:.1f} MB")

ds.close()

# =============================================================================
# VERIFICATION
# =============================================================================
print("\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80)

# Reload and verify
ds_check = xr.open_dataset(STATICMAPS_FILE)

ldd_check = ds_check['wflow_ldd'].values
ldd_valid = ldd_check[~np.isnan(ldd_check)]
print(f"\nLDD values: {np.unique(ldd_valid).astype(int)}")
print(f"Pit cells: {(ldd_check == 5).sum()}")

river_check = ds_check['wflow_river'].values
print(f"River cells: {np.nansum(river_check == 1):.0f}")

uparea_check = ds_check['wflow_uparea'].values
print(f"Max upstream area: {np.nanmax(uparea_check):.1f} km²")

ds_check.close()

print("\n" + "=" * 80)
print("DONE! LDD fixed using pyflwdir")
print("=" * 80)
print("\nThe staticmaps.nc file now has a cycle-free LDD derived from the DEM.")
print("This should resolve any 'LDD cycles detected' errors in Wflow.")
