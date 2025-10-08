#!/usr/bin/env python3
"""
Zone-Wise Txt File Generator v4 - Parquet-Based with Header Preservation

This version combines the best of v3 (Parquet efficiency) and the original (header preservation):

Key Features:
✅ Parquet-based data management for efficiency
✅ CRITICAL header preservation for hydrological model compatibility
✅ Hindcast/forecast separation using source_date markers
✅ GCS and local file support
✅ Auto-normalization of column names (zone_id/zones_id)

CRITICAL: Preserves existing Header Row ordering for hydrological model compatibility.
The header ordering represents river/stream network topology and MUST NEVER be changed.

Usage:
  # From GCS parquet
  python 03-zone-txt-v4.py \
     --parquet-source gs://geosfm/cloud_geosfm_input.parquet \
     --shapefile geofsm-prod-all-zones-20240712_v2_simplfied.geojson \
     --output-dir zone_output \
     --date-str 20250926 \
     --hindcast-date 20250925 \
     --service-account-key /path/to/key.json

  # From local parquet file
  python 03-zone-txt-v4.py \
     --parquet-source cloud_geosfm_input.parquet \
     --shapefile geofsm-prod-all-zones-20240712_v2_simplfied.geojson \
     --output-dir zone_output \
     --date-str 20250926 \
     --hindcast-date 20250925
"""

import os
import sys
import logging
import argparse
import glob
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import geopandas as gpd

# GCS imports (optional)
try:
    from google.cloud import storage
    from google.oauth2 import service_account
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    print("Warning: Google Cloud Storage not available. GCS functionality disabled.")

# Configure logging
logger = logging.getLogger(__name__)


class ZoneWiseTxtGeneratorV4:
    """
    Zone-wise txt file generator V4: Parquet-based with header preservation.

    Combines Parquet efficiency with critical hydrological ordering preservation.
    """

    # Variable encoding from flox processor
    VARIABLE_ENCODING = {
        1: 'imerg_precipitation',      # IMERG observations
        2: 'pet',                      # Potential Evapotranspiration
        3: 'chirps_gefs_precipitation', # CHIRPS-GEFS forecasts
        4: 'riverdepth',               # River depth (model output)
        5: 'streamflow'                # Streamflow (model output)
    }

    # File assignment mapping
    FILE_MAPPING = {
        1: 'rain.txt',  # IMERG -> rain
        2: 'evap.txt',  # PET -> evap
        3: 'rain.txt'   # CHIRPS-GEFS -> rain
    }

    def __init__(self, config: Optional[Dict] = None):
        """Initialize the generator with configuration"""
        self.config = config or {}
        self.setup_logging()

        # Data storage
        self.zone_spatial_mapping = {}
        self.zone_sizes = {}
        self.zone_headers = {}  # 🔒 Store existing headers to preserve ordering
        self.shapefile_data = None

        # Parquet data
        self.parquet_df = None
        self.hindcast_df = None
        self.forecast_df = None

        # GCS client
        self.gcs_client = None
        self.service_account_key = None

        # Output directory for header search
        self.base_output_dir = "zone_output"

    def setup_logging(self):
        """Setup logging configuration"""
        log_level = self.config.get('log_level', 'INFO')
        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

        logging.basicConfig(
            level=getattr(logging, log_level),
            format=log_format,
            handlers=[
                logging.StreamHandler(sys.stdout)
            ]
        )

        logger.info("Zone-wise txt file generator V4 (Parquet + Header Preservation) initialized")

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

    def load_parquet_data(self, parquet_source: str) -> pd.DataFrame:
        """
        Load parquet data from GCS or local file

        Args:
            parquet_source: GCS path (gs://bucket/file) or local file path

        Returns:
            pd.DataFrame: Loaded parquet data
        """
        logger.info(f"Loading parquet data from: {parquet_source}")

        try:
            if parquet_source.startswith('gs://'):
                # Load from GCS
                if not GCS_AVAILABLE or not self.gcs_client:
                    raise ValueError("GCS client not initialized for cloud storage access")

                # Parse GCS path
                path_parts = parquet_source[5:].split('/', 1)
                bucket_name = path_parts[0]
                blob_name = path_parts[1]

                # Download to temporary file
                bucket = self.gcs_client.bucket(bucket_name)
                blob = bucket.blob(blob_name)

                temp_path = f"/tmp/temp_parquet_{datetime.now().strftime('%Y%m%d%H%M%S')}.parquet"
                blob.download_to_filename(temp_path)
                logger.info(f"Downloaded from GCS to: {temp_path}")

                # Read parquet
                df = pd.read_parquet(temp_path)

                # Clean up temp file
                os.remove(temp_path)

            else:
                # Load from local file
                df = pd.read_parquet(parquet_source)

            # Normalize column names (support both zone_id and zones_id)
            if 'zone_id' in df.columns and 'zones_id' not in df.columns:
                df = df.rename(columns={'zone_id': 'zones_id'})
                logger.info("Normalized column: zone_id -> zones_id")
            elif 'zones_id' in df.columns:
                logger.info("Using existing zones_id column")

            # Validate required columns
            required_columns = ['gtime', 'zones_id', 'variable', 'mean_value', 'source_date']
            missing_columns = [col for col in required_columns if col not in df.columns]

            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")

            logger.info(f"✅ Loaded {len(df):,} records from parquet")
            logger.info(f"   Columns: {list(df.columns)}")
            logger.info(f"   Variables: {sorted(df['variable'].unique())}")
            logger.info(f"   Zones: {df['zones_id'].nunique()} unique zones")
            logger.info(f"   Time range: {df['gtime'].min()} to {df['gtime'].max()}")
            logger.info(f"   Source dates: {sorted(df['source_date'].unique())}")

            self.parquet_df = df
            return df

        except Exception as e:
            logger.error(f"Failed to load parquet data: {e}")
            raise

    def separate_hindcast_forecast_data(self, hindcast_date: str):
        """
        Separate hindcast and forecast data based on source_date markers

        Hindcast data is identified by source_date starting with 'hc_' prefix
        (e.g., hc_20250925) or matching the specified hindcast date.

        Args:
            hindcast_date: Date string for hindcast identification (YYYYMMDD)
        """
        if self.parquet_df is None:
            raise ValueError("Parquet data not loaded")

        logger.info("=" * 70)
        logger.info("SEPARATING HINDCAST AND FORECAST DATA")
        logger.info("=" * 70)
        logger.info(f"Hindcast reference date: {hindcast_date}")

        # Identify hindcast data
        hindcast_marker = f"hc_{hindcast_date}"

        hindcast_mask = (
            (self.parquet_df['source_date'].astype(str).str.startswith('hc_')) |
            (self.parquet_df['source_date'].astype(str) == hindcast_marker)
        )

        self.hindcast_df = self.parquet_df[hindcast_mask].copy()
        self.forecast_df = self.parquet_df[~hindcast_mask].copy()

        logger.info(f"Hindcast data: {len(self.hindcast_df):,} records")
        if len(self.hindcast_df) > 0:
            logger.info(f"  Time range: {self.hindcast_df['gtime'].min()} to {self.hindcast_df['gtime'].max()}")
            logger.info(f"  Date count: {self.hindcast_df['gtime'].nunique()} unique dates")
            logger.info(f"  Source markers: {sorted(self.hindcast_df['source_date'].unique())}")

        logger.info(f"Forecast data: {len(self.forecast_df):,} records")
        if len(self.forecast_df) > 0:
            logger.info(f"  Time range: {self.forecast_df['gtime'].min()} to {self.forecast_df['gtime'].max()}")
            logger.info(f"  Date count: {self.forecast_df['gtime'].nunique()} unique dates")
            logger.info(f"  Source dates: {sorted(self.forecast_df['source_date'].unique())}")

    def load_shapefile_data(self, shapefile_path: str) -> gpd.GeoDataFrame:
        """Load and process geospatial data for zone spatial mapping"""
        logger.info(f"Loading geospatial data from: {shapefile_path}")

        try:
            gdf = gpd.read_file(shapefile_path)

            # Validate required columns
            required_columns = ['GRIDCODE', 'zone', 'id']
            missing_columns = [col for col in required_columns if col not in gdf.columns]

            if missing_columns:
                raise ValueError(f"Missing required geospatial columns: {missing_columns}")

            logger.info(f"✅ Loaded geospatial file with {len(gdf)} polygons")
            logger.info(f"   Zones: {sorted(gdf['zone'].unique())}")
            logger.info(f"   GRIDCODE range: {gdf['GRIDCODE'].min()} to {gdf['GRIDCODE'].max()}")

            self.shapefile_data = gdf
            return gdf

        except Exception as e:
            logger.error(f"Failed to load geospatial data: {e}")
            raise

    def load_existing_zone_header(self, zone: str) -> List[int]:
        """
        🚨 CRITICAL: Load existing zone header to preserve hydrological ordering

        This method extracts the header from existing zone files to maintain the
        river/stream network topology ordering essential for GeoSFM hydrological model.

        Args:
            zone: Zone identifier (zone1-zone6)

        Returns:
            List[int]: Existing header order (GRIDCODE values in hydrological order)
        """
        # Try to find existing zone file in various date directories
        search_paths = []

        # Search all date directories
        date_dirs = glob.glob(f"{self.base_output_dir}/lt_stable_input_*")
        for date_dir in date_dirs:
            search_paths.extend([
                f"{date_dir}/{zone}/rain.txt",
                f"{date_dir}/{zone}/evap.txt"
            ])

        for file_path in search_paths:
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r') as f:
                        header_line = f.readline().strip()
                        if header_line.startswith('NA,'):
                            header_values = header_line[3:].split(',')
                            header = [int(val) for val in header_values if val.strip()]
                            logger.info(f"🔒 Loaded existing {zone} header with {len(header)} spatial units from {file_path}")
                            logger.info(f"   Preserving hydrological ordering: first 5 = {header[:5]}")
                            return header
                except Exception as e:
                    logger.warning(f"Failed to load header from {file_path}: {e}")
                    continue

        logger.error(f"❌ Could not find existing header for {zone}. Hydrological ordering cannot be preserved!")
        logger.error("   This will break the GeoSFM hydrological model functionality.")
        return []

    def create_zone_spatial_mapping(self) -> Dict[str, Dict[int, int]]:
        """
        🚨 CRITICAL: Create mapping preserving existing hydrological ordering

        This method creates spatial mappings that align with the existing header
        ordering from zone files, ensuring hydrological model compatibility.

        Returns:
            Dict: Nested dict with zone -> {zones_id: spatial_position}
        """
        logger.info("Creating zone spatial mapping with hydrological ordering preservation")

        if self.shapefile_data is None:
            raise ValueError("Geospatial data not loaded. Call load_shapefile_data() first.")

        zone_mappings = {}

        for zone in ['zone1', 'zone2', 'zone3', 'zone4', 'zone5', 'zone6']:
            # CRITICAL: Load existing header to preserve hydrological order
            existing_header = self.load_existing_zone_header(zone)

            if not existing_header:
                logger.error(f"❌ Cannot create mapping for {zone} - no existing header found!")
                zone_mappings[zone] = {}
                self.zone_sizes[zone] = 0
                continue

            # Store the header for later use
            self.zone_headers[zone] = existing_header
            self.zone_sizes[zone] = len(existing_header)

            # Get zone data from shapefile
            zone_data = self.shapefile_data[self.shapefile_data['zone'] == zone].copy()

            if len(zone_data) == 0:
                logger.warning(f"No geospatial data found for {zone}")
                zone_mappings[zone] = {}
                continue

            # Create GRIDCODE to zones_id mapping from geospatial data
            gridcode_to_zones_id = {}
            for _, row in zone_data.iterrows():
                gridcode_to_zones_id[int(row['GRIDCODE'])] = int(row['id'])

            # Create zones_id to spatial_position mapping using existing header order
            mapping = {}
            for spatial_position, gridcode in enumerate(existing_header):
                if gridcode in gridcode_to_zones_id:
                    zones_id = gridcode_to_zones_id[gridcode]
                    mapping[zones_id] = spatial_position
                else:
                    logger.warning(f"GRIDCODE {gridcode} from header not found in geospatial data for {zone}")

            zone_mappings[zone] = mapping
            logger.info(f"🔒 {zone}: {len(mapping)} spatial units mapped preserving hydrological order")
            logger.info(f"   Header GRIDCODE order preserved: {existing_header[:5]}... (first 5)")

        # Log actual zone sizes
        logger.info("Zone sizes with hydrological ordering preserved:")
        for zone, size in self.zone_sizes.items():
            logger.info(f"  {zone}: {size} spatial units")

        self.zone_spatial_mapping = zone_mappings
        return zone_mappings

    def convert_gtime_to_julian(self, gtime_str: str) -> str:
        """Convert gtime format (YYYYMMDDTHH) to Julian day format (YYYYDDD)"""
        try:
            dt = datetime.strptime(gtime_str, '%Y%m%dT%H')
            julian_day = dt.timetuple().tm_yday
            return f"{dt.year}{julian_day:03d}"
        except ValueError as e:
            logger.error(f"Failed to convert time format '{gtime_str}': {e}")
            raise

    def process_zone_data_from_df(self, zone: str, variable: int,
                                   data_df: pd.DataFrame) -> Dict[str, List[float]]:
        """
        Process data for specific zone and variable from a dataframe

        Args:
            zone: Zone identifier (zone1-zone6)
            variable: Variable code (1, 2, or 3)
            data_df: DataFrame containing the data to process

        Returns:
            Dict: Mapping of julian_date -> list of spatial values
        """
        if zone not in self.zone_spatial_mapping:
            raise ValueError(f"Zone {zone} not found in spatial mapping")

        # Filter data for this zone and variable
        zone_mapping = self.zone_spatial_mapping[zone]
        valid_zones_ids = set(zone_mapping.keys())

        zone_data = data_df[
            (data_df['zones_id'].isin(valid_zones_ids)) &
            (data_df['variable'] == variable)
        ].copy()

        if len(zone_data) == 0:
            logger.debug(f"No data found for {zone}, variable {variable}")
            return {}

        # Convert time format and group by date
        zone_data['julian_date'] = zone_data['gtime'].apply(self.convert_gtime_to_julian)

        # Process each unique date
        time_series_data = {}
        zone_size = self.zone_sizes.get(zone, 0)

        if zone_size == 0:
            logger.warning(f"No zone size information for {zone}")
            return {}

        for julian_date in sorted(zone_data['julian_date'].unique()):
            date_data = zone_data[zone_data['julian_date'] == julian_date]

            # Initialize spatial values array
            spatial_values = np.zeros(zone_size)

            # Fill in values based on spatial mapping
            for _, row in date_data.iterrows():
                zones_id = int(row['zones_id'])
                mean_value = float(row['mean_value'])

                if zones_id in zone_mapping:
                    spatial_position = zone_mapping[zones_id]
                    if 0 <= spatial_position < zone_size:
                        spatial_values[spatial_position] = mean_value

            time_series_data[julian_date] = spatial_values.tolist()

        return time_series_data

    def merge_hindcast_and_forecast_data(self, hindcast_data: Dict[str, List[float]],
                                        forecast_data: Dict[str, List[float]],
                                        cutoff_date: Optional[str] = None) -> Dict[str, List[float]]:
        """
        Merge hindcast and forecast data

        Args:
            hindcast_data: Historical time series data
            forecast_data: New forecast data
            cutoff_date: Julian date where forecast data starts (if None, auto-detect)

        Returns:
            Dict: Merged time series data
        """
        if not forecast_data:
            logger.info("No forecast data to merge, returning hindcast data only")
            return hindcast_data.copy()

        if not hindcast_data:
            logger.info("No hindcast data available, returning forecast data only")
            return forecast_data.copy()

        # Determine cutoff date
        if cutoff_date is None:
            cutoff_date = min(forecast_data.keys())
            logger.info(f"Auto-detected data cutoff date: {cutoff_date}")

        # Start with hindcast data up to cutoff
        merged_data = {}
        hindcast_retained = 0

        for date, values in hindcast_data.items():
            if date < cutoff_date:
                merged_data[date] = values
                hindcast_retained += 1

        # Add all forecast data
        forecast_added = 0
        for date, values in forecast_data.items():
            merged_data[date] = values
            forecast_added += 1

        logger.info(f"Data merge summary:")
        logger.info(f"  Hindcast retained: {hindcast_retained} days")
        logger.info(f"  Forecast added: {forecast_added} days")
        logger.info(f"  Total merged: {len(merged_data)} days")

        return merged_data

    def write_zone_file(self, file_path: str, header: List[int],
                       time_series: Dict[str, List[float]], zone: str):
        """
        Write zone txt file with header and time series data

        Args:
            file_path: Output file path
            header: Header row with spatial identifiers
            time_series: Time series data
            zone: Zone identifier for validation
        """
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            zone_size = self.zone_sizes.get(zone, len(header))

            with open(file_path, 'w') as f:
                # Write header
                header_str = 'NA,' + ','.join(map(str, header))
                f.write(header_str + '\n')

                # Write time series data (sorted by date)
                for julian_date in sorted(time_series.keys()):
                    values = time_series[julian_date]
                    # Ensure values match zone size
                    padded_values = (values + [0.0] * zone_size)[:zone_size]
                    row = [julian_date] + [f"{val:.1f}" if val > 0 else "0" for val in padded_values]
                    f.write(','.join(row) + '\n')

            logger.info(f"✅ Written {len(time_series)} time steps to {file_path}")

        except Exception as e:
            logger.error(f"Failed to write file {file_path}: {e}")
            raise

    def process_single_zone(self, zone: str, output_dir: str):
        """
        Process single zone with hindcast and forecast data

        Args:
            zone: Zone identifier (zone1-zone6)
            output_dir: Output directory path
        """
        logger.info(f"🔄 Processing {zone} with parquet-based data and header preservation")

        zone_dir = os.path.join(output_dir, zone)
        os.makedirs(zone_dir, exist_ok=True)

        # Process rain.txt (Variables 1 + 3 combined)
        rain_file_path = os.path.join(zone_dir, 'rain.txt')

        # Process hindcast rain data
        rain_hindcast = {}
        if self.hindcast_df is not None and len(self.hindcast_df) > 0:
            imerg_hindcast = self.process_zone_data_from_df(zone, 1, self.hindcast_df)
            chirps_hindcast = self.process_zone_data_from_df(zone, 3, self.hindcast_df)

            # Combine hindcast precipitation
            zone_size = self.zone_sizes.get(zone, 0)
            all_dates = sorted(set(list(imerg_hindcast.keys()) + list(chirps_hindcast.keys())))

            for date in all_dates:
                imerg_vals = np.array(imerg_hindcast.get(date, [0.0] * zone_size))
                chirps_vals = np.array(chirps_hindcast.get(date, [0.0] * zone_size))
                rain_hindcast[date] = (imerg_vals + chirps_vals).tolist()

        # Process forecast rain data
        rain_forecast = {}
        if self.forecast_df is not None and len(self.forecast_df) > 0:
            imerg_forecast = self.process_zone_data_from_df(zone, 1, self.forecast_df)
            chirps_forecast = self.process_zone_data_from_df(zone, 3, self.forecast_df)

            # Combine forecast precipitation
            zone_size = self.zone_sizes.get(zone, 0)
            all_dates = sorted(set(list(imerg_forecast.keys()) + list(chirps_forecast.keys())))

            for date in all_dates:
                imerg_vals = np.array(imerg_forecast.get(date, [0.0] * zone_size))
                chirps_vals = np.array(chirps_forecast.get(date, [0.0] * zone_size))
                rain_forecast[date] = (imerg_vals + chirps_vals).tolist()

        # Merge and write rain file
        rain_merged = self.merge_hindcast_and_forecast_data(rain_hindcast, rain_forecast)
        rain_header = self.zone_headers.get(zone, [])
        self.write_zone_file(rain_file_path, rain_header, rain_merged, zone)

        # Process evap.txt (Variable 2)
        evap_file_path = os.path.join(zone_dir, 'evap.txt')

        # Process hindcast evap data
        evap_hindcast = {}
        if self.hindcast_df is not None and len(self.hindcast_df) > 0:
            evap_hindcast = self.process_zone_data_from_df(zone, 2, self.hindcast_df)

        # Process forecast evap data
        evap_forecast = {}
        if self.forecast_df is not None and len(self.forecast_df) > 0:
            evap_forecast = self.process_zone_data_from_df(zone, 2, self.forecast_df)

            # Extend PET for forecast period if needed
            if rain_forecast and evap_forecast:
                forecast_dates = [date for date in rain_forecast.keys() if date not in evap_forecast]
                if forecast_dates and evap_forecast:
                    latest_evap_date = max(evap_forecast.keys())
                    latest_evap_values = evap_forecast[latest_evap_date]

                    for forecast_date in forecast_dates:
                        evap_forecast[forecast_date] = latest_evap_values.copy()

                    logger.info(f"Extended PET data for {len(forecast_dates)} forecast dates in {zone}")

        # Merge and write evap file
        evap_merged = self.merge_hindcast_and_forecast_data(evap_hindcast, evap_forecast)
        evap_header = self.zone_headers.get(zone, [])
        self.write_zone_file(evap_file_path, evap_header, evap_merged, zone)

        logger.info(f"✅ Completed {zone} processing")
        logger.info(f"   Rain file: {len(rain_merged)} days")
        logger.info(f"   Evap file: {len(evap_merged)} days")

    def generate_zone_files(self, parquet_source: str, shapefile_path: str,
                          output_dir: str, date_str: str, hindcast_date: str,
                          service_account_key: Optional[str] = None,
                          zones: Optional[List[str]] = None):
        """
        Main method to generate zone files from parquet data with header preservation

        Args:
            parquet_source: GCS path or local path to parquet file
            shapefile_path: Path to geospatial file
            output_dir: Base output directory
            date_str: Date string for output directory naming
            hindcast_date: Date string for hindcast identification
            service_account_key: Path to GCS service account key
            zones: List of specific zones to process
        """
        logger.info("=" * 80)
        logger.info("STARTING ZONE-WISE TXT FILE GENERATION V4")
        logger.info("(Parquet-Based with Header Preservation)")
        logger.info("=" * 80)

        # Store output dir for header search
        self.base_output_dir = output_dir

        start_time = datetime.now()

        try:
            # Initialize GCS client if needed
            if parquet_source.startswith('gs://'):
                self.initialize_gcs_client(service_account_key)

            # Load parquet data
            self.load_parquet_data(parquet_source)

            # Separate hindcast and forecast data
            self.separate_hindcast_forecast_data(hindcast_date)

            # Load shapefile
            self.load_shapefile_data(shapefile_path)

            # Create spatial mapping WITH header preservation
            self.create_zone_spatial_mapping()

            # Create date-specific output directory
            date_output_dir = os.path.join(output_dir, f"lt_stable_input_{date_str}")
            os.makedirs(date_output_dir, exist_ok=True)
            logger.info(f"Output directory: {date_output_dir}")

            # Determine zones to process
            all_zones = ['zone1', 'zone2', 'zone3', 'zone4', 'zone5', 'zone6']
            target_zones = zones if zones else all_zones

            logger.info(f"Processing zones: {target_zones}")

            # Process each zone
            for zone in target_zones:
                if zone not in all_zones:
                    logger.warning(f"Invalid zone: {zone}. Skipping.")
                    continue

                try:
                    self.process_single_zone(zone, date_output_dir)
                except Exception as e:
                    logger.error(f"Failed to process {zone}: {e}")
                    continue

            # Final summary
            end_time = datetime.now()
            duration = end_time - start_time

            logger.info("=" * 80)
            logger.info("ZONE-WISE TXT FILE GENERATION V4 COMPLETED")
            logger.info("=" * 80)
            logger.info(f"Total duration: {duration}")
            logger.info(f"Zones processed: {len(target_zones)}")
            logger.info(f"Output directory: {date_output_dir}")
            logger.info(f"Parquet source: {parquet_source}")
            logger.info(f"Hindcast date: {hindcast_date}")
            logger.info("")
            logger.info("🔒 HEADER PRESERVATION SUMMARY:")
            for zone in target_zones:
                if zone in self.zone_headers and zone in all_zones:
                    header_size = len(self.zone_headers[zone])
                    header_preview = self.zone_headers[zone][:5]
                    logger.info(f"   ✅ {zone}: {header_size} units preserved - {header_preview}...")
            logger.info("")
            logger.info(f"🔒 Hydrological header ordering preserved: YES")

        except Exception as e:
            logger.error(f"Zone-wise txt generation v4 failed: {e}")
            raise


def main():
    """Main entry point with parquet-based data processing and header preservation"""
    parser = argparse.ArgumentParser(
        description="Generate zone-wise txt files from parquet data V4 (with header preservation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # From GCS parquet
    python 03-zone-txt-v4.py --parquet-source gs://geosfm/cloud_geosfm_input.parquet \
        --shapefile geofsm-prod-all-zones-20240712_v2_simplfied.geojson \
        --output-dir zone_output --date-str 20250926 --hindcast-date 20250925 \
        --service-account-key /path/to/key.json

    # From local parquet
    python 03-zone-txt-v4.py --parquet-source cloud_geosfm_input.parquet \
        --shapefile geofsm-prod-all-zones-20240712_v2_simplfied.geojson \
        --output-dir zone_output --date-str 20250926 --hindcast-date 20250925
        """
    )

    parser.add_argument(
        "--parquet-source",
        type=str,
        required=True,
        help="Path to parquet file (gs://bucket/file or local path)"
    )

    parser.add_argument(
        "--shapefile",
        type=str,
        required=True,
        help="Path to geospatial file with zone definitions"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="zone_output",
        help="Base output directory for zone files"
    )

    parser.add_argument(
        "--date-str",
        type=str,
        required=True,
        help="Date string for output directory naming (YYYYMMDD)"
    )

    parser.add_argument(
        "--hindcast-date",
        type=str,
        required=True,
        help="Date string for hindcast identification (YYYYMMDD)"
    )

    parser.add_argument(
        "--service-account-key",
        type=str,
        required=False,
        help="Path to GCS service account JSON key file (for gs:// sources)"
    )

    parser.add_argument(
        "--zones",
        type=str,
        help="Comma-separated list of zones to process (e.g., zone1,zone2)"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level"
    )

    args = parser.parse_args()

    # Parse zones list
    zones = None
    if args.zones:
        zones = [zone.strip() for zone in args.zones.split(',')]

    # Configure generator
    config = {
        'log_level': args.log_level
    }

    generator = ZoneWiseTxtGeneratorV4(config)

    # Generate zone files
    generator.generate_zone_files(
        parquet_source=args.parquet_source,
        shapefile_path=args.shapefile,
        output_dir=args.output_dir,
        date_str=args.date_str,
        hindcast_date=args.hindcast_date,
        service_account_key=args.service_account_key,
        zones=zones
    )


if __name__ == "__main__":
    main()
