import os
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv
import xarray as xr
import numpy as np
from xclim.indices import standardized_precipitation_index
from google.oauth2 import service_account
from dask.distributed import Client
import coiled
from dask.diagnostics import ProgressBar

def load_credentials(credentials_path, scopes=None):
    """
    Load GCP service account credentials from a file.
    
    Args:
        credentials_path (str): Path to the service account JSON file
        scopes (list): List of authentication scopes (default: read/write access)
    
    Returns:
        google.auth.credentials.Credentials: The credentials object
    """
    if scopes is None:
        scopes = ["https://www.googleapis.com/auth/devstorage.read_write"]
    
    return service_account.Credentials.from_service_account_file(
        credentials_path, scopes=scopes
    )

def create_coiled_cluster(config):
    """
    Create and configure a Coiled cluster.
    
    Args:
        config (dict): Cluster configuration parameters
    
    Returns:
        tuple: (coiled.Cluster, dask.distributed.Client)
    """
    print("Setting up Coiled cluster...")
    cluster = coiled.Cluster(
        name=config["cluster_name"],
        software=config["software_env"],
        n_workers=config["n_workers"],
        scheduler_vm_types=[config["vm_type"]],
        worker_vm_types=config["vm_type"],
        region=config["region"],
        arm=config["use_arm"],
        compute_purchase_option=config["compute_option"],
        workspace=config["workspace"],
        worker_options={
            "security": {
                "key_path": config["credentials_path"]
            }
        }
    )
    
    client = Client(cluster)
    print(f"Dask dashboard: {client.dashboard_link}")
    return cluster, client

def calculate_spi(ds, params):
    """
    Calculate Standardized Precipitation Index on the dataset.
    
    Args:
        ds (xarray.Dataset): Dataset containing precipitation data
        params (dict): SPI calculation parameters
    
    Returns:
        xarray.Dataset: Dataset containing SPI values
    """
    print("Calculating SPI...")
    
    # Extract precipitation data
    precip_data = ds[params["precip_var"]]
    precip_data.attrs['units'] = params["precip_units"]
    
    # Compute SPI using xclim
    spi = standardized_precipitation_index(
        precip_data,
        freq=params["freq"],
        window=params["window"],
        dist=params["dist"],
        method=params["method"],
        cal_start=params["cal_start"],
        cal_end=params["cal_end"],
        fitkwargs={"floc": 0}
    )
    
    # Create a proper dataset with coordinates
    spi_result = xr.Dataset(
        {params["output_var"]: spi},
        coords=ds.coords
    )
    
    # Add metadata
    spi_result[params["output_var"]].attrs.update({
        'long_name': f'Standardized Precipitation Index ({params["window"]}-month)',
        'units': 'unitless',
        'description': f'SPI calculated using {params["dist"]} distribution with {params["method"]} method'
    })
    
    return spi_result

def save_to_zarr(spi_result, output_path, storage_options, client, chunks=None):
    """
    Save the SPI result to a Zarr store.
    
    Args:
        spi_result (xarray.Dataset): SPI calculation results
        output_path (str): Path to save the Zarr store
        storage_options (dict): Storage options for cloud storage
        client (dask.distributed.Client): Dask client
        chunks (dict, optional): Chunk sizes for each dimension
    """
    print(f"Writing result to {output_path}...")
    
    # If no chunks provided, use existing chunking
    if chunks is None:
        chunks = {dim: spi_result.chunks[dim][0] for dim in spi_result.dims}
    
    # Define variable to encode
    var_name = list(spi_result.data_vars)[0]
    
    # Define encoding for compression and chunks
    encoding = {
        var_name: {
            'compressor': None,
            'dtype': 'float32',
            '_FillValue': -9999.0,
            'chunks': tuple(chunks[dim] for dim in spi_result[var_name].dims)
        }
    }
    
    # Write to storage
    with ProgressBar():
        write_job = spi_result.to_zarr(
            output_path,
            mode='w',
            encoding=encoding,
            consolidated=True,
            storage_options=storage_options,
            compute=False
        )
        
        # Execute the write task
        future = client.compute(write_job)
        
        # Wait for completion
        future.result()

def print_stats(spi_result, var_name):
    """
    Calculate and print simple statistics on the SPI result.
    
    Args:
        spi_result (xarray.Dataset): SPI calculation results
        var_name (str): Name of the SPI variable
    """
    with ProgressBar():
        spi_min = float(spi_result[var_name].min().compute())
        spi_max = float(spi_result[var_name].max().compute())
        spi_mean = float(spi_result[var_name].mean().compute())
    
    print(f"SPI stats: min={spi_min:.3f}, max={spi_max:.3f}, mean={spi_mean:.3f}")

def parse_arguments():
    """
    Parse command line arguments.
    
    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Calculate SPI from CHIRPS data using Coiled')
    parser.add_argument('--env-file', type=str, default='.env', 
                        help='Path to .env file (default: .env)')
    parser.add_argument('--region', type=str, default=None,
                        help='Region code (overrides ENV setting)')
    parser.add_argument('--output-suffix', type=str, default=None,
                        help='Optional suffix for output filename')
    return parser.parse_args()

def main():
    # Start timing
    start_time = time.time()
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Load environment variables
    load_dotenv(args.env_file)
    
    # Configuration from environment variables
    config = {
        # GCP and storage configuration
        "credentials_path": os.getenv("GCP_CREDENTIALS_PATH", "service-account.json"),
        "input_bucket": os.getenv("INPUT_BUCKET", "ittseas51"),
        "output_bucket": os.getenv("OUTPUT_BUCKET", "ittseas51"),
        "region_code": args.region or os.getenv("REGION_CODE", "ea"),
        
        # Coiled cluster configuration
        "cluster_name": os.getenv("COILED_CLUSTER_NAME", "spi-calculation"),
        "software_env": os.getenv("COILED_SOFTWARE_ENV", "itt-jupyter-env-v20250318"),
        "n_workers": int(os.getenv("COILED_N_WORKERS", "2")),
        "vm_type": os.getenv("COILED_VM_TYPE", "n2-standard-4"),
        "region": os.getenv("COILED_REGION", "us-east1"),
        "use_arm": os.getenv("COILED_USE_ARM", "false").lower() == "true",
        "compute_option": os.getenv("COILED_COMPUTE_OPTION", "spot"),
        "workspace": os.getenv("COILED_WORKSPACE", "geosfm"),
        
        # Data chunking
        "chunk_latitude": int(os.getenv("CHUNK_LATITUDE", "50")),
        "chunk_longitude": int(os.getenv("CHUNK_LONGITUDE", "50")),
        "chunk_time": int(os.getenv("CHUNK_TIME", "531")),
        
        # SPI calculation parameters
        "precip_var": os.getenv("PRECIP_VAR", "precip"),
        "precip_units": os.getenv("PRECIP_UNITS", "mm/month"),
        "window": int(os.getenv("SPI_WINDOW", "3")),
        "freq": os.getenv("SPI_FREQ", "MS"),
        "dist": os.getenv("SPI_DIST", "gamma"),
        "method": os.getenv("SPI_METHOD", "APP"),
        "cal_start": os.getenv("SPI_CAL_START", "1991-01-01"),
        "cal_end": os.getenv("SPI_CAL_END", "2018-01-01"),
        "output_var": f"spi{os.getenv('SPI_WINDOW', '3')}"
    }
    
    # Construct input and output paths
    dataset_filename = f"{config['region_code']}_chirps_v20_monthly_20250415.zarr"
    output_suffix = args.output_suffix or time.strftime("%Y%m%d")
    output_filename = f"{config['region_code']}_spi{config['window']}_output_{output_suffix}.zarr"
    
    input_path = f"gs://{config['input_bucket']}/{dataset_filename}"
    output_path = f"gs://{config['output_bucket']}/{output_filename}"
    
    # Create credentials and storage options
    credentials = load_credentials(config["credentials_path"])
    storage_options = {'token': credentials}
    
    # Set up cluster
    cluster, client = None, None
    
    try:
        # Create Coiled cluster
        cluster, client = create_coiled_cluster({
            "cluster_name": config["cluster_name"],
            "software_env": config["software_env"],
            "n_workers": config["n_workers"],
            "vm_type": config["vm_type"],
            "region": config["region"],
            "use_arm": config["use_arm"],
            "compute_option": config["compute_option"],
            "workspace": config["workspace"],
            "credentials_path": config["credentials_path"]
        })
        
        # Open dataset with custom chunks
        print(f"Opening dataset from {input_path}...")
        chunk_sizes = {
            'latitude': config["chunk_latitude"],
            'longitude': config["chunk_longitude"],
            'time': config["chunk_time"]
        }
        
        ds = xr.open_dataset(
            input_path, 
            engine='zarr', 
            chunks=chunk_sizes,
            consolidated=False,
            storage_options=storage_options
        )
        
        print("Dataset info:")
        print(ds)
        print(f"Dataset chunking: {ds.chunks}")
        
        # Calculate SPI
        spi_params = {
            "precip_var": config["precip_var"],
            "precip_units": config["precip_units"],
            "window": config["window"],
            "freq": config["freq"],
            "dist": config["dist"],
            "method": config["method"],
            "cal_start": config["cal_start"],
            "cal_end": config["cal_end"],
            "output_var": config["output_var"]
        }
        
        spi_result = calculate_spi(ds, spi_params)
        
        print("SPI result info:")
        print(spi_result)
        
        # Save results
        save_to_zarr(
            spi_result, 
            output_path, 
            storage_options, 
            client, 
            chunks=chunk_sizes
        )
        
        # Print statistics
        print_stats(spi_result, config["output_var"])
        
        total_time = time.time() - start_time
        print(f"Processing completed successfully in {total_time:.2f} seconds.")
        
    except Exception as e:
        print(f"Error during processing: {str(e)}")
        raise
        
    finally:
        # Clean up resources
        if client:
            client.close()
        if cluster:
            cluster.close()
        print("Coiled cluster closed.")

if __name__ == "__main__":
    main()
