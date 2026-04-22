#!/usr/bin/env python3
"""
Combine Ethiopia simulation output files and handle missing dates.
Missing dates: 2021-10-04 (truncated), 2022-07-12 (gap between runs)
"""

import pandas as pd
import numpy as np
from pathlib import Path

output_dir = Path("data/output")

# Read all three files
print("Reading output files...")
df_backup = pd.read_csv(output_dir / "output_ethiopia_partial_backup.csv", parse_dates=['time'])
df_main = pd.read_csv(output_dir / "output_ethiopia.csv", parse_dates=['time'])
df_part2 = pd.read_csv(output_dir / "output_ethiopia_part2.csv", parse_dates=['time'])

print(f"Backup file: {df_backup['time'].min()} to {df_backup['time'].max()} ({len(df_backup)} rows)")
print(f"Main file: {df_main['time'].min()} to {df_main['time'].max()} ({len(df_main)} rows)")
print(f"Part2 file: {df_part2['time'].min()} to {df_part2['time'].max()} ({len(df_part2)} rows)")

# Check the last row of backup file (2021-10-04 is incomplete)
print(f"\nLast row of backup (incomplete 2021-10-04):")
print(df_backup.tail(1))

# Remove incomplete 2021-10-04 row from backup
df_backup_clean = df_backup[df_backup['time'] < '2021-10-04']
print(f"\nBackup after removing 2021-10-04: {len(df_backup_clean)} rows")

# Combine all three dataframes
df_combined = pd.concat([df_backup_clean, df_main, df_part2], ignore_index=True)
df_combined = df_combined.sort_values('time').reset_index(drop=True)

print(f"\nCombined data: {df_combined['time'].min()} to {df_combined['time'].max()} ({len(df_combined)} rows)")

# Find missing dates
full_date_range = pd.date_range(start=df_combined['time'].min(), end=df_combined['time'].max(), freq='D')
existing_dates = set(df_combined['time'])
missing_dates = [d for d in full_date_range if d not in existing_dates]

print(f"\nMissing dates ({len(missing_dates)}):")
for d in missing_dates:
    print(f"  - {d.strftime('%Y-%m-%d')}")

# Interpolate missing dates
if missing_dates:
    print("\nInterpolating missing dates...")
    # Create full date range dataframe
    df_full = pd.DataFrame({'time': full_date_range})
    df_full = df_full.merge(df_combined, on='time', how='left')

    # Linear interpolation for numeric columns
    numeric_cols = ['Q', 'recharge', 'soil_moisture_L1', 'soil_moisture_L2', 'soil_moisture_L3']
    for col in numeric_cols:
        df_full[col] = df_full[col].interpolate(method='linear')

    df_combined = df_full

print(f"\nFinal combined data: {len(df_combined)} rows")

# Calculate expected vs actual days
expected_days = (df_combined['time'].max() - df_combined['time'].min()).days + 1
print(f"Expected days: {expected_days}")
print(f"Actual rows: {len(df_combined)}")
print(f"Match: {expected_days == len(df_combined)}")

# Save combined output
output_file = output_dir / "output_ethiopia_combined.csv"
df_combined.to_csv(output_file, index=False, date_format='%Y-%m-%dT00:00:00')
print(f"\nSaved combined output to: {output_file}")

# Print summary statistics
print("\n=== Summary Statistics ===")
print(f"Period: {df_combined['time'].min().strftime('%Y-%m-%d')} to {df_combined['time'].max().strftime('%Y-%m-%d')}")
print(f"Total days: {len(df_combined)}")
print(f"\nDischarge (Q) [m³/s]:")
print(f"  Min: {df_combined['Q'].min():.2f}")
print(f"  Max: {df_combined['Q'].max():.2f}")
print(f"  Mean: {df_combined['Q'].mean():.2f}")
print(f"\nRecharge [mm/day]:")
print(f"  Min: {df_combined['recharge'].min():.4f}")
print(f"  Max: {df_combined['recharge'].max():.4f}")
print(f"  Mean: {df_combined['recharge'].mean():.4f}")
print(f"\nSoil Moisture L1 [vol fraction]:")
print(f"  Min: {df_combined['soil_moisture_L1'].min():.4f}")
print(f"  Max: {df_combined['soil_moisture_L1'].max():.4f}")
print(f"  Mean: {df_combined['soil_moisture_L1'].mean():.4f}")
