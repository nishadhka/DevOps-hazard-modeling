#!/usr/bin/env python3
"""
Memory-Optimized Complete workflow v5: Tiled Regridding for Large Scale Processing
Features:
- 10-degree tiled regridding to handle memory constraints with 1km resolution
- Download → Plot → Tile-based regridding → Concatenate → Icechunk
- Cartopy-based plotting for visualization and verification
- Test mode using existing 20250722 data with 10km resolution
- Progressive tile processing with memory cleanup

Usage:
  python create_regridded_icechunk_memory_optimized_v5.py                        # Download + full workflow
  python create_regridded_icechunk_memory_optimized_v5.py --skip-download        # Skip download
  python create_regridded_icechunk_memory_optimized_v5.py --test-mode            # Test with existing data
  python create_regridded_icechunk_memory_optimized_v5.py --test-mode --plot-only # Test plotting only
"""

import sys
import os
import time
import shutil
import gc
from datetime import datetime
from pathlib import Path
import math

# Add current directory to path
sys.path.append('/home/runner/workspace')

import numpy as np
import xarray as xr
import icechunk
import rioxarray
import xesmf as xe
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter

# Import download functions
from download_pet_imerg_chirpsgefs import (download_pet_data,
                                           download_imerg_data,
                                           download_chirps_gefs_data)


def setup_config(target_date,
                 lat_bounds=(-12.0, 24.2),
                 lon_bounds=(22.9, 51.6),
                 resolution=0.01,
                 tile_size=10.0,
                 test_mode=False):
    """Setup configuration for tiled processing"""
    config = {
        'TARGET_DATE': target_date,
        'LAT_BOUNDS': lat_bounds,
        'LON_BOUNDS': lon_bounds,
        'TARGET_RESOLUTION': resolution,
        'TILE_SIZE': tile_size,  # degrees
        'TEST_MODE': test_mode,
        'OUTPUT_DIR': f"./{target_date.strftime('%Y%m%d')}",
        'ICECHUNK_PATH': f"./east_africa_regridded_{target_date.strftime('%Y%m%d')}.zarr",
        'WEIGHTS_DIR': "./regridder_weights_tiled",
        'PLOTS_DIR': f"./plots_{target_date.strftime('%Y%m%d')}",
        'TILES_DIR': f"./tiles_{target_date.strftime('%Y%m%d')}"
    }

    # Create directories
    for dir_key in ['WEIGHTS_DIR', 'PLOTS_DIR', 'TILES_DIR']:
        os.makedirs(config[dir_key], exist_ok=True)

    # Update the download script configuration if not in test mode
    if not test_mode:
        import download_pet_imerg_chirpsgefs
        download_pet_imerg_chirpsgefs.TARGET_DATE = target_date
        download_pet_imerg_chirpsgefs.LAT_BOUNDS = lat_bounds
        download_pet_imerg_chirpsgefs.LON_BOUNDS = lon_bounds
        download_pet_imerg_chirpsgefs.OUTPUT_DIR = config['OUTPUT_DIR']

    return config


def create_tile_bounds(lat_bounds, lon_bounds, tile_size):
    """Create list of tile bounds for processing"""
    lat_min, lat_max = lat_bounds
    lon_min, lon_max = lon_bounds

    # Calculate number of tiles needed
    lat_tiles = math.ceil((lat_max - lat_min) / tile_size)
    lon_tiles = math.ceil((lon_max - lon_min) / tile_size)

    tiles = []

    for i in range(lat_tiles):
        for j in range(lon_tiles):
            tile_lat_min = lat_min + i * tile_size
            tile_lat_max = min(lat_min + (i + 1) * tile_size, lat_max)
            tile_lon_min = lon_min + j * tile_size
            tile_lon_max = min(lon_min + (j + 1) * tile_size, lon_max)

            tiles.append({
                'id': f"tile_{i:02d}_{j:02d}",
                'lat_bounds': (tile_lat_min, tile_lat_max),
                'lon_bounds': (tile_lon_min, tile_lon_max),
                'i': i, 'j': j
            })

    print(f"🧩 Created {len(tiles)} tiles ({lat_tiles}x{lon_tiles}) of {tile_size}° each")
    return tiles


def plot_data_with_cartopy(data, title, output_path, bounds=None, vmin=None, vmax=None):
    """Plot data using cartopy with East Africa focus"""
    plt.figure(figsize=(12, 10))

    # Create map projection
    ax = plt.axes(projection=ccrs.PlateCarree())

    # Set extent for East Africa
    if bounds:
        ax.set_extent([bounds[2], bounds[3], bounds[0], bounds[1]], crs=ccrs.PlateCarree())
    else:
        ax.set_extent([22, 52, -12, 25], crs=ccrs.PlateCarree())

    # Add map features
    ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
    ax.add_feature(cfeature.BORDERS, linewidth=0.5)
    ax.add_feature(cfeature.OCEAN, color='lightblue', alpha=0.5)
    ax.add_feature(cfeature.LAND, color='lightgray', alpha=0.3)

    # Add gridlines
    gl = ax.gridlines(draw_labels=True, linewidth=0.5, alpha=0.5)
    gl.top_labels = False
    gl.right_labels = False
    gl.xformatter = LongitudeFormatter()
    gl.yformatter = LatitudeFormatter()

    # Plot data
    if isinstance(data, xr.DataArray):
        # Handle time dimension if present
        if 'time' in data.dims:
            data_to_plot = data.isel(time=0)  # Plot first time step
        else:
            data_to_plot = data

        im = data_to_plot.plot(ax=ax, transform=ccrs.PlateCarree(),
                              add_colorbar=False, vmin=vmin, vmax=vmax)

        # Add colorbar
        cbar = plt.colorbar(im, ax=ax, orientation='vertical',
                           shrink=0.8, aspect=20)
        if hasattr(data, 'units'):
            cbar.set_label(f"{data.long_name} ({data.units})")
        else:
            cbar.set_label(title)

    plt.title(title, fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"   📊 Plot saved: {output_path}")


def create_target_grid_for_tile(tile_bounds, resolution):
    """Create target grid for a specific tile"""
    lat_min, lat_max = tile_bounds['lat_bounds']
    lon_min, lon_max = tile_bounds['lon_bounds']

    lat_points = int((lat_max - lat_min) / resolution) + 1
    lon_points = int((lon_max - lon_min) / resolution) + 1

    lat = np.linspace(lat_min, lat_max, lat_points)
    lon = np.linspace(lon_min, lon_max, lon_points)

    target_grid = xr.Dataset({
        'lat': (['lat'], lat),
        'lon': (['lon'], lon),
    })

    return target_grid


def subset_to_tile_robust(ds, tile_bounds, buffer_deg=1.0):
    """Subset dataset to tile with buffer"""
    lat_min, lat_max = tile_bounds['lat_bounds']
    lon_min, lon_max = tile_bounds['lon_bounds']

    # Add buffer
    lat_min_buf = lat_min - buffer_deg
    lat_max_buf = lat_max + buffer_deg
    lon_min_buf = lon_min - buffer_deg
    lon_max_buf = lon_max + buffer_deg

    try:
        # Get coordinate information
        lat_coord = ds.lat
        lon_coord = ds.lon

        # Check coordinate order and fix if needed
        if lat_coord[0] > lat_coord[-1]:
            ds = ds.isel(lat=slice(None, None, -1))
            lat_coord = ds.lat

        # Ensure longitude is in correct range
        if float(lon_coord.max()) > 180:
            ds = ds.assign_coords(lon=(ds.lon + 180) % 360 - 180)
            ds = ds.sortby('lon')
            lon_coord = ds.lon

        # Find indices for subsetting
        lat_mask = (lat_coord >= lat_min_buf) & (lat_coord <= lat_max_buf)
        lon_mask = (lon_coord >= lon_min_buf) & (lon_coord <= lon_max_buf)

        lat_indices = np.where(lat_mask)[0]
        lon_indices = np.where(lon_mask)[0]

        if len(lat_indices) == 0 or len(lon_indices) == 0:
            return None  # No data in this tile

        # Apply subsetting
        lat_start, lat_end = lat_indices[0], lat_indices[-1] + 1
        lon_start, lon_end = lon_indices[0], lon_indices[-1] + 1

        ds_subset = ds.isel(lat=slice(lat_start, lat_end),
                           lon=slice(lon_start, lon_end))

        return ds_subset

    except Exception as e:
        print(f"      ⚠ Tile subset failed: {e}")
        return None


def download_all_data(config):
    """Download all three data sources"""
    print("📥 Downloading climate data...")
    
    try:
        # Download PET data
        print("   🌡 Downloading PET data...")
        pet_success = download_pet_data()
        
        # Download IMERG data  
        print("   🛰 Downloading IMERG data...")
        imerg_success = download_imerg_data()
        
        # Download CHIRPS-GEFS data
        print("   🌧 Downloading CHIRPS-GEFS data...")
        chirps_success = download_chirps_gefs_data()
        
        results = {
            'pet': pet_success,
            'imerg': imerg_success, 
            'chirps': chirps_success
        }
        
        total_success = sum([pet_success, imerg_success, chirps_success])
        print(f"   ✅ Download complete: {total_success}/3 sources successful")
        
        return results
        
    except Exception as e:
        print(f"   ❌ Download failed: {e}")
        return {'pet': False, 'imerg': False, 'chirps': False}


def load_and_plot_original_data(config):
    """Load and plot original downloaded data for visualization"""
    print("📊 Loading and plotting original data...")

    plots_created = []

    # Plot PET data
    try:
        if config['TEST_MODE']:
            pet_dir = os.path.join(config['OUTPUT_DIR'], 'pet_data')
        else:
            pet_dir = os.path.join(config['OUTPUT_DIR'], 'pet_data')

        bil_files = list(Path(pet_dir).glob('*.bil'))
        if bil_files:
            print("   🌡 Plotting PET data...")

            # Load PET file (simplified version for plotting)
            bil_file = bil_files[0]
            with open(bil_file, 'rb') as f:
                data = np.frombuffer(f.read(), dtype=np.float32)

            # Determine dimensions (simplified)
            file_size = len(data)
            if file_size == 181 * 360:
                height, width = 181, 360
            elif file_size == 361 * 720:
                height, width = 361, 720
            elif file_size == 721 * 1440:
                height, width = 721, 1440
            else:
                height = int(np.sqrt(file_size))
                width = file_size // height

            data = data.reshape(height, width)
            data = np.where(data < -9000, np.nan, data)

            # Create coordinates
            lat_step = 180.0 / height
            lon_step = 360.0 / width
            lat = np.linspace(90 - lat_step / 2, -90 + lat_step / 2, height)
            lon = np.linspace(-180 + lon_step / 2, 180 - lon_step / 2, width)

            pet_da = xr.DataArray(data, coords=[lat, lon], dims=['lat', 'lon'])
            pet_da.attrs = {'long_name': 'Potential Evapotranspiration', 'units': 'mm/day'}

            # Subset to East Africa for plotting
            pet_ea = pet_da.sel(lat=slice(25, -12), lon=slice(22, 52))

            plot_path = os.path.join(config['PLOTS_DIR'], 'original_pet_data.png')
            plot_data_with_cartopy(pet_ea, 'Original PET Data', plot_path,
                                 bounds=config['LAT_BOUNDS'] + config['LON_BOUNDS'])
            plots_created.append(plot_path)
    except Exception as e:
        print(f"   ⚠ PET plotting failed: {e}")

    # Plot IMERG data
    try:
        if config['TEST_MODE']:
            imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
        else:
            imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')

        tiff_files = list(Path(imerg_dir).glob('*.tif'))
        if tiff_files:
            print("   🛰 Plotting IMERG data...")

            tiff_file = tiff_files[0]
            ds = rioxarray.open_rasterio(tiff_file)
            ds = ds.squeeze('band').drop('band')

            if 'x' in ds.dims:
                ds = ds.rename({'x': 'lon', 'y': 'lat'})

            ds.attrs = {'long_name': 'Precipitation Rate', 'units': 'mm/day'}

            plot_path = os.path.join(config['PLOTS_DIR'], 'original_imerg_data.png')
            plot_data_with_cartopy(ds, 'Original IMERG Data', plot_path,
                                 bounds=config['LAT_BOUNDS'] + config['LON_BOUNDS'])
            plots_created.append(plot_path)
    except Exception as e:
        print(f"   ⚠ IMERG plotting failed: {e}")

    # Plot CHIRPS data
    try:
        if config['TEST_MODE']:
            chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')
        else:
            chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')

        nc_files = list(Path(chirps_dir).glob('*.nc'))
        if nc_files:
            print("   🌧 Plotting CHIRPS-GEFS data...")

            nc_file = nc_files[0]
            ds = xr.open_dataset(nc_file)

            # Rename coordinates if needed
            if 'y' in ds.dims and 'lat' not in ds.dims:
                ds = ds.rename({'y': 'lat', 'x': 'lon'})

            # Find precipitation variable
            precip_vars = [var for var in ds.data_vars if 'precip' in var.lower()]
            if precip_vars:
                precip_var = precip_vars[0]
                ds[precip_var].attrs = {'long_name': 'Precipitation Forecast', 'units': 'mm/day'}

                plot_path = os.path.join(config['PLOTS_DIR'], 'original_chirps_data.png')
                plot_data_with_cartopy(ds[precip_var], 'Original CHIRPS-GEFS Data', plot_path,
                                     bounds=config['LAT_BOUNDS'] + config['LON_BOUNDS'])
                plots_created.append(plot_path)
    except Exception as e:
        print(f"   ⚠ CHIRPS plotting failed: {e}")

    print(f"   ✅ Created {len(plots_created)} original data plots")
    return plots_created


def process_tile_regridding(config, tile, source_data, target_resolution, data_type):
    """Process regridding for a single tile"""
    print(f"   🧩 Processing {tile['id']} for {data_type}...")

    # Subset data to tile
    tile_data = subset_to_tile_robust(source_data, tile, buffer_deg=1.0)
    if tile_data is None:
        print(f"      ⚠ No data in tile {tile['id']}")
        return None

    # Create target grid for tile
    target_grid = create_target_grid_for_tile(tile, target_resolution)

    # Create regridder
    try:
        regridder = xe.Regridder(tile_data, target_grid, 'bilinear')

        # Apply regridding
        regridded_tile = regridder(tile_data)

        # Clean up
        del regridder, tile_data
        gc.collect()

        # Save tile
        tile_path = os.path.join(config['TILES_DIR'], f"{data_type}_{tile['id']}.zarr")
        regridded_tile.to_zarr(tile_path, mode='w')

        print(f"      ✅ Tile {tile['id']} processed and saved")
        return tile_path

    except Exception as e:
        print(f"      ❌ Tile {tile['id']} processing failed: {e}")
        return None


def load_and_regrid_pet_tiled(config, tiles):
    """Process PET data using tiled approach"""
    print("🌡 Processing PET data with tiled regridding...")

    if config['TEST_MODE']:
        pet_dir = os.path.join(config['OUTPUT_DIR'], 'pet_data')
    else:
        pet_dir = os.path.join(config['OUTPUT_DIR'], 'pet_data')

    bil_files = list(Path(pet_dir).glob('*.bil'))
    if not bil_files:
        print("   ❌ No PET files found")
        return []

    try:
        # Load global PET data (same as v4)
        bil_file = bil_files[0]
        with open(bil_file, 'rb') as f:
            data = np.frombuffer(f.read(), dtype=np.float32)

        file_size = len(data)
        possible_dims = [(181, 360), (361, 720), (721, 1440), (1801, 3600), (181, 180)]

        height, width = None, None
        for h, w in possible_dims:
            if h * w == file_size:
                height, width = h, w
                break

        if height is None:
            # Try to infer dimensions from square root
            sqrt_size = int(np.sqrt(file_size))
            if sqrt_size * sqrt_size == file_size:
                height, width = sqrt_size, sqrt_size
            elif sqrt_size * (sqrt_size + 1) == file_size:
                height, width = sqrt_size, sqrt_size + 1
            elif (sqrt_size + 1) * sqrt_size == file_size:
                height, width = sqrt_size + 1, sqrt_size
            else:
                # Try common ratios
                for ratio in [2, 1.5, 0.5]:
                    w = int(sqrt_size * ratio)
                    h = file_size // w
                    if h * w == file_size:
                        height, width = h, w
                        break
        
        if height is None:
            print(f"   ❌ Cannot determine PET dimensions for size {file_size}")
            return []

        data = data.reshape(height, width)
        data = np.where(data < -9000, np.nan, data)

        # Create coordinates
        lat_step = 180.0 / height
        lon_step = 360.0 / width
        lat_global = np.linspace(90 - lat_step / 2, -90 + lat_step / 2, height)
        lon_global = np.linspace(-180 + lon_step / 2, 180 - lon_step / 2, width)

        pet_ds_global = xr.Dataset({'pet': (['lat', 'lon'], data)},
                                  coords={'lat': lat_global, 'lon': lon_global})

        pet_ds_global.pet.attrs = {
            'long_name': 'potential_evapotranspiration',
            'units': 'mm/day',
            'source': 'USGS FEWS NET'
        }

        # Process each tile
        tile_paths = []
        for tile in tiles:
            tile_path = process_tile_regridding(config, tile, pet_ds_global,
                                              config['TARGET_RESOLUTION'], 'pet')
            if tile_path:
                tile_paths.append(tile_path)

        # Clean up global data
        del pet_ds_global, data
        gc.collect()

        return tile_paths

    except Exception as e:
        print(f"   ❌ PET tiled processing failed: {e}")
        return []


def load_and_regrid_imerg_tiled(config, tiles):
    """Process IMERG data using tiled approach"""
    print("🛰 Processing IMERG data with tiled regridding...")

    if config['TEST_MODE']:
        imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')
    else:
        imerg_dir = os.path.join(config['OUTPUT_DIR'], 'imerg_data')

    tiff_files = list(Path(imerg_dir).glob('*.tif'))
    if not tiff_files:
        print("   ❌ No IMERG files found")
        return []

    try:
        # Load and combine IMERG files
        datasets = []
        for tiff_file in sorted(tiff_files)[:3]:  # Limit for memory
            ds = rioxarray.open_rasterio(tiff_file)
            ds = ds.squeeze('band').drop('band')

            if 'x' in ds.dims:
                ds = ds.rename({'x': 'lon', 'y': 'lat'})

            # Add time dimension
            filename = os.path.basename(tiff_file)
            try:
                date_str = filename.split('.')[3][:8]
                file_date = datetime.strptime(date_str, '%Y%m%d')
            except:
                file_date = datetime.fromtimestamp(os.path.getmtime(tiff_file))

            ds = ds.expand_dims('time')
            ds = ds.assign_coords(time=[file_date])
            datasets.append(ds)

        # Combine datasets
        imerg_combined = xr.concat(datasets, dim='time')

        # Rename to precipitation
        if hasattr(imerg_combined, 'data_vars') and len(imerg_combined.data_vars) > 0:
            data_var = list(imerg_combined.data_vars)[0]
            imerg_combined = imerg_combined.rename({data_var: 'precipitation'})
        else:
            imerg_combined.name = 'precipitation'
            imerg_combined = imerg_combined.to_dataset()

        imerg_combined.precipitation.attrs = {
            'long_name': 'precipitation_rate',
            'units': 'mm/day',
            'source': 'NASA IMERG'
        }

        # Process each tile
        tile_paths = []
        for tile in tiles:
            tile_path = process_tile_regridding(config, tile, imerg_combined,
                                              config['TARGET_RESOLUTION'], 'imerg')
            if tile_path:
                tile_paths.append(tile_path)

        # Clean up
        del imerg_combined, datasets
        gc.collect()

        return tile_paths

    except Exception as e:
        print(f"   ❌ IMERG tiled processing failed: {e}")
        return []


def load_and_regrid_chirps_tiled(config, tiles):
    """Process CHIRPS-GEFS data using tiled approach"""
    print("🌧 Processing CHIRPS-GEFS data with tiled regridding...")

    if config['TEST_MODE']:
        chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')
    else:
        chirps_dir = os.path.join(config['OUTPUT_DIR'], 'chirps_gefs_data')

    nc_files = list(Path(chirps_dir).glob('*.nc'))
    if not nc_files:
        print("   ❌ No CHIRPS-GEFS files found")
        return []

    try:
        nc_file = nc_files[0]
        chirps_ds = xr.open_dataset(nc_file)

        # Standardize coordinates
        if 'y' in chirps_ds.dims and 'lat' not in chirps_ds.dims:
            chirps_ds = chirps_ds.rename({'y': 'lat', 'x': 'lon'})

        # Find precipitation variable
        precip_vars = [var for var in chirps_ds.data_vars if 'precip' in var.lower()]
        if precip_vars:
            chirps_ds = chirps_ds.rename({precip_vars[0]: 'precipitation'})

        chirps_ds.precipitation.attrs = {
            'long_name': 'precipitation_forecast',
            'units': 'mm/day',
            'source': 'CHIRPS-GEFS'
        }

        # Process each tile
        tile_paths = []
        for tile in tiles:
            tile_path = process_tile_regridding(config, tile, chirps_ds,
                                              config['TARGET_RESOLUTION'], 'chirps')
            if tile_path:
                tile_paths.append(tile_path)

        # Clean up
        del chirps_ds
        gc.collect()

        return tile_paths

    except Exception as e:
        print(f"   ❌ CHIRPS-GEFS tiled processing failed: {e}")
        return []


def concatenate_tiles_to_icechunk(config, pet_tiles, imerg_tiles, chirps_tiles):
    """Concatenate all tiles into final icechunk dataset"""
    print("🔗 Concatenating tiles into icechunk dataset...")

    if os.path.exists(config['ICECHUNK_PATH']):
        shutil.rmtree(config['ICECHUNK_PATH'])

    try:
        # Create icechunk store
        storage = icechunk.local_filesystem_storage(config['ICECHUNK_PATH'])
        repo = icechunk.Repository.create(storage)
        session = repo.writable_session("main")
        store = session.store

        # Initialize store with a simple structure first
        initialized = False
        
        # Process each data type
        for data_type, tile_list in [('pet', pet_tiles), ('imerg', imerg_tiles), ('chirps', chirps_tiles)]:
            if not tile_list:
                continue

            print(f"   📋 Concatenating {data_type} tiles...")

            # Load all tiles for this data type
            tile_datasets = []
            for tile_path in tile_list:
                try:
                    tile_ds = xr.open_zarr(tile_path)
                    tile_datasets.append(tile_ds)
                except Exception as e:
                    print(f"      ⚠ Failed to load tile {tile_path}: {e}")

            if not tile_datasets:
                continue

            # Concatenate tiles spatially
            # Sort by lat/lon bounds and concatenate
            combined_ds = xr.combine_by_coords(tile_datasets, combine_attrs='drop_conflicts')
            
            # Rename variables to avoid conflicts and be more descriptive
            if data_type == 'pet':
                # PET typically has no time dimension
                var_names = list(combined_ds.data_vars)
                if var_names:
                    combined_ds = combined_ds.rename({var_names[0]: f'{data_type}_data'})
            else:
                # For IMERG and CHIRPS, rename variables with data type prefix
                var_names = list(combined_ds.data_vars)
                if var_names:
                    var_mappings = {}
                    for var in var_names:
                        var_mappings[var] = f'{data_type}_{var}'
                    combined_ds = combined_ds.rename(var_mappings)
                
                # Also rename time dimension to be unique
                if 'time' in combined_ds.dims:
                    combined_ds = combined_ds.rename({'time': f'{data_type}_time'})

            # Write to icechunk
            if not initialized:
                combined_ds.to_zarr(store, mode='w', consolidated=False)
                initialized = True
            else:
                # For subsequent datasets, ensure compatibility
                combined_ds.to_zarr(store, mode='a', consolidated=False)

            # Clean up
            del combined_ds, tile_datasets
            gc.collect()

        # Commit the session
        session.commit(f"Tiled regridded East Africa data for {config['TARGET_DATE'].strftime('%Y-%m-%d')}")

        # Calculate size
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(config['ICECHUNK_PATH']):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                total_size += os.path.getsize(filepath)

        size_mb = total_size / (1024 * 1024)
        size_gb = total_size / (1024 * 1024 * 1024)

        print(f"   ✅ Icechunk created: {config['ICECHUNK_PATH']}")
        print(f"   💾 Size: {size_mb:.2f} MB ({size_gb:.3f} GB)")

        return True, total_size

    except Exception as e:
        print(f"   ❌ Tile concatenation failed: {e}")
        import traceback
        traceback.print_exc()
        return False, 0


def plot_sample_from_icechunk(config, num_samples=3):
    """Plot sample time steps from final icechunk store"""
    print("📊 Creating sample plots from icechunk dataset...")

    try:
        # Open icechunk dataset using icechunk library
        storage = icechunk.local_filesystem_storage(config['ICECHUNK_PATH'])
        repo = icechunk.Repository.open_existing(storage)
        session = repo.readonly_session("main")
        store = session.store
        
        ds = xr.open_zarr(store, consolidated=False)

        # Get available variables and time steps
        variables = list(ds.data_vars)
        time_steps = ds.time.values if 'time' in ds.dims else [None]

        print(f"   📋 Available variables: {variables}")
        print(f"   ⏰ Time steps: {len(time_steps)}")

        plots_created = []

        # Sample a few time steps
        sample_indices = np.linspace(0, len(time_steps)-1, min(num_samples, len(time_steps)), dtype=int)

        for var in variables:
            for i, time_idx in enumerate(sample_indices):
                try:
                    if len(time_steps) > 1:
                        data_slice = ds[var].isel(time=time_idx)
                        time_str = str(time_steps[time_idx])[:10]
                        title = f"Final {var} - {time_str}"
                        filename = f"final_{var}_time_{i:02d}.png"
                    else:
                        data_slice = ds[var]
                        title = f"Final {var}"
                        filename = f"final_{var}.png"

                    plot_path = os.path.join(config['PLOTS_DIR'], filename)
                    plot_data_with_cartopy(data_slice, title, plot_path,
                                         bounds=config['LAT_BOUNDS'] + config['LON_BOUNDS'])
                    plots_created.append(plot_path)

                except Exception as e:
                    print(f"      ⚠ Failed to plot {var} at time {i}: {e}")

        print(f"   ✅ Created {len(plots_created)} final dataset plots")
        return plots_created

    except Exception as e:
        print(f"   ❌ Final plotting failed: {e}")
        return []


def main(target_date,
         lat_bounds=(-12.0, 24.2),
         lon_bounds=(22.9, 51.6),
         resolution=0.01,
         tile_size=10.0,
         skip_download=False,
         test_mode=False,
         plot_only=False):
    """Tiled regridding workflow v5"""

    # Setup
    config = setup_config(target_date, lat_bounds, lon_bounds, resolution, tile_size, test_mode)

    print("🚀 TILED Climate Data Workflow v5")
    print("=" * 80)
    print(f"Date: {target_date.strftime('%Y-%m-%d')}")
    print(f"Region: {lat_bounds[0]}° to {lat_bounds[1]}°N, {lon_bounds[0]}° to {lon_bounds[1]}°E")
    print(f"Resolution: {resolution}°")
    print(f"Tile size: {tile_size}°")
    print(f"Test mode: {test_mode}")
    print(f"Strategy: Download → Plot → Tile Regrid → Concatenate → Plot")
    print("=" * 80)

    start_time = time.time()

    # Step 1: Download (if not skipped or test mode)
    if test_mode or skip_download:
        print("\n📥 STEP 1: Using existing data")
        if test_mode:
            print("   🧪 Test mode: Using 20250722 folder data")
            config['OUTPUT_DIR'] = "./20250722"
    else:
        print("\n📥 STEP 1: Data Download")
        download_results = download_all_data(config)

    # Step 2: Plot original data
    print("\n📊 STEP 2: Plot Original Data")
    original_plots = load_and_plot_original_data(config)

    if plot_only:
        print("   🎯 Plot-only mode complete")
        return True, 0

    # Step 3: Create tiles and process
    print("\n🧩 STEP 3: Tiled Regridding")

    # Create tile bounds
    tiles = create_tile_bounds(lat_bounds, lon_bounds, tile_size)

    # Process each data type with tiles
    pet_tiles = load_and_regrid_pet_tiled(config, tiles)
    imerg_tiles = load_and_regrid_imerg_tiled(config, tiles)
    chirps_tiles = load_and_regrid_chirps_tiled(config, tiles)

    # Step 4: Concatenate tiles
    print("\n🔗 STEP 4: Concatenate Tiles")
    success, dataset_size = concatenate_tiles_to_icechunk(config, pet_tiles, imerg_tiles, chirps_tiles)

    # Step 5: Plot final results
    print("\n📊 STEP 5: Plot Final Results")
    final_plots = plot_sample_from_icechunk(config)

    total_time = time.time() - start_time

    # Summary
    print("\n" + "=" * 80)
    print("🎉 TILED WORKFLOW v5 COMPLETE")
    print("=" * 80)

    if success:
        size_mb = dataset_size / (1024 * 1024)
        size_gb = dataset_size / (1024 * 1024 * 1024)

        print(f"✅ Success! Dataset created: {config['ICECHUNK_PATH']}")
        print(f"💾 Final size: {size_mb:.2f} MB ({size_gb:.3f} GB)")
        print(f"⏱ Total time: {total_time:.2f} seconds ({total_time/60:.2f} minutes)")
        print(f"🧩 Tiles processed: {len(tiles)}")
        print(f"📊 Original plots: {len(original_plots)}")
        print(f"📊 Final plots: {len(final_plots)}")

        return True, dataset_size
    else:
        print("❌ Workflow failed")
        return False, 0


# Example usage
if __name__ == "__main__":
    # Parse command line arguments
    skip_download = '--skip-download' in sys.argv
    test_mode = '--test-mode' in sys.argv
    plot_only = '--plot-only' in sys.argv

    # Example: Process July 22, 2025 with tiled regridding
    target_date = datetime(2025, 7, 22)

    # Different configurations for testing
    if test_mode:
        # Test with 10km resolution and smaller tiles
        resolution = 0.1  # 10km
        tile_size = 5.0   # 5-degree tiles
        print("🧪 TEST MODE: 10km resolution, 5-degree tiles")
    else:
        # Production with 1km resolution
        resolution = 0.01  # 1km
        tile_size = 10.0   # 10-degree tiles
        print("🚀 PRODUCTION MODE: 1km resolution, 10-degree tiles")

    try:
        success, size = main(target_date,
                           resolution=resolution,
                           tile_size=tile_size,
                           skip_download=skip_download,
                           test_mode=test_mode,
                           plot_only=plot_only)

        if success:
            print(f"\n🎯 Success! Check plots in: ./plots_{target_date.strftime('%Y%m%d')}/")
            if not plot_only:
                print(f"Dataset location: {target_date.strftime('%Y%m%d')}.zarr")
                print(f"Dataset size: {size / (1024*1024):.2f} MB")
        else:
            print("❌ Workflow failed")
            sys.exit(1)

    except Exception as e:
        print(f"❌ Workflow failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)