"""
PET Data Processing Script: Download, Convert to Zarr, and Upload to GCS

This script performs the following tasks:
1. Downloads PET data from USGS servers for a specified date range
2. Processes the data (converts from BIL to NetCDF)
3. Converts to Zarr format for cloud storage and efficient access
4. Uploads processed files to Google Cloud Storage
5. Creates a separate Zarr file for each date in the range
"""

import os
import argparse
import re
from datetime import datetime, timedelta
import numpy as np
import tarfile
import tempfile
import rasterio
import rioxarray
import xarray as xr
import pandas as pd
import zarr
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import logging
from pathlib import Path
from google.cloud import storage
from google.oauth2 import service_account
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Default to yesterday if date is not provided
yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

# Define East Africa extent from environment variables
EXTENT = [
    float(os.getenv('EXTENT_X1', '21.85')),  # min longitude
    float(os.getenv('EXTENT_X2', '51.50')),  # max longitude
    float(os.getenv('EXTENT_Y1', '-11.72')), # min latitude
    float(os.getenv('EXTENT_Y2', '23.14'))   # max latitude
]

# Log the extent values being used
logger.info(f"Using extent: [lon_min={EXTENT[0]}, lon_max={EXTENT[1]}, lat_min={EXTENT[2]}, lat_max={EXTENT[3]}]")

# Base URL for PET data
PET_BASE_URL = "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/fews/web/global/daily/pet/downloads/daily/"

def date_range(start_date_str, end_date_str):
    """
    Generate a list of date strings between start and end dates (inclusive)
    
    Args:
        start_date_str: Start date in YYYYMMDD format
        end_date_str: End date in YYYYMMDD format
        
    Returns:
        List of date strings in YYYYMMDD format
    """
    start_date = datetime.strptime(start_date_str, '%Y%m%d')
    end_date = datetime.strptime(end_date_str, '%Y%m%d')
    
    dates = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date.strftime('%Y%m%d'))
        current_date += timedelta(days=1)
    
    return dates

def get_pet_file_for_date(date_string):
    """
    Get the PET file URL for a specific date
    
    Args:
        date_string: Date in YYYYMMDD format
    
    Returns:
        URL of the PET file for the specified date or None if not found
    """
    # Parse the date
    date_obj = datetime.strptime(date_string, '%Y%m%d')
    
    # ET files use 2-digit year format
    yy = date_obj.strftime('%y')
    mm = date_obj.strftime('%m')
    dd = date_obj.strftime('%d')
    
    # Expected filename pattern is etYYMMDD.tar.gz (e.g., et250501.tar.gz for 2025-05-01)
    target_file = f"et{yy}{mm}{dd}.tar.gz"
    
    logger.info(f"Looking for file: {target_file} for date {date_string}")
    
    try:
        # Get directory listing
        response = requests.get(PET_BASE_URL)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find the file link
        for link in soup.find_all('a'):
            href = link.get('href')
            if href and href.endswith(target_file):
                file_url = urljoin(PET_BASE_URL, href)
                logger.info(f"Found PET file for {date_string}: {file_url}")
                return file_url
        
        logger.warning(f"PET file {target_file} not found for date {date_string}")
        return None
        
    except requests.RequestException as e:
        logger.error(f"Error accessing PET directory: {e}")
        return None

def download_extract_archive(file_url, output_dir):
    """
    Download and extract a PET tar.gz archive
    
    Args:
        file_url: URL of the PET tar.gz file
        output_dir: Directory to save and extract the file
    
    Returns:
        List of extracted BIL file paths
    """
    if not file_url:
        logger.error("No file URL provided")
        return []
    
    filename = os.path.basename(file_url)
    logger.info(f"Downloading and extracting archive: {filename}")
    
    try:
        # Create directories
        download_dir = os.path.join(output_dir, 'downloads')
        os.makedirs(download_dir, exist_ok=True)
        
        extract_dir = os.path.join(output_dir, 'extracted', filename.split('.')[0])
        os.makedirs(extract_dir, exist_ok=True)
        
        # Download the file
        local_file = os.path.join(download_dir, filename)
        
        # Skip download if file already exists
        if os.path.exists(local_file):
            logger.info(f"File {filename} already exists, skipping download")
        else:
            logger.info(f"Downloading {filename}")
            response = requests.get(file_url, stream=True)
            response.raise_for_status()
            
            with open(local_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        # Extract archive
        bil_files = []
        with tarfile.open(local_file, 'r:gz') as tar:
            # Extract all files
            tar.extractall(path=extract_dir)
            
            # Find all .bil files
            for member in tar.getmembers():
                if member.name.endswith('.bil'):
                    bil_path = os.path.join(extract_dir, member.name)
                    bil_files.append(bil_path)
                    logger.debug(f"Extracted BIL file: {bil_path}")
        
        logger.info(f"Successfully processed archive, found {len(bil_files)} BIL files")
        return bil_files
    
    except requests.RequestException as e:
        logger.error(f"Download failed for {file_url}: {e}")
        return []
    except tarfile.TarError as e:
        logger.error(f"Extraction failed for {file_url}: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error processing archive: {e}")
        return []

def process_bil_file(bil_path, date_str, netcdf_dir, extent):
    """
    Convert a BIL file to NetCDF format
    
    Args:
        bil_path: Path to the BIL file
        date_str: Date string in YYYYMMDD format
        netcdf_dir: Directory to save the NetCDF file
        extent: List of [min_lon, max_lon, min_lat, max_lat]
    
    Returns:
        Path to the NetCDF file
    """
    logger.info(f"Processing BIL file: {bil_path}")
    try:
        # Create directory if it doesn't exist
        os.makedirs(netcdf_dir, exist_ok=True)
        
        # Open BIL file
        with rioxarray.open_rasterio(bil_path) as xds:
            # Clip to East Africa extent
            clipped = xds.rio.clip_box(
                minx=extent[0],
                miny=extent[2],
                maxx=extent[1],
                maxy=extent[3]
            )
            
            # Add time dimension
            date_obj = datetime.strptime(date_str, '%Y%m%d')
            clipped = clipped.expand_dims(time=[date_obj])
            clipped = clipped.rename('pet')
            
            # Add metadata
            clipped.attrs.update({
                'long_name': 'Potential Evapotranspiration',
                'units': 'mm/day',
                'source': 'USGS FEWS NET',
                'processing_date': datetime.now().isoformat()
            })
            
            # Save as NetCDF
            nc_filename = f"pet_{date_str}.nc"
            nc_path = os.path.join(netcdf_dir, nc_filename)
            clipped.to_netcdf(nc_path)
            
            logger.info(f"Successfully created NetCDF: {nc_path}")
            return nc_path
    
    except rasterio.RasterioIOError as e:
        logger.error(f"Error reading BIL file {bil_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error processing BIL file: {e}")
        return None

def convert_to_zarr(data_array, zarr_path, date_string):
    """
    Convert a DataArray to a Zarr dataset for a single date
    
    Args:
        data_array: xarray.DataArray or Dataset object
        zarr_path: Path to save Zarr dataset
        date_string: Date string for metadata (YYYYMMDD)
    
    Returns:
        Path to Zarr dataset
    """
    logger.info(f"Converting data to Zarr format for date {date_string}")
    
    try:
        # If data_array is a NetCDF file path, open it
        if isinstance(data_array, str) and data_array.endswith('.nc'):
            ds = xr.open_dataset(data_array)
        else:
            # Assume it's already a Dataset or DataArray
            if hasattr(data_array, 'to_dataset'):
                ds = data_array.to_dataset()
            else:
                ds = data_array  # Already a Dataset
        
        # Add metadata
        ds.attrs.update({
            'created': datetime.now().isoformat(),
            'source': 'USGS PET',
            'date': date_string,
            'description': 'Potential Evapotranspiration data for East Africa',
            'processing_notes': 'Clipped to East Africa extent and converted to Zarr format'
        })
        
        # Set chunking
        chunks = {'time': 1}
        if 'y' in ds.dims and 'x' in ds.dims:
            chunks.update({'y': 200, 'x': 200})
        ds = ds.chunk(chunks)
        
        # Save as Zarr
        logger.info(f"Saving dataset to {zarr_path} with chunking {chunks}")
        ds.to_zarr(zarr_path, mode='w')
        
        logger.info(f"Successfully created Zarr dataset at {zarr_path}")
        return zarr_path
    
    except Exception as e:
        logger.error(f"Error creating Zarr dataset: {e}")
        logger.error(f"Exception details: {str(e)}")
        return None

def check_gcs_exists(client, bucket_name, gcs_path):
    """
    Check if a Zarr dataset already exists in GCS
    
    Args:
        client: GCS client
        bucket_name: GCS bucket name (without gs:// prefix)
        gcs_path: Path to Zarr dataset in GCS
    
    Returns:
        True if dataset exists, False otherwise
    """
    try:
        bucket = client.get_bucket(bucket_name)
        # Check if .zgroup exists (indicator of Zarr dataset)
        blob = bucket.blob(f"{gcs_path}/.zgroup")
        return blob.exists()
    except Exception as e:
        logger.error(f"Error checking if dataset exists in GCS: {e}")
        return False

def upload_to_gcs(src_path, bucket_name, gcs_path):
    """
    Upload Zarr dataset to Google Cloud Storage
    
    Args:
        src_path: Path to Zarr dataset directory
        bucket_name: GCS bucket name
        gcs_path: Destination path in GCS bucket
    
    Returns:
        GCS URL of uploaded dataset
    """
    # Remove 'gs://' prefix from bucket name if present
    if bucket_name.startswith('gs://'):
        bucket_name = bucket_name.replace('gs://', '', 1)
    
    logger.info(f"Uploading Zarr dataset {os.path.basename(src_path)} to GCS bucket {bucket_name}")
    
    # Get credentials from environment variable or service account file
    credentials_file = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    
    try:
        if credentials_file and os.path.exists(credentials_file):
            # Use service account file
            logger.info(f"Using credentials from {credentials_file}")
            credentials = service_account.Credentials.from_service_account_file(
                credentials_file
            )
            client = storage.Client(credentials=credentials)
        else:
            # Use default credentials
            logger.info("Using default credentials")
            client = storage.Client()
        
        # Get the bucket (don't create if it doesn't exist)
        try:
            bucket = client.get_bucket(bucket_name)
        except Exception as e:
            logger.error(f"Bucket {bucket_name} does not exist or is not accessible: {e}")
            return None
        
        # Check if dataset already exists in GCS
        if check_gcs_exists(client, bucket_name, gcs_path):
            logger.info(f"Dataset already exists in GCS at gs://{bucket_name}/{gcs_path}")
            return f"gs://{bucket_name}/{gcs_path}"
        
        # Count total files to upload for progress tracking
        total_files = sum(1 for _ in Path(src_path).glob('**/*') if _.is_file())
        uploaded_files = 0
        
        # Upload all files in the Zarr dataset directory and its subdirectories
        for local_path in Path(src_path).glob('**/*'):
            if local_path.is_file():
                # Get the relative path from the Zarr root directory
                relative_path = local_path.relative_to(src_path)
                # Construct the GCS blob path
                blob_path = f"{gcs_path}/{relative_path}"
                # Upload the file
                blob = bucket.blob(blob_path)
                blob.upload_from_filename(str(local_path))
                
                # Update progress
                uploaded_files += 1
                if uploaded_files % 20 == 0 or uploaded_files == total_files:
                    logger.info(f"Uploaded {uploaded_files}/{total_files} files")
        
        gcs_url = f"gs://{bucket_name}/{gcs_path}"
        logger.info(f"Successfully uploaded Zarr dataset to {gcs_url}")
        return gcs_url
    
    except Exception as e:
        logger.error(f"Error uploading to GCS: {e}")
        logger.error(f"Exception details: {str(e)}")
        return None

def process_pet_file_for_date(file_url, output_dir, bucket_name, date_string):
    """
    Process PET file for a single date: download, extract, convert to NetCDF, clip to East Africa, convert to Zarr, and upload to GCS
    
    Args:
        file_url: URL of the PET tar.gz file
        output_dir: Directory to save processed data
        bucket_name: GCS bucket name
        date_string: Date string in YYYYMMDD format
    
    Returns:
        Dictionary with path to Zarr dataset and GCS URL
    """
    logger.info(f"Processing PET file for date {date_string}")
    
    # Create output subdirectories
    zarr_dir = os.path.join(output_dir, "PET_ZARR")
    netcdf_dir = os.path.join(output_dir, "PET_NETCDF")
    
    os.makedirs(zarr_dir, exist_ok=True)
    os.makedirs(netcdf_dir, exist_ok=True)
    
    # Create zarr path for this date
    zarr_path = os.path.join(zarr_dir, f"pet_{date_string}.zarr")
    
    # Format GCS path
    gcs_path = f"inputs/zarr/pet_{date_string}"
    
    # Initialize result
    result = {
        "date": date_string,
        "zarr_path": None,
        "gcs_url": None
    }
    
    # Check if output already exists
    if os.path.exists(zarr_path):
        logger.info(f"Zarr dataset {os.path.basename(zarr_path)} already exists, skipping processing")
        result["zarr_path"] = zarr_path
        
        # Check if we should upload to GCS
        do_upload = os.getenv('UPLOAD_TO_GCS', 'False').lower() in ('true', 'yes', '1', 't')
        if do_upload:
            logger.info(f"Uploading existing dataset to GCS")
            gcs_url = upload_to_gcs(zarr_path, bucket_name, gcs_path)
            result["gcs_url"] = gcs_url
        else:
            logger.info(f"Upload to GCS skipped as requested by environment variable")
        
        return result
    
    # 1. Download and extract archive
    bil_files = download_extract_archive(file_url, output_dir)
    if not bil_files:
        logger.error(f"No BIL files extracted for date {date_string}")
        return result
    
    # 2. Process BIL files to NetCDF and clip to East Africa
    nc_files = []
    for bil_file in bil_files:
        nc_file = process_bil_file(bil_file, date_string, netcdf_dir, EXTENT)
        if nc_file:
            nc_files.append(nc_file)
    
    if not nc_files:
        logger.error(f"No NetCDF files created for date {date_string}")
        return result
    
    # 3. Convert to Zarr
    # For now, we'll just use the first one if multiple were created
    nc_file = nc_files[0]
    if len(nc_files) > 1:
        logger.warning(f"Multiple NetCDF files created for date {date_string}, using only the first one")
    
    zarr_dataset = convert_to_zarr(nc_file, zarr_path, date_string)
    if not zarr_dataset:
        logger.error(f"Failed to create Zarr dataset for date {date_string}")
        return result
    
    result["zarr_path"] = zarr_dataset
    
    # 4. Upload to GCS if requested
    do_upload = os.getenv('UPLOAD_TO_GCS', 'False').lower() in ('true', 'yes', '1', 't')
    if do_upload:
        logger.info(f"Uploading dataset to GCS bucket {bucket_name}")
        gcs_url = upload_to_gcs(zarr_dataset, bucket_name, gcs_path)
        result["gcs_url"] = gcs_url
    else:
        logger.info(f"Upload to GCS skipped as requested by environment variable")
    
    return result

def main(start_date=None, end_date=None, output_dir=None, bucket_name=None):
    """
    Main function to download, process, and upload PET data for a date range
    
    Args:
        start_date: Start date in YYYYMMDD format (default: May 1, 2025)
        end_date: End date in YYYYMMDD format (default: May 3, 2025)
        output_dir: Directory to save processed files (default: from ENV or ./output)
        bucket_name: GCS bucket name (default: from ENV or geosfm)
    
    Returns:
        List of dictionaries with paths to Zarr datasets and GCS URLs
    """
    # Set default values (May 1-3, 2025) if no dates provided
    if not start_date:
        start_date = '20250501'
    if not end_date:
        end_date = '20250503'
    
    # Set default output directory and bucket name
    if not output_dir:
        output_dir = os.getenv('OUTPUT_DIR', './output')
    
    if not bucket_name:
        bucket_name = os.getenv('GCS_BUCKET_NAME', 'geosfm')  # Default to geosfm
    
    logger.info(f"Processing PET data from {start_date} to {end_date}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"GCS bucket name: {bucket_name}")
    
    # Check if upload to GCS is enabled
    do_upload = os.getenv('UPLOAD_TO_GCS', 'False').lower() in ('true', 'yes', '1', 't')
    logger.info(f"Upload to GCS: {do_upload}")
    
    # Check GCS credentials if uploading
    if do_upload:
        credentials_file = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        if credentials_file:
            if os.path.exists(credentials_file):
                logger.info(f"GCS credentials file found at {credentials_file}")
            else:
                logger.warning(f"GCS credentials file not found at {credentials_file}")
        else:
            logger.warning("GOOGLE_APPLICATION_CREDENTIALS environment variable not set")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate list of dates to process
    dates_to_process = date_range(start_date, end_date)
    logger.info(f"Processing {len(dates_to_process)} dates: {', '.join(dates_to_process)}")
    
    # Process each date
    results = []
    for date_string in dates_to_process:
        # Get file URL for date
        file_url = get_pet_file_for_date(date_string)
        
        if not file_url:
            logger.warning(f"No PET file found for date {date_string}, skipping")
            continue
        
        # Process file for this date
        result = process_pet_file_for_date(file_url, output_dir, bucket_name, date_string)
        if result and result.get("zarr_path"):
            results.append(result)
    
    logger.info(f"PET processing completed for {len(results)} dates")
    return results

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Download, process, and upload PET data to Zarr')
    parser.add_argument('--start-date', type=str, default=None,
                      help='Start date in YYYYMMDD format (default: 20250501)')
    parser.add_argument('--end-date', type=str, default=None,
                      help='End date in YYYYMMDD format (default: 20250503)')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='Directory to save processed files (default: from ENV or ./output)')
    parser.add_argument('--bucket-name', type=str, default=None,
                        help='GCS bucket name (default: from ENV or geosfm)')
    
    args = parser.parse_args()
    
    # Set up logging
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    log_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f"pet_zarr_processing_{log_timestamp}.log")
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    logger.info("=" * 80)
    logger.info("STARTING PET ZARR PROCESSING")
    logger.info("=" * 80)
    
    start_time = datetime.now()
    results = main(args.start_date, args.end_date, args.output_dir, args.bucket_name)
    end_time = datetime.now()
    
    logger.info("=" * 80)
    if results:
        logger.info(f"Successfully processed {len(results)} dates:")
        for result in results:
            date_string = result.get("date", "unknown date")
            zarr_path = result.get("zarr_path")
            if zarr_path:
                zarr_filename = os.path.basename(zarr_path)
                logger.info(f"  - {date_string}: {zarr_filename}")
                gcs_url = result.get("gcs_url")
                if gcs_url:
                    logger.info(f"    Uploaded to: {gcs_url}")
                else:
                    do_upload = os.getenv('UPLOAD_TO_GCS', 'False').lower() in ('true', 'yes', '1', 't')
                    if do_upload:
                        logger.info(f"    Not uploaded to GCS (upload failed)")
                    else:
                        logger.info(f"    Not uploaded to GCS (upload disabled)")
    else:
        logger.info("No dates were processed")
    
    logger.info(f"Total processing time: {end_time - start_time}")
    logger.info("=" * 80)
    
    # Print path to log file
    print(f"Process completed. Log file saved to: {log_file}")