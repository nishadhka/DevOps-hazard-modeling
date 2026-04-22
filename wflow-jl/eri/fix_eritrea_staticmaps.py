#!/usr/bin/env python3
"""
Fix Eritrea staticmaps by setting minimum soil thickness for active cells.

The Eritrea staticmaps has 34.4% of cells with SoilThickness = 0, which causes
Wflow to crash when calculating hydraulic conductivity at depth. This script
sets a minimum soil thickness for all cells within the model domain (where
wflow_subcatch > 0) to avoid indexing errors.
"""

import xarray as xr
import numpy as np
import shutil
from pathlib import Path

def fix_staticmaps():
    # Backup original file
    input_file = 'data/input/staticmaps.nc'
    backup_file = 'data/input/staticmaps_eritrea_original.nc'

    print(f"Creating backup: {backup_file}")
    shutil.copy2(input_file, backup_file)

    # Open dataset
    print(f"\nOpening {input_file}...")
    ds = xr.open_dataset(input_file)

    # Check current state
    soil_thick = ds['SoilThickness'].values
    subcatch = ds['wflow_subcatch'].values

    print(f"\nBefore fix:")
    print(f"  Total cells: {soil_thick.size}")
    print(f"  Zero thickness cells: {(soil_thick == 0).sum()} ({100*(soil_thick == 0).sum()/soil_thick.size:.1f}%)")
    print(f"  Active basin cells (subcatch > 0): {(subcatch > 0).sum()}")
    print(f"  Active cells with zero thickness: {((subcatch > 0) & (soil_thick == 0)).sum()}")

    # Set minimum soil thickness for active cells (where subcatch > 0)
    MIN_SOIL_THICKNESS = 100.0  # mm

    # Create mask for cells that need fixing
    needs_fix = (subcatch > 0) & (soil_thick < MIN_SOIL_THICKNESS)

    if needs_fix.sum() > 0:
        print(f"\nFixing {needs_fix.sum()} cells with thickness < {MIN_SOIL_THICKNESS} mm...")

        # Update SoilThickness
        soil_thick_fixed = soil_thick.copy()
        soil_thick_fixed[needs_fix] = MIN_SOIL_THICKNESS

        # Update the dataset
        ds['SoilThickness'].values = soil_thick_fixed

        print(f"\nAfter fix:")
        print(f"  Zero thickness cells: {(soil_thick_fixed == 0).sum()} ({100*(soil_thick_fixed == 0).sum()/soil_thick_fixed.size:.1f}%)")
        print(f"  Active cells with zero thickness: {((subcatch > 0) & (soil_thick_fixed == 0)).sum()}")
        print(f"  Min thickness in active cells: {soil_thick_fixed[subcatch > 0].min():.1f} mm")
        print(f"  Mean thickness in active cells: {soil_thick_fixed[subcatch > 0].mean():.1f} mm")

        # Save fixed dataset
        print(f"\nSaving fixed staticmaps to {input_file}...")
        ds.to_netcdf(input_file, format='NETCDF4')
        print("✓ Fixed staticmaps saved successfully!")

    else:
        print("\nNo cells need fixing.")

    ds.close()
    print(f"\nOriginal file backed up to: {backup_file}")

if __name__ == '__main__':
    fix_staticmaps()
