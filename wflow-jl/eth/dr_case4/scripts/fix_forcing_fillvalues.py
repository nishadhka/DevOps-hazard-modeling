#!/usr/bin/env python3
"""
Fix -9999 fill values in forcing.nc using streaming approach.
Modifies file in place without loading entire array.
"""

from netCDF4 import Dataset
import numpy as np

FORCING_FILE = "/data/bdi_trail2/dr_case4/data/input/forcing.nc"

print("Fixing fill values in forcing.nc (in-place)...")

nc = Dataset(FORCING_FILE, 'r+')
nt = len(nc.dimensions['time'])

for var_name in ['precip', 'pet']:
    print(f"\nProcessing {var_name}...")
    var = nc.variables[var_name]

    fixed_count = 0
    for t in range(nt):
        if t % 200 == 0:
            print(f"  Timestep {t}/{nt}")

        data = var[t, :, :]
        bad_mask = data < -9000
        if np.any(bad_mask):
            data[bad_mask] = 0.0
            var[t, :, :] = data
            fixed_count += np.sum(bad_mask)

        # Also fix negative values
        neg_mask = data < 0
        if np.any(neg_mask):
            data[neg_mask] = 0.0
            var[t, :, :] = data
            fixed_count += np.sum(neg_mask)

    print(f"  Fixed {fixed_count:,} values")

nc.sync()
nc.close()

print("\nDone! Verifying...")

# Quick verify
nc = Dataset(FORCING_FILE, 'r')
for var_name in ['precip', 'temp', 'pet']:
    data = nc.variables[var_name][0, :, :]
    print(f"{var_name}: min={np.min(data):.3f}, max={np.max(data):.3f}")
nc.close()

print("\nForcing file fixed!")
