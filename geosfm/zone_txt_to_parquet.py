#!/usr/bin/env python3
"""
Zone TXT Files to Parquet Converter with GCS Upload

This script converts GeoSFM zone txt files (rain.txt, evap.txt) into a standardized
long-table parquet format and uploads to GCS with append functionality.

Key Features:
- Reads rain.txt and evap.txt from zone directories
- Converts to standardized long-table format matching cloud_geosfm_input.parquet
- Marks hindcast data with 'hc_' prefix in source_date field
- Uploads to GCS with automatic deduplication
- Supports batch processing of multiple zone directories

Variable Encoding:
- 1 = imerg (observations) - used for hindcast rain.txt
- 2 = pet (evapotranspiration) - used for evap.txt
- 3 = chirps (forecasts) - combined with imerg in rain.txt
- 4 = riverdepth (model output)
- 5 = streamflow (model output)

Note: rain.txt contains combined precipitation (imerg + chirps), we use variable
code 1 for hindcast rain data to maintain compatibility with forecast data.

Output Format (matching 02-flox-groupby.py output):
- gtime: YYYYMMDDTHH format
- zone_id: Zone identifier
- zone_nu: Zone number (set to 1)
- variable: Encoded as 1=imerg/rain, 2=pet
- mean_value: Float value
- processed_at: YYYYMMDDTHH format
- source_date: Marked as hc_YYYYMMDD for hindcast data

Usage:
    # Convert single date's zone files
    python zone_txt_to_parquet.py \
        --zone-dir zone_output/lt_stable_input_20250925 \
        --date-str 20250925 \
        --output-parquet hindcast_20250925.parquet

    # Convert and upload to GCS
    python zone_txt_to_parquet.py \
        --zone-dir zone_output/lt_stable_input_20250925 \
        --date-str 20250925 \
        --upload-to-gcs \
        --gcs-bucket geosfm \
        --gcs-parquet cloud_geosfm_input.parquet \
        --service-account-key /path/to/key.json
"""

import os
import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# GCS imports (optional)
try:
    from google.cloud import storage
    from google.oauth2 import service_account
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    print("Warning: Google Cloud Storage not available. GCS functionality disabled.")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class ZoneTxtToParquetConverter:
    """Converter for zone txt files to parquet format with GCS upload"""

    # Variable mapping for txt files
    # Note: rain.txt contains combined precipitation (imerg + chirps)
    # We use variable code 1 (imerg) as the primary code for hindcast rain data
    VARIABLE_MAPPING = {
        'rain.txt': 1,  # Combined precipitation (imerg observations + chirps forecasts)
        'evap.txt': 2   # PET code (same as flox processor)
    }

    def __init__(self):
        """Initialize converter"""
        self.gcs_client = None
        self.service_account_key = None

    def initialize_gcs_client(self, service_account_key: Optional[str] = None):
        """Initialize GCS client for cloud storage access"""
        if not GCS_AVAILABLE:
            logger.warning("GCS functionality not available")
            return False

        try:
            if service_account_key and Path(service_account_key).exists():
                logger.info(f"Using service account: {service_account_key}")
                credentials = service_account.Credentials.from_service_account_file(
                    service_account_key
                )
                self.gcs_client = storage.Client(credentials=credentials)
                self.service_account_key = service_account_key
            else:
                logger.info("Using default credentials (ADC)")
                self.gcs_client = storage.Client()

            logger.info("✅ GCS client initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize GCS client: {e}")
            return False

    def parse_txt_file(self, txt_path: str) -> Tuple[List[int], Dict[str, List[float]]]:
        """
        Parse zone txt file to extract header and time series data

        Args:
            txt_path: Path to txt file

        Returns:
            Tuple: (header with zone IDs, time_series data)
        """
        try:
            with open(txt_path, 'r') as f:
                lines = f.readlines()

            if len(lines) < 2:
                logger.warning(f"Insufficient data in {txt_path}")
                return [], {}

            # Parse header (first line: NA,44,46,50,...)
            header_line = lines[0].strip()
            if header_line.startswith('NA,'):
                header_values = header_line[3:].split(',')
                header = [int(val.strip()) for val in header_values if val.strip().isdigit()]
            else:
                logger.warning(f"Unexpected header format in {txt_path}")
                return [], {}

            # Parse time series data
            time_series = {}
            for line in lines[1:]:
                line = line.strip()
                if not line:
                    continue

                parts = line.split(',')
                if len(parts) < 2:
                    continue

                julian_date = parts[0].strip()

                # Parse values
                values = []
                for val in parts[1:]:
                    val_clean = val.strip()
                    if val_clean == '' or val_clean.upper() == 'NA':
                        values.append(0.0)
                    else:
                        try:
                            values.append(float(val_clean))
                        except ValueError:
                            values.append(0.0)

                # Ensure values match header length
                if len(values) < len(header):
                    values.extend([0.0] * (len(header) - len(values)))
                elif len(values) > len(header):
                    values = values[:len(header)]

                time_series[julian_date] = values

            return header, time_series

        except Exception as e:
            logger.error(f"Failed to parse {txt_path}: {e}")
            return [], {}

    def julian_to_gtime(self, julian_date: str) -> str:
        """
        Convert Julian date (YYYYDDD) to gtime format (YYYYMMDDTHH)

        Args:
            julian_date: Julian date string (e.g., '2025001')

        Returns:
            str: gtime format (e.g., '20250101T00')
        """
        try:
            year = int(julian_date[:4])
            day_of_year = int(julian_date[4:])

            # Create date from year and day of year
            date = datetime(year, 1, 1) + timedelta(days=day_of_year - 1)

            # Convert to gtime format (YYYYMMDDTHH)
            return date.strftime('%Y%m%dT00')

        except Exception as e:
            logger.error(f"Failed to convert Julian date '{julian_date}': {e}")
            return None

    def convert_zone_txt_to_long_table(self, zone_dir: str, zone_name: str,
                                      date_str: str) -> pd.DataFrame:
        """
        Convert zone txt files to long table format

        Args:
            zone_dir: Path to zone directory containing rain.txt and evap.txt
            zone_name: Zone name (e.g., 'zone1')
            date_str: Date string for source_date marking (YYYYMMDD)

        Returns:
            pd.DataFrame: Long table with standardized format
        """
        logger.info(f"Converting {zone_name} txt files to long table")

        all_records = []

        for txt_file in ['rain.txt', 'evap.txt']:
            txt_path = os.path.join(zone_dir, txt_file)

            if not os.path.exists(txt_path):
                logger.warning(f"File not found: {txt_path}")
                continue

            # Parse txt file
            header, time_series = self.parse_txt_file(txt_path)

            if not header or not time_series:
                logger.warning(f"No data extracted from {txt_path}")
                continue

            logger.info(f"  {txt_file}: {len(header)} zones, {len(time_series)} time steps")

            # Get variable code
            variable_code = self.VARIABLE_MAPPING[txt_file]

            # Convert to long table format
            for julian_date, values in time_series.items():
                # Convert Julian date to gtime
                gtime = self.julian_to_gtime(julian_date)
                if gtime is None:
                    continue

                # Create record for each zone
                for zone_id, value in zip(header, values):
                    record = {
                        'gtime': gtime,
                        'zone_id': int(zone_id),
                        'zone_nu': 1,
                        'variable': variable_code,
                        'mean_value': float(value),
                        'processed_at': datetime.now().strftime('%Y%m%dT%H'),
                        'source_date': f"hc_{date_str}"  # Mark as hindcast with hc_ prefix
                    }
                    all_records.append(record)

        if not all_records:
            logger.warning(f"No records created for {zone_name}")
            return pd.DataFrame()

        # Create DataFrame
        df = pd.DataFrame(all_records)

        # Sort by gtime, zone_id, variable
        df = df.sort_values(['gtime', 'zone_id', 'variable']).reset_index(drop=True)

        logger.info(f"✅ {zone_name}: {len(df):,} records created")
        logger.info(f"   Time range: {df['gtime'].min()} to {df['gtime'].max()}")
        logger.info(f"   Unique dates: {df['gtime'].nunique()}")

        return df

    def convert_all_zones(self, zone_base_dir: str, date_str: str) -> pd.DataFrame:
        """
        Convert all zone directories to a single long table

        Args:
            zone_base_dir: Base directory containing zone1, zone2, etc.
            date_str: Date string for source_date marking

        Returns:
            pd.DataFrame: Combined long table for all zones
        """
        logger.info("=" * 70)
        logger.info("CONVERTING ZONE TXT FILES TO PARQUET")
        logger.info("=" * 70)
        logger.info(f"Zone base directory: {zone_base_dir}")
        logger.info(f"Date string: {date_str}")

        all_zone_dfs = []

        for zone_num in range(1, 7):
            zone_name = f"zone{zone_num}"
            zone_dir = os.path.join(zone_base_dir, zone_name)

            if not os.path.exists(zone_dir):
                logger.warning(f"Zone directory not found: {zone_dir}")
                continue

            # Convert zone
            zone_df = self.convert_zone_txt_to_long_table(zone_dir, zone_name, date_str)

            if not zone_df.empty:
                all_zone_dfs.append(zone_df)

        if not all_zone_dfs:
            logger.error("No data converted from any zones")
            return pd.DataFrame()

        # Combine all zones
        combined_df = pd.concat(all_zone_dfs, ignore_index=True)

        # Sort final dataframe
        combined_df = combined_df.sort_values(['gtime', 'zone_id', 'variable']).reset_index(drop=True)

        logger.info("=" * 70)
        logger.info("CONVERSION SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total records: {len(combined_df):,}")
        logger.info(f"Zones processed: {len(all_zone_dfs)}")
        logger.info(f"Variables: {sorted(combined_df['variable'].unique())}")
        logger.info(f"Time range: {combined_df['gtime'].min()} to {combined_df['gtime'].max()}")
        logger.info(f"Unique dates: {combined_df['gtime'].nunique()}")
        logger.info(f"Source marker: hc_{date_str}")

        return combined_df

    def save_to_parquet(self, df: pd.DataFrame, output_path: str):
        """
        Save DataFrame to parquet file with optimized compression

        Args:
            df: DataFrame to save
            output_path: Output parquet file path
        """
        logger.info(f"Saving to parquet: {output_path}")

        try:
            # Convert to PyArrow Table
            table = pa.Table.from_pandas(df, preserve_index=False)

            # Write with optimized compression
            pq.write_table(
                table,
                output_path,
                compression='snappy',
                use_dictionary=True,
                write_statistics=True
            )

            file_size_mb = os.path.getsize(output_path) / 1024 / 1024
            logger.info(f"✅ Saved {len(df):,} records to {output_path}")
            logger.info(f"   File size: {file_size_mb:.2f} MB")

        except Exception as e:
            logger.error(f"Failed to save parquet: {e}")
            raise

    def upload_to_gcs_parquet(self, df: pd.DataFrame, bucket_name: str,
                             parquet_name: str) -> bool:
        """
        Upload DataFrame to GCS as parquet with append functionality

        Args:
            df: DataFrame to upload
            bucket_name: GCS bucket name
            parquet_name: Parquet file name in GCS

        Returns:
            bool: Success status
        """
        if not GCS_AVAILABLE or not self.gcs_client:
            logger.error("GCS client not initialized")
            return False

        logger.info("=" * 70)
        logger.info("UPLOADING TO GCS AS PARQUET")
        logger.info("=" * 70)
        logger.info(f"Bucket: gs://{bucket_name}/{parquet_name}")
        logger.info(f"New data: {len(df):,} rows")

        try:
            bucket = self.gcs_client.bucket(bucket_name)
            blob = bucket.blob(parquet_name)

            # Convert new data to PyArrow Table
            new_table = pa.Table.from_pandas(df, preserve_index=False)
            logger.info(f"New table: {len(new_table):,} rows")

            # Download existing parquet if it exists
            existing_table = None
            if blob.exists():
                logger.info("Downloading existing parquet file...")
                temp_download = f"/tmp/existing_{parquet_name}"
                blob.download_to_filename(temp_download)
                existing_table = pq.read_table(temp_download)
                logger.info(f"Existing table: {len(existing_table):,} rows")
                os.remove(temp_download)

            # Append or use new table
            if existing_table is not None:
                logger.info("Appending to existing table...")
                combined_table = pa.concat_tables([existing_table, new_table])
                logger.info(f"Combined (before dedup): {len(combined_table):,} rows")

                # Deduplicate
                combined_df = combined_table.to_pandas()
                original_len = len(combined_df)
                combined_df = combined_df.drop_duplicates()
                deduped_len = len(combined_df)
                duplicates_removed = original_len - deduped_len

                logger.info(f"Duplicates removed: {duplicates_removed:,}")
                logger.info(f"Final rows: {deduped_len:,}")

                final_table = pa.Table.from_pandas(combined_df, preserve_index=False)
            else:
                logger.info("No existing file, using new data only")
                final_table = new_table

            # Write to temporary file
            temp_upload = f"/tmp/upload_{parquet_name}"
            pq.write_table(
                final_table,
                temp_upload,
                compression='snappy',
                use_dictionary=True,
                write_statistics=True
            )

            file_size_mb = os.path.getsize(temp_upload) / 1024 / 1024
            logger.info(f"Parquet file size: {file_size_mb:.2f} MB")

            # Upload to GCS
            blob.upload_from_filename(temp_upload, content_type='application/octet-stream')
            os.remove(temp_upload)

            logger.info(f"✅ Successfully uploaded to GCS")
            logger.info(f"   URL: gs://{bucket_name}/{parquet_name}")
            logger.info(f"   Total rows: {len(final_table):,}")

            return True

        except Exception as e:
            logger.error(f"Failed to upload to GCS: {e}")
            return False


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Convert zone txt files to parquet with GCS upload',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Convert to local parquet
    python zone_txt_to_parquet.py \
        --zone-dir zone_output/lt_stable_input_20250925 \
        --date-str 20250925 \
        --output-parquet hindcast_20250925.parquet

    # Convert and upload to GCS
    python zone_txt_to_parquet.py \
        --zone-dir zone_output/lt_stable_input_20250925 \
        --date-str 20250925 \
        --upload-to-gcs \
        --gcs-bucket geosfm \
        --gcs-parquet cloud_geosfm_input.parquet \
        --service-account-key /path/to/key.json
        """
    )

    parser.add_argument(
        '--zone-dir',
        type=str,
        required=True,
        help='Base directory containing zone1, zone2, etc. subdirectories'
    )

    parser.add_argument(
        '--date-str',
        type=str,
        required=True,
        help='Date string for source_date marking (YYYYMMDD)'
    )

    parser.add_argument(
        '--output-parquet',
        type=str,
        help='Output parquet file path (optional if uploading to GCS)'
    )

    parser.add_argument(
        '--upload-to-gcs',
        action='store_true',
        help='Upload to GCS with append functionality'
    )

    parser.add_argument(
        '--gcs-bucket',
        type=str,
        default='geosfm',
        help='GCS bucket name (default: geosfm)'
    )

    parser.add_argument(
        '--gcs-parquet',
        type=str,
        default='cloud_geosfm_input.parquet',
        help='GCS parquet file name (default: cloud_geosfm_input.parquet)'
    )

    parser.add_argument(
        '--service-account-key',
        type=str,
        help='Path to GCS service account JSON key file'
    )

    args = parser.parse_args()

    # Validate inputs
    if not Path(args.zone_dir).exists():
        logger.error(f"Zone directory not found: {args.zone_dir}")
        sys.exit(1)

    # Initialize converter
    converter = ZoneTxtToParquetConverter()

    # Convert zone txt files to DataFrame
    df = converter.convert_all_zones(args.zone_dir, args.date_str)

    if df.empty:
        logger.error("No data converted. Exiting.")
        sys.exit(1)

    # Save to local parquet if specified
    if args.output_parquet:
        converter.save_to_parquet(df, args.output_parquet)

    # Upload to GCS if specified
    if args.upload_to_gcs:
        converter.initialize_gcs_client(args.service_account_key)
        success = converter.upload_to_gcs_parquet(df, args.gcs_bucket, args.gcs_parquet)

        if not success:
            logger.error("GCS upload failed")
            sys.exit(1)

    logger.info("=" * 70)
    logger.info("CONVERSION COMPLETED SUCCESSFULLY")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()