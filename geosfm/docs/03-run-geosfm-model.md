# Guide to Running the GeoSFM Forecast Model for East Africa

## Introduction

This guide provides detailed instructions for running the Geospatial Stream Flow Model (GeoSFM) customized for the East Africa region. The model divides East Africa into 6 zones, with each zone configured independently.

## Prerequisites

Before running the model, ensure you have:

1. A Windows Server with GeoSFM model files installed
   - See [Windows VM in GCP Deployment and Access Guide](gcp-windows-vm.md) for creating a VM
   - See [Windows Server Setup for GeoSFM Forecasting](get-ready-win-vm-geofsm-run.md) for installing required software
2. Input data files for each zone:
   - `rain.txt`: IMERG dataset averaged at subcatchment level, with GEFS CHRUPs data for 15-day forecasts
   - `evap.txt`: PET NASA satellite imagery averages with duplicated last 15 days of data for forecasting

## Configuration Steps

### 1. Prepare Data Files

For each of the 6 zones, ensure that you have updated the following files:
- `rain.txt`: Contains historical precipitation data plus 15-day GEFS CHRUPs forecast data
- `evap.txt`: Contains historical PET data with the last 15 days duplicated for the forecast period

### 2. Edit Parameter Files

For each zone, you need to edit two parameter files:

#### a. Edit routparam.txt

```
4889    # Number of days in simulation
2011    # Start year
1       # Start day
86      # Number of subcatchments
24      # Simulation timesteps (hours)
0       # Simulation (0) / Calibration (1) mode
3       # Number of no-rain forecast days
0       # Reservoir parameter
0       # Additional parameter
0       # Additional parameter
```

#### b. Edit balparam.txt

```
4       # Number of days surface runoff takes to reach the river
4889    # Number of days in simulation
2011    # Start year
1       # Start day
86      # Number of subcatchments
24      # Simulation timestep (hours)
1       # Calibration (0) / Simulation (1) mode
0       # Additional parameter
0.1     # Initial soil moisture (10%)
0       # Additional parameter
```

### 3. Update Path Files

For each zone, update the path information in the following files. After unzipping the GeoSFM files from Google Drive, the paths will need to be updated to match your local environment.

#### a. Edit balfiles.txt

Replace the paths with the correct location of the unzipped files. For example, if the files are in `C:\Users\nkalladath\Downloads\geosfm_zones\zone1\`, use:

```
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\rain.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\evap.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\basin.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\response.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\balparam.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\basinrunoffyield.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\soilwater.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\actualevap.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\gwloss.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\cswater.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\excessflow.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\interflow.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\baseflow.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\massbalance.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\logfilesoil.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\initial.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\
```

For each zone (zone1 to zone6), update the path accordingly.

#### b. Edit routfiles.txt

Similarly, update the paths in routfiles.txt for each zone:

```
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\routparam.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\river.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\initial.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\basinrunoffyield.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\damlink.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\forecast.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\rating.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\streamflow.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\localflow.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\riverdepth.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\inflow.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\logfileflow.txt
C:\Users\nkalladath\Downloads\geosfm_zones\zone1\
```

**Note:** Pay attention to the capitalization in the paths if your original files use mixed capitalization. The example above uses lowercase "zone1" but adjust as needed based on your extracted file structure.

## Running the Model

### 1. For Each Zone:

1. Ensure all input files are prepared
2. Verify parameter files are correctly updated
3. Check that all path files point to the correct locations
4. Execute the model using the provided executable

### 2. Run Process:

For each zone (1-6), follow these steps:
1. Navigate to the zone directory (e.g., C:\Users\nkalladath\Downloads\geosfm_zones\zone1\)
2. Locate and run the executable file `dllcaller22.exe`
   - This executable is available inside each zone folder
   - It will automatically handle both the soil water balance and river routing calculations
3. Wait for the execution to complete - this may take a few minutes depending on the system performance

### 3. Model Output

After successful execution, the model will generate the following key output files:
- `basinrunoffyield.txt`: Contains runoff from each subcatchment
- `streamflow.txt`: Contains streamflow at each river reach (critical for downstream visualization)
- `riverdepth.txt`: Contains river depth information (critical for flood forecasting)
- `forecast.txt`: Contains the 15-day forecast streamflow data
- `soilwater.txt`: Contains soil moisture information
- `actualevap.txt`: Contains actual evapotranspiration

The `streamflow.txt` and `riverdepth.txt` files are particularly important as they are used for downstream visualization and flood forecasting applications.

## Troubleshooting

- Verify that `rain.txt` and `evap.txt` contain data for the correct time period
- Check for consistent number of subcatchments across all configuration files
- Ensure paths in the balfiles.txt and routfiles.txt are correct
- Check logfilesoil.txt and logfileflow.txt for any error messages

## Running the Forecast

When running the forecast:
1. Ensure that GEFS CHRUPs data is appended to the rain.txt file for the next 15 days
2. Use duplicated PET data for the last 15 days in the evap.txt file
3. Set the number of simulation days (4889) to include both historical and forecast periods
4. In routparam.txt, ensure the "Number of no-rain forecast days" parameter is set correctly (default: 3)

## Conclusion

By following these steps, you can successfully run the GeoSFM forecast model for all 6 zones in the East Africa region. The model will generate streamflow forecasts for the next 15 days based on historical data and GEFS CHRUPs forecast data.
