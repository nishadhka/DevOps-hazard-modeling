#!/usr/bin/env python3
"""
Merge partial Ethiopia simulation outputs.
Usage: python merge_outputs.py output1.csv output2.csv merged_output.csv
"""
import sys
import pandas as pd

def merge_outputs(file1, file2, output_file):
    df1 = pd.read_csv(file1)
    df2 = pd.read_csv(file2)

    # Get last date from first file
    last_date_df1 = pd.to_datetime(df1['time']).max()

    # Filter second file to only dates after first file
    df2['time_parsed'] = pd.to_datetime(df2['time'])
    df2_filtered = df2[df2['time_parsed'] > last_date_df1].drop(columns=['time_parsed'])

    # Concatenate
    merged = pd.concat([df1, df2_filtered], ignore_index=True)
    merged.to_csv(output_file, index=False)

    print(f"Merged: {len(df1)} + {len(df2_filtered)} = {len(merged)} rows")
    print(f"Period: {merged['time'].iloc[0]} to {merged['time'].iloc[-1]}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python merge_outputs.py output1.csv output2.csv merged.csv")
        sys.exit(1)
    merge_outputs(sys.argv[1], sys.argv[2], sys.argv[3])
