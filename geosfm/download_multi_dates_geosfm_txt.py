#!/usr/bin/env python3
"""
Download GeoSFM txt files from multiple dates and create long tables
Creates separate folders for each date under geosfm_txt_files/
"""

import os
import pandas as pd
from google.cloud import storage
from datetime import datetime
import argparse

# Configuration
GCS_BUCKET = "geosfm"
GCS_BASE_PREFIX = "geosfm_output_icpac_pc"
SERVICE_ACCOUNT_PATH = "coiled-data-e4drr_202505.json"
BASE_DOWNLOAD_FOLDER = "geosfm_txt_files"
ZONES = [1, 2, 3, 4, 5, 6]
VARIABLES = ["riverdepth", "streamflow"]

# Variable encoding for consistency with docs
VARIABLE_ENCODING = {
    'riverdepth': 4,
    'streamflow': 5
}

def setup_gcs_client():
    """Setup GCS client with service account credentials"""
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = SERVICE_ACCOUNT_PATH
    return storage.Client()

def download_txt_files_for_date(date_str):
    """Download all required txt files for a specific date from GCS bucket"""
    client = setup_gcs_client()
    bucket = client.bucket(GCS_BUCKET)

    # Create date-specific download folder
    date_folder = os.path.join(BASE_DOWNLOAD_FOLDER, date_str)
    os.makedirs(date_folder, exist_ok=True)

    downloaded_files = []
    gcs_path_prefix = f"{GCS_BASE_PREFIX}/{date_str}"

    print(f"Downloading files for {date_str} to {date_folder}/")

    for variable in VARIABLES:
        for zone in ZONES:
            blob_name = f"{gcs_path_prefix}/{variable}_imerg_zone{zone}.txt"
            local_filename = os.path.join(date_folder, f"{variable}_imerg_zone{zone}.txt")

            try:
                blob = bucket.blob(blob_name)
                blob.download_to_filename(local_filename)
                print(f"  Downloaded: {blob_name} -> {local_filename}")
                downloaded_files.append(local_filename)
            except Exception as e:
                print(f"  Warning: Could not download {blob_name}: {e}")

    print(f"Downloaded {len(downloaded_files)} files for {date_str}")
    return downloaded_files

def read_txt_file(filepath):
    """Read a txt file and return DataFrame with proper zone ID handling"""
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()

        if len(lines) < 2:  # Need header + data
            print(f"File {filepath} has insufficient data")
            return None

        # Parse header (first line) - this is CSV format
        header_parts = lines[0].strip().split(',')

        # Create column names: Time + zone_ids from header
        columns = ['Time']
        zone_ids_from_header = []

        for i in range(1, len(header_parts)):
            zone_id = header_parts[i].strip()
            columns.append(f'zone_id_{zone_id}')
            zone_ids_from_header.append(zone_id)

        # Read data (skip header line) - CSV format
        data_lines = []
        for line in lines[1:]:
            if line.strip():  # Skip empty lines
                parts = line.strip().split(',')
                if len(parts) >= len(columns):  # Make sure we have enough columns
                    data_lines.append(parts[:len(columns)])  # Take only needed columns

        # Create DataFrame
        df = pd.DataFrame(data_lines, columns=columns)
        df.zone_ids_from_header = zone_ids_from_header

        return df

    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return None

def simple_date_parser(date_str):
    """Simple date parser that handles various formats"""
    date_str = str(date_str).strip()

    try:
        if len(date_str) == 10 and date_str.count('-') == 2:  # YYYY-MM-DD
            parts = date_str.split('-')
            year, month, day = parts
            return f"{year}{month.zfill(2)}{day.zfill(2)}T00"
        elif len(date_str) == 8 and date_str.isdigit():  # YYYYMMDD
            return f"{date_str}T00"
        elif '/' in date_str and date_str.count('/') == 2:  # MM/DD/YYYY format
            parts = date_str.split('/')
            if len(parts[2]) == 4:  # MM/DD/YYYY
                month, day, year = parts
                return f"{year}{month.zfill(2)}{day.zfill(2)}T00"
            else:
                return f"{date_str}T00"
        else:
            return f"{date_str}T00"
    except Exception as e:
        print(f"Error parsing date '{date_str}': {e}")
        return f"{date_str}T00"

def create_long_table_for_date(date_str, variable_type):
    """Create long table for specified variable type and date"""

    long_table_data = []
    current_time = datetime.now().strftime('%Y%m%dT%H')
    date_folder = os.path.join(BASE_DOWNLOAD_FOLDER, date_str)

    print(f"  Processing {variable_type} data for {date_str}...")

    # Process each zone file
    for zone_nu in ZONES:
        filename = os.path.join(date_folder, f"{variable_type}_imerg_zone{zone_nu}.txt")

        if not os.path.exists(filename):
            print(f"    File not found: {filename}")
            continue

        df = read_txt_file(filename)
        if df is None:
            continue

        print(f"    Processing {filename} with shape: {df.shape}")

        # Get zone_ids from header
        zone_ids_from_header = getattr(df, 'zone_ids_from_header', [])

        # Process each row (each day) of the dataframe
        for _, row in df.iterrows():
            # Extract date from first column
            date_raw = str(row.iloc[0])

            # Format date to match docs format (YYYYMMDDTHH) - simple parser
            gtime = simple_date_parser(date_raw)

            # Process zone columns (skip first column which is date)
            zone_columns = [col for col in df.columns if col.startswith('zone_id_')]

            for i, zone_col in enumerate(zone_columns):
                value = row[zone_col]

                # Skip null/nan values or convert to numeric
                try:
                    value = float(value)
                    if pd.isna(value):  # Skip null values (but keep zeros)
                        continue
                except (ValueError, TypeError):
                    continue

                # Extract zone_id from header (the actual zone identifier from first line)
                if i < len(zone_ids_from_header):
                    zone_id = zone_ids_from_header[i]
                else:
                    zone_id = zone_col.replace('zone_id_', '')

                # Create record following docs format with corrected column names
                record = {
                    'gtime': gtime,
                    'zone_id': zone_id,          # Zone ID from first line of txt file
                    'zone_nu': zone_nu,          # File zone number (1-6)
                    'variable': VARIABLE_ENCODING[variable_type],
                    'mean_value': value,
                    'processed_at': current_time,
                    'source_date': date_str      # Add source date for tracking
                }

                long_table_data.append(record)

    # Create DataFrame and sort as per docs
    long_table_df = pd.DataFrame(long_table_data)

    if not long_table_df.empty:
        # Sort by time, zone_nu, zone_id, and variable for optimal access patterns
        long_table_df = long_table_df.sort_values(['gtime', 'zone_nu', 'zone_id', 'variable'])

        # Filter out any rows with null mean_values (following docs)
        long_table_df = long_table_df.dropna(subset=['mean_value'])

        print(f"    Created long table for {variable_type} ({date_str}) with {len(long_table_df)} records")

    return long_table_df

def process_dates(dates_to_process, skip_download=False):
    """Process multiple dates"""

    all_results = {
        'riverdepth': [],
        'streamflow': []
    }

    for date_str in dates_to_process:
        print(f"\n=== Processing {date_str} ===")

        if not skip_download:
            # Download files for this date
            downloaded_files = download_txt_files_for_date(date_str)
        else:
            print(f"Skipping download for {date_str}, using local files...")

        # Create long tables for each variable type
        for variable in VARIABLES:
            long_table_df = create_long_table_for_date(date_str, variable)

            if not long_table_df.empty:
                all_results[variable].append(long_table_df)

                # Save individual date file
                date_folder = os.path.join(BASE_DOWNLOAD_FOLDER, date_str)
                csv_filename = os.path.join(date_folder, f"{variable}_long_table_{date_str}.csv")
                long_table_df.to_csv(csv_filename, index=False)
                print(f"    Saved {csv_filename} with {len(long_table_df)} records")

    # Combine all dates for each variable
    print(f"\n=== Combining all dates ===")
    for variable in VARIABLES:
        if all_results[variable]:
            combined_df = pd.concat(all_results[variable], ignore_index=True)
            combined_df = combined_df.sort_values(['source_date', 'gtime', 'zone_nu', 'zone_id', 'variable'])

            # Save combined file
            combined_csv = os.path.join(BASE_DOWNLOAD_FOLDER, f"combined_{variable}_long_table.csv")
            combined_df.to_csv(combined_csv, index=False)

            combined_parquet = os.path.join(BASE_DOWNLOAD_FOLDER, f"combined_{variable}_long_table.parquet")
            combined_df.to_parquet(combined_parquet, index=False)

            print(f"Saved combined {variable} data:")
            print(f"  - {combined_csv} ({len(combined_df):,} records)")
            print(f"  - {combined_parquet}")

    return all_results

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Download and process GeoSFM txt files for multiple dates')
    parser.add_argument('--skip-download', action='store_true',
                        help='Skip download and use local files only')
    parser.add_argument('--dates', nargs='+',
                        help='Specific dates to process (YYYYMMDD format)',
                        #default=['20250721', '20250722', '20250724'])  # Sample dates
                        default=['20250822', '20250823', '20250824', '20250825', '20250826', '20250827', '20250828', '20250829', '20250830', '20250831', '20250901', '20250902', '20250903', '20250904', '20250905', '20250906', '20250907', '20250908', '20250909', '20250910', '20250911', '20250912', '20250913', '20250914', '20250915', '20250916', '20250917', '20250918', '20250919', '20250920', '20250921', '20250922', '20250923', '20250924'])

    args = parser.parse_args()

    print("Starting multi-date GeoSFM txt file processing...")
    print(f"Dates to process: {args.dates}")

    # Create base download folder
    os.makedirs(BASE_DOWNLOAD_FOLDER, exist_ok=True)

    # Process the dates
    results = process_dates(args.dates, args.skip_download)

    print(f"\n=== Summary ===")
    print(f"Processed {len(args.dates)} dates")
    print(f"Individual date folders created under: {BASE_DOWNLOAD_FOLDER}/")
    print(f"Combined files saved in: {BASE_DOWNLOAD_FOLDER}/")

if __name__ == "__main__":
    main()
