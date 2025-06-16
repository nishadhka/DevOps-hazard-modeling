from prefect import flow, task
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import xarray as xr
from dask.distributed import Client, as_completed
from dask import delayed
import geopandas as gp
import pandas as pd
import numpy as np
import glob
from concurrent.futures import ThreadPoolExecutor
import asyncio
import aiohttp
import requests

from utils import (
    pet_list_files_by_date,
    pet_download_extract_bilfile_parallel,
    pet_bil_netcdf_parallel,
    pet_read_netcdf_files_in_date_range,
    get_dask_client_params,
    process_zone_from_combined,
    regrid_dataset_parallel,
    zone_mean_df_parallel,
    pet_download_files_parallel
)

load_dotenv()

@task
def get_current_date():
    """Get the current date in YYYYMMDD format."""
    return datetime.now().strftime('%Y%m%d')

@task
def setup_environment():
    """Set up the environment for data processing"""
    data_path = os.getenv("data_path", "./data/")
    output_dir = f'{data_path}geofsm-input/pet/dir/'
    netcdf_path = f'{data_path}geofsm-input/pet/netcdf/'
    zone_input_path = f"{data_path}zone_wise_txt_files/"
    init_zone_path = f"{data_path}zone_wise_txt_files/init/"
    
    # Create all necessary directories
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(netcdf_path, exist_ok=True)
    os.makedirs(zone_input_path, exist_ok=True)
    os.makedirs(init_zone_path, exist_ok=True)
    
    # Get optimized Dask client parameters
    params = get_dask_client_params()
    # Increase workers for parallel processing
    params['n_workers'] = min(params['n_workers'] * 2, 8)  # Up to 8 workers
    client = Client(**params)
    
    print(f"Environment setup complete. Using data_path: {data_path}")
    print(f"Dask dashboard available at: {client.dashboard_link}")
    print(f"Using {params['n_workers']} workers with {params['threads_per_worker']} threads each")
    return data_path, output_dir, netcdf_path, client

def get_last_date_from_evap(zone_dir, is_init=False):
    """Read the existing evap.txt file and determine the last date in the file."""
    evap_file = os.path.join(zone_dir, 'evap.txt')
    dir_type = "init" if is_init else "standard"
    
    if not os.path.exists(evap_file):
        print(f"No existing evap.txt found at {evap_file} ({dir_type} directory)")
        return None
    
    try:
        df = pd.read_csv(evap_file, sep=",")
        if 'NA' not in df.columns:
            print(f"Invalid format in evap.txt ({dir_type} directory) - missing 'NA' column")
            return None
        
        last_date_str = df['NA'].iloc[-1]
        last_date = datetime.strptime(str(last_date_str), '%Y%j')
        print(f"Last date in {dir_type} evap.txt: {last_date.strftime('%Y-%m-%d')} (Day {last_date_str})")
        return last_date
        
    except Exception as e:
        print(f"Error reading existing evap.txt ({dir_type} directory): {e}")
        return None

def pet_extend_forecast_improved(df, date_column, days_to_add=16):
    """Add a forecast extension by copying the last 15 days of data."""
    df = df.copy()
    
    def safe_to_datetime(date_str):
        try:
            return datetime.strptime(str(date_str), '%Y%j')
        except ValueError:
            return None

    df['_temp_date'] = df[date_column].apply(safe_to_datetime)
    df = df.dropna(subset=['_temp_date'])
    
    if df.empty:
        print(f"No valid dates found in the '{date_column}' column.")
        return df
        
    df = df.sort_values('_temp_date')
    days_to_copy = min(15, len(df))
    historical_pattern = df.iloc[-days_to_copy:].copy()
    
    new_rows = []
    last_date = df['_temp_date'].iloc[-1]
    
    for i in range(days_to_add):
        new_date = last_date + timedelta(days=i+1)
        historical_idx = i % len(historical_pattern)
        new_row = historical_pattern.iloc[historical_idx].copy()
        new_row['_temp_date'] = new_date
        new_rows.append(new_row)
    
    new_rows_df = pd.DataFrame(new_rows)
    result_df = pd.concat([df, new_rows_df], ignore_index=True)
    result_df[date_column] = result_df['_temp_date'].dt.strftime('%Y%j')
    result_df = result_df.drop(columns=['_temp_date'])
    
    return result_df

def update_standard_directory_with_forecast(data_path, zone_str):
    """Update standard directory with forecast from init directory."""
    zone_input_path = f"{data_path}zone_wise_txt_files/"
    init_zone_dir = f"{zone_input_path}init/{zone_str}"
    standard_zone_dir = f"{zone_input_path}{zone_str}"
    
    os.makedirs(standard_zone_dir, exist_ok=True)
    
    init_evap_file = os.path.join(init_zone_dir, 'evap.txt')
    standard_evap_file = os.path.join(standard_zone_dir, 'evap.txt')
    standard_zone_specific_file = os.path.join(standard_zone_dir, f'evap_{zone_str}.txt')
    
    if not os.path.exists(init_evap_file):
        print(f"Error: No evap.txt found in init directory for {zone_str}")
        return None, None
    
    try:
        df = pd.read_csv(init_evap_file, sep=",")
        df_with_forecast = pet_extend_forecast_improved(df, 'NA')
        
        df_with_forecast.to_csv(standard_evap_file, index=False)
        df_with_forecast.to_csv(standard_zone_specific_file, index=False)
        
        print(f"Updated standard directory with forecast for {zone_str}")
        return standard_evap_file, standard_zone_specific_file
        
    except Exception as e:
        print(f"Error updating standard directory with forecast for {zone_str}: {e}")
        return None, None

def pet_update_input_data(z1a, zone_input_path, zone_str, start_date, end_date):
    """Process evaporation data and generate output files."""
    zone_dir = f'{zone_input_path}{zone_str}'
    init_zone_dir = f'{zone_input_path}init/{zone_str}'
    
    os.makedirs(zone_dir, exist_ok=True)
    os.makedirs(init_zone_dir, exist_ok=True)
    
    z1a['pet'] = z1a['pet'] / 10
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    historical_df = z1a.copy()
    historical_df = historical_df[historical_df['time'] < today]
    
    zz1 = z1a.pivot(index='time', columns='group', values='pet')
    historical_zz1 = historical_df.pivot(index='time', columns='group', values='pet')
    
    zz1 = zz1.apply(lambda row: row.map(lambda x: f'{x:.1f}' if isinstance(x, (int, float)) and pd.notna(x) else x), axis=1)
    historical_zz1 = historical_zz1.apply(lambda row: row.map(lambda x: f'{x:.1f}' if isinstance(x, (int, float)) and pd.notna(x) else x), axis=1)
    
    azz1 = zz1.reset_index()
    azz1['NA'] = azz1['time'].dt.strftime('%Y%j')
    azz1.columns = [str(col) if isinstance(col, int) else col for col in azz1.columns]
    azz1 = azz1.rename(columns={'time': 'date'})
    
    historical_azz1 = historical_zz1.reset_index()
    historical_azz1['NA'] = historical_azz1['time'].dt.strftime('%Y%j')
    historical_azz1.columns = [str(col) if isinstance(col, int) else col for col in historical_azz1.columns]
    historical_azz1 = historical_azz1.rename(columns={'time': 'date'})
    
    evap_file = f'{zone_dir}/evap.txt'
    base_evap_file = f'{init_zone_dir}/evap.txt'
    
    # Process standard files
    if os.path.exists(evap_file):
        try:
            ez1 = pd.read_csv(evap_file, sep=",")
            ez1['date'] = pd.to_datetime(ez1['NA'], format='%Y%j')
            mask = (ez1['date'] < start_date) | (ez1['date'] > end_date)
            aez1 = ez1[mask]
            bz1 = pd.concat([aez1, azz1], axis=0)
            bz1.drop(['date'], axis=1, inplace=True)
            bz1.reset_index(drop=True, inplace=True)
        except Exception as e:
            print(f"Error reading existing evap.txt: {e}")
            bz1 = azz1.drop(['date'], axis=1).reset_index(drop=True)
    else:
        bz1 = azz1.drop(['date'], axis=1).reset_index(drop=True)
    
    # Process init files
    if os.path.exists(base_evap_file):
        try:
            base_ez1 = pd.read_csv(base_evap_file, sep=",")
            base_ez1['date'] = pd.to_datetime(base_ez1['NA'], format='%Y%j')
            
            filter_date = start_date
            if filter_date >= today:
                base_bz1 = base_ez1.copy()
            else:
                mask = (base_ez1['date'] < start_date) | (base_ez1['date'] >= today)
                base_aez1 = base_ez1[mask]
                base_bz1 = pd.concat([base_aez1, historical_azz1], axis=0)
                base_bz1.drop(['date'], axis=1, inplace=True)
                base_bz1.reset_index(drop=True, inplace=True)
        except Exception as e:
            print(f"Error reading existing base evap.txt: {e}")
            base_bz1 = historical_azz1.drop(['date'], axis=1).reset_index(drop=True)
    else:
        base_bz1 = historical_azz1.drop(['date'], axis=1).reset_index(drop=True)
    
    if 'NA' in bz1.columns:
        bz1['NA'] = bz1['NA'].astype(str)
    if 'NA' in base_bz1.columns:
        base_bz1['NA'] = base_bz1['NA'].astype(str)
    
    bz1 = bz1.sort_values(by='NA').reset_index(drop=True)
    base_bz1 = base_bz1.sort_values(by='NA').reset_index(drop=True)
    
    bz2 = pet_extend_forecast_improved(bz1, 'NA')
    
    # Save all files
    bz2.to_csv(evap_file, index=False)
    zone_specific_file = f'{zone_dir}/evap_{zone_str}.txt'
    bz2.to_csv(zone_specific_file, index=False)
    
    base_bz1.to_csv(base_evap_file, index=False)
    base_zone_specific_file = f'{init_zone_dir}/evap_{zone_str}.txt'
    base_bz1.to_csv(base_zone_specific_file, index=False)
    
    print(f"Updated files for {zone_str}")
    
    return evap_file, zone_specific_file, base_evap_file, base_zone_specific_file

@task
def get_pet_files(url, start_date, end_date):
    """Get the list of PET files for the date range."""
    try:
        print(f"Getting PET files from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        pet_list = pet_list_files_by_date(url, start_date, end_date)
        print(f"Found {len(pet_list)} PET files in date range")
        return pet_list
    except Exception as e:
        print(f"Error fetching PET files: {e}")
        raise

@task
def process_pet_files_parallel(pet_list, output_dir, netcdf_path, client):
    """Download and process PET files in parallel using Dask."""
    print(f"Processing {len(pet_list)} PET files in parallel")
    
    # Check which files already exist
    files_to_process = []
    for file_url, date in pet_list:
        date_str = date.strftime('%Y%m%d')
        nc_file = os.path.join(netcdf_path, f"{date_str}.nc")
        if not os.path.exists(nc_file):
            files_to_process.append((file_url, date))
    
    if not files_to_process:
        print("All files already processed")
        return len(pet_list)
    
    print(f"Need to process {len(files_to_process)} new files")
    
    # Use parallel download function
    pet_download_files_parallel(files_to_process, output_dir, netcdf_path, max_workers=8)
    
    print(f"Processed {len(files_to_process)} PET files")
    return len(pet_list)

@delayed
def process_single_date_delayed(data_path, netcdf_path, zone_str, file_date):
    """Process PET data for a single zone and date - Dask delayed version."""
    try:
        date_str = file_date.strftime('%Y%m%d')
        nc_file = os.path.join(netcdf_path, f"{date_str}.nc")
        
        if not os.path.exists(nc_file):
            return None
        
        # Read the single file
        ds = xr.open_dataset(nc_file)
        
        if 'spatial_ref' in ds.variables:
            ds = ds.drop_vars('spatial_ref')
        if 'band' in ds.variables:
            ds = ds.drop_vars('band')
        if 'date' in ds.variables:
            ds = ds.drop_vars('date')
        if 'band' in ds.dims:
            ds = ds.squeeze('band')
        if '__xarray_dataarray_variable__' in ds.data_vars:
            ds = ds.rename_vars({'__xarray_dataarray_variable__': 'pet'})
        
        ds = ds.expand_dims(time=[file_date])
        
        rename_dict = {}
        if 'x' in ds.dims and 'lon' not in ds.dims:
            rename_dict['x'] = 'lon'
        if 'y' in ds.dims and 'lat' not in ds.dims:
            rename_dict['y'] = 'lat'
        
        if rename_dict:
            ds = ds.rename(rename_dict)
        
        # Process zone
        master_shapefile = f'{data_path}WGS/geofsm-prod-all-zones-20240712.shp'
        z1ds, pdsz1, zone_extent = process_zone_from_combined(master_shapefile, zone_str, 1, ds)
        
        # Regrid in parallel
        regridded_data = regrid_dataset_parallel(pdsz1, zone_extent)
        
        # Calculate zone means in parallel
        zone_means = zone_mean_df_parallel(regridded_data, z1ds)
        
        return zone_means
        
    except Exception as e:
        print(f"Error processing {zone_str} for date {file_date}: {e}")
        return None

@flow
def process_zone_pet_parallel(data_path, netcdf_path, zone_str, start_date, end_date, client):
    """Process PET data for a single zone across multiple dates in parallel."""
    print(f"Processing zone {zone_str} from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    if not isinstance(zone_str, str):
        zone_str = str(zone_str)
    
    if zone_str.isdigit():
        zone_str = f'zone{zone_str}'
    elif not zone_str.startswith('zone'):
        zone_str = f'zone{zone_str}'
    
    try:
        # Generate date range
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        
        # Create delayed tasks for each date
        delayed_results = []
        for file_date in date_range:
            delayed_result = process_single_date_delayed(data_path, netcdf_path, zone_str, file_date)
            delayed_results.append(delayed_result)
        
        # Compute all results in parallel
        futures = client.compute(delayed_results)
        
        # Gather results as they complete
        all_results = []
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                all_results.append(result)
        
        if all_results:
            combined_results = pd.concat(all_results, ignore_index=True)
            
            evap_file, zone_specific_file, base_evap_file, base_zone_specific_file = pet_update_input_data(
                combined_results, f"{data_path}zone_wise_txt_files/", zone_str, start_date, end_date
            )
            
            return evap_file, zone_specific_file, base_evap_file, base_zone_specific_file
        else:
            print(f"No valid results found for {zone_str} in date range")
            return None, None, None, None
    
    except Exception as e:
        print(f"Error in process_zone_pet_parallel for {zone_str}: {e}")
        return None, None, None, None

@delayed
def process_zone_delayed(zone_str, data_path, netcdf_path, url, today):
    """Process a single zone - Dask delayed version."""
    try:
        if not isinstance(zone_str, str):
            zone_str = str(zone_str)
        
        if zone_str.isdigit():
            zone_str = f'zone{zone_str}'
        elif not zone_str.startswith('zone'):
            zone_str = f'zone{zone_str}'
        
        print(f"\n===== Processing {zone_str} =====")
        
        zone_dir = f"{data_path}zone_wise_txt_files/{zone_str}"
        init_zone_dir = f"{data_path}zone_wise_txt_files/init/{zone_str}"
        
        os.makedirs(zone_dir, exist_ok=True)
        os.makedirs(init_zone_dir, exist_ok=True)
        
        last_date = get_last_date_from_evap(init_zone_dir, is_init=True)
        if last_date is None:
            last_date = get_last_date_from_evap(zone_dir, is_init=False)
        
        need_new_data = False
        if last_date:
            start_date = last_date + timedelta(days=1)
            if start_date >= today:
                print(f"Init directory already up to date (last date: {last_date.strftime('%Y-%m-%d')})")
                standard_evap_file, zone_specific_file = update_standard_directory_with_forecast(data_path, zone_str)
                
                if standard_evap_file and zone_specific_file:
                    return {
                        'zone': zone_str,
                        'standard_files': [standard_evap_file, zone_specific_file],
                        'base_files': [],
                        'success': True
                    }
                else:
                    return {'zone': zone_str, 'success': False}
            else:
                need_new_data = True
        else:
            start_date = today - timedelta(days=30)
            need_new_data = True
        
        if need_new_data:
            end_date = today - timedelta(days=1)
            
            # Get PET files
            pet_files = pet_list_files_by_date(url, start_date, end_date)
            
            if not pet_files:
                print(f"No new PET files found for {zone_str}")
                return {'zone': zone_str, 'success': False}
            
            # Download files if needed (this will be handled by the main flow)
            return {
                'zone': zone_str,
                'start_date': start_date,
                'end_date': end_date,
                'pet_files': pet_files,
                'needs_processing': True
            }
    
    except Exception as e:
        print(f"Error processing {zone_str}: {e}")
        return {'zone': zone_str, 'success': False, 'error': str(e)}

@flow
def pet_all_zones_workflow():
    """Main workflow for processing PET data for all zones in parallel."""
    data_path, output_dir, netcdf_path, client = setup_environment()
    
    try:
        url = "https://edcintl.cr.usgs.gov/downloads/sciweb1/shared/fews/web/global/daily/pet/downloads/daily/"
        
        master_shapefile = f'{data_path}WGS/geofsm-prod-all-zones-20240712.shp'
        if not os.path.exists(master_shapefile):
            print(f"ERROR: Master shapefile not found at {master_shapefile}")
            raise FileNotFoundError(f"Master shapefile not found: {master_shapefile}")
        
        print(f"Found master shapefile: {master_shapefile}")
        
        all_zones = gp.read_file(master_shapefile)
        unique_zones = all_zones['zone'].unique()
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Phase 1: Check all zones to determine what needs processing
        print("\nPhase 1: Checking all zones...")
        zones_to_process = []
        all_pet_files_needed = set()
        
        for zone_str in unique_zones:
            print(f"\n===== Processing {zone_str} =====")
            zone_dir = f"{data_path}zone_wise_txt_files/{zone_str}"
            init_zone_dir = f"{data_path}zone_wise_txt_files/init/{zone_str}"
            
            os.makedirs(zone_dir, exist_ok=True)
            os.makedirs(init_zone_dir, exist_ok=True)
            
            last_date = get_last_date_from_evap(init_zone_dir, is_init=True)
            if last_date is None:
                last_date = get_last_date_from_evap(zone_dir, is_init=False)
            
            if last_date:
                start_date = last_date + timedelta(days=1)
                if start_date >= today:
                    print(f"Init directory already up to date (last date: {last_date.strftime('%Y-%m-%d')}")
                    standard_evap_file, zone_specific_file = update_standard_directory_with_forecast(data_path, zone_str)
                    continue
            else:
                start_date = today - timedelta(days=30)
            
            end_date = today - timedelta(days=1)
            pet_files = pet_list_files_by_date(url, start_date, end_date)
            
            if pet_files:
                zones_to_process.append({
                    'zone': zone_str,
                    'start_date': start_date,
                    'end_date': end_date,
                    'pet_files': pet_files
                })
                for file_url, date in pet_files:
                    all_pet_files_needed.add((file_url, date))
        
        # Phase 2: Download all required files in parallel
        if all_pet_files_needed:
            print(f"\nPhase 2: Downloading {len(all_pet_files_needed)} PET files in parallel...")
            pet_files_list = list(all_pet_files_needed)
            process_pet_files_parallel(pet_files_list, output_dir, netcdf_path, client)
        
        # Phase 3: Process zones with new data
        if zones_to_process:
            print(f"\nPhase 3: Processing {len(zones_to_process)} zones with new data...")
            
            # Use Dask delayed for the computationally intensive parts
            delayed_results = []
            for zone_info in zones_to_process:
                for file_date in pd.date_range(zone_info['start_date'], zone_info['end_date'], freq='D'):
                    delayed_result = process_single_date_delayed(
                        data_path, netcdf_path, zone_info['zone'], file_date
                    )
                    delayed_results.append(delayed_result)
            
            # Compute all results in parallel
            futures = client.compute(delayed_results)
            results = client.gather(futures)
            
            # Process results for each zone
            for zone_info in zones_to_process:
                zone_results = [r for r in results if r is not None and r['zone'] == zone_info['zone']]
                if zone_results:
                    combined_results = pd.concat(zone_results, ignore_index=True)
                    pet_update_input_data(
                        combined_results, 
                        f"{data_path}zone_wise_txt_files/", 
                        zone_info['zone'], 
                        zone_info['start_date'], 
                        zone_info['end_date']
                    )
        
        print("\nWorkflow completed successfully!")
        return True
    
    except Exception as e:
        print(f"Error in workflow: {e}")
        raise
    finally:
        client.close()
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Process PET data for hydrological modeling with parallel processing')
    args = parser.parse_args()
    
    print(f"Processing PET data from last available date forward with parallel processing")
    result = pet_all_zones_workflow()
    print(f"Generated standard files (with forecast): {result['standard_files']}")
    print(f"Generated base files (historical only): {result['base_files']}")