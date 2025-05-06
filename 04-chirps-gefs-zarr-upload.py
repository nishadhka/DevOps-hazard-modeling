"""
CHIRPS-GEFS Data Processing Script: Download, Convert to Zarr, and Upload to GCS

This script performs the following tasks:
1. Downloads CHIRPS-GEFS precipitation forecast data for a specified date range
2. Subsets data to East Africa region
3. Converts to Zarr format for cloud storage and efficient access
4. Uploads processed files to Google Cloud Storage
"""

import os
import argparse
from datetime import datetime, timedelta
import numpy as np
import rasterio
import rioxarray
import xarray as xr
import pandas as pd
import zarr
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
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

def list_chirps_gefs_files(base_url, date_string):
    """
    List CHIRPS-GEFS files available for download for a specific date
    
    Args:
        base_url: Base URL for CHIRPS-GEFS data
        date_string: Date in YYYYMMDD format
    
    Returns:
        List of file URLs matching only the actual date (not forecasts)
    """
    # Parse the date string
    year = date_string[:4]
    month = date_string[4:6]
    day = date_string[6:8]
    
    # Construct the URL
    url = f"{base_url}{year}/{month}/{day}/"
    
    logger.info(f"Looking for CHIRPS-GEFS files at URL: {url}")
    
    try:
        # Fetch the content of the URL
        response = requests.get(url)
        response.raise_for_status()
        
        # Parse the content using BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Find all links to TIF files
        tiff_files = []
        for link in soup.find_all('a'):
            href = link.get('href')
            if href and href.endswith('.tif'):
                # Only include files for the actual date, not forecasts
                if f"data.{year}.{month}{day}.tif" in href:
                    full_url = urljoin(url, href)
                    tiff_files.append(full_url)
        
        logger.info(f"Found {len(tiff_files)} CHIRPS-GEFS files for date {date_string}")
        return tiff_files
    
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching file list for {date_string}: {e}")
        return []
    
def download_chirps_gefs_file(url, output_dir):
    """
    Download a single CHIRPS-GEFS file
    
    Args:
        url: URL of the file to download
        output_dir: Directory to save the downloaded file
    
    Returns:
        Path to the downloaded file
    """
    filename = os.path.basename(url)
    output_path = os.path.join(output_dir, filename)
    
    # Skip if file already exists
    if os.path.exists(output_path):
        logger.info(f"File {filename} already exists, skipping download")
        return output_path
    
    logger.info(f"Downloading {filename}")
    
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"Successfully downloaded {filename}")
        return output_path
    
    except requests.RequestException as e:
        logger.error(f"Error downloading {filename}: {e}")
        return None

def clip_to_extent(src_path, extent):
    """
    Clip raster to the specified extent and return as xarray DataArray
    
    Args:
        src_path: Path to source raster
        extent: List of [min_lon, max_lon, min_lat, max_lat]
    
    Returns:
        xarray.DataArray of clipped data
    """
    logger.info(f"Clipping {os.path.basename(src_path)} to East Africa extent")
    
    try:
        # Open with rioxarray
        with rioxarray.open_rasterio(src_path) as rds:
            # Clip to extent
            clipped = rds.rio.clip_box(
                minx=extent[0],
                miny=extent[2],
                maxx=extent[1],
                maxy=extent[3]
            )
            
            # Ensure the data is in a proper format
            clipped = clipped.astype('float32')
            
            # If there are missing values, replace with NaN
            if hasattr(clipped, '_FillValue'):
                clipped = clipped.where(clipped != clipped._FillValue)
            
            return clipped
    
    except Exception as e:
        logger.error(f"Error clipping raster: {e}")
        return None

def convert_to_zarr(data_arrays, zarr_path, date_string):
    """
    Convert a list of DataArrays to a single Zarr dataset
    
    Args:
        data_arrays: List of xarray.DataArray objects
        zarr_path: Path to save Zarr dataset
        date_string: Date string for metadata
    
    Returns:
        Path to Zarr dataset
    """
    logger.info(f"Converting {len(data_arrays)} arrays to Zarr format")
    
    try:
        # Concatenate all DataArrays along time dimension
        if len(data_arrays) > 1:
            # We need to ensure all arrays have the same structure
            combined = xr.concat(data_arrays, dim='time')
        else:
            combined = data_arrays[0]
        
        # Rename to precipitation
        if 'band' in combined.dims:
            combined = combined.squeeze('band')
        
        combined = combined.rename('precipitation')
        
        # Create a Dataset from the DataArray
        ds = combined.to_dataset()
        
        # Add metadata
        ds.attrs['created'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ds.attrs['source'] = 'CHIRPS-GEFS'
        ds.attrs['date'] = date_string
        ds.attrs['description'] = 'CHIRPS-GEFS precipitation forecast data for East Africa'
        
        # Set up chunking for efficient access
        chunk_sizes = {'time': 1, 'y': 200, 'x': 200}
        ds = ds.chunk(chunk_sizes)
        
        # Save to Zarr format
        logger.info(f"Saving dataset to {zarr_path} with chunking {chunk_sizes}")
        ds.to_zarr(zarr_path, mode='w')
        
        logger.info(f"Successfully saved Zarr dataset to {zarr_path}")
        return zarr_path
    
    except Exception as e:
        logger.error(f"Error converting to Zarr: {e}")
        return None

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
            credentials = service_account.Credentials.from_service_account_file(
                credentials_file
            )
            client = storage.Client(credentials=credentials)
        else:
            # Use default credentials
            client = storage.Client()
        
        bucket = client.bucket(bucket_name)
        
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
        
        gcs_url = f"gs://{bucket_name}/{gcs_path}"
        logger.info(f"Successfully uploaded Zarr dataset to {gcs_url}")
        return gcs_url
    
    except Exception as e:
        logger.error(f"Error uploading to GCS: {e}")
        return None

def process_chirps_gefs_data(file_paths, output_dir, bucket_name, date_string):
    """
    Process CHIRPS-GEFS files: clip, convert to Zarr, and upload to GCS
    
    Args:
        file_paths: List of paths to CHIRPS-GEFS files
        output_dir: Directory to save processed data
        bucket_name: GCS bucket name
        date_string: Date string for the data (YYYYMMDD)
    
    Returns:
        Dictionary with path to Zarr dataset and GCS URL
    """
    logger.info(f"Processing {len(file_paths)} CHIRPS-GEFS files for {date_string}")
    
    # Create output subdirectories
    zarr_dir = os.path.join(output_dir, "CHIRPS_GEFS_ZARR")
    os.makedirs(zarr_dir, exist_ok=True)
    
    # Create zarr path for this date
    zarr_path = os.path.join(zarr_dir, f"chirps_gefs_{date_string}.zarr")
    
    # Check if output already exists
    if os.path.exists(zarr_path):
        logger.info(f"Zarr dataset {os.path.basename(zarr_path)} already exists, skipping processing")
        return {
            "zarr_path": zarr_path,
            "gcs_url": None  # Will be populated if upload is requested
        }
    
    # GCS path
    year = date_string[:4]
    month = date_string[4:6]
    day = date_string[6:8]
    gcs_path = f"CHIRPS_GEFS_ZARR/{year}/{month}/{day}/chirps_gefs_{date_string}.zarr"
    
    # Initialize result
    result = {
        "zarr_path": None,
        "gcs_url": None
    }
    
    # Process all files
    data_arrays = []
    
    for file_path in file_paths:
        # 1. Clip to East Africa extent
        clipped_data = clip_to_extent(file_path, EXTENT)
        if clipped_data is None:
            logger.warning(f"Failed to clip {os.path.basename(file_path)}, skipping")
            continue
        
        # Extract date from filename using the date_string and add as time coordinate
        file_date = datetime.strptime(date_string, '%Y%m%d')
        
        # Add time dimension with the file date
        clipped_data = clipped_data.expand_dims(time=[file_date])
        
        data_arrays.append(clipped_data)
    
    if not data_arrays:
        logger.error(f"No data arrays created for {date_string}")
        return result
    
    # 2. Convert to Zarr
    zarr_dataset = convert_to_zarr(data_arrays, zarr_path, date_string)
    if zarr_dataset is None:
        logger.error(f"Failed to create Zarr dataset for {date_string}")
        return result
    
    result["zarr_path"] = zarr_dataset
    
    # 3. Upload to GCS if requested
    do_upload = os.getenv('UPLOAD_TO_GCS', 'False').lower() in ('true', 'yes', '1', 't')
    if do_upload:
        gcs_url = upload_to_gcs(zarr_dataset, bucket_name, gcs_path)
        result["gcs_url"] = gcs_url
    else:
        logger.info(f"Upload to GCS skipped as requested")
    
    return result

def main(start_date=None, end_date=None, output_dir=None, bucket_name=None):
    """
    Main function to download, process, and upload CHIRPS-GEFS data
    
    Args:
        start_date: Start date in YYYYMMDD format (default: May 1, 2024)
        end_date: End date in YYYYMMDD format (default: May 3, 2024)
        output_dir: Directory to save processed files (default: from ENV or ./output)
        bucket_name: GCS bucket name (default: from ENV)
    """
    # Set default values (May 1-3, 2024) if no dates provided
    if not start_date:
        start_date = '20250501'
    if not end_date:
        end_date = '20250503'

    # Rest of the main function remains the same...
    if not output_dir:
        output_dir = os.getenv('OUTPUT_DIR', './output')
    
    if not bucket_name:
        bucket_name = os.getenv('GCS_BUCKET_NAME', 'dummy-bucket')
    
    logger.info(f"Processing CHIRPS-GEFS data from {start_date} to {end_date}")
    logger.info(f"Output directory: {output_dir}")
    
    # Generate list of dates to process
    date_list = date_range(start_date, end_date)
    logger.info(f"Processing {len(date_list)} dates: {', '.join(date_list)}")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Process each date
    results = {}
    for date_string in date_list:
        logger.info(f"Processing date: {date_string}")
        
        # Create a download directory for this date
        download_dir = os.path.join(output_dir, f"CHIRPS_GEFS_DOWNLOAD/{date_string}")
        os.makedirs(download_dir, exist_ok=True)
        
        # List CHIRPS-GEFS files for this date
        base_url = "https://data.chc.ucsb.edu/products/EWX/data/forecasts/CHIRPS-GEFS_precip_v12/daily_16day/"
        file_list = list_chirps_gefs_files(base_url, date_string)
        
        if not file_list:
            logger.warning(f"No CHIRPS-GEFS files found for date {date_string}")
            continue
        
        # Download files for this date
        downloaded_files = []
        for file_url in file_list:
            file_path = download_chirps_gefs_file(file_url, download_dir)
            if file_path:
                downloaded_files.append(file_path)
        
        if not downloaded_files:
            logger.warning(f"No CHIRPS-GEFS files downloaded for date {date_string}")
            continue
        
        # Process files for this date
        result = process_chirps_gefs_data(downloaded_files, output_dir, bucket_name, date_string)
        if result and result.get("zarr_path"):
            results[date_string] = result
    
    logger.info(f"CHIRPS-GEFS processing completed for {len(results)} dates")
    return results

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Download, process, and upload CHIRPS-GEFS data')
    parser.add_argument('--start-date', type=str, default=None,
                      help='Start date in YYYYMMDD format (default: 20250501)')
    parser.add_argument('--end-date', type=str, default=None,
                      help='End date in YYYYMMDD format (default: 20250503)')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='Directory to save processed files (default: from ENV or ./output)')
    parser.add_argument('--bucket-name', type=str, default=None,
                        help='GCS bucket name (default: from ENV)')
    
    args = parser.parse_args()
    
    # Set up logging
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    log_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f"chirps_gefs_processing_{log_timestamp}.log")
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    logger.info("=" * 80)
    logger.info("STARTING CHIRPS-GEFS PROCESSING")
    logger.info("=" * 80)
    
    start_time = datetime.now()
    results = main(args.start_date, args.end_date, args.output_dir, args.bucket_name)
    end_time = datetime.now()
    
    logger.info("=" * 80)
    if results:
        logger.info(f"Successfully processed data for {len(results)} dates:")
        for date_string, result in results.items():
            logger.info(f"  - {date_string}: {os.path.basename(result['zarr_path'])}")
    else:
        logger.info("No data was processed")
    
    logger.info(f"Total processing time: {end_time - start_time}")
    logger.info("=" * 80)