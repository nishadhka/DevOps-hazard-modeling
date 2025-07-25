"""
IMERG Data Processing Script: Download, Convert to Zarr, and Upload to GCS

This script performs the following tasks:
1. Downloads IMERG satellite data for specified date(s)
2. Subsets data to East Africa region
3. Converts to Zarr format for cloud storage and efficient access
4. Uploads processed files to Google Cloud Storage
5. Creates a separate Zarr file for each date (no date ranges)
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
from requests.auth import HTTPBasicAuth
import re
from pathlib import Path
import logging
from bs4 import BeautifulSoup
from urllib.parse import urljoin
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

def list_imerg_files_by_date(url, file_filter, username, password, start_date, end_date=None):
    """
    List IMERG GIS files available for download within a date range
    
    Args:
        url: Base URL for IMERG GIS data
        file_filter: String to filter filenames
        username: NASA Earthdata username
        password: NASA Earthdata password
        start_date: Start date in YYYYMMDD format
        end_date: End date in YYYYMMDD format (optional, defaults to start_date)
    
    Returns:
        Dictionary mapping date strings to file URLs
    """
    if not end_date:
        end_date = start_date
    
    # Convert dates to datetime objects
    start_dt = datetime.strptime(start_date, '%Y%m%d')
    end_dt = datetime.strptime(end_date, '%Y%m%d')
    
    logger.info(f"Finding IMERG files from {start_date} to {end_date}")
    
    # Generate list of months to check (NASA organizes by year/month, not day)
    months_to_check = set()
    current_dt = start_dt
    while current_dt <= end_dt:
        year_month = current_dt.strftime('%Y/%m')
        months_to_check.add(year_month)
        # Move to next day
        current_dt += timedelta(days=1)
    
    logger.info(f"Checking {len(months_to_check)} month(s) in the date range")
    
    # Find files for each month
    files_by_date = {}
    for year_month in months_to_check:
        # Construct directory URL
        dir_url = f"{url}/{year_month}/"
        
        # List files in directory
        try:
            logger.info(f"Checking directory: {dir_url}")
            response = requests.get(dir_url, auth=HTTPBasicAuth(username, password))
            response.raise_for_status()
            
            # Use BeautifulSoup for more robust HTML parsing
            soup = BeautifulSoup(response.text, 'html.parser')
            links = soup.find_all('a')
            
            found_files_count = 0
            
            # Filter files by date range and file filter
            for link in links:
                href = link.get('href')
                if href and file_filter in href:
                    # Extract date from filename - the pattern is now 3IMERG.YYYYMMDD in the filename
                    date_match = re.search(r'3IMERG\.(\d{8})', href)
                    if not date_match:
                        # Try alternative pattern: may be 3IMERG.YYYYMMDD-S...
                        date_match = re.search(r'3IMERG\.(\d{8})-', href)
                    
                    if not date_match:
                        # Try one more pattern
                        date_match = re.search(r'3IMERG\.(\d{8})\.', href)
                    
                    if not date_match:
                        # One final attempt with the format shown in your screenshot
                        date_match = re.search(r'3IMERG\.(\d{8})', href)
                    
                    if date_match:
                        file_date_str = date_match.group(1)
                        try:
                            file_date = datetime.strptime(file_date_str, '%Y%m%d')
                            
                            # Check if the file date is within our range
                            if start_dt <= file_date <= end_dt:
                                full_url = urljoin(dir_url, href)
                                date_key = file_date.strftime('%Y%m%d')
                                
                                # Store file URL by date
                                if date_key not in files_by_date:
                                    files_by_date[date_key] = []
                                files_by_date[date_key].append(full_url)
                                
                                found_files_count += 1
                                logger.debug(f"Matched file: {href}")
                        except ValueError:
                            logger.warning(f"Invalid date format in filename: {href}")
            
            logger.info(f"Found {found_files_count} files for {year_month} within date range")
            
        except requests.RequestException as e:
            logger.error(f"Error listing files for {year_month}: {e}")
    
    # Log summary of files found by date
    for date_key, files in files_by_date.items():
        logger.info(f"Date {date_key}: Found {len(files)} files")
    
    # Log a sample of found URLs to help with debugging
    for date_key, files in files_by_date.items():
        if files:
            logger.info(f"Sample URL for {date_key}: {files[0]}")
            break
    
    return files_by_date

def check_file_exists(output_dir, filename):
    """
    Check if file already exists in output directory
    
    Args:
        output_dir: Directory to check
        filename: Filename to check
    
    Returns:
        Boolean indicating if file exists
    """
    file_path = os.path.join(output_dir, filename)
    return os.path.exists(file_path)

def download_imerg_file(url, username, password, output_dir):
    """
    Download a single IMERG file
    
    Args:
        url: URL of the file to download
        username: NASA Earthdata username
        password: NASA Earthdata password
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
        response = requests.get(url, auth=HTTPBasicAuth(username, password), stream=True)
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

def extract_date_from_filename(filename):
    """
    Extract date from IMERG filename
    
    Args:
        filename: IMERG filename
    
    Returns:
        Date string in YYYYMMDD format or None if not found
    """
    # Try different patterns to extract the date
    patterns = [
        r'3IMERG\.(\d{8})',
        r'3IMERG\.(\d{8})-',
        r'3IMERG\.(\d{8})\.'
    ]
    
    for pattern in patterns:
        date_match = re.search(pattern, filename)
        if date_match:
            date_str = date_match.group(1)
            try:
                datetime.strptime(date_str, '%Y%m%d')  # Validate date format
                return date_str
            except ValueError:
                continue
    
    return None

def convert_to_zarr(data_array, zarr_path, date_string):
    """
    Convert a DataArray to a Zarr dataset for a single date
    
    Args:
        data_array: xarray.DataArray object
        zarr_path: Path to save Zarr dataset
        date_string: Date string for metadata (YYYYMMDD)
    
    Returns:
        Path to Zarr dataset
    """
    logger.info(f"Converting data to Zarr format for date {date_string}")
    
    try:
        # Process the data array
        if 'band' in data_array.dims:
            data_array = data_array.squeeze('band')
        
        # Add time dimension if it doesn't exist
        if 'time' not in data_array.dims:
            file_date = datetime.strptime(date_string, '%Y%m%d')
            data_array = data_array.expand_dims(time=[file_date])
        
        # Rename to precipitation
        data_array = data_array.rename('precipitation')
        
        # Create a Dataset from the DataArray
        ds = data_array.to_dataset()
        
        # Add metadata
        ds.attrs['created'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ds.attrs['source'] = 'IMERG'
        ds.attrs['date'] = date_string
        ds.attrs['description'] = 'IMERG precipitation data for East Africa'
        
        # Set up chunking for efficient access
        chunk_sizes = {'time': 1, 'y': 200, 'x': 200}
        ds = ds.chunk(chunk_sizes)
        
        # Save to Zarr format
        logger.info(f"Saving dataset to {zarr_path} with chunking {chunk_sizes}")
        ds.to_zarr(zarr_path, mode='w', consolidated=False)
        
        logger.info(f"Successfully saved Zarr dataset to {zarr_path}")
        return zarr_path
    
    except Exception as e:
        logger.error(f"Error converting to Zarr: {e}")
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

def process_imerg_file_for_date(file_paths, output_dir, bucket_name, date_string):
    """
    Process IMERG files for a single date: clip to East Africa extent, convert to Zarr, and upload to GCS
    
    Args:
        file_paths: List of paths to IMERG files for the date
        output_dir: Directory to save processed data
        bucket_name: GCS bucket name
        date_string: Date string in YYYYMMDD format
    
    Returns:
        Dictionary with path to Zarr dataset and GCS URL
    """
    logger.info(f"Processing {len(file_paths)} IMERG files for date {date_string}")
    
    # Create output subdirectories
    zarr_dir = os.path.join(output_dir, "IMERG_ZARR")
    os.makedirs(zarr_dir, exist_ok=True)
    
    # Create zarr path for this date
    zarr_path = os.path.join(zarr_dir, f"imerg_{date_string}.zarr")
    
    # Format GCS path
    gcs_path = f"inputs/zarr/imerg_{date_string}"
    
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
    
    # Process all files for this date
    # For IMERG data, we typically have one file per date, but we'll handle multiple just in case
    
    # Clip all files to the East Africa extent
    clipped_arrays = []
    for file_path in file_paths:
        clipped_data = clip_to_extent(file_path, EXTENT)
        if clipped_data is None:
            logger.warning(f"Failed to clip {os.path.basename(file_path)}, skipping")
            continue
        
        clipped_arrays.append(clipped_data)
    
    if not clipped_arrays:
        logger.error(f"No data arrays created for date {date_string}")
        return result
    
    # Since we're handling a single date, if we have multiple arrays, we'll need to combine them
    # For now, we'll just use the first one (typically there's only one daily file)
    data_array = clipped_arrays[0]
    if len(clipped_arrays) > 1:
        logger.warning(f"Multiple files found for date {date_string}, using only the first one")
    
    # Convert to Zarr
    zarr_dataset = convert_to_zarr(data_array, zarr_path, date_string)
    if zarr_dataset is None:
        logger.error(f"Failed to create Zarr dataset for date {date_string}")
        return result
    
    result["zarr_path"] = zarr_dataset
    
    # Upload to GCS if requested
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
    Main function to download, process, and upload IMERG data
    
    Args:
        start_date: Start date in YYYYMMDD format (default: 3 days ago)
        end_date: End date in YYYYMMDD format (default: yesterday)
        output_dir: Directory to save processed files (default: from ENV or ./output)
        bucket_name: GCS bucket name (default: from ENV)
    
    Returns:
        List of dictionaries with paths to Zarr datasets and GCS URLs
    """
    # Get dates from environment variables
    env_start_date = os.getenv('IMERG_START_DATE')
    env_end_date = os.getenv('IMERG_END_DATE')
    env_days_back = os.getenv('IMERG_DAYS_BACK')
    
    # Calculate default dates based on environment variables or fallback values
    today = datetime.now()
    default_end_date = (today - timedelta(days=1)).strftime('%Y%m%d')  # Yesterday
    
    # If IMERG_DAYS_BACK is set, use that for the default start date
    if env_days_back:
        try:
            days_back = int(env_days_back)
            default_start_date = (today - timedelta(days=days_back)).strftime('%Y%m%d')
            logger.info(f"Using IMERG_DAYS_BACK={days_back}, calculated start date: {default_start_date}")
        except ValueError:
            logger.warning(f"Invalid IMERG_DAYS_BACK value: {env_days_back}. Using 3 days as default.")
            default_start_date = (today - timedelta(days=3)).strftime('%Y%m%d')
    else:
        default_start_date = (today - timedelta(days=3)).strftime('%Y%m%d')
    
    # Set final values with priority: Function args > ENV vars > calculated defaults
    if not start_date:
        start_date = env_start_date if env_start_date else default_start_date
        logger.info(f"Using start date: {start_date} (source: {'environment variable' if env_start_date else 'calculated default'})")
    
    if not end_date:
        end_date = env_end_date if env_end_date else default_end_date
        logger.info(f"Using end date: {end_date} (source: {'environment variable' if env_end_date else 'calculated default'})")
    
    if not output_dir:
        output_dir = os.getenv('OUTPUT_DIR', './output')
    
    if not bucket_name:
        bucket_name = os.getenv('GCS_BUCKET_NAME', 'geosfm')  # Default to geosfm
    
    logger.info(f"Processing IMERG data from {start_date} to {end_date}")
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
    
    # Create a download directory
    download_dir = os.path.join(output_dir, "IMERG_DOWNLOAD")
    os.makedirs(download_dir, exist_ok=True)
    
    # Get IMERG credentials
    username = os.getenv('IMERG_USERNAME')
    password = os.getenv('IMERG_PASSWORD')
    
    if not username or not password:
        logger.error("IMERG credentials not found in environment variables")
        return None
    
    # Generate list of dates to process
    dates_to_process = date_range(start_date, end_date)
    logger.info(f"Processing {len(dates_to_process)} dates: {', '.join(dates_to_process)}")
    
    # List IMERG files by date
    url = "https://jsimpsonhttps.pps.eosdis.nasa.gov/imerg/gis/early/"
    file_filter = '-S233000-E235959.1410.V07B.1day.tif'
    
    logger.info(f"Using file filter: {file_filter}")
    
    files_by_date = list_imerg_files_by_date(
        url, file_filter, username, password, start_date, end_date
    )
    
    if not files_by_date:
        logger.warning(f"No IMERG files found for date range {start_date} to {end_date}")
        return []
    
    # Download and process files for each date
    results = []
    
    for date_string in dates_to_process:
        # Skip dates with no files
        if date_string not in files_by_date:
            logger.warning(f"No files found for date {date_string}, skipping")
            continue
        
        file_urls = files_by_date[date_string]
        logger.info(f"Processing date {date_string} with {len(file_urls)} files")
        
        # Download files for this date
        downloaded_files = []
        for file_url in file_urls:
            file_path = download_imerg_file(file_url, username, password, download_dir)
            if file_path:
                downloaded_files.append(file_path)
        
        if not downloaded_files:
            logger.warning(f"No files downloaded for date {date_string}, skipping")
            continue
        
        # Process files for this date
        result = process_imerg_file_for_date(downloaded_files, output_dir, bucket_name, date_string)
        results.append(result)
    
    logger.info(f"IMERG processing completed for {len(results)} dates")
    return results

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Download, process, and upload IMERG data to Zarr')
    parser.add_argument('--start-date', type=str, default=None,
                      help='Start date in YYYYMMDD format (default: 3 days ago)')
    parser.add_argument('--end-date', type=str, default=None,
                      help='End date in YYYYMMDD format (default: yesterday)')
    parser.add_argument('--output-dir', type=str, default=None,
                        help='Directory to save processed files (default: from ENV or ./output)')
    parser.add_argument('--bucket-name', type=str, default=None,
                        help='GCS bucket name (default: from ENV or geosfm)')
    
    args = parser.parse_args()
    
    # Set up logging
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    log_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f"imerg_zarr_processing_{log_timestamp}.log")
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    logger.info("=" * 80)
    logger.info("STARTING IMERG ZARR PROCESSING")
    logger.info("=" * 80)
    
    start_time = datetime.now()
    results = main(args.start_date, args.end_date, args.output_dir, args.bucket_name)
    end_time = datetime.now()
    
    logger.info("=" * 80)
    if results:
        logger.info(f"Successfully processed {len(results)} dates:")
        for result in results:
            date_string = result.get("date", "unknown date")
            zarr_path = result.get("zarr_path", "not created")
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