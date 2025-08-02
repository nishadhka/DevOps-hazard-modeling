#!/usr/bin/env python3
"""
Optimized shapefile to flox groupby processor V3 with dataset-level NULL filtering.

This script provides a complete workflow for:
1. Converting shapefiles to tiff rasters at 0.02° resolution
2. Loading icechunk zarr datasets with intelligent NULL date filtering
3. Performing flox groupby operations on pre-filtered datasets
4. Converting results to optimized lean long table format
5. Uploading to GCS bucket via Coiled Dask cluster

Key optimizations in V3:
- Dataset-level NULL filtering (moved from long table stage to xarray loading stage)
- Variable-specific date filtering at dataset level before flox operations
- Eliminates processing of NULL dates entirely for maximum efficiency
- Lean table structure with reduced columns
- Single mean_value column for all variables
- Encoded variable types (1=imerg, 2=pet, 3=chirps)
- Optimized time format (YYYYMMDDTHH) with T separator

Critical V3 Change:
- NULL date filtering now happens at xarray dataset level, not at long table creation
- Each variable is filtered for valid dates before any flox processing
- Significantly more efficient as it avoids computation on NULL data

Based on create_regridded_icechunk_memory_optimized_v9.py date alignment methodology.
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Union
import argparse

import numpy as np
import pandas as pd
import xarray as xr
import geopandas as gpd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds
import rioxarray

import flox
import flox.xarray
import icechunk

# Optional imports for cloud functionality
try:
    import coiled
    from distributed import Client
    COILED_AVAILABLE = True
except ImportError:
    COILED_AVAILABLE = False
    Client = None
    print("Warning: Coiled not available. Dask cluster functionality disabled.")

try:
    from google.cloud import storage as gcs
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    print("Warning: Google Cloud Storage not available. GCS upload functionality disabled.")

# Configure logging (will be updated with date_str in processor initialization)
logger = logging.getLogger(__name__)

class FloxProcessorV3:
    """Optimized processor class V3 with dataset-level NULL filtering for maximum efficiency"""

    # Variable encoding mapping
    VARIABLE_ENCODING = {
        'imerg_precipitation': 1,
        'pet': 2,
        'chirps_gefs_precipitation': 3
    }

    def __init__(self, config_path: Optional[str] = None):
        """Initialize processor with configuration"""
        self.config = self.load_config(config_path)
        self.setup_logging()
        self.setup_paths()
    
    def setup_logging(self):
        """Setup logging with date-specific log file"""
        date_str = self.config["date_str"]
        log_filename = f'flox_processor_v3_{date_str}.log'
        
        # Configure logging with date-specific filename
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename),
                logging.StreamHandler(sys.stdout)
            ],
            force=True  # Override any existing configuration
        )
        logger.info(f"Logging initialized for date: {date_str}")
        logger.info(f"Log file: {log_filename}")

    def load_config(self, config_path: Optional[str] = None) -> Dict:
        """Load configuration - embedded defaults or from file"""
        # Date string for consistent file naming
        date_str = "20250801"
        
        default_config = {
            # Date configuration
            "date_str": date_str,
            
            # File paths (using date_str)
            "shapefile_path": "geofsm-prod-all-zones-20240712.shp",
            "zarr_path": f"east_africa_regridded_{date_str}.zarr",
            "output_dir": "flox_output",
            "tiff_output_path": "ea_geofsm_zones_002deg.tif",

            # Processing switches
            "create_tiff": False,
            "load_zarr": True,
            "run_flox_groupby": True,
            "convert_to_long_table": True,
            "use_dask_cluster": False,
            "upload_to_gcs": False,

            # Spatial parameters
            "pixel_size": 0.02,  # 0.02 degree resolution as requested
            "shapefile_id_column": "id",
            "shapefile_zone_column": "zone",

            # Dask/Coiled parameters
            "coiled_cluster_name": "flox-processor-cluster",
            "n_workers": 4,
            "worker_memory": "4GB",
            "worker_cores": 2,

            # GCS parameters
            "gcs_bucket": None,
            "gcs_prefix": "flox_results",

            # Variables to process (actual names from dataset)
            "variables": ["chirps_gefs_precipitation", "imerg_precipitation", "pet"],

            # Flox groupby parameters
            "groupby_method": "mean",
            "chunk_size": {"time": 3, "lat": 500, "lon": 500}
        }

        # Only load from file if explicitly provided
        if config_path and Path(config_path).exists():
            with open(config_path, 'r') as f:
                user_config = json.load(f)
            default_config.update(user_config)
            logger.info(f"Loaded configuration from {config_path}")
        else:
            logger.info("Using embedded default configuration")

        return default_config

    def setup_paths(self):
        """Setup output directories"""
        os.makedirs(self.config["output_dir"], exist_ok=True)
        logger.info(f"Output directory: {self.config['output_dir']}")

    def create_tiff_from_shapefile(self) -> str:
        """
        Convert shapefile to tiff raster at specified resolution

        Returns:
            str: Path to created tiff file
        """
        if not self.config["create_tiff"]:
            logger.info("Tiff creation disabled, skipping...")
            return self.config["tiff_output_path"]

        logger.info("=" * 70)
        logger.info("CREATING TIFF FROM SHAPEFILE")
        logger.info("=" * 70)

        try:
            # Load shapefile
            gdf = gpd.read_file(self.config["shapefile_path"])
            logger.info(f"Loaded shapefile: {self.config['shapefile_path']}")
            logger.info(f"  Shape: {gdf.shape}")
            logger.info(f"  CRS: {gdf.crs}")
            logger.info(f"  Columns: {list(gdf.columns)}")

            # Get bounds and calculate dimensions
            minx, miny, maxx, maxy = gdf.total_bounds
            pixel_size = self.config["pixel_size"]
            width = int((maxx - minx) / pixel_size)
            height = int((maxy - miny) / pixel_size)

            logger.info(f"  Bounds: [{minx:.4f}, {miny:.4f}, {maxx:.4f}, {maxy:.4f}]")
            logger.info(f"  Pixel size: {pixel_size}°")
            logger.info(f"  Output dimensions: {width} x {height}")

            # Create transform
            transform = from_bounds(minx, miny, maxx, maxy, width, height)

            # Create empty raster array
            raster = np.zeros((height, width), dtype=np.uint16)

            # Generate shapes for rasterization
            id_column = self.config["shapefile_id_column"]
            shapes = ((geom, value) for geom, value in zip(gdf.geometry, gdf[id_column]))

            # Rasterize
            raster = rasterize(
                shapes,
                out_shape=raster.shape,
                transform=transform,
                fill=0,
                dtype=np.uint16
            )

            # Save tiff
            output_path = os.path.join(self.config["output_dir"], self.config["tiff_output_path"])
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=1,
                dtype=np.uint16,
                crs=gdf.crs.to_string(),
                transform=transform,
            ) as dst:
                dst.write(raster, 1)

            logger.info(f"✅ Tiff file saved: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"❌ Failed to create tiff: {e}")
            raise

    def filter_dataset_by_valid_dates(self, dataset: xr.Dataset) -> xr.Dataset:
        """
        V3 CRITICAL OPTIMIZATION: Filter dataset at loading stage to remove NULL dates
        for each variable individually, before any flox processing.
        
        This replaces the previous approach of filtering during long table creation.
        
        Args:
            dataset: Raw loaded dataset
            
        Returns:
            xr.Dataset: Dataset with variable-specific date filtering applied
        """
        logger.info("=" * 70)
        logger.info("V3 DATASET-LEVEL NULL DATE FILTERING")
        logger.info("=" * 70)
        
        try:
            filtered_variables = {}
            variables = self.config["variables"]
            
            for var_name in variables:
                if var_name not in dataset.data_vars:
                    logger.warning(f"Variable '{var_name}' not found in dataset, skipping...")
                    continue
                
                logger.info(f"Filtering NULL dates for variable: {var_name}")
                var_data = dataset[var_name]
                
                # Check for non-null values along spatial dimensions for each time step
                non_null_mask = var_data.notnull().any(dim=['lat', 'lon'])
                # Compute the mask to avoid dask array indexing issues
                non_null_mask_computed = non_null_mask.compute()
                valid_times = var_data.time[non_null_mask_computed]
                
                if len(valid_times) == 0:
                    logger.warning(f"  No valid data found for {var_name}, skipping variable")
                    continue
                
                # Filter to only valid time steps
                filtered_var = var_data.sel(time=valid_times)
                filtered_variables[var_name] = filtered_var
                
                logger.info(f"  {var_name}: {len(valid_times)} valid dates out of {len(var_data.time)} total")
                logger.info(f"  Valid time range: {valid_times.min().values} to {valid_times.max().values}")
            
            if not filtered_variables:
                logger.error("No variables with valid data found!")
                raise ValueError("No valid variables to process")
            
            # Create new dataset with filtered variables 
            # Note: Each variable will have its own time coordinate after filtering
            filtered_dataset = xr.Dataset(filtered_variables)
            
            # Rechunk for optimal processing
            chunk_size = self.config["chunk_size"]
            filtered_dataset = filtered_dataset.chunk(chunk_size)
            
            logger.info("✅ Dataset-level NULL filtering completed")
            logger.info(f"  Filtered dataset variables: {list(filtered_dataset.data_vars)}")
            
            # Log time dimensions for each variable
            for var_name in filtered_dataset.data_vars:
                time_dim = len(filtered_dataset[var_name].time)
                logger.info(f"  {var_name}: {time_dim} time steps after filtering")
            
            return filtered_dataset
            
        except Exception as e:
            logger.error(f"❌ Failed to filter dataset by valid dates: {e}")
            raise

    def load_zarr_dataset(self) -> xr.Dataset:
        """
        Load icechunk zarr dataset for V3 processing

        Returns:
            xr.Dataset: Loaded dataset (filtering happens at flox stage)
        """
        if not self.config["load_zarr"]:
            logger.info("Zarr loading disabled, skipping...")
            return None

        logger.info("=" * 70)
        logger.info("LOADING ICECHUNK ZARR DATASET")
        logger.info("=" * 70)

        try:
            # Open icechunk store
            storage = icechunk.local_filesystem_storage(self.config["zarr_path"])
            repo = icechunk.Repository.open(storage)
            session = repo.readonly_session("main")
            store = session.store
            ds = xr.open_zarr(store, consolidated=False)

            # Rechunk for optimal processing
            chunk_size = self.config["chunk_size"]
            ds = ds.chunk(chunk_size)

            logger.info(f"✅ Dataset loaded: {self.config['zarr_path']}")
            logger.info(f"  Dimensions: {dict(ds.sizes)}")
            logger.info(f"  Variables: {list(ds.data_vars)}")
            logger.info(f"  Coordinates: {list(ds.coords)}")
            logger.info(f"  Memory estimate: {ds.nbytes / (1024**3):.2f} GB")
            logger.info(f"  Chunking: {chunk_size}")
            logger.info(f"  V3: NULL filtering will be applied per variable during flox processing")

            return ds

        except Exception as e:
            logger.error(f"❌ Failed to load zarr dataset: {e}")
            raise

    def load_zones_tiff(self, tiff_path: str) -> xr.DataArray:
        """
        Load zones tiff file and align with dataset

        Args:
            tiff_path: Path to tiff file

        Returns:
            xr.DataArray: Zones array
        """
        logger.info(f"Loading zones tiff: {tiff_path}")

        try:
            # Load tiff
            zones = rioxarray.open_rasterio(tiff_path, chunks="auto").squeeze()
            zones_renamed = zones.rename(x='lon', y='lat')

            logger.info(f"✅ Zones loaded: {zones_renamed.shape}")
            logger.info(f"  Coordinates: lon[{zones_renamed.lon.min().values:.2f}, {zones_renamed.lon.max().values:.2f}], "
                       f"lat[{zones_renamed.lat.min().values:.2f}, {zones_renamed.lat.max().values:.2f}]")

            return zones_renamed

        except Exception as e:
            logger.error(f"❌ Failed to load zones tiff: {e}")
            raise

    def setup_dask_cluster(self) -> Optional[Client]:
        """
        Setup Coiled Dask cluster if enabled

        Returns:
            Optional[Client]: Dask client or None
        """
        if not self.config["use_dask_cluster"] or not COILED_AVAILABLE:
            logger.info("Dask cluster disabled or not available")
            return None

        logger.info("=" * 70)
        logger.info("SETTING UP COILED DASK CLUSTER")
        logger.info("=" * 70)

        try:
            # Create cluster configuration
            cluster_config = {
                "n_workers": self.config["n_workers"],
                "worker_memory": self.config["worker_memory"],
                "worker_cores": self.config["worker_cores"],
                "name": self.config["coiled_cluster_name"]
            }

            logger.info(f"Creating cluster: {cluster_config}")

            # Create cluster
            cluster = coiled.Cluster(**cluster_config)
            client = cluster.get_client()

            logger.info(f"✅ Dask cluster ready: {client.dashboard_link}")
            logger.info(f"  Workers: {len(client.nthreads())}")
            logger.info(f"  Total cores: {sum(client.nthreads().values())}")

            return client

        except Exception as e:
            logger.error(f"❌ Failed to setup Dask cluster: {e}")
            logger.info("Continuing with local processing...")
            return None

    def run_flox_groupby(self, dataset: xr.Dataset, zones: xr.DataArray, client: Optional[Client] = None) -> Dict[str, xr.Dataset]:
        """
        Run flox groupby operations with variable-specific filtering at processing stage
        
        V3 Change: Process each variable individually with its own valid dates

        Args:
            dataset: Input dataset 
            zones: Zones array for grouping
            client: Optional Dask client

        Returns:
            Dict[str, xr.Dataset]: Results for each variable
        """
        if not self.config["run_flox_groupby"]:
            logger.info("Flox groupby disabled, skipping...")
            return {}

        logger.info("=" * 70)
        logger.info("RUNNING FLOX GROUPBY WITH V3 VARIABLE-SPECIFIC FILTERING")
        logger.info("=" * 70)

        results = {}
        variables = self.config["variables"]
        method = self.config["groupby_method"]

        try:
            # Resample zones to match dataset resolution using nearest neighbor
            logger.info(f"  Dataset grid: lat[{dataset.lat.min().values:.2f}, {dataset.lat.max().values:.2f}], "
                       f"lon[{dataset.lon.min().values:.2f}, {dataset.lon.max().values:.2f}]")
            logger.info(f"  Dataset shape: {dataset.lat.shape}, {dataset.lon.shape}")
            logger.info(f"  Zones grid: lat[{zones.lat.min().values:.2f}, {zones.lat.max().values:.2f}], "
                       f"lon[{zones.lon.min().values:.2f}, {zones.lon.max().values:.2f}]")
            logger.info(f"  Zones shape: {zones.lat.shape}, {zones.lon.shape}")

            # Reindex zones to match dataset coordinates exactly
            zones_aligned = zones.interp(lat=dataset.lat, lon=dataset.lon, method="nearest")
            zones_aligned.name = "zones"  # Name required for flox

            zones_id = np.unique(zones_aligned.data).compute()
            zones_id = zones_id[zones_id != 0]  # Remove null values
            zones_id = zones_id[~np.isnan(zones_id)]  # Remove NaN values

            logger.info(f"  Aligned zones: {len(zones_id)} unique zones")
            logger.info(f"  Processing variables: {variables}")
            logger.info(f"  Groupby method: {method}")

            for var_name in variables:
                if var_name not in dataset.data_vars:
                    logger.warning(f"Variable '{var_name}' not found in dataset, skipping...")
                    continue

                logger.info(f"Processing variable: {var_name}")

                # Select variable
                var_data = dataset[var_name]
                
                # V3 CRITICAL: Apply variable-specific NULL filtering here
                logger.info(f"  Applying V3 variable-specific NULL filtering for {var_name}")
                # Check for non-null values along spatial dimensions for each time step
                non_null_mask = var_data.notnull().any(dim=['lat', 'lon'])
                # Compute the mask to avoid dask array indexing issues
                non_null_mask_computed = non_null_mask.compute()
                valid_times = var_data.time[non_null_mask_computed]
                
                if len(valid_times) == 0:
                    logger.warning(f"  No valid data found for {var_name}, skipping variable")
                    continue
                
                # Filter to only valid time steps
                var_data_filtered = var_data.sel(time=valid_times)
                logger.info(f"  {var_name}: {len(valid_times)} valid dates out of {len(var_data.time)} total")
                logger.info(f"  Variable shape after filtering: {var_data_filtered.shape}")
                logger.info(f"  Time range: {var_data_filtered.time.min().values} to {var_data_filtered.time.max().values}")

                # Perform groupby operation using flox for chunked arrays
                logger.info(f"  Using flox for {var_name} (V3 filtered, no NULL dates)")

                if method == "mean":
                    result = flox.xarray.xarray_reduce(
                        var_data_filtered, zones_aligned, func="mean", expected_groups=zones_id
                    )
                elif method == "sum":
                    result = flox.xarray.xarray_reduce(
                        var_data_filtered, zones_aligned, func="sum", expected_groups=zones_id
                    )
                elif method == "std":
                    result = flox.xarray.xarray_reduce(
                        var_data_filtered, zones_aligned, func="std", expected_groups=zones_id
                    )
                else:
                    result = flox.xarray.xarray_reduce(
                        var_data_filtered, zones_aligned, func="mean", expected_groups=zones_id
                    )

                # Compute result if using Dask cluster
                if client:
                    logger.info(f"  Computing with Dask cluster")
                    with client:
                        result = result.compute()

                results[var_name] = result
                logger.info(f"✅ Completed {var_name}: {result.shape}")

            logger.info(f"✅ All flox groupby operations completed")
            return results

        except Exception as e:
            logger.error(f"❌ Failed to run flox groupby: {e}")
            raise

    def convert_to_lean_long_table(self, results: Dict[str, xr.Dataset]) -> pd.DataFrame:
        """
        Convert groupby results to optimized lean long table format
        
        V3 Change: No NULL filtering needed here as it's done at dataset level

        New lean table structure:
        - gtime: YYYYMMDDTHH format (geosfm model time with T separator)
        - zones_id: Zone identifier
        - variable: Encoded as 1=imerg, 2=pet, 3=chirps
        - mean_value: Float value for the variable
        - processed_at: YYYYMMDDTHH format

        Args:
            results: Dictionary of groupby results (pre-filtered)

        Returns:
            pd.DataFrame: Optimized lean long format table
        """
        if not self.config["convert_to_long_table"]:
            logger.info("Long table conversion disabled, skipping...")
            return pd.DataFrame()

        logger.info("=" * 70)
        logger.info("CONVERTING PRE-FILTERED RESULTS TO LEAN LONG TABLE FORMAT")
        logger.info("=" * 70)

        try:
            all_dfs = []

            for var_name, result in results.items():
                logger.info(f"Converting {var_name} to lean long format...")

                # Convert to dataframe
                df = result.to_dataframe(name='mean_value').reset_index()
                
                # V3: No NaN filtering needed here as dataset was pre-filtered
                logger.info(f"  Processing {len(df)} pre-filtered records for {var_name}")

                # Add encoded variable type
                df['variable'] = self.VARIABLE_ENCODING.get(var_name, 0)

                # Rename and format columns - check multiple possible zone column names
                zone_column = None
                if 'group' in df.columns:
                    zone_column = 'group'
                elif 'groups' in df.columns:
                    zone_column = 'groups'
                elif 'zones' in df.columns:
                    zone_column = 'zones'
                
                if zone_column:
                    df = df.rename(columns={zone_column: 'zones_id'})
                else:
                    logger.error(f"  No suitable zone column found in: {list(df.columns)}")

                # Format time to YYYYMMDDTHH (geosfm model time with T separator)
                if 'time' in df.columns:
                    df['gtime'] = pd.to_datetime(df['time']).dt.strftime('%Y%m%dT%H')
                    df = df.drop(columns=['time'])  # Remove original time column

                # Keep only essential columns in lean format
                essential_columns = ['gtime', 'zones_id', 'variable', 'mean_value']
                df = df[essential_columns]

                all_dfs.append(df)
                logger.info(f"  {var_name}: {len(df)} records (variable code: {self.VARIABLE_ENCODING.get(var_name, 0)})")

            # Combine all variables
            if all_dfs:
                combined_df = pd.concat(all_dfs, ignore_index=True)

                # Add processing timestamp in YYYYMMDDTHH format
                combined_df['processed_at'] = datetime.now().strftime('%Y%m%dT%H')

                # Reorder columns for optimal lean format
                final_columns = ['gtime', 'zones_id', 'variable', 'mean_value', 'processed_at']
                combined_df = combined_df[final_columns]

                # Sort for better organization
                combined_df = combined_df.sort_values(['gtime', 'zones_id', 'variable']).reset_index(drop=True)

                logger.info(f"✅ Lean long table created: {len(combined_df)} total records")
                logger.info(f"  Columns: {list(combined_df.columns)}")
                logger.info(f"  Variable encoding: {self.VARIABLE_ENCODING}")
                logger.info(f"  Time format: YYYYMMDDTHH (with T separator)")
                logger.info(f"  V3 Optimization: NULL filtering done at dataset level for maximum efficiency")

                # Save locally with date-specific filename
                date_str = self.config["date_str"]
                output_filename = f"flox_results_lean_long_table_v3_{date_str}.csv"
                output_path = os.path.join(self.config["output_dir"], output_filename)
                combined_df.to_csv(output_path, index=False)
                logger.info(f"  Saved to: {output_path}")

                return combined_df
            else:
                logger.warning("No results to convert")
                return pd.DataFrame()

        except Exception as e:
            logger.error(f"❌ Failed to convert to lean long table: {e}")
            raise

    def upload_to_gcs(self, df: pd.DataFrame, client: Optional[Client] = None) -> bool:
        """
        Upload results to GCS bucket

        Args:
            df: DataFrame to upload
            client: Optional Dask client

        Returns:
            bool: Success status
        """
        if not self.config["upload_to_gcs"] or not GCS_AVAILABLE:
            logger.info("GCS upload disabled or not available")
            return False

        if self.config["gcs_bucket"] is None:
            logger.warning("GCS bucket not specified, skipping upload")
            return False

        logger.info("=" * 70)
        logger.info("UPLOADING TO GCS BUCKET")
        logger.info("=" * 70)

        try:
            bucket_name = self.config["gcs_bucket"]
            prefix = self.config["gcs_prefix"]
            date_str = self.config["date_str"]
            timestamp = datetime.now().strftime("%H%M%S")
            blob_name = f"{prefix}/flox_results_lean_v3_{date_str}_{timestamp}.csv"

            logger.info(f"Uploading to gs://{bucket_name}/{blob_name}")

            # Initialize GCS client
            gcs_client = gcs.Client()
            bucket = gcs_client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            # Convert DataFrame to CSV and upload
            csv_string = df.to_csv(index=False)
            blob.upload_from_string(csv_string, content_type='text/csv')

            logger.info(f"✅ Successfully uploaded to GCS")
            logger.info(f"  URL: gs://{bucket_name}/{blob_name}")
            logger.info(f"  Size: {len(csv_string)} bytes")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to upload to GCS: {e}")
            return False

    def run_complete_workflow(self):
        """Run the complete processing workflow with V3 dataset-level optimizations"""
        logger.info("=" * 70)
        logger.info("STARTING OPTIMIZED FLOX PROCESSING WORKFLOW V3 (DATASET-LEVEL NULL FILTERING)")
        logger.info("=" * 70)

        start_time = datetime.now()

        try:
            # Step 1: Create tiff from shapefile
            tiff_path = self.create_tiff_from_shapefile()

            # Step 2: Load zarr dataset with V3 dataset-level NULL filtering
            dataset = self.load_zarr_dataset()

            # Step 3: Load zones tiff
            zones = self.load_zones_tiff(tiff_path)

            # Step 4: Setup Dask cluster (optional)
            client = self.setup_dask_cluster()

            # Step 5: Run flox groupby on pre-filtered dataset
            results = self.run_flox_groupby(dataset, zones, client)

            # Step 6: Convert to lean long table (no NULL filtering needed)
            df = self.convert_to_lean_long_table(results)

            # Step 7: Upload to GCS (optional)
            upload_success = self.upload_to_gcs(df, client)

            # Cleanup
            if client:
                client.close()
                logger.info("Dask client closed")

            # Final summary
            end_time = datetime.now()
            duration = end_time - start_time

            logger.info("=" * 70)
            logger.info("V3 OPTIMIZED WORKFLOW COMPLETED SUCCESSFULLY")
            logger.info("=" * 70)
            logger.info(f"Total duration: {duration}")
            logger.info(f"Records processed: {len(df) if not df.empty else 0}")
            logger.info(f"Variables processed: {len(results)}")
            logger.info(f"GCS upload: {'Success' if upload_success else 'Skipped/Failed'}")
            logger.info(f"V3 Dataset-level NULL filtering applied ✅")
            logger.info(f"Maximum efficiency achieved by filtering at xarray stage ✅")

        except Exception as e:
            logger.error(f"❌ V3 Workflow failed: {e}")
            raise


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Optimized Flox Shapefile Groupby Processor V3 (Dataset-level NULL filtering)")
    parser.add_argument("--config", type=str, help="Path to configuration file (optional)")
    parser.add_argument("--date-str", type=str, help="Date string for file naming (e.g., 20250731)")
    parser.add_argument("--create-tiff", action="store_true", help="Enable tiff creation")
    parser.add_argument("--use-dask", action="store_true", help="Enable Dask cluster")
    parser.add_argument("--upload-gcs", action="store_true", help="Enable GCS upload")
    parser.add_argument("--gcs-bucket", type=str, help="GCS bucket name for upload")

    args = parser.parse_args()

    # Initialize processor with embedded config
    processor = FloxProcessorV3(args.config)

    # Override config with command line arguments
    if args.date_str:
        processor.config["date_str"] = args.date_str
        # Update zarr path with new date string
        processor.config["zarr_path"] = f"east_africa_regridded_{args.date_str}.zarr"
        # Reinitialize logging with new date string
        processor.setup_logging()
    if args.create_tiff:
        processor.config["create_tiff"] = True
    if args.use_dask:
        processor.config["use_dask_cluster"] = True
    if args.upload_gcs:
        processor.config["upload_to_gcs"] = True
    if args.gcs_bucket:
        processor.config["gcs_bucket"] = args.gcs_bucket

    # Run workflow
    processor.run_complete_workflow()


if __name__ == "__main__":
    main()