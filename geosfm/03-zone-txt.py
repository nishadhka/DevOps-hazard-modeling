#!/usr/bin/env python3
"""
Zone-Wise Txt File Generator v3

This script converts lean long table format climate data from flox_shapefile_groupby_processor_v3.py
into zone-specific txt files suitable for hydrological modeling workflows.

Features:
- Converts lean table format to zone-wise rainfall and evapotranspiration files
- Preserves historical data while incorporating new observations and forecasts
- Handles temporal alignment and forecast period management
- Supports 6-zone structure with variable spatial units per zone (86-1619 units)
- Implements comprehensive data validation and quality control

Based on ZONE_WISE_TXT_FILE_GENERATION_GUIDEv3.md specifications.

CRITICAL: Preserves existing Header Row ordering for hydrological model compatibility.
The header ordering represents river/stream network topology and MUST NEVER be changed.
"""

import os
import sys
import json
import logging
import argparse
import shutil
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Union
import warnings

import numpy as np
import pandas as pd
import geopandas as gpd
from collections import defaultdict

# Configure logging
logger = logging.getLogger(__name__)

class ZoneWiseTxtGenerator:
    """
    Generates zone-wise txt files from lean long table climate data.
    
    Converts optimized climate data into zone-specific rainfall and evapotranspiration
    files for hydrological modeling applications.
    """
    
    # Variable encoding from flox processor
    VARIABLE_ENCODING = {
        1: 'imerg_precipitation',      # IMERG observations
        2: 'pet',                      # Potential Evapotranspiration  
        3: 'chirps_gefs_precipitation' # CHIRPS-GEFS forecasts
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
        self.zone_sizes = {}  # Track actual zone sizes
        self.zone_headers = {}  # Store existing headers to preserve hydrological ordering
        self.lean_table_data = None
        self.shapefile_data = None
        
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
        
        logger.info("Zone-wise txt file generator initialized")
    
    def load_lean_table_data(self, lean_table_path: str) -> pd.DataFrame:
        """
        Load and validate lean long table data from flox processor
        
        Args:
            lean_table_path: Path to CSV file with lean table data
            
        Returns:
            pd.DataFrame: Validated lean table data
        """
        logger.info(f"Loading lean table data from: {lean_table_path}")
        
        try:
            # Load CSV data
            df = pd.read_csv(lean_table_path)
            
            # Validate required columns
            required_columns = ['gtime', 'zones_id', 'variable', 'mean_value', 'processed_at']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")
            
            # Validate variable encoding
            valid_variables = set(self.VARIABLE_ENCODING.keys())
            invalid_variables = set(df['variable'].unique()) - valid_variables
            
            if invalid_variables:
                logger.warning(f"Found invalid variable codes: {invalid_variables}")
                df = df[df['variable'].isin(valid_variables)]
            
            # Validate time format (YYYYMMDDTHH)
            try:
                df['gtime_parsed'] = pd.to_datetime(df['gtime'], format='%Y%m%dT%H')
            except ValueError as e:
                logger.error(f"Invalid time format in gtime column: {e}")
                raise
            
            # Sort by time and zone for consistent processing
            df = df.sort_values(['gtime_parsed', 'zones_id', 'variable']).reset_index(drop=True)
            
            logger.info(f"Loaded {len(df)} records from lean table")
            logger.info(f"Variables present: {sorted(df['variable'].unique())}")
            logger.info(f"Zones present: {sorted(df['zones_id'].unique())}")
            logger.info(f"Time range: {df['gtime'].min()} to {df['gtime'].max()}")
            
            self.lean_table_data = df
            return df
            
        except Exception as e:
            logger.error(f"Failed to load lean table data: {e}")
            raise
    
    def load_shapefile_data(self, shapefile_path: str) -> gpd.GeoDataFrame:
        """
        Load and process geospatial data (shapefile or GeoJSON) for zone spatial mapping
        
        Args:
            shapefile_path: Path to geospatial file with zone definitions (shapefile or GeoJSON)
            
        Returns:
            gpd.GeoDataFrame: Processed geospatial data
        """
        logger.info(f"Loading geospatial data from: {shapefile_path}")
        
        try:
            # Load geospatial file (supports shapefile, GeoJSON, etc.)
            gdf = gpd.read_file(shapefile_path)
            
            # Validate required columns
            required_columns = ['GRIDCODE', 'zone', 'id']
            missing_columns = [col for col in required_columns if col not in gdf.columns]
            
            if missing_columns:
                raise ValueError(f"Missing required geospatial file columns: {missing_columns}")
            
            logger.info(f"Loaded geospatial file with {len(gdf)} polygons")
            logger.info(f"Zones present: {sorted(gdf['zone'].unique())}")
            logger.info(f"GRIDCODE range: {gdf['GRIDCODE'].min()} to {gdf['GRIDCODE'].max()}")
            
            self.shapefile_data = gdf
            return gdf
            
        except Exception as e:
            logger.error(f"Failed to load geospatial data: {e}")
            raise
    
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
            
            # Create mapping based on existing header order
            # existing_header contains GRIDCODE values in hydrological order
            # We need to map zones_id (from shapefile) to position in this order
            
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
        
        # Log actual zone sizes (variable per zone)
        logger.info("Zone sizes with hydrological ordering preserved:")
        for zone, size in self.zone_sizes.items():
            logger.info(f"  {zone}: {size} spatial units")
        
        self.zone_spatial_mapping = zone_mappings
        return zone_mappings
    
    def extract_date_from_filename(self, lean_table_path: str) -> str:
        """
        Extract date from flox results filename
        
        Args:
            lean_table_path: Path to lean table CSV file
            
        Returns:
            str: Extracted date string (YYYYMMDD)
        """
        filename = os.path.basename(lean_table_path)
        
        # Pattern to match date in filename (e.g., flox_results_lean_long_table_v3_20250731.csv)
        date_pattern = r'(\d{8})'
        match = re.search(date_pattern, filename)
        
        if match:
            extracted_date = match.group(1)
            logger.info(f"Extracted date from filename: {extracted_date}")
            return extracted_date
        else:
            logger.warning(f"Could not extract date from filename: {filename}")
            # Fallback to current date
            fallback_date = datetime.now().strftime('%Y%m%d')
            logger.warning(f"Using fallback date: {fallback_date}")
            return fallback_date
    
    def copy_existing_zone_structure(self, source_base_dir: str, target_base_dir: str, 
                                   source_date: str, target_date: str) -> bool:
        """
        Copy existing zone folder structure to new date-specific folder
        
        Args:
            source_base_dir: Base output directory (e.g., 'zone_output')
            target_base_dir: Base output directory (same as source)
            source_date: Source date string for folder name (e.g., '20250501')
            target_date: Target date string for folder name (e.g., '20250731')
            
        Returns:
            bool: True if copy successful, False otherwise
        """
        source_dir = os.path.join(source_base_dir, f"lt_stable_input_{source_date}")
        target_dir = os.path.join(target_base_dir, f"lt_stable_input_{target_date}")
        
        if not os.path.exists(source_dir):
            logger.warning(f"Source directory does not exist: {source_dir}")
            logger.info("Will create new folder structure from scratch")
            return False
        
        if os.path.exists(target_dir):
            logger.warning(f"Target directory already exists: {target_dir}")
            logger.info("Will use existing target directory")
            return True
        
        try:
            logger.info(f"Copying folder structure from {source_dir} to {target_dir}")
            shutil.copytree(source_dir, target_dir)
            logger.info(f"Successfully copied zone structure to {target_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to copy folder structure: {e}")
            logger.info("Will create new folder structure from scratch")
            return False
    
    def find_latest_zone_folder(self, base_dir: str) -> Optional[str]:
        """
        Find the most recent zone folder to use as source for copying
        
        Args:
            base_dir: Base output directory
            
        Returns:
            str: Latest date string found, or None if no folders exist
        """
        import glob
        
        pattern = os.path.join(base_dir, "lt_stable_input_*")
        folders = glob.glob(pattern)
        
        if not folders:
            logger.warning(f"No existing zone folders found in {base_dir}")
            return None
        
        # Extract dates from folder names and find latest
        dates = []
        for folder in folders:
            folder_name = os.path.basename(folder)
            if folder_name.startswith("lt_stable_input_"):
                date_part = folder_name.replace("lt_stable_input_", "")
                if len(date_part) == 8 and date_part.isdigit():
                    dates.append(date_part)
        
        if dates:
            latest_date = max(dates)
            logger.info(f"Found latest zone folder: lt_stable_input_{latest_date}")
            return latest_date
        
        logger.warning("No valid date folders found")
        return None
    
    def convert_gtime_to_julian(self, gtime_str: str) -> str:
        """
        Convert gtime format (YYYYMMDDTHH) to Julian day format (YYYYDDD)
        
        Args:
            gtime_str: Time string in YYYYMMDDTHH format
            
        Returns:
            str: Julian day format YYYYDDD
        """
        try:
            dt = datetime.strptime(gtime_str, '%Y%m%dT%H')
            julian_day = dt.timetuple().tm_yday
            return f"{dt.year}{julian_day:03d}"
        except ValueError as e:
            logger.error(f"Failed to convert time format '{gtime_str}': {e}")
            raise
    
    def process_zone_data(self, zone: str, variable: int) -> Dict[str, List[float]]:
        """
        Process data for specific zone and variable combination
        
        Args:
            zone: Zone identifier (zone1-zone6)
            variable: Variable code (1, 2, or 3)
            
        Returns:
            Dict: Mapping of julian_date -> list of spatial values (zone-specific count)
        """
        if self.lean_table_data is None:
            raise ValueError("Lean table data not loaded")
        
        if zone not in self.zone_spatial_mapping:
            raise ValueError(f"Zone {zone} not found in spatial mapping")
        
        # Filter data for this zone and variable
        zone_mapping = self.zone_spatial_mapping[zone]
        valid_zones_ids = set(zone_mapping.keys())
        
        zone_data = self.lean_table_data[
            (self.lean_table_data['zones_id'].isin(valid_zones_ids)) &
            (self.lean_table_data['variable'] == variable)
        ].copy()
        
        if len(zone_data) == 0:
            logger.warning(f"No data found for {zone}, variable {variable}")
            return {}
        
        # Convert time format and group by date
        zone_data['julian_date'] = zone_data['gtime'].apply(self.convert_gtime_to_julian)
        
        # Process each unique date
        time_series_data = {}
        
        for julian_date in sorted(zone_data['julian_date'].unique()):
            date_data = zone_data[zone_data['julian_date'] == julian_date]
            
            # Get zone size and initialize spatial values array (variable size per zone)
            zone_size = self.zone_sizes.get(zone, 0)
            if zone_size == 0:
                logger.warning(f"No size information for {zone}")
                continue
            
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
    
    def load_existing_zone_header(self, zone: str, base_output_dir: str = "zone_output") -> List[int]:
        """
        🚨 CRITICAL: Load existing zone header to preserve hydrological ordering
        
        This method extracts the header from existing zone files to maintain the
        river/stream network topology ordering essential for GeoSFM hydrological model.
        
        Args:
            zone: Zone identifier (zone1-zone6)
            base_output_dir: Base directory containing existing zone files
            
        Returns:
            List[int]: Existing header order (GRIDCODE values in hydrological order)
        """
        # Try to find existing zone file in various date directories
        search_paths = [
            f"{base_output_dir}/lt_stable_input_20250501/{zone}/rain.txt",
            f"{base_output_dir}/lt_stable_input_20250501/{zone}/evap.txt",
        ]
        
        # Also search for any other date directories
        import glob
        date_dirs = glob.glob(f"{base_output_dir}/lt_stable_input_*")
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
        
    def generate_zone_header(self, zone: str) -> List[int]:
        """
        Generate zone-specific header row preserving hydrological ordering
        
        Args:
            zone: Zone identifier (zone1-zone6)
            
        Returns:
            List[int]: Zone-specific spatial unit identifiers in hydrological order
        """
        # CRITICAL: Always use existing header to preserve hydrological ordering
        if zone not in self.zone_headers:
            existing_header = self.load_existing_zone_header(zone)
            if existing_header:
                self.zone_headers[zone] = existing_header
            else:
                logger.error(f"❌ Cannot generate header for {zone} - no existing reference found!")
                return []
        
        return self.zone_headers[zone]
    
    def generate_header_row(self) -> List[int]:
        """
        Generate header row with spatial unit identifiers (legacy method)
        
        Returns:
            List[int]: All spatial unit identifiers
        """
        # Generate dynamic header based on geospatial data GRIDCODE values
        # This returns all GRIDCODE values across all zones
        if self.shapefile_data is not None:
            # Use actual GRIDCODE values from geospatial data for consistency
            header = sorted(self.shapefile_data['GRIDCODE'].unique().tolist())
            logger.info(f"Generated dynamic header with {len(header)} spatial units from geospatial data")
        else:
            # Fallback to example pattern if geospatial data not loaded
            header = [
                44, 46, 50, 14, 53, 58, 15, 18, 62, 25, 69, 26, 70, 28, 73, 52, 76, 30, 55, 61,
                8, 54, 79, 5, 33, 64, 82, 4, 23, 27, 81, 65, 48, 60, 42, 9, 63, 32, 37, 36,
                24, 16, 3, 86, 39, 85, 17, 47, 71, 84, 29, 45, 31, 77, 72, 74, 35, 12, 49, 43,
                67, 22, 34, 56, 57, 19, 59, 20, 41, 78, 83, 1, 80, 68, 75, 66, 11, 51, 2, 21,
                7, 6, 13, 40, 38, 10
            ]
            logger.warning("Using fallback header pattern - geospatial data not loaded")
        
        return header
    
    def load_existing_zone_file(self, file_path: str) -> Tuple[List[int], Dict[str, List[float]]]:
        """
        Load existing zone file and parse header + time series data
        
        Args:
            file_path: Path to existing zone txt file
            
        Returns:
            Tuple: (header_row, time_series_data)
        """
        if not os.path.exists(file_path):
            logger.info(f"File does not exist: {file_path}")
            return [], {}
        
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()
            
            if len(lines) < 1:
                logger.warning(f"Empty file: {file_path}")
                return [], {}
            
            # Parse header (first line)
            header_line = lines[0].strip()
            if header_line.startswith('NA,'):
                header_values = header_line[3:].split(',')  # Remove 'NA,' prefix
                header = [int(val) for val in header_values if val.strip()]
            else:
                logger.warning(f"Unexpected header format in {file_path}")
                header = []
            
            # Parse time series data
            time_series = {}
            for line in lines[1:]:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split(',')
                if len(parts) < 2:
                    continue
                
                julian_date = parts[0]
                # Handle 'NA' values and empty values
                values = []
                for val in parts[1:]:
                    if val.strip() == '' or val.strip().upper() == 'NA':
                        values.append(0.0)
                    else:
                        try:
                            values.append(float(val))
                        except ValueError:
                            values.append(0.0)
                
                # Ensure correct number of values based on expected zone structure
                # Note: Variable zone sizes, not fixed at 87
                
                time_series[julian_date] = values
            
            logger.info(f"Loaded {len(time_series)} time steps from {file_path}")
            return header, time_series
            
        except Exception as e:
            logger.error(f"Failed to load existing file {file_path}: {e}")
            return [], {}
    
    def filter_historical_data(self, time_series: Dict[str, List[float]], 
                              forecast_start_date: str) -> Dict[str, List[float]]:
        """
        Filter time series to keep only historical/observational data
        
        Args:
            time_series: Time series data dict
            forecast_start_date: Julian date string where forecasts begin
            
        Returns:
            Dict: Filtered time series with only historical data
        """
        historical_data = {}
        
        for julian_date, values in time_series.items():
            if julian_date < forecast_start_date:
                historical_data[julian_date] = values
        
        logger.info(f"Filtered to {len(historical_data)} historical records " +
                   f"(before {forecast_start_date})")
        return historical_data
    
    def combine_time_series(self, historical_data: Dict[str, List[float]], 
                          new_data: Dict[str, List[float]]) -> Dict[str, List[float]]:
        """
        Combine historical and new time series data
        
        Args:
            historical_data: Historical time series
            new_data: New observations and forecasts
            
        Returns:
            Dict: Combined time series
        """
        combined = historical_data.copy()
        combined.update(new_data)
        
        logger.info(f"Combined time series: {len(historical_data)} historical + " +
                   f"{len(new_data)} new = {len(combined)} total records")
        
        return combined
    
    def write_zone_file(self, file_path: str, header: List[int], 
                       time_series: Dict[str, List[float]], zone: str):
        """
        Write zone txt file with header and time series data (variable length per zone)
        
        Args:
            file_path: Output file path
            header: Header row with spatial identifiers
            time_series: Time series data
            zone: Zone identifier for size validation
        """
        try:
            # Create output directory if needed
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Get expected zone size
            zone_size = self.zone_sizes.get(zone, len(header))
            
            with open(file_path, 'w') as f:
                # Write header (zone-specific length)
                zone_header = header[:zone_size] if len(header) >= zone_size else header + [0] * (zone_size - len(header))
                header_str = 'NA,' + ','.join(map(str, zone_header))
                f.write(header_str + '\n')
                
                # Write time series data (sorted by date)
                for julian_date in sorted(time_series.keys()):
                    values = time_series[julian_date]
                    # Ensure values match zone size
                    padded_values = (values + [0.0] * zone_size)[:zone_size]
                    row = [julian_date] + [f"{val:.1f}" if val > 0 else "0" for val in padded_values]
                    f.write(','.join(row) + '\n')
            
            logger.info(f"Written {len(time_series)} time steps to {file_path}")
            
        except Exception as e:
            logger.error(f"Failed to write file {file_path}: {e}")
            raise
    
    def replicate_pet_for_forecast(self, pet_data: Dict[str, List[float]], 
                                  forecast_dates: List[str]) -> Dict[str, List[float]]:
        """
        Replicate latest PET values for forecast period
        
        Args:
            pet_data: Existing PET time series
            forecast_dates: List of Julian dates for forecast period
            
        Returns:
            Dict: PET data extended with replicated forecast values
        """
        if not pet_data:
            logger.warning("No PET data available for replication")
            return {}
        
        # Get the most recent PET values
        latest_date = max(pet_data.keys())
        latest_values = pet_data[latest_date]
        
        # Extend with replicated values
        extended_data = pet_data.copy()
        
        for forecast_date in forecast_dates:
            if forecast_date not in extended_data:
                extended_data[forecast_date] = latest_values.copy()
        
        logger.info(f"Replicated PET values for {len(forecast_dates)} forecast dates")
        return extended_data
    
    def process_single_zone(self, zone: str, output_dir: str, preserve_history: bool = True):
        """
        Process data for a single zone and generate rain.txt and evap.txt files
        
        Args:
            zone: Zone identifier (zone1-zone6)
            output_dir: Output directory path
            preserve_history: Whether to preserve historical data from existing files
        """
        logger.info(f"Processing {zone}")
        
        # Create zone output directory
        zone_dir = os.path.join(output_dir, zone)
        os.makedirs(zone_dir, exist_ok=True)
        
        # Process rainfall data (Variables 1 + 3)
        rain_file_path = os.path.join(zone_dir, 'rain.txt')
        
        # Load existing rain data if preserving history
        rain_header = self.generate_zone_header(zone)
        rain_historical = {}
        
        if preserve_history:
            rain_header, rain_historical = self.load_existing_zone_file(rain_file_path)
        
        # Process new IMERG data (Variable 1)
        imerg_data = self.process_zone_data(zone, 1)
        
        # Process new CHIRPS-GEFS data (Variable 3)
        chirps_data = self.process_zone_data(zone, 3)
        
        # Combine IMERG and CHIRPS-GEFS data
        rain_new_data = {}
        zone_size = self.zone_sizes.get(zone, 0)
        
        for date in sorted(set(list(imerg_data.keys()) + list(chirps_data.keys()))):
            # Combine values from both sources (sum precipitation)
            imerg_vals = np.array(imerg_data.get(date, [0.0] * zone_size))
            chirps_vals = np.array(chirps_data.get(date, [0.0] * zone_size))
            combined_vals = imerg_vals + chirps_vals
            rain_new_data[date] = combined_vals.tolist()
        
        # Determine forecast start date (approximate based on data)
        if rain_new_data:
            forecast_start_date = min(rain_new_data.keys())
            
            # Filter historical data to remove old forecasts
            if preserve_history:
                rain_historical = self.filter_historical_data(rain_historical, forecast_start_date)
            
            # Combine historical and new data
            rain_combined = self.combine_time_series(rain_historical, rain_new_data)
        else:
            rain_combined = rain_historical
        
        # Write rain file
        self.write_zone_file(rain_file_path, rain_header, rain_combined, zone)
        
        # Process evapotranspiration data (Variable 2)
        evap_file_path = os.path.join(zone_dir, 'evap.txt')
        
        # Load existing evap data if preserving history
        evap_header = self.generate_zone_header(zone)
        evap_historical = {}
        
        if preserve_history:
            evap_header, evap_historical = self.load_existing_zone_file(evap_file_path)
        
        # Process new PET data (Variable 2)
        pet_data = self.process_zone_data(zone, 2)
        
        # Extend PET data for forecast period (replicate latest values)
        if rain_new_data and pet_data:
            forecast_dates = [date for date in rain_new_data.keys() 
                            if date not in pet_data]
            pet_extended = self.replicate_pet_for_forecast(pet_data, forecast_dates)
        else:
            pet_extended = pet_data
        
        # Filter historical evap data and combine with new data
        if pet_extended:
            forecast_start_date = min(pet_extended.keys()) if pet_extended else None
            
            if preserve_history and forecast_start_date:
                evap_historical = self.filter_historical_data(evap_historical, forecast_start_date)
            
            evap_combined = self.combine_time_series(evap_historical, pet_extended)
        else:
            evap_combined = evap_historical
        
        # Write evap file
        self.write_zone_file(evap_file_path, evap_header, evap_combined, zone)
        
        logger.info(f"Completed processing {zone}")
    
    def generate_zone_files(self, lean_table_path: str, shapefile_path: str, 
                          output_dir: str, date_str: str = None, zones: Optional[List[str]] = None,
                          preserve_history: bool = True):
        """
        Main method to generate zone-wise txt files
        
        Args:
            lean_table_path: Path to lean table CSV file
            shapefile_path: Path to geospatial file with zone definitions (shapefile or GeoJSON)
            output_dir: Base output directory
            date_str: Date string for output directory naming (if None, extract from filename)
            zones: List of specific zones to process (default: all zones)
            preserve_history: Whether to preserve historical data
        """
        logger.info("=" * 70)
        logger.info("STARTING ZONE-WISE TXT FILE GENERATION")
        logger.info("=" * 70)
        
        start_time = datetime.now()
        
        try:
            # Extract date from filename if not provided
            if date_str is None:
                date_str = self.extract_date_from_filename(lean_table_path)
            
            logger.info(f"Using date: {date_str}")
            
            # Find latest existing folder to copy from
            latest_source_date = self.find_latest_zone_folder(output_dir)
            
            # Copy existing folder structure if available
            if latest_source_date and latest_source_date != date_str:
                logger.info(f"Copying existing structure from {latest_source_date} to {date_str}")
                copy_success = self.copy_existing_zone_structure(
                    output_dir, output_dir, latest_source_date, date_str
                )
                if copy_success:
                    logger.info("✓ Successfully copied existing folder structure")
                else:
                    logger.info("Will create new folder structure")
            else:
                logger.info("No existing folder to copy or target already exists")
            
            # Load input data
            self.load_lean_table_data(lean_table_path)
            self.load_shapefile_data(shapefile_path)
            
            # Create spatial mapping
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
                    self.process_single_zone(zone, date_output_dir, preserve_history)
                except Exception as e:
                    logger.error(f"Failed to process {zone}: {e}")
                    continue
            
            # Final summary
            end_time = datetime.now()
            duration = end_time - start_time
            
            logger.info("=" * 70)
            logger.info("ZONE-WISE TXT FILE GENERATION COMPLETED")
            logger.info("=" * 70)
            logger.info(f"Total duration: {duration}")
            logger.info(f"Zones processed: {len(target_zones)}")
            logger.info(f"Output directory: {date_output_dir}")
            logger.info(f"Historical data preserved: {preserve_history}")
            
        except Exception as e:
            logger.error(f"Zone-wise txt generation failed: {e}")
            raise


def main():
    """Main entry point for command line usage"""
    parser = argparse.ArgumentParser(
        description="Generate zone-wise txt files from lean table climate data"
    )
    
    parser.add_argument(
        "--lean-table", 
        type=str, 
        required=True,
        help="Path to lean long table CSV file from flox processor"
    )
    
    parser.add_argument(
        "--shapefile", 
        type=str, 
        required=True,
        help="Path to geospatial file with zone definitions (shapefile or GeoJSON)"
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
        required=False,
        help="Date string for output directory naming (YYYYMMDD). If not provided, will extract from lean-table filename"
    )
    
    parser.add_argument(
        "--zones", 
        type=str,
        help="Comma-separated list of zones to process (e.g., zone1,zone3,zone5)"
    )
    
    parser.add_argument(
        "--no-preserve-history", 
        action="store_true",
        help="Do not preserve historical data from existing files"
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
    
    generator = ZoneWiseTxtGenerator(config)
    
    # Generate zone files
    generator.generate_zone_files(
        lean_table_path=args.lean_table,
        shapefile_path=args.shapefile,
        output_dir=args.output_dir,
        date_str=args.date_str,
        zones=zones,
        preserve_history=not args.no_preserve_history
    )


if __name__ == "__main__":
    main()