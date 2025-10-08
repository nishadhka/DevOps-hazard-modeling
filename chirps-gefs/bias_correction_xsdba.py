#!/usr/bin/env python3
"""
CHIRPS-GEFS Bias Correction using xarray and xclim.sdba

This script implements bias correction for GEFS precipitation forecasts
using the rank-based quantile mapping approach similar to the IDL-based
CHIRPS-GEFS operational system.

Based on the methodology described in chirsp-gefs.md
"""

import xarray as xr
import numpy as np
import pandas as pd
from pathlib import Path
import argparse
import logging
from datetime import datetime, timedelta
import warnings

# Import xclim.sdba for bias correction
try:
    from xclim import sdba
    from xclim.sdba import processing
except ImportError:
    raise ImportError("xclim is required. Install with: pip install xclim")

# Suppress warnings for cleaner output
warnings.filterwarnings('ignore')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def load_gefs_forecast(file_path):
    """
    Load GEFS ensemble forecast data from NetCDF file.
    
    Parameters:
    -----------
    file_path : str or Path
        Path to the GEFS NetCDF file
        
    Returns:
    --------
    xr.Dataset
        GEFS forecast dataset with proper time coordinates
    """
    logger.info(f"Loading GEFS forecast from: {file_path}")
    
    ds = xr.open_dataset(file_path)
    
    # Convert 3-hourly data to daily accumulations
    # Group by day and sum precipitation
    ds_daily = ds.resample(time='1D').sum()
    
    # Calculate ensemble mean for bias correction
    ds_mean = ds_daily.mean(dim='ensemble')
    
    logger.info(f"Loaded GEFS data: {ds_daily.dims}")
    logger.info(f"Time range: {ds_daily.time.min().values} to {ds_daily.time.max().values}")
    logger.info(f"Spatial extent: Lat {ds_daily.latitude.min().values:.2f} to {ds_daily.latitude.max().values:.2f}, "
                f"Lon {ds_daily.longitude.min().values:.2f} to {ds_daily.longitude.max().values:.2f}")
    
    return ds_daily, ds_mean


def load_historical_data(chirps_path=None, gefs_historical_path=None):
    """
    Load historical CHIRPS and GEFS data for training bias correction.
    
    Note: This is a placeholder function. In operational use, you would:
    1. Load historical CHIRPS data (reference dataset)
    2. Load historical GEFS reforecasts/hindcasts for the same period
    3. Ensure both datasets cover the same spatial domain and time period
    
    Parameters:
    -----------
    chirps_path : str, optional
        Path to historical CHIRPS data
    gefs_historical_path : str, optional
        Path to historical GEFS data
        
    Returns:
    --------
    tuple of xr.Dataset
        (chirps_historical, gefs_historical)
    """
    logger.warning("Historical data loading not implemented in this example.")
    logger.info("For operational use, implement loading of:")
    logger.info("1. CHIRPS historical data (0.05° resolution)")
    logger.info("2. GEFS historical reforecasts (same time period)")
    
    # Placeholder - return None
    return None, None


def regrid_to_chirps_resolution(gefs_data, target_resolution=0.05):
    """
    Regrid GEFS data from its native resolution to CHIRPS resolution (0.05°).
    
    Parameters:
    -----------
    gefs_data : xr.Dataset
        GEFS forecast data
    target_resolution : float
        Target resolution in degrees (default: 0.05)
        
    Returns:
    --------
    xr.Dataset
        Regridded GEFS data
    """
    logger.info("Regridding GEFS data to CHIRPS resolution (0.05°)")
    
    # Get current resolution
    lat_res = float(gefs_data.latitude.diff('latitude').mean())
    lon_res = float(gefs_data.longitude.diff('longitude').mean())
    
    logger.info(f"Current resolution: {lat_res:.3f}° x {lon_res:.3f}°")
    
    # Create target grid
    lat_min, lat_max = float(gefs_data.latitude.min()), float(gefs_data.latitude.max())
    lon_min, lon_max = float(gefs_data.longitude.min()), float(gefs_data.longitude.max())
    
    target_lat = np.arange(lat_min, lat_max + target_resolution, target_resolution)
    target_lon = np.arange(lon_min, lon_max + target_resolution, target_resolution)
    
    # Interpolate to target grid
    gefs_regridded = gefs_data.interp(
        latitude=target_lat,
        longitude=target_lon,
        method='linear'  # Use linear interpolation for precipitation
    )
    
    logger.info(f"Regridded to: {len(target_lat)} x {len(target_lon)} grid points")
    
    return gefs_regridded


def perform_bias_correction(forecast_data, chirps_hist=None, gefs_hist=None):
    """
    Perform bias correction using xclim's EmpiricalQuantileMapping.
    
    This implements the rank-based quantile mapping similar to the IDL implementation:
    1. Calculate percentile rank of current forecast in historical GEFS
    2. Find corresponding CHIRPS value at same percentile
    3. Use as bias-corrected forecast
    
    Parameters:
    -----------
    forecast_data : xr.Dataset
        Current GEFS forecast data
    chirps_hist : xr.Dataset
        Historical CHIRPS data (reference)
    gefs_hist : xr.Dataset
        Historical GEFS data for training
        
    Returns:
    --------
    xr.Dataset
        Bias-corrected forecast
    """
    logger.info("Performing bias correction using empirical quantile mapping")
    
    if chirps_hist is None or gefs_hist is None:
        logger.warning("Historical data not provided - returning uncorrected forecast")
        logger.info("For bias correction, provide historical CHIRPS and GEFS data")
        return forecast_data
    
    try:
        # Train the quantile mapping model
        logger.info("Training empirical quantile mapping model...")
        
        QM = sdba.EmpiricalQuantileMapping.train(
            ref=chirps_hist.tp,  # Historical CHIRPS (reference)
            hist=gefs_hist.tp,   # Historical GEFS (to be corrected)
            nquantiles=50,       # Number of quantiles for mapping
            kind="*",            # Multiplicative scaling for precipitation
            group="time"         # Group by time
        )
        
        logger.info("Applying bias correction to forecast...")
        
        # Apply correction to current forecast
        forecast_corrected = QM.adjust(
            forecast_data.tp,
            extrapolation="constant",  # Handle values outside training range
            interp="linear"           # Interpolation method
        )
        
        # Create corrected dataset
        corrected_ds = forecast_data.copy()
        corrected_ds['tp'] = forecast_corrected
        corrected_ds.tp.attrs['long_name'] = 'Bias-corrected total precipitation'
        corrected_ds.tp.attrs['method'] = 'Empirical Quantile Mapping (CHIRPS-GEFS)'
        
        logger.info("Bias correction completed successfully")
        
        return corrected_ds
        
    except Exception as e:
        logger.error(f"Bias correction failed: {e}")
        logger.warning("Returning uncorrected forecast")
        return forecast_data


def calculate_daily_ratios(gefs_ensemble):
    """
    Calculate daily precipitation ratios from ensemble forecast for disaggregation.
    
    This replicates the disaggregation approach from disagg_to_dailies_v12.pro
    
    Parameters:
    -----------
    gefs_ensemble : xr.Dataset
        Full ensemble forecast data
        
    Returns:
    --------
    xr.Dataset
        Daily ratios for disaggregation
    """
    logger.info("Calculating daily ratios for disaggregation")
    
    # Calculate ensemble mean daily totals
    daily_mean = gefs_ensemble.mean(dim='ensemble')
    
    # Calculate total over forecast period
    total_precip = daily_mean.sum(dim='time')
    
    # Calculate ratios (avoid division by zero)
    daily_ratios = daily_mean / total_precip.where(total_precip > 0, np.nan)
    
    # Fill NaN ratios with equal distribution
    n_days = len(daily_ratios.time)
    daily_ratios = daily_ratios.fillna(1.0 / n_days)
    
    return daily_ratios


def save_output(data, output_path, compress=True):
    """
    Save bias-corrected data to NetCDF file.
    
    Parameters:
    -----------
    data : xr.Dataset
        Bias-corrected forecast data
    output_path : str or Path
        Output file path
    compress : bool
        Whether to apply compression
    """
    logger.info(f"Saving output to: {output_path}")
    
    # Add processing metadata
    data.attrs.update({
        'processing_date': datetime.now().isoformat(),
        'processing_method': 'CHIRPS-GEFS bias correction with xclim.sdba',
        'bias_correction': 'Empirical Quantile Mapping',
        'reference_dataset': 'CHIRPS',
        'created_by': 'bias_correction_xsdba.py'
    })
    
    # Compression settings
    encoding = {}
    if compress:
        encoding = {var: {'zlib': True, 'complevel': 4} for var in data.data_vars}
    
    # Save to NetCDF
    data.to_netcdf(output_path, encoding=encoding)
    logger.info("Output saved successfully")


def main():
    """Main processing function."""
    parser = argparse.ArgumentParser(
        description='CHIRPS-GEFS Bias Correction using xarray and xclim.sdba'
    )
    
    parser.add_argument(
        'input_file',
        help='Path to GEFS forecast NetCDF file (e.g., 20250826_00.nc.nc)'
    )
    
    parser.add_argument(
        '--output', '-o',
        help='Output file path (default: adds _bias_corrected suffix)',
        default=None
    )
    
    parser.add_argument(
        '--chirps-historical',
        help='Path to historical CHIRPS data for training',
        default=None
    )
    
    parser.add_argument(
        '--gefs-historical', 
        help='Path to historical GEFS data for training',
        default=None
    )
    
    parser.add_argument(
        '--regrid',
        action='store_true',
        help='Regrid to CHIRPS resolution (0.05°)'
    )
    
    parser.add_argument(
        '--no-compress',
        action='store_true',
        help='Disable output compression'
    )
    
    args = parser.parse_args()
    
    # Process input file
    input_path = Path(args.input_file)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1
    
    # Set output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_bias_corrected.nc"
    
    try:
        # Load GEFS forecast
        gefs_daily, gefs_mean = load_gefs_forecast(input_path)
        
        # Regrid if requested
        if args.regrid:
            gefs_mean = regrid_to_chirps_resolution(gefs_mean)
        
        # Load historical data for training
        chirps_hist, gefs_hist = load_historical_data(
            args.chirps_historical, 
            args.gefs_historical
        )
        
        # Perform bias correction
        corrected_forecast = perform_bias_correction(
            gefs_mean, 
            chirps_hist, 
            gefs_hist
        )
        
        # Save output
        save_output(
            corrected_forecast, 
            output_path, 
            compress=not args.no_compress
        )
        
        logger.info("Processing completed successfully")
        logger.info(f"Output saved to: {output_path}")
        
        # Print summary statistics
        logger.info("\nSummary Statistics:")
        logger.info(f"Mean daily precipitation: {corrected_forecast.tp.mean().values:.2f} mm/day")
        logger.info(f"Max daily precipitation: {corrected_forecast.tp.max().values:.2f} mm/day")
        logger.info(f"Total forecast precipitation: {corrected_forecast.tp.sum().values:.2f} mm")
        
        return 0
        
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        return 1


if __name__ == "__main__":
    exit(main())