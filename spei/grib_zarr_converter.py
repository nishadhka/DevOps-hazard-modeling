import xarray as xr
import cfgrib
import zarr
import numpy as np
from google.cloud import storage
import pandas as pd
from pathlib import Path
import logging
from typing import List, Dict, Tuple
import tempfile
import os
import gcsfs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class GribToZarrConverter:
    """Convert ECMWF seasonal forecast GRIB files to unified Zarr format in GCS"""
    
    def __init__(self, gcs_bucket: str, zarr_path: str):
        self.gcs_bucket = gcs_bucket
        self.zarr_path = zarr_path
        self.client = storage.Client()
        
        # Variable mappings and temporal resolutions
        self.daily_vars = ['mx2t24', 'mn2t24', 'ssrd', 'strd', 'ssr', 'str', 'e', 'tp']
        self.sixhourly_vars = ['u10', 'v10', 't2m']
        
    def load_and_align_grib(self, grib_file: str) -> Dict[str, xr.Dataset]:
        """Load GRIB file and align temporal dimensions"""
        datasets = cfgrib.open_datasets(grib_file, decode_timedelta=False)
        
        aligned_datasets = {}
        
        for i, ds in enumerate(datasets):
            # Identify dataset type by step dimension size
            if ds.dims['step'] > 500:  # 6-hourly data
                logger.info(f"Processing 6-hourly dataset with {ds.dims['step']} steps")
                aligned_ds = self._process_sixhourly_data(ds)
                aligned_datasets['sixhourly'] = aligned_ds
            else:  # Daily data
                logger.info(f"Processing daily dataset with {ds.dims['step']} steps")
                aligned_ds = self._process_daily_data(ds)
                aligned_datasets['daily'] = aligned_ds
                
        return aligned_datasets
    
    def load_grib_with_separation(self, grib_path: str) -> Dict[str, xr.Dataset]:
        """Load GRIB file with proper variable separation - SIMPLIFIED VERSION"""
        
        datasets = {}
        
        try:
            # Use cfgrib.open_datasets which already separates by temporal resolution
            logger.info("Loading GRIB datasets...")
            all_datasets = cfgrib.open_datasets(grib_path, decode_timedelta=False)
            
            logger.info(f"Found {len(all_datasets)} datasets in GRIB file")
            
            for i, ds in enumerate(all_datasets):
                logger.info(f"Dataset {i}: {dict(ds.dims)}, variables: {list(ds.data_vars.keys())}")
                
                # Determine dataset type based on variables present
                ds_vars = set(ds.data_vars.keys())
                daily_overlap = len(ds_vars.intersection(self.daily_vars))
                sixhourly_overlap = len(ds_vars.intersection(self.sixhourly_vars))
                
                if daily_overlap > 0 and sixhourly_overlap == 0:
                    dataset_type = 'daily'
                    logger.info(f"Dataset {i} identified as DAILY: {list(ds_vars)}")
                elif sixhourly_overlap > 0 and daily_overlap == 0:
                    dataset_type = 'sixhourly'
                    logger.info(f"Dataset {i} identified as 6-HOURLY: {list(ds_vars)}")
                else:
                    # Mixed or unclear - use step count as fallback
                    if ds.sizes.get('step', 0) > 500:
                        dataset_type = 'sixhourly'
                        logger.info(f"Dataset {i} identified as 6-HOURLY (by step count): {ds.sizes['step']} steps")
                    else:
                        dataset_type = 'daily'
                        logger.info(f"Dataset {i} identified as DAILY (by step count): {ds.sizes['step']} steps")
                
                # Store the dataset
                if dataset_type in datasets:
                    logger.warning(f"Multiple {dataset_type} datasets found - merging is not implemented")
                    # For now, keep the first one and close the duplicate
                    ds.close()
                else:
                    datasets[dataset_type] = ds
            
            logger.info(f"Successfully loaded {len(datasets)} dataset types: {list(datasets.keys())}")
            
        except Exception as e:
            logger.error(f"Failed to load GRIB datasets: {e}")
            # Clean up any opened datasets
            if 'all_datasets' in locals():
                for ds in all_datasets:
                    if hasattr(ds, 'close'):
                        ds.close()
            raise
        
        return datasets 

    def _process_sixhourly_data(self, ds: xr.Dataset, initial_time: pd.Timestamp) -> xr.Dataset:
        """Process 6-hourly variables with proper CF convention structure"""
        
        # Keep step as step (forecast lead time as timedelta)
        forecast_steps = pd.to_timedelta(ds.step.values)
        
        # Create processed dataset with CF convention structure
        ds_processed = ds.copy()
        # Keep 'step' as 'step' and rename 'time' to 'time' (initialization time)
        if 'time' in ds_processed.coords:
            ds_processed = ds_processed.assign_coords(time=initial_time)
        else:
            ds_processed = ds_processed.assign_coords(time=initial_time)
        
        # Ensure step coordinate has proper timedelta values
        ds_processed = ds_processed.assign_coords(step=forecast_steps)
        
        # Calculate valid_time for reference (time + step)
        valid_times = initial_time + forecast_steps
        ds_processed = ds_processed.assign_coords(valid_time=('step', valid_times))
        
        # Update attributes
        ds_processed.attrs.update({
            "GRIB_edition": "1",
            "GRIB_centre": "ecmf", 
            "GRIB_centreDescription": "European Centre for Medium-Range Weather Forecasts",
            "GRIB_subCentre": "0",
            "Conventions": "CF-1.7",
            "institution": "European Centre for Medium-Range Weather Forecasts",
            "processed_by": "GribToZarrConverter_CF",
            "processing_notes": "CF convention structure: time (init) + step (lead time)",
            "initial_time_str": str(initial_time),
            "dataset_type": "sixhourly",
            "history": f"Converted from GRIB using CF conventions. {ds.attrs.get('history', '')}"
        })
        
        logger.info(f"Processed 6-hourly dataset: {len(forecast_steps)} steps, time: {initial_time}")
        return ds_processed


    def _process_daily_data(self, ds: xr.Dataset, initial_time: pd.Timestamp) -> xr.Dataset:
        """Process daily aggregated variables with proper CF convention structure"""
        
        # Keep step as step (forecast lead time as timedelta)  
        forecast_steps = pd.to_timedelta(ds.step.values)
        
        # Create processed dataset with CF convention structure
        ds_processed = ds.copy()
        # Keep 'step' as 'step' and rename 'time' to 'time' (initialization time)
        if 'time' in ds_processed.coords:
            ds_processed = ds_processed.assign_coords(time=initial_time)
        else:
            ds_processed = ds_processed.assign_coords(time=initial_time)
        
        # Ensure step coordinate has proper timedelta values
        ds_processed = ds_processed.assign_coords(step=forecast_steps)
        
        # Calculate valid_time for reference (time + step)
        valid_times = initial_time + forecast_steps
        ds_processed = ds_processed.assign_coords(valid_time=('step', valid_times))
        
        # Update attributes
        ds_processed.attrs.update({
            "GRIB_edition": "1",
            "GRIB_centre": "ecmf",
            "GRIB_centreDescription": "European Centre for Medium-Range Weather Forecasts", 
            "GRIB_subCentre": "0",
            "Conventions": "CF-1.7",
            "institution": "European Centre for Medium-Range Weather Forecasts",
            "processed_by": "GribToZarrConverter_CF",
            "processing_notes": "CF convention structure: time (init) + step (lead time)",
            "initial_time_str": str(initial_time),
            "dataset_type": "daily",
            "history": f"Converted from GRIB using CF conventions. {ds.attrs.get('history', '')}"
        })
        
        logger.info(f"Processed daily dataset: {len(forecast_steps)} steps, time: {initial_time}")
        return ds_processed
    
    def create_unified_dataset(self, aligned_datasets: Dict[str, xr.Dataset]) -> xr.Dataset:
        """Merge daily and 6-hourly datasets with minimal memory footprint"""
        
        if 'daily' in aligned_datasets and 'sixhourly' in aligned_datasets:
            daily_ds = aligned_datasets['daily']
            sixhourly_ds = aligned_datasets['sixhourly']
            
            logger.info(f"Daily dataset size: {daily_ds.nbytes / 1e9:.2f} GB")
            logger.info(f"6-hourly dataset size: {sixhourly_ds.nbytes / 1e9:.2f} GB")
            
            # Use the 6-hourly time grid as the base (more frequent)
            base_time = sixhourly_ds.forecast_time
            
            # For daily variables, only assign values at specific hours (e.g., 00:00)
            # This avoids forward-filling and keeps NaN for non-matching times
            daily_aligned = daily_ds.reindex(
                forecast_time=base_time,
                method=None  # No forward/backward filling - keep NaN
            )
            
            # Merge datasets - xarray will automatically align on common dimensions
            unified_ds = xr.merge([
                sixhourly_ds,  # 6-hourly variables (complete coverage)
                daily_aligned  # Daily variables (sparse coverage with NaN)
            ], compat='override')
            
            logger.info(f"Unified dataset size: {unified_ds.nbytes / 1e9:.2f} GB")
            
        elif 'daily' in aligned_datasets:
            unified_ds = aligned_datasets['daily']
        else:
            unified_ds = aligned_datasets['sixhourly']
            
        return unified_ds
    
    def initialize_zarr_store(self, sample_ds: xr.Dataset) -> str:
        """Initialize Zarr store in GCS with proper structure - memory efficient"""
        
        # Define chunks for optimal performance
        chunks = {
            'forecast_time': 168,  # 1 week of 6-hourly data
            'number': 25,
            'latitude': sample_ds.sizes['latitude'],
            'longitude': sample_ds.sizes['longitude']
        }
        
        # Create coordinate arrays for full time range (1981-2025)
        # Use 6-hourly resolution as the base
        full_time_range = pd.date_range('1981-01-01', '2025-12-31', freq='6h')
        
        coords = {
            'forecast_time': full_time_range,
            'number': sample_ds.number.values,
            'latitude': sample_ds.latitude.values,
            'longitude': sample_ds.longitude.values
        }
        
        # Create empty dataset structure without loading all data into memory
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        
        # Initialize with a small dummy dataset first
        dummy_shape = (1, len(sample_ds.number), 
                      len(sample_ds.latitude), len(sample_ds.longitude))
        
        data_vars = {}
        all_vars = list(set(self.daily_vars + self.sixhourly_vars))
        for var in all_vars:
            if var in sample_ds.data_vars:
                data_vars[var] = (
                    ['forecast_time', 'number', 'latitude', 'longitude'],
                    np.full(dummy_shape, np.nan, dtype=np.float32)
                )
        
        # Create initial dataset with single time step
        init_coords = {k: v[:1] if k == 'forecast_time' else v for k, v in coords.items()}
        init_dataset = xr.Dataset(data_vars, coords=init_coords)
        
        # Set chunking
        chunk_dict = {
            'forecast_time': chunks['forecast_time'],
            'number': chunks['number'],
            'latitude': chunks['latitude'],
            'longitude': chunks['longitude']
        }
        init_dataset = init_dataset.chunk(chunk_dict)
        
        # Set proper time encoding
        time_encoding = {
            'forecast_time': {
                'units': 'hours since 1970-01-01',
                'dtype': 'int64',
                'calendar': 'proleptic_gregorian'
            }
        }
        
        # Save initial structure
        init_dataset.to_zarr(
            zarr_path, 
            mode='w', 
            encoding=time_encoding,
            consolidated=False
        )
        
        # Now extend the time dimension to full range without loading data
        with xr.open_zarr(zarr_path) as ds:
            # Create template with full time range
            full_ds = ds.reindex(forecast_time=full_time_range, fill_value=np.nan)
            full_ds = full_ds.chunk(chunk_dict)
            full_ds.to_zarr(
                zarr_path, 
                mode='w', 
                encoding=time_encoding,
                consolidated=False
            )
        
        logger.info(f"Initialized Zarr store with {len(full_time_range)} time steps")
        logger.info(f"Variables: {list(data_vars.keys())}")
        
        return zarr_path
    
    def append_to_zarr(self, unified_ds: xr.Dataset, zarr_path: str):
        """Append data to existing Zarr store - memory efficient"""
        
        logger.info(f"Appending data with {len(unified_ds.forecast_time)} time steps")
        
        # Process variables in chunks to avoid memory issues
        chunk_size = 50  # Process 50 time steps at a time
        
        for var_name in unified_ds.data_vars:
            logger.info(f"Processing variable {var_name}")
            
            var_data = unified_ds[var_name]
            
            # Skip if all NaN
            if var_data.isnull().all():
                logger.info(f"Skipping {var_name} - all NaN")
                continue
            
            # Process in time chunks
            n_times = len(var_data.forecast_time)
            for i in range(0, n_times, chunk_size):
                end_idx = min(i + chunk_size, n_times)
                chunk_data = var_data.isel(forecast_time=slice(i, end_idx))
                
                # Skip if chunk is all NaN
                if chunk_data.isnull().all():
                    continue
                
                try:
                    # Write chunk using region specification
                    chunk_data.to_zarr(
                        zarr_path,
                        region={'forecast_time': slice(i, end_idx)},
                        mode='r+'
                    )
                    
                except Exception as e:
                    logger.warning(f"Failed to write chunk {i}-{end_idx} for {var_name}: {e}")
                    
                # Force garbage collection to manage memory
                import gc
                gc.collect()
            
            logger.info(f"Completed {var_name}")
        
        logger.info("Append operation completed")
    
    def process_grib_file_memory_efficient(self, grib_path: str, initialize_store: bool = False):
        """Memory-efficient processing for large GRIB files"""
        logger.info(f"Processing {grib_path} (memory-efficient mode)")
        
        # Load datasets separately to avoid memory issues
        datasets = cfgrib.open_datasets(grib_path)
        
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        
        # First pass: determine the common time grid
        all_times = []
        processed_datasets = []
        
        for i, ds in enumerate(datasets):
            if ds.sizes['step'] > 500:  # 6-hourly data  # 6-hourly data
                aligned_ds = self._process_sixhourly_data(ds)
                dataset_type = 'sixhourly'
            else:  # Daily data
                aligned_ds = self._process_daily_data(ds)
                dataset_type = 'daily'
            
            all_times.extend(aligned_ds.forecast_time.values)
            processed_datasets.append((aligned_ds, dataset_type))
            
            ds.close()
        
        # Create unified time grid (6-hourly resolution)
        all_times = pd.to_datetime(sorted(set(all_times)))
        time_min, time_max = all_times.min(), all_times.max()
        unified_time_grid = pd.date_range(time_min, time_max, freq='6h')
        
        logger.info(f"Unified time grid: {len(unified_time_grid)} steps from {time_min} to {time_max}")
        
        # Initialize store if needed
        if initialize_store:
            zarr_path = self.initialize_zarr_store_with_time_grid(
                processed_datasets[0][0], unified_time_grid
            )
        
        # Second pass: align each dataset to unified time grid and append
        for aligned_ds, dataset_type in processed_datasets:
            logger.info(f"Aligning {dataset_type} dataset to unified time grid")
            
            # Align to unified time grid
            if dataset_type == 'daily':
                # For daily data, only keep values at daily intervals (00:00)
                daily_times = unified_time_grid[unified_time_grid.hour == 0]
                aligned_to_grid = aligned_ds.reindex(
                    forecast_time=daily_times, 
                    method='nearest',
                    tolerance=pd.Timedelta('12h')
                ).reindex(forecast_time=unified_time_grid)
            else:
                # For 6-hourly data, direct alignment
                aligned_to_grid = aligned_ds.reindex(forecast_time=unified_time_grid)
            
            # Append to zarr
            self.append_aligned_data(aligned_to_grid, zarr_path)
            
            del aligned_ds, aligned_to_grid
            import gc
            gc.collect()
        
        logger.info(f"Completed processing {grib_path}")
    
    def initialize_zarr_store_with_time_grid(self, sample_ds: xr.Dataset, time_grid: pd.DatetimeIndex) -> str:
        """Initialize store with specific time grid"""
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        
        # Create coordinate structure
        coords = {
            'forecast_time': time_grid,
            'number': sample_ds.number.values,
            'latitude': sample_ds.latitude.values,
            'longitude': sample_ds.longitude.values
        }
        
        # Create empty data vars for all expected variables
        shape = (len(time_grid), len(sample_ds.number), 
                len(sample_ds.latitude), len(sample_ds.longitude))
        
        data_vars = {}
        all_vars = list(set(self.daily_vars + self.sixhourly_vars))
        # Add this debug code before line 347
        logger.info(f"Variables in sample_ds: {list(sample_ds.data_vars.keys())}")
        logger.info(f"All expected vars: {all_vars}")
        # Only create variables that exist in sample
        for var in all_vars:
            data_vars[var] = (
                ['forecast_time', 'number', 'latitude', 'longitude'],
                np.full(shape, np.nan, dtype=np.float32)
            )
        # Add this debug line
        logger.info(f"Creating data_vars: {list(data_vars.keys())}")
        # Create dataset with proper chunking
        init_ds = xr.Dataset(data_vars, coords=coords)
        init_ds = init_ds.chunk({
            'forecast_time': 168,  # 1 week
            'number': 25,
            'latitude': sample_ds.sizes['latitude'],
            'longitude': sample_ds.sizes['longitude']
        })
        
        # Set proper time encoding to avoid warnings
        time_encoding = {
            'forecast_time': {
                'units': 'hours since 1970-01-01',
                'dtype': 'int64',
                'calendar': 'proleptic_gregorian'
            }
        }
        
        # Write to zarr with proper encoding and without consolidated metadata
        init_ds.to_zarr(
            zarr_path, 
            mode='w', 
            encoding=time_encoding,
            consolidated=False  # Avoid Zarr v3 consolidated metadata warning
        )
        # Add this debug line
        logger.info(f"Successfully wrote variables to zarr: {list(init_ds.data_vars.keys())}")
        logger.info(f"Initialized Zarr store with {len(time_grid)} time steps")
        return zarr_path
    
    def append_aligned_data(self, aligned_ds: xr.Dataset, zarr_path: str):
        """Append pre-aligned data to zarr store"""
        
        # Open existing store to get time indices
        with xr.open_zarr(zarr_path, consolidated=False) as existing_ds:
            zarr_times = pd.to_datetime(existing_ds.forecast_time.values)
        
        # Set consistent time encoding for all operations
        time_encoding = {
            'forecast_time': {
                'units': 'hours since 1970-01-01',
                'dtype': 'int64',
                'calendar': 'proleptic_gregorian'
            }
        }
        
        # Process each variable
        for var_name in aligned_ds.data_vars:
            logger.info(f"Appending {var_name}")
            
            var_data = aligned_ds[var_name]
            
            # Skip if all NaN
            if var_data.isnull().all():
                logger.info(f"Skipping {var_name} - all NaN")
                continue
            
            # Find time indices where we have valid data
            ds_times = pd.to_datetime(var_data.forecast_time.values)
            valid_mask = ds_times.isin(zarr_times)
            
            if not valid_mask.any():
                continue
            
            # Get the data for valid times only
            valid_data = var_data.where(xr.DataArray(valid_mask, dims=['forecast_time'], coords=[ds_times]), drop=True)
            
            if len(valid_data.forecast_time) == 0:
                continue
            
            # Find indices in zarr time array
            time_indices = []
            for t in valid_data.forecast_time.values:
                idx = np.where(zarr_times == pd.to_datetime(t))[0]
                if len(idx) > 0:
                    time_indices.append(idx[0])
            
            if not time_indices:
                continue
            
            # Write data using region specification
            try:
                # Create region dict for the time indices
                min_idx, max_idx = min(time_indices), max(time_indices)
                
                # Reindex to continuous range for region writing
                continuous_times = zarr_times[min_idx:max_idx+1]
                region_data = valid_data.reindex(forecast_time=continuous_times)
                
                # Apply consistent encoding
                #var_encoding = time_encoding.copy()
                
                # Drop coordinate variables that don't need region writing
                coords_to_drop = ['number', 'latitude', 'longitude', 'surface', 'initial_time']
                region_data_clean = region_data.drop_vars([c for c in coords_to_drop if c in region_data.coords])
                
                # Don't encode coordinates that already exist
                var_encoding = {}  # Empty encoding to avoid coordinate conflicts
                
                region_data_clean.to_zarr(
                    zarr_path,
                    region={'forecast_time': slice(min_idx, max_idx+1)},
                    mode='r+',
                    encoding=var_encoding,
                    consolidated=False
                )
                
                logger.info(f"Successfully appended {var_name}")
                
            except Exception as e:
                # Try alternative approach for problematic variables
                logger.warning(f"Region write failed for {var_name}: {e}")
                
                try:
                    # Try writing without region (append mode)
                    logger.info(f"Attempting alternative write for {var_name}")
                    valid_data.to_zarr(zarr_path, mode='a', consolidated=False)
                    logger.info(f"Successfully appended {var_name} (alternative method)")
                except Exception as e2:
                    logger.error(f"Failed to append {var_name} with alternative method: {e2}")
                    continue
    
    def process_multiple_files(self, grib_files: List[str]):
        """Process multiple GRIB files in sequence"""
        
        # Initialize with first file
        if grib_files:
            self.process_grib_file(grib_files[0], initialize_store=True)
            
            # Process remaining files
            for grib_file in grib_files[1:]:
                self.process_grib_file(grib_file, initialize_store=False)
    
    def validate_zarr_store(self) -> Dict:
        """Validate the created Zarr store"""
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        ds = xr.open_zarr(zarr_path)
        
        validation_info = {
            'time_range': f"{ds.forecast_time.min().values} to {ds.forecast_time.max().values}",
            'total_time_steps': len(ds.forecast_time),
            'variables': list(ds.data_vars.keys()),
            'data_coverage': {}
        }
        
        # Check data coverage for each variable
        for var_name in ds.data_vars:
            total_points = ds[var_name].size
            valid_points = ds[var_name].count().compute()
            validation_info['data_coverage'][var_name] = float(valid_points / total_points)
        
        return validation_info

    def process_multiple_grib_files_with_initial_times(self, grib_files: List[str]):
        """Process multiple GRIB files with different initial times"""
        
        logger.info(f"Processing {len(grib_files)} GRIB files with initial time tracking")
        
        # Process first file to initialize store
        if grib_files:
            logger.info(f"Initializing store with {grib_files[0]}")
            self.process_grib_file_memory_efficient(grib_files[0], initialize_store=True)
            
            # Process remaining files
            for i, grib_file in enumerate(grib_files[1:], 1):
                logger.info(f"Processing file {i+1}/{len(grib_files)}: {grib_file}")
                
                # Extract date from filename or use file modification time
                try:
                    # Try to extract year from path like 'grib_downloads/1993/file.grib'
                    parts = Path(grib_file).parts
                    if len(parts) >= 2 and parts[-2].isdigit():
                        year = int(parts[-2])
                        # Assume January 1st if only year is available
                        file_initial_time = pd.Timestamp(f'{year}-01-01')
                    else:
                        # Fallback to file modification time
                        file_time = os.path.getmtime(grib_file)
                        file_initial_time = pd.Timestamp.fromtimestamp(file_time)
                    
                    logger.info(f"Inferred initial time for {grib_file}: {file_initial_time}")
                    
                except Exception as e:
                    logger.warning(f"Could not infer initial time for {grib_file}: {e}")
                    file_initial_time = None
                
                # Process the file
                self.process_grib_file_memory_efficient(grib_file, initialize_store=False)
                
                # Update initial_time tracking
                if file_initial_time:
                    self.track_initial_time(file_initial_time)
        
        logger.info("Completed processing all GRIB files")
        
    def track_initial_time(self, initial_time: pd.Timestamp):
        """Track initial times from multiple GRIB files"""
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        
        try:
            # Create a separate dataset for initial time tracking
            initial_times_path = f'{zarr_path}_initial_times'
            
            # Try to read existing initial times
            try:
                existing_times = xr.open_zarr(initial_times_path, consolidated=False)
                times_list = list(existing_times.initial_times.values)
                times_list.append(initial_time)
                times_array = pd.to_datetime(sorted(set(times_list)))
            except:
                # First time - create new
                times_array = pd.to_datetime([initial_time])
            
            # Create dataset with all initial times
            times_ds = xr.Dataset({
                'initial_times': ('time_idx', times_array)
            }, coords={'time_idx': range(len(times_array))})
            
            # Save updated initial times
            times_ds.to_zarr(initial_times_path, mode='w', consolidated=False)
            
            logger.info(f"Updated initial times tracking: {len(times_array)} unique times")
            
        except Exception as e:
            logger.warning(f"Could not track initial time {initial_time}: {e}")
    
    def get_all_initial_times(self) -> List[pd.Timestamp]:
        """Retrieve all tracked initial times"""
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        initial_times_path = f'{zarr_path}_initial_times'
        
        try:
            times_ds = xr.open_zarr(initial_times_path, consolidated=False)
            return list(pd.to_datetime(times_ds.initial_times.values))
        except:
            logger.warning("No initial times tracking found")
            return []
    
    def validate_zarr_store(self) -> Dict:
        """Validate the created Zarr store"""
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        ds = xr.open_zarr(zarr_path)
        
        validation_info = {
            'time_range': f"{ds.forecast_time.min().values} to {ds.forecast_time.max().values}",
            'total_time_steps': len(ds.forecast_time),
            'variables': list(ds.data_vars.keys()),
            'data_coverage': {}
        }
        
        # Check data coverage for each variable
        for var_name in ds.data_vars:
            total_points = ds[var_name].size
            valid_points = ds[var_name].count().compute()
            validation_info['data_coverage'][var_name] = float(valid_points / total_points)
        
        return validation_info

    def initialize_zarr_store_with_multi_init(self, sample_ds: xr.Dataset, 
                                        initial_times: List[pd.Timestamp]) -> str:
        """Initialize store with proper CF convention multi-initialization structure"""
        
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        
        # Use the actual forecast steps from the sample dataset (860 steps)
        # This should be 6-hourly resolution matching what's in the GRIB files
        if 'step' in sample_ds.coords:
            forecast_steps = pd.to_timedelta(sample_ds.step.values)
        else:
            # Fallback: create 860 six-hourly steps (matching GRIB structure)
            forecast_steps = pd.timedelta_range('6h', periods=860, freq='6h')
        
        logger.info(f"Using step coordinate: {len(forecast_steps)} steps (should be 860)")
        
        # Create coordinate structure - CF CONVENTION
        coords = {
            'time': sorted(initial_times),                   # Initialization times (CF convention)
            'step': forecast_steps,                          # Forecast lead times as timedelta (CF convention)
            'number': sample_ds.number.values,               # Ensemble members
            'latitude': sample_ds.latitude.values,           # Latitude points
            'longitude': sample_ds.longitude.values          # Longitude points
        }
        
        # Create shape for CF convention structure
        shape = (
            len(coords['time']),             # Number of initialization times
            len(coords['step']),             # Number of forecast steps
            len(coords['number']),           # Ensemble members
            len(coords['latitude']),         # Latitude points  
            len(coords['longitude'])         # Longitude points
        )
        
        # Create data variables for all expected variables
        data_vars = {}
        all_vars = list(set(self.daily_vars + self.sixhourly_vars))
        
        logger.info(f"Variables in sample_ds: {list(sample_ds.data_vars.keys())}")
        logger.info(f"All expected vars: {all_vars}")
        logger.info(f"Creating CF convention zarr shape: {shape}")
        
        for var in all_vars:
            data_vars[var] = (
                ['time', 'step', 'number', 'latitude', 'longitude'],  # CF convention dimensions
                np.full(shape, np.nan, dtype=np.float32)
            )
        
        logger.info(f"Creating data_vars: {list(data_vars.keys())}")
        
        # Create dataset with proper CF convention structure  
        init_ds = xr.Dataset(data_vars, coords=coords)
        
        # Set chunking - process one time at a time
        init_ds = init_ds.chunk({
            'time': 1,                                      # One initialization at a time
            'step': 168,                                    # 1 week of 6-hourly data
            'number': len(coords['number']),                # All ensemble members
            'latitude': len(coords['latitude']),            # All latitudes
            'longitude': len(coords['longitude'])           # All longitudes
        })
        
        # Set proper encoding for CF convention
        encoding = {
            'time': {
                'units': 'hours since 1970-01-01',
                'dtype': 'int64',
                'calendar': 'proleptic_gregorian'
            },
            'step': {
                'units': 'nanoseconds',
                'dtype': 'int64'
            }
        }
        
        # Write to zarr with CF convention structure
        init_ds.to_zarr(
            zarr_path,
            mode='w',
            encoding=encoding,
            consolidated=False
        )
        
        logger.info(f"Successfully initialized CF convention zarr store:")
        logger.info(f"  - Initialization times: {len(initial_times)}")
        logger.info(f"  - Forecast steps: {len(coords['step'])}")
        logger.info(f"  - Variables: {list(data_vars.keys())}")
        logger.info(f"  - Shape: {shape}")
        
        return zarr_path


    def append_to_multi_init_zarr(self, processed_ds: xr.Dataset, dataset_type: str,
                                initial_time: pd.Timestamp, zarr_path: str):
        """Append data to CF convention multi-initialization zarr store"""
        
        # Open existing zarr to get structure
        with xr.open_zarr(zarr_path, consolidated=False) as existing_ds:
            zarr_times = pd.to_datetime(existing_ds.time.values)
            zarr_steps = pd.to_timedelta(existing_ds.step.values)
        
        # Find the index for this initialization time
        try:
            time_idx = np.where(zarr_times == initial_time)[0][0]
        except IndexError:
            logger.error(f"Initialization time {initial_time} not found in zarr store")
            logger.error(f"Available times: {zarr_times}")
            return
        
        logger.info(f"Appending {dataset_type} data for time index {time_idx}")
        
        # Align forecast steps to zarr grid
        if dataset_type == 'daily':
            # For daily data, only keep values at daily intervals (multiples of 24 hours)
            daily_steps = zarr_steps[zarr_steps.total_seconds() % (24*3600) == 0]
            aligned_ds = processed_ds.reindex(
                step=daily_steps,
                method='nearest', 
                tolerance=pd.Timedelta('12h')
            )
            # Then reindex to full 6-hourly grid with NaN for non-daily steps
            aligned_ds = aligned_ds.reindex(step=zarr_steps)
        else:
            # For 6-hourly data, direct alignment
            aligned_ds = processed_ds.reindex(step=zarr_steps)
        
        # Process each variable with memory management
        chunk_size = 50  # Process 50 forecast steps at a time
        
        for var_name in aligned_ds.data_vars:
            if var_name not in existing_ds.data_vars:
                logger.warning(f"Variable {var_name} not found in zarr store, skipping")
                continue
                
            logger.info(f"Appending {var_name} to time slice {time_idx}")
            
            var_data = aligned_ds[var_name]
            
            # Skip if all NaN
            if var_data.isnull().all():
                logger.info(f"Skipping {var_name} - all NaN")
                continue
            
            # Process in step chunks to manage memory
            n_steps = len(var_data.step)
            for i in range(0, n_steps, chunk_size):
                end_idx = min(i + chunk_size, n_steps)
                
                try:
                    # Get chunk of data
                    chunk_data = var_data.isel(step=slice(i, end_idx))
                    
                    # Skip if chunk is all NaN
                    if chunk_data.isnull().all():
                        continue
                    
                    # Write using region specification for this time and step range
                    chunk_data.to_zarr(
                        zarr_path,
                        region={
                            'time': slice(time_idx, time_idx + 1),
                            'step': slice(i, end_idx)
                        },
                        mode='r+'
                    )
                    
                except Exception as e:
                    logger.error(f"Failed to write chunk {i}-{end_idx} for {var_name}: {e}")
                    continue
                
                # Force garbage collection after each chunk
                import gc
                gc.collect()
            
            logger.info(f"Successfully appended {var_name}")


    def process_grib_file_memory_efficient_multi_init(self, grib_path: str, 
                                                     all_initial_times: List[pd.Timestamp],
                                                     initialize_store: bool = False):
        """Memory-efficient processing with proper CF convention structure"""
        
        logger.info(f"Processing {grib_path} (CF convention memory-efficient mode)")
        
        zarr_path = f'gs://{self.gcs_bucket}/{self.zarr_path}'
        
        # Load datasets using improved separation
        datasets = self.load_grib_with_separation(grib_path)
        
        if not datasets:
            logger.error(f"No datasets loaded from {grib_path}")
            return
        
        # Extract initial time from first dataset or filename
        first_ds = list(datasets.values())[0]
        if 'time' in first_ds.coords:
            initial_time = pd.Timestamp(first_ds.time.values)
        else:
            # Extract from filename
            try:
                parts = Path(grib_path).parts
                if len(parts) >= 2 and parts[-2].isdigit():
                    year = int(parts[-2])
                    initial_time = pd.Timestamp(f'{year}-01-01')
                else:
                    initial_time = pd.Timestamp('1992-01-01')  # Default
            except:
                initial_time = pd.Timestamp('1992-01-01')
        
        logger.info(f"Extracted initialization time: {initial_time}")
        
        # Initialize store if needed (with ALL initialization times)
        if initialize_store:
            zarr_path = self.initialize_zarr_store_with_multi_init(first_ds, all_initial_times)
        
        # Process each dataset type with proper initialization time
        for dataset_type, ds in datasets.items():
            logger.info(f"Processing {dataset_type} dataset for time {initial_time}")
            
            try:
                # Process with initialization time
                if dataset_type == 'sixhourly':
                    processed_ds = self._process_sixhourly_data(ds, initial_time)
                else:
                    processed_ds = self._process_daily_data(ds, initial_time)
                
                # Append to CF convention zarr store
                self.append_to_multi_init_zarr(processed_ds, dataset_type, initial_time, zarr_path)
                
                # Clean up
                del processed_ds
                ds.close()
                
            except Exception as e:
                logger.error(f"Failed to process {dataset_type} dataset: {e}")
                ds.close()
                continue
        
        # Force garbage collection
        import gc
        gc.collect()
        
        logger.info(f"Completed processing {grib_path} for time {initial_time}")


    def process_multiple_grib_files_with_multi_init(self, grib_files: List[str]):
        """Process multiple GRIB files with proper CF convention structure"""
        
        logger.info(f"Processing {len(grib_files)} GRIB files with CF convention structure")
        
        # Step 1: Extract all initialization times from ALL files first
        all_initial_times = []
        
        for grib_file in grib_files:
            try:
                # Load just to extract initial time
                temp_datasets = self.load_grib_with_separation(grib_file)
                if temp_datasets:
                    first_ds = list(temp_datasets.values())[0]
                    if 'time' in first_ds.coords:
                        initial_time = pd.Timestamp(first_ds.time.values)
                    else:
                        # Extract from filename
                        parts = Path(grib_file).parts
                        if len(parts) >= 2 and parts[-2].isdigit():
                            year = int(parts[-2])
                            initial_time = pd.Timestamp(f'{year}-01-01')
                        else:
                            initial_time = pd.Timestamp('1992-01-01')
                    
                    all_initial_times.append(initial_time)
                    logger.info(f"File {grib_file} -> Initial time: {initial_time}")
                    
                    # Close datasets
                    for ds in temp_datasets.values():
                        ds.close()
                        
            except Exception as e:
                logger.error(f"Failed to extract initial time from {grib_file}: {e}")
        
        if not all_initial_times:
            raise ValueError("No valid initial times found")
        
        # Remove duplicates and sort
        unique_initial_times = sorted(list(set(all_initial_times)))
        logger.info(f"Found {len(unique_initial_times)} unique initial times: {unique_initial_times}")
        
        # Step 2: Process each file with the complete initial_times list
        for i, grib_file in enumerate(grib_files):
            logger.info(f"Processing file {i+1}/{len(grib_files)}: {grib_file}")
            
            try:
                self.process_grib_file_memory_efficient_multi_init(
                    grib_file,
                    unique_initial_times,  # Pass ALL initial times for proper zarr structure
                    initialize_store=(i == 0)  # Initialize only on first file
                )
                
            except Exception as e:
                logger.error(f"Failed to process {grib_file}: {e}")
                continue
            
            # Memory cleanup
            import gc
            gc.collect()
        
        logger.info("Completed processing all GRIB files with multi-init structure")
        return f'gs://{self.gcs_bucket}/{self.zarr_path}'


# Usage example and testing functions
def diagnose_zarr_store(zarr_path: str):
    """Diagnose issues with Zarr store"""
    import zarr
    
    try:
        # Try to open as zarr directly
        store = zarr.open(zarr_path)
        print("Zarr store structure:")
        print(f"Root keys: {list(store.keys())}")
        
        for key in store.keys():
            if hasattr(store[key], 'shape'):
                print(f"{key}: shape {store[key].shape}, dtype {store[key].dtype}")
            else:
                print(f"{key}: {type(store[key])}")
        
        # Check time dimensions specifically
        if 'forecast_time' in store:
            print(f"forecast_time length: {len(store['forecast_time'])}")
        
        # Check each variable's time dimension
        for key in store.keys():
            if key not in ['forecast_time', 'number', 'latitude', 'longitude']:
                if hasattr(store[key], 'shape'):
                    print(f"{key} time dimension (axis 0): {store[key].shape[0]}")
        
    except Exception as e:
        print(f"Error opening zarr store: {e}")

def fix_zarr_time_alignment(zarr_path: str):
    """Fix time alignment issues in existing zarr store"""
    import zarr
    
    store = zarr.open(zarr_path, mode='r+')
    
    # Find the correct time dimension length
    time_lengths = {}
    for key in store.keys():
        if key not in ['forecast_time', 'number', 'latitude', 'longitude']:
            if hasattr(store[key], 'shape'):
                time_lengths[key] = store[key].shape[0]
    
    print("Time dimension lengths:", time_lengths)
    
    # Use the most common length or the 6-hourly one (larger)
    target_length = max(time_lengths.values())
    print(f"Target time length: {target_length}")
    
    # This would require recreating the store - better to regenerate


def batch_process_grib_files():
    """Process multiple GRIB files from different years/computers"""
    
    converter = GribToZarrConverter(
        gcs_bucket='your-bucket-name',
        zarr_path='ecmwf-seasonal/unified_zarr'
    )
    
    # Collect all GRIB files
    grib_files = []
    base_path = Path('grib_downloads')
    
    for year_dir in base_path.iterdir():
        if year_dir.is_dir():
            for grib_file in year_dir.glob('*.grib'):
                grib_files.append(str(grib_file))
    
    # Sort by year for logical processing order
    grib_files.sort()
    
    logger.info(f"Found {len(grib_files)} GRIB files to process")
    
    # Process all files
    converter.process_multiple_files(grib_files)
    
    # Final validation
    validation = converter.validate_zarr_store()
    logger.info(f"Final validation: {validation}")


if __name__ == "__main__":
    # Start with single file test
    test_single_grib_conversion()
    
    # Then process all files
    # batch_process_grib_files()




