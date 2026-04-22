# Climate Data Download Scripts for Kenya (2020-2023)

This folder contains scripts to download CHIRPS precipitation and ERA5 climate data for drought simulation in Kenya.

## Period
- **Start**: 2020-01-01
- **End**: 2023-12-31
- **Duration**: 48 months (1461 days)
- **Reference**: [E4DRR Drought Events](https://icpac-igad.github.io/e4drr/blog/2025-04-drought-events/)

## Region Bounds
- **West**: 34.0°
- **East**: 41.9°
- **South**: -4.7°
- **North**: 5.0°

## Scripts

### 1. Download CHIRPS Precipitation
```bash
python 01_download_chirps_kenya.py
```
- Downloads daily CHIRPS v2.0 precipitation data
- Source: https://data.chc.ucsb.edu/products/CHIRPS-2.0/
- Resolution: 0.05° (~5km)
- Output: `../data/chirps/daily/` (1461 GeoTIFF files)
- **Estimated time**: 60-90 minutes

### 2. Download ERA5 Climate Data
```bash
python 02_download_era5_kenya.py
```
- Downloads ERA5 reanalysis data (temperature, PET, pressure)
- Source: Copernicus Climate Data Store (CDS)
- Resolution: 0.25° (~25km)
- **Requires**: CDS API setup (see below)
- Output: `../data/era5/` (3 NetCDF files)
- **Estimated time**: 80-120 minutes (20-30 min per year)

### 3. Prepare Forcing File
```bash
python 03_prepare_forcing_kenya.py
```
- Combines CHIRPS and ERA5 into Wflow forcing file
- Output: `../forcing/forcing.nc`
- **Estimated time**: 15-30 minutes

## Setup

### ERA5 CDS API Setup
1. Register at: https://cds.climate.copernicus.eu/
2. Install: `pip install cdsapi`
3. Create `~/.cdsapirc`:
   ```
   url: https://cds.climate.copernicus.eu/api/v2
   key: YOUR_UID:YOUR_API_KEY
   ```

## Workflow

```bash
# Step 1: Download CHIRPS
python 01_download_chirps_kenya.py

# Step 2: Download ERA5 (requires CDS API)
python 02_download_era5_kenya.py

# Step 3: Prepare forcing file
python 03_prepare_forcing_kenya.py
```

## Output Structure

```
04_Kenya_2020_2023/
├── data/
│   ├── chirps/
│   │   ├── daily/          # 1461 GeoTIFF files
│   │   └── download_info.json
│   └── era5/
│       ├── temperature_2m_2020_2023.nc
│       ├── potential_evaporation_2020_2023.nc
│       ├── surface_pressure_2020_2023.nc
│       └── download_info.json
└── forcing/
    ├── forcing.nc          # Final Wflow forcing file
    └── forcing_info.json
```

## Notes

- CHIRPS downloads are automatic (no authentication required)
- ERA5 downloads require CDS account and API key
- Processing is done in chunks to manage memory
- All scripts include progress tracking and error handling
