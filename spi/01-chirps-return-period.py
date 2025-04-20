import os
import sys
import numpy as np
import pandas as pd
import xarray as xr
import rioxarray
import fsspec
from datetime import datetime
from dateutil.relativedelta import relativedelta
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
from scipy import stats
from google.oauth2 import service_account
from rio_cogeo.cogeo import cog_translate
from rio_cogeo.profiles import cog_profiles
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.io import MemoryFile
import rasterio
import logging
from google.cloud import storage
import json
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Default configuration values
DEFAULT_CONFIG = {
    'INPUT_ZARR_PATH': 'gs://ittseas51/ea_spi3_chirps_20250417.zarr',
    'SERVICE_ACCOUNT_KEY': 'coiled-data-e4drr.json',
    'OUTPUT_BUCKET': 'ittseas51',  # Changed from 'gs://ittseas51' to just 'ittseas51'
    'OUTPUT_FOLDER': 'ea_chirpsv2_spi_return_periods',
    'REGION_EXTENT': [21.0, 51.0, -12.0, 23.0],
    'RETURN_PERIODS': [2, 5, 10, 20, 50, 100],
    'TARGET_CRS': 'EPSG:3857'
}

def load_environment(env_file=None):
    """
    Load environment variables from specified .env file
    If no file is specified, it will try to find .env in the current directory
    """
    # If env_file is specified, load it
    if env_file and os.path.exists(env_file):
        logger.info(f"Loading environment from: {env_file}")
        load_dotenv(env_file)
    # Otherwise, try to find .env in the current directory
    else:
        env_path = find_dotenv()
        if env_path:
            logger.info(f"Loading environment from: {env_path}")
            load_dotenv(env_path)
        else:
            logger.warning("No .env file found, using default values")

    # Load configuration from environment variables
    config = {
        'INPUT_ZARR_PATH': os.getenv('SPI_ZARR_PATH', DEFAULT_CONFIG['INPUT_ZARR_PATH']),
        'SERVICE_ACCOUNT_KEY': os.getenv('SPI_SERVICE_ACCOUNT_KEY', DEFAULT_CONFIG['SERVICE_ACCOUNT_KEY']),
        'OUTPUT_BUCKET': os.getenv('SPI_OUTPUT_BUCKET', DEFAULT_CONFIG['OUTPUT_BUCKET']),
        'OUTPUT_FOLDER': os.getenv('SPI_OUTPUT_FOLDER', DEFAULT_CONFIG['OUTPUT_FOLDER']),
        'REGION_EXTENT': [
            float(os.getenv('SPI_EXTENT_X1', DEFAULT_CONFIG['REGION_EXTENT'][0])),
            float(os.getenv('SPI_EXTENT_X2', DEFAULT_CONFIG['REGION_EXTENT'][1])),
            float(os.getenv('SPI_EXTENT_Y1', DEFAULT_CONFIG['REGION_EXTENT'][2])),
            float(os.getenv('SPI_EXTENT_Y2', DEFAULT_CONFIG['REGION_EXTENT'][3]))
        ],
        'RETURN_PERIODS': [int(x) for x in os.getenv('SPI_RETURN_PERIODS', 
                                                   ','.join(map(str, DEFAULT_CONFIG['RETURN_PERIODS']))).split(',')],
        'TARGET_CRS': os.getenv('SPI_TARGET_CRS', DEFAULT_CONFIG['TARGET_CRS'])
    }
    
    return config

def get_credentials(service_account_key):
    """Create and return Google Cloud credentials."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            service_account_key,
            scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
        )
        logger.info("Successfully loaded GCP credentials")
        return credentials
    except Exception as e:
        logger.error(f"Error loading credentials: {e}")
        raise

def load_spi_data(input_zarr_path, credentials):
    """
    Load SPI data from ZARR file in GCS.
    
    Args:
        input_zarr_path (str): Path to the input ZARR file in GCS
        credentials: Google Cloud credentials
        
    Returns:
        xarray.Dataset: The loaded SPI dataset
    """
    try:
        logger.info(f"Loading SPI data from {input_zarr_path}")
        # Open with fsspec to handle GCS path
        ds = xr.open_zarr(
            input_zarr_path,
            storage_options={'token': credentials},
            consolidated=False
        )
        logger.info(f"Successfully loaded SPI dataset with shape: {ds.dims}")
        return ds
    except Exception as e:
        logger.error(f"Error loading SPI data: {e}")
        raise

def assign_season_names(ds, spi_var_name='spi3'):
    """
    Assign 3-month season names (MAM, JJA, SON, DJF) to the SPI dataset.
    
    Args:
        ds (xarray.Dataset): The SPI dataset
        spi_var_name (str): Name of the SPI variable in the dataset
        
    Returns:
        xarray.Dataset: Dataset with season coordinates added
    """
    try:
        logger.info("Assigning season names to SPI data")
        
        # Create a pandas DataFrame with the time values
        db = pd.DataFrame()
        
        # Check if 'time' or 'valid_time' is used in the dataset
        time_dim = 'time' if 'time' in ds.dims else 'valid_time'
        
        db["dt"] = ds[time_dim].values
        db["dt1"] = db["dt"].apply(
            lambda x: datetime(x.year, x.month, x.day, x.hour, x.minute, x.second)
            if hasattr(x, 'year') else pd.to_datetime(x)
        )
        
        # Generate 3-letter month abbreviations (first letter of each month in the 3-month window)
        db["month"] = db["dt1"].dt.strftime("%b").astype(str).str[0]
        db["year"] = db["dt1"].dt.strftime("%Y")
        
        # Create season names by concatenating month abbreviations
        db["spi_prod"] = (
            db.groupby("year")["month"].shift(2) +
            db.groupby("year")["month"].shift(1) +
            db.groupby("year")["month"].shift(0)
        )
        
        # Fix for NaN values - determine correct seasons based on month
        for idx, row in db.iterrows():
            if pd.isna(row['spi_prod']):
                month_num = row['dt1'].month
                
                # Determine the correct season based on the month
                if month_num == 1:  # January
                    # For January, use NDJ (Nov-Dec-Jan)
                    db.at[idx, 'spi_prod'] = 'NDJ'
                elif month_num == 2:  # February
                    # For February, use DJF (Dec-Jan-Feb)
                    db.at[idx, 'spi_prod'] = 'DJF'
                elif month_num == 12:  # December
                    # For December of the previous year, look ahead
                    # This will be part of DJF that starts in this December
                    if idx+1 < len(db) and idx+2 < len(db):
                        next_two_months = db.iloc[idx+1]['month'] + db.iloc[idx+2]['month']
                        db.at[idx, 'spi_prod'] = 'D' + next_two_months
                    else:
                        # If we're at the end of the data, just use 'DJF'
                        db.at[idx, 'spi_prod'] = 'DJF'
        
        # Assign season names as a coordinate in the dataset
        spi_prod_list = db["spi_prod"].tolist()
        ds = ds.assign_coords(spi_prod=(time_dim, spi_prod_list))
        
        logger.info(f"Season names assigned. Unique seasons: {set([s for s in spi_prod_list if not pd.isna(s)])}")
        return ds
        
    except Exception as e:
        logger.error(f"Error assigning season names: {e}")
        raise

def spi3_prod_name_creator(ds_ens, var_name):
    """
    Convenience function to generate a list of SPI product
    names, such as MAM, so that can be used to filter the
    SPI product from dataframe

    added with method to convert the valid_time in CF format into datetime at
    line 3, which is the format given by climpred valid_time calculation

    Parameters
    ----------
    ds_ens : xarray dataframe
        The data farme with SPI output organized for
        the period 1981-2023.

    Returns
    -------
    spi_prod_list : String list
        List of names with iteration of SPI3 product names such as
        ['JFM','FMA','MAM',......]

    """
    db = pd.DataFrame()
    db["dt"] = ds_ens[var_name].values
    db["dt1"] = db["dt"].apply(
        lambda x: datetime(x.year, x.month, x.day, x.hour, x.minute, x.second)
    )
    # db['dt1']=db['dt'].to_datetimeindex()
    db["month"] = db["dt1"].dt.strftime("%b").astype(str).str[0]
    db["year"] = db["dt1"].dt.strftime("%Y")
    db["spi_prod"] = (
        db.groupby("year")["month"].shift(2)
        + db.groupby("year")["month"].shift(1)
        + db.groupby("year")["month"].shift(0)
    )
    spi_prod_list = db["spi_prod"].tolist()
    return spi_prod_list




def group_by_season(ds, seasons=['MAM', 'JJA', 'SON', 'DJF'], spi_var_name='spi3'):
    """
    Group the SPI dataset by season and create a dictionary of datasets for each season.
    
    Args:
        ds (xarray.Dataset): The SPI dataset with season coordinates
        seasons (list): List of seasons to extract
        spi_var_name (str): Name of the SPI variable in the dataset
        
    Returns:
        dict: Dictionary with season names as keys and corresponding datasets as values
    """
    try:
        logger.info(f"Grouping SPI data by seasons: {seasons}")
        season_datasets = {}
        
        for season in seasons:
            logger.info(f"Processing season {season}")
            season_ds = ds.where(ds.spi_prod == season, drop=True)
            
            if len(season_ds[spi_var_name]) > 0:
                season_datasets[season] = season_ds
                logger.info(f"Season {season} has {len(season_ds[spi_var_name])} time steps")
            else:
                logger.warning(f"No data found for season {season}")
        
        return season_datasets
    
    except Exception as e:
        logger.error(f"Error grouping by season: {e}")
        raise

def calculate_return_period_threshold(return_period):
    """
    Convert return period to SPI value.
    
    Args:
        return_period (float): Return period in years
        
    Returns:
        float: SPI value corresponding to the return period
    """
    # Convert return period to probability
    probability = 1 / return_period
    
    # Calculate the SPI value using the inverse CDF (ppf) of the standard normal distribution
    spi_value = stats.norm.ppf(probability)
    
    logger.info(f"Return period {return_period} years corresponds to SPI value {spi_value:.3f}")
    return spi_value

def calculate_return_period_maps(season_datasets, return_periods, spi_var_name='spi3'):
    """
    Calculate return period exceedance maps for each season.
    
    Args:
        season_datasets (dict): Dictionary of seasonal datasets
        return_periods (list): List of return periods in years
        spi_var_name (str): Name of the SPI variable in the dataset
        
    Returns:
        dict: Dictionary with season and return period as keys, and exceedance maps as values
    """
    try:
        logger.info(f"Calculating return period maps for {len(return_periods)} return periods")
        
        return_period_maps = {}
        
        for season, ds in season_datasets.items():
            logger.info(f"Processing return periods for season {season}")
            return_period_maps[season] = {}
            
            for return_period in return_periods:
                # Calculate SPI threshold for this return period
                spi_threshold = calculate_return_period_threshold(return_period)
                
                # Calculate exceedance map (percentage of time SPI <= threshold)
                # First create a binary mask where 1 = SPI below threshold, 0 = above
                time_dim = 'time' if 'time' in ds.dims else 'valid_time'
                exceedance = (ds[spi_var_name] <= spi_threshold).astype(int)
                
                # Calculate percentage over time
                exceedance_pct = exceedance.mean(dim=time_dim) * 100
                
                # Store the result
                return_period_maps[season][return_period] = exceedance_pct
                
                logger.info(f"Season {season}, Return Period {return_period} years: SPI threshold = {spi_threshold:.3f}")
        
        return return_period_maps
        
    except Exception as e:
        logger.error(f"Error calculating return period maps: {e}")
        raise

def save_as_cog(data_array, file_path, nodata=-9999, target_crs="EPSG:3857"):
    """
    Save an xarray DataArray as a Cloud Optimized GeoTIFF, reprojected to Web Mercator (EPSG:3857).
    
    Args:
        data_array (xarray.DataArray): Data to save
        file_path (str): Path to save the file
        nodata (int/float): Value to use for nodata
        target_crs (str): Target coordinate reference system, default is Web Mercator
        
    Returns:
        str: Path to the saved file
    """
    try:
        # Ensure the data array has CRS information
        if not hasattr(data_array, 'rio'):
            data_array = data_array.rio.write_crs("EPSG:4326")
        
        # First save as a temporary GeoTIFF
        temp_file = file_path + "_temp.tif"
        data_array.rio.to_raster(temp_file, nodata=nodata)
        
        # Then convert to COG and reproject to Web Mercator (EPSG:3857)
        with rasterio.open(temp_file) as src:
            # Setup output profile
            profile = src.profile.copy()
            
            # Calculate transform for reprojection to Web Mercator
            transform, width, height = calculate_default_transform(
                src.crs, target_crs, src.width, src.height, *src.bounds
            )
            
            profile.update({
                "crs": target_crs,
                "transform": transform,
                "width": width,
                "height": height,
                "driver": "GTiff",
                "tiled": True,
                "blockxsize": 512,
                "blockysize": 512,
                "compress": "deflate",
                "interleave": "band"
            })
            
            # Create COG profile
            cog_profile = cog_profiles.get("deflate")
            
            # Create intermediate reprojected file
            reprojected_file = file_path + "_reprojected.tif"
            
            with rasterio.open(reprojected_file, 'w', **profile) as dst:
                # Reproject the source raster to Web Mercator
                reproject(
                    source=rasterio.band(src, 1),
                    destination=rasterio.band(dst, 1),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=target_crs,
                    resampling=Resampling.nearest
                )
            
            # Convert the reprojected file to COG
            cog_translate(
                reprojected_file, 
                file_path, 
                cog_profile, 
                in_memory=False,
                quiet=True
            )
        
        # Remove temporary files
        for temp in [temp_file, reprojected_file]:
            if os.path.exists(temp):
                os.remove(temp)
            
        logger.info(f"Saved Cloud Optimized GeoTIFF in {target_crs}: {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"Error saving as COG: {e}")
        # Clean up temporary files
        for temp in [temp_file, file_path + "_reprojected.tif"]:
            if os.path.exists(temp):
                os.remove(temp)
        raise

def upload_to_gcs(local_file_path, destination_blob_name, bucket_name, service_account_key):
    """
    Upload a file to Google Cloud Storage.
    
    Args:
        local_file_path (str): Path to the local file
        destination_blob_name (str): Path to the blob in GCS
        bucket_name (str): Name of the GCS bucket
        service_account_key (str): Path to service account key
        
    Returns:
        str: GCS URI of the uploaded file
    """
    try:
        client = storage.Client.from_service_account_json(service_account_key)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        
        blob.upload_from_filename(local_file_path)
        
        gcs_uri = f"gs://{bucket_name}/{destination_blob_name}"
        logger.info(f"File uploaded to {gcs_uri}")
        return gcs_uri
        
    except Exception as e:
        logger.error(f"Error uploading to GCS: {e}")
        raise

def process_and_save_return_period_maps(return_period_maps, config):
    """
    Process return period maps and save them as COGs in GCS.
    
    Args:
        return_period_maps (dict): Dictionary of return period maps
        config (dict): Configuration dictionary
        
    Returns:
        dict: Dictionary mapping seasons and return periods to GCS URIs
    """
    try:
        logger.info("Processing and saving return period maps as COGs")
        output_uris = {}
        
        # Create a temporary directory for saving files
        temp_dir = "temp_cogs"
        os.makedirs(temp_dir, exist_ok=True)
        
        for season, rp_maps in return_period_maps.items():
            output_uris[season] = {}
            
            for return_period, data_array in rp_maps.items():
                # Generate file name
                file_name = f"spi_exceedance_{season}_rp{return_period}.tif"
                local_path = os.path.join(temp_dir, file_name)
                
                # Save as COG
                save_as_cog(data_array, local_path, target_crs=config['TARGET_CRS'])
                
                # Upload to GCS
                gcs_path = os.path.join(config['OUTPUT_FOLDER'], file_name)
                gcs_uri = upload_to_gcs(
                    local_path, 
                    gcs_path, 
                    config['OUTPUT_BUCKET'], 
                    config['SERVICE_ACCOUNT_KEY']
                )
                
                # Record the URI
                output_uris[season][return_period] = gcs_uri
                
                # Remove local file
                if os.path.exists(local_path):
                    os.remove(local_path)
        
        # Remove temporary directory
        if os.path.exists(temp_dir):
            try:
                os.rmdir(temp_dir)
            except:
                pass
            
        return output_uris
        
    except Exception as e:
        logger.error(f"Error processing and saving return period maps: {e}")
        raise

def create_seasonal_maps(season_datasets, config, spi_var_name='spi3'):
    """
    Create and save seasonal SPI maps.
    
    Args:
        season_datasets (dict): Dictionary of seasonal datasets
        config (dict): Configuration dictionary
        spi_var_name (str): Name of the SPI variable in the dataset
        
    Returns:
        list: List of paths to generated maps
    """
    try:
        logger.info("Creating seasonal SPI maps")
        map_paths = []
        
        # Create a temporary directory for saving files
        temp_dir = "temp_maps"
        os.makedirs(temp_dir, exist_ok=True)
        
        for season, ds in season_datasets.items():
            # Calculate long-term average SPI for this season
            time_dim = 'time' if 'time' in ds.dims else 'valid_time'
            avg_spi = ds[spi_var_name].mean(dim=time_dim)
            
            # Create the plot
            fig, ax = plt.subplots(figsize=(10, 8), subplot_kw={'projection': ccrs.PlateCarree()})
            
            # Plot the data with appropriate colormap
            cmap = plt.cm.RdBu  # Red-Blue colormap for SPI (red for dry, blue for wet)
            vmin, vmax = -2, 2  # Common SPI range
            
            avg_spi.plot(ax=ax, cmap=cmap, vmin=vmin, vmax=vmax, 
                         transform=ccrs.PlateCarree(),
                         cbar_kwargs={'label': 'SPI Value'})
            
            # Add coastlines and borders
            ax.coastlines()
            ax.gridlines(draw_labels=True)
            
            # Add title
            plt.title(f'Long-term Average SPI for {season}')
            
            # Save the figure
            map_path = os.path.join(temp_dir, f"spi_map_{season}.png")
            plt.savefig(map_path, dpi=300, bbox_inches='tight')
            plt.close()
            
            # Upload to GCS
            gcs_path = os.path.join(config['OUTPUT_FOLDER'], f"spi_map_{season}.png")
            upload_to_gcs(
                map_path, 
                gcs_path, 
                config['OUTPUT_BUCKET'], 
                config['SERVICE_ACCOUNT_KEY']
            )
            
            map_paths.append(map_path)
            
            logger.info(f"Created and saved map for season {season}")
        
        return map_paths
        
    except Exception as e:
        logger.error(f"Error creating seasonal maps: {e}")
        raise

def process_spi_data(config):
    """
    Run the complete SPI processing pipeline.
    
    Args:
        config (dict): Configuration dictionary
        
    Returns:
        dict: Dictionary with results
    """
    try:
        logger.info("Starting SPI processing pipeline")
        
        # Get GCP credentials
        credentials = get_credentials(config['SERVICE_ACCOUNT_KEY'])
        
        # Load the SPI data
        ds = load_spi_data(config['INPUT_ZARR_PATH'], credentials)
        
        # Assign season names
        ds_with_seasons = assign_season_names(ds)
        
        # Group by season
        season_datasets = group_by_season(ds_with_seasons)
        
        # Calculate return period maps
        return_period_maps = calculate_return_period_maps(
            season_datasets, 
            config['RETURN_PERIODS']
        )
        
        # Process and save return period maps as COGs
        output_uris = process_and_save_return_period_maps(return_period_maps, config)
        
        # Create seasonal maps
        map_paths = create_seasonal_maps(season_datasets, config)
        
        logger.info("SPI processing pipeline completed successfully")
        
        return {
            "return_period_uris": output_uris,
            "map_paths": map_paths
        }
        
    except Exception as e:
        logger.error(f"Error in SPI processing pipeline: {e}")
        raise

def main():
    """Main function to run the script"""
    try:
        # Define the name of the .env file from command line arg or use default
        env_file = '.env.spi'
        if len(sys.argv) > 1:
            env_file = sys.argv[1]
        
        # Load environment variables
        config = load_environment(env_file)
        
        # Validate required configuration
        missing_vars = []
        for name, value in [
            ('INPUT_ZARR_PATH', config['INPUT_ZARR_PATH']),
            ('SERVICE_ACCOUNT_KEY', config['SERVICE_ACCOUNT_KEY']),
            ('OUTPUT_BUCKET', config['OUTPUT_BUCKET'])
        ]:
            if value == 'your-output-bucket' or 'your-bucket' in str(value):
                missing_vars.append(name)
        
        if missing_vars:
            logger.error(f"Missing or invalid configuration variables: {', '.join(missing_vars)}")
            logger.error(f"Please set these variables in the {env_file} file or directly in the environment")
            sys.exit(1)
        
        # Run the SPI processing pipeline
        results = process_spi_data(config)
        
        # Print summary of results
        print("\nProcessing completed successfully!")
        print("\nReturn Period Maps:")
        for season, rp_maps in results["return_period_uris"].items():
            print(f"\n  Season: {season}")
            for rp, uri in rp_maps.items():
                print(f"    {rp} year return period: {uri}")
                
        print("\nSeasonal Maps:")
        for map_path in results["map_paths"]:
            print(f"  {map_path}")
            
    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
