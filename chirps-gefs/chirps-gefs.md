Implementation of CHIRPS-GEFS Bias Correction with xclim and Zarr
 
Overview
 
The CHIRPS-GEFS (Climate Hazards InfraRed Precipitation with Stations - Global Ensemble Forecast System) dataset provides bias-corrected precipitation forecasts at 0.05-degree resolution. This note summarizes the IDL-based implementation and proposes how it could be reimplemented using xclim's Statistical Downscaling and Bias-Adjustment (sdba) module with Zarr datasets.
 
Current CHIRPS-GEFS Implementation
 
The operational CHIRPS-GEFS process consists of four main IDL scripts:
 
get_gefs_op_v12_p25.pro: Retrieves GEFS forecast files from NOAA servers
Downloads 0.25° resolution data for days 1-10
Downloads 0.5° resolution data for days 11-16
mk_gefs_op_v12_dailies.pro: Creates daily precipitation accumulations
Processes GRIB files into daily totals
Centers data on longitude 0 (like CHIRPS)
Limits to 50 degrees N & S
Writes daily output files
mk_chirps_gefs_v12.pro: Creates 16-day CHIRPS-GEFS forecasts using rank-based quantile matching
Key function implementing bias correction
Resamples GEFS forecasts to match CHIRPS 0.05° resolution
Uses historical GEFS and CHIRPS data for 2000-present
disagg_to_dailies_v12.pro: Disaggregates 16-day forecasts into daily totals
Uses daily GEFS ratios to split the 16-day CHIRPS-GEFS total
Creates final daily output files
 
Key Bias Correction Method: Rank-Based Quantile Matching
 
The core of CHIRPS-GEFS is a rank-based quantile matching approach implemented in mk_chirps_gefs_v12.pro:
 
Calculate the percentile rank of current GEFS forecast relative to historical GEFS
Find the corresponding CHIRPS value at the same percentile from historical CHIRPS
Use this value as the bias-corrected forecast
 
This statistical method preserves the distribution of the reference dataset (CHIRPS) while maintaining the temporal sequencing of weather events from the GEFS forecast.
 
Implementation with xclim.sdba and Zarr
 
Using xclim.sdba
 
The xclim.sdba module provides similar bias correction methods that could replicate the CHIRPS-GEFS methodology. The most relevant class is EmpiricalQuantileMapping, which implements quantile mapping similar to the CHIRPS-GEFS approach.
 
Key functions from xclim.sdba that would be useful:
 # Training the adjustment model
QM = sdba.EmpiricalQuantileMapping.train(
    ref=chirps_historical,  # Historical CHIRPS data (reference)
    hist=gefs_historical,   # Historical GEFS reforecasts
    nquantiles=20,          # Number of quantiles
    kind="*",               # Multiplicative for precipitation
    group="time"            # Group all time periods
)

# Applying the adjustment
forecast_corrected = QM.adjust(
    forecast_raw,           # Raw GEFS forecast
    extrapolation="constant", 
    interp="nearest"
)

 
Zarr Dataset Integration
 
Using Zarr instead of the current file system approach would offer:
 
Chunking for parallel processing: Improve performance with dask integration
Cloud compatibility: Easier deployment on cloud platforms
Partial data access: Read only needed portions of large datasets
 
Implementation approach:
 import xarray as xr
import zarr
import dask
from xclim import sdba

# Access GEFS data in Zarr format
gefs_forecast = xr.open_zarr('s3://dynamically.org/gefs-zarr-data/forecast')
gefs_historical = xr.open_zarr('s3://dynamically.org/gefs-zarr-data/historical')
chirps_historical = xr.open_zarr('s3://path/to/chirps/historical')

# Spatially downscale from 0.25/0.5° to 0.05°
# Using bilinear interpolation for days 11-16
gefs_regridded = regrid_to_chirps_resolution(gefs_forecast)

# Perform rank-based quantile mapping
QM = sdba.EmpiricalQuantileMapping.train(
    chirps_historical, 
    gefs_historical,
    nquantiles=15, 
    kind="*"
)

# Apply correction
chirps_gefs = QM.adjust(gefs_regridded)

# For disaggregation to daily values
daily_ratios = calculate_daily_ratios(gefs_forecast)
chirps_gefs_daily = disaggregate_with_ratios(chirps_gefs, daily_ratios)

# Save output to Zarr
chirps_gefs_daily.to_zarr('path/to/output/zarr')

 
Adaptation Considerations
 
Key considerations for adapting the CHIRPS-GEFS process to xclim and Zarr:
 
Handling frequency adaptation: Use sdba.processing.adapt_freq to properly handle dry days in precipitation forecasts
Scaling to global data: Use dask and chunking to efficiently process the global datasetwith dask.diagnostics.ProgressBar():
    result = chirps_gefs_daily.compute()

Real-time processing workflow: Set up a pipeline to download new GEFS forecasts daily and process them automatically
Detrending considerations: Implement trend-preserving bias correction if needed, using techniques like DetrendedQuantileMapping
 
Conclusion
 
The CHIRPS-GEFS methodology can be effectively reimplemented using xclim's sdba module with Zarr datasets. This would provide a more modern, cloud-ready implementation with improved scalability and maintainability compared to the current IDL scripts. The core rank-based quantile mapping technique would remain the same, ensuring compatibility with the existing CHIRPS-GEFS product.
