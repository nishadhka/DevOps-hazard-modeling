#!/usr/bin/env python3
"""
Climate Data Plotting Script V4: Enhanced Variable-Specific Plotting
Features:
- Separate PNG files for each variable (PET, IMERG, CHIRPS-GEFS)
- PET: Only plots available data date (non-null)
- CHIRPS-GEFS: Plots 3 random dates for data validity checking
- IMERG: Plots all available dates (as before)
- Professional cartographic styling
- Variable-specific handling

Usage:
  python plot_climate_data_comprehensive_v4.py --date 20250722
"""

import sys
import os
import argparse
import time
import random
from datetime import datetime
from pathlib import Path

import numpy as np
import xarray as xr
import icechunk
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import warnings

warnings.filterwarnings('ignore')

# Coverage area for East Africa
LAT_MIN, LAT_MAX = -12.0, 24.2
LON_MIN, LON_MAX = 22.9, 51.6

# Variable configurations
VARIABLE_CONFIGS = {
    'pet': {
        'cmap': 'Oranges',
        'label': 'Potential Evapotranspiration (mm/day)',
        'title_prefix': 'PET',
        'strategy': 'non_null_only'  # Only plot dates with data
    },
    'imerg_precipitation': {
        'cmap': 'Blues',
        'label': 'IMERG Precipitation (mm/day)',
        'title_prefix': 'IMERG',
        'strategy': 'all_dates'  # Plot all available dates
    },
    'chirps_gefs_precipitation': {
        'cmap': 'Greens',
        'label': 'CHIRPS-GEFS Precipitation (mm/day)', 
        'title_prefix': 'CHIRPS-GEFS',
        'strategy': 'random_three'  # Plot 3 random dates
    }
}


def open_zarr_dataset(zarr_path, dataset_type="unknown"):
    """Open zarr dataset using icechunk"""
    try:
        print(f"   📖 Opening {dataset_type} zarr: {zarr_path}")
        
        if not os.path.exists(zarr_path):
            print(f"   ❌ Zarr path does not exist: {zarr_path}")
            return None
            
        # Open with icechunk store
        storage = icechunk.local_filesystem_storage(zarr_path)
        repo = icechunk.Repository.open(storage)
        session = repo.readonly_session("main")
        store = session.store
        ds = xr.open_zarr(store, consolidated=False)
        
        print(f"   ✅ Opened {dataset_type} dataset:")
        print(f"      Variables: {list(ds.data_vars)}")
        print(f"      Time range: {len(ds.time)} steps")
        
        return ds
        
    except Exception as e:
        print(f"   ❌ Failed to open {dataset_type} zarr: {e}")
        return None


def find_non_null_pet_times(ds):
    """Find time steps where PET data is not null"""
    if 'pet' not in ds:
        return []
    
    print("   🔍 Finding non-null PET time steps...")
    pet_data = ds['pet']
    
    # Count non-null values per time step
    non_null_counts = (~pet_data.isnull()).sum(dim=['lat', 'lon']).compute()
    valid_mask = (non_null_counts > 0).compute()
    
    valid_times = pet_data.time[valid_mask]
    print(f"   ✅ Found {len(valid_times)} time steps with PET data")
    
    return valid_times


def select_plot_times(ds, variable_name, strategy):
    """Select time steps to plot based on strategy"""
    all_times = ds.time.values
    
    if strategy == 'non_null_only':
        # For PET: only non-null data
        if variable_name == 'pet':
            valid_times = find_non_null_pet_times(ds)
            selected_times = valid_times.values if len(valid_times) > 0 else []
        else:
            selected_times = all_times
            
    elif strategy == 'random_three':
        # For CHIRPS-GEFS: 3 random dates
        if len(all_times) >= 3:
            selected_times = random.sample(list(all_times), 3)
        else:
            selected_times = all_times
            
    elif strategy == 'all_dates':
        # For IMERG: all dates (limited to max 9)
        selected_times = all_times[:9]
        
    else:
        selected_times = all_times[:9]
    
    print(f"   📅 Selected {len(selected_times)} time steps for plotting ({strategy})")
    return selected_times


def create_variable_plot(ds, variable_name, output_dir, date_str):
    """Create plot for a single variable with variable-specific strategy"""
    
    if variable_name not in ds:
        print(f"   ⚠️ Variable {variable_name} not found in dataset")
        return None
    
    # Get variable configuration
    var_config = VARIABLE_CONFIGS.get(variable_name, {
        'cmap': 'viridis',
        'label': f'{variable_name}',
        'title_prefix': variable_name.upper(),
        'strategy': 'all_dates'
    })
    
    print(f"\n   🎨 Creating plot for {variable_name} ({var_config['strategy']})")
    
    # Select time steps based on strategy
    selected_times = select_plot_times(ds, variable_name, var_config['strategy'])
    
    if len(selected_times) == 0:
        print(f"   ⚠️ No valid time steps found for {variable_name}")
        return None
    
    var_data = ds[variable_name]
    
    # Calculate grid dimensions
    n_times = len(selected_times)
    if n_times <= 3:
        nrows, ncols = 1, n_times
    elif n_times <= 6:
        nrows, ncols = 2, 3
    else:
        nrows, ncols = 3, 3
        n_times = min(9, n_times)  # Limit to 9 max
    
    # Create figure
    fig, axes = plt.subplots(nrows, ncols, 
                            figsize=(5*ncols, 4*nrows),
                            subplot_kw={'projection': ccrs.PlateCarree()})
    
    # Handle single subplot case
    if n_times == 1:
        axes = [axes]
    elif nrows == 1 or ncols == 1:
        axes = axes.flatten()
    else:
        axes = axes.flatten()
    
    # Get spatial coordinates
    lats = ds.lat.values
    lons = ds.lon.values
    
    print(f"   📊 Grid layout: {nrows}x{ncols} for {n_times} time steps")
    print(f"   🗺️ Spatial grid: {len(lats)} x {len(lons)}")
    
    # Calculate data range for consistent colorbar
    all_data = []
    for i, time_val in enumerate(selected_times[:n_times]):
        # Find time index in original dataset
        time_idx = np.where(ds.time.values == time_val)[0]
        if len(time_idx) > 0:
            data_slice = var_data.isel(time=time_idx[0])
            finite_data = data_slice.values[np.isfinite(data_slice.values)]
            if len(finite_data) > 0:
                all_data.extend(finite_data)
    
    if all_data:
        vmin = np.percentile(all_data, 2)
        vmax = np.percentile(all_data, 98)
        # Ensure positive range for precipitation data
        if 'precipitation' in variable_name:
            vmin = max(0, vmin)
            vmax = max(1, vmax)
    else:
        vmin, vmax = 0, 1
    
    print(f"   📈 Data range: {vmin:.2f} to {vmax:.2f}")
    
    # Plot each selected timestep
    plotted_count = 0
    
    for i, time_val in enumerate(selected_times[:n_times]):
        if i >= len(axes):
            break
            
        ax = axes[i]
        
        # Find time index in original dataset
        time_idx = np.where(ds.time.values == time_val)[0]
        
        if len(time_idx) > 0:
            # Get data for this timestep
            data_slice = var_data.isel(time=time_idx[0])
            plot_data = data_slice.values
            
            # Create timestamp for title
            if hasattr(time_val, 'strftime'):
                time_str = time_val.strftime('%Y-%m-%d')
            else:
                # Handle numpy datetime64
                time_str = str(time_val)[:10]
            
            # Create contour plot
            try:
                # Create meshgrid for plotting
                lon_grid, lat_grid = np.meshgrid(lons, lats)
                
                # Plot with adaptive levels
                if vmax > vmin:
                    levels = np.linspace(vmin, vmax, 15)
                    cf = ax.contourf(lon_grid, lat_grid, plot_data,
                                   levels=levels, cmap=var_config['cmap'],
                                   transform=ccrs.PlateCarree(), extend='max')
                else:
                    # Fallback for uniform data
                    cf = ax.contourf(lon_grid, lat_grid, plot_data,
                                   cmap=var_config['cmap'],
                                   transform=ccrs.PlateCarree())
                
                plotted_count += 1
                
            except Exception as e:
                print(f"      ⚠️ Plotting failed for timestep {i}: {e}")
                ax.text(0.5, 0.5, f'Plot Error\n{time_str}', 
                       transform=ax.transAxes, ha='center', va='center',
                       bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
        else:
            # Time not found
            ax.text(0.5, 0.5, f'Time Not Found', 
                   transform=ax.transAxes, ha='center', va='center',
                   bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.5))
            time_str = "N/A"
        
        # Add map features
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5, color='gray')
        ax.add_feature(cfeature.BORDERS, linewidth=0.3, color='gray')
        ax.add_feature(cfeature.LAND, alpha=0.1, facecolor='lightgray')
        
        # Set extent to East Africa
        ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX])
        
        # Add title with timestamp
        max_val = np.nanmax(plot_data) if len(time_idx) > 0 else 0
        ax.set_title(f'{time_str}\nMax: {max_val:.1f}', 
                    fontsize=11, pad=10)
        
        # Add gridlines to first subplot
        if i == 0:
            gl = ax.gridlines(crs=ccrs.PlateCarree(), draw_labels=True,
                             linewidth=0.3, color='gray', alpha=0.5, linestyle='--')
            gl.top_labels = False
            gl.right_labels = False
            gl.xlabel_style = {'size': 9}
            gl.ylabel_style = {'size': 9}
    
    # Hide unused subplots
    for i in range(n_times, len(axes)):
        axes[i].set_visible(False)
    
    # Add colorbar (if we have plotted data)
    if plotted_count > 0 and 'cf' in locals():
        cbar_ax = fig.add_axes([0.92, 0.15, 0.02, 0.7])
        cbar = plt.colorbar(cf, cax=cbar_ax)
        cbar.set_label(var_config['label'], rotation=270, labelpad=20)
    
    # Overall title
    strategy_desc = {
        'non_null_only': 'Available Data Only',
        'random_three': '3 Random Dates',
        'all_dates': 'All Available Dates'
    }
    
    fig.suptitle(f'{var_config["title_prefix"]} - East Africa\n'
                 f'Date: {date_str} | Strategy: {strategy_desc.get(var_config["strategy"], "Standard")}\n'
                 f'Plots: {plotted_count}/{len(selected_times)} | Coverage: {LAT_MIN}°-{LAT_MAX}°N, {LON_MIN}°-{LON_MAX}°E',
                 fontsize=14, y=0.98)
    
    # Save figure
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f'{variable_name}_{date_str}.png')
    plt.tight_layout(rect=[0, 0, 0.9, 0.96])
    plt.savefig(output_file, dpi=200, bbox_inches='tight')
    print(f"   ✅ Plot saved: {output_file}")
    plt.close()
    
    return output_file


def process_zarr_dataset(zarr_path, dataset_type, date_str, output_dir):
    """Process zarr dataset and create separate plots for each variable"""
    print(f"\n📊 Processing {dataset_type} dataset...")
    
    # Open dataset
    ds = open_zarr_dataset(zarr_path, dataset_type)
    if ds is None:
        return []
    
    # Find variables to plot
    available_vars = list(ds.data_vars)
    plot_vars = []
    
    # Map dataset variables to our configurations
    for var in available_vars:
        if var in VARIABLE_CONFIGS:
            plot_vars.append(var)
        elif var == 'pet_data':  # Handle different naming
            plot_vars.append('pet')
    
    if not plot_vars:
        print(f"   ⚠️ No recognized variables found in {dataset_type} dataset")
        print(f"      Available variables: {available_vars}")
        return []
    
    print(f"   🎯 Creating separate plots for {len(plot_vars)} variables: {plot_vars}")
    
    # Create plots for each variable
    output_files = []
    for variable in plot_vars:
        # Handle pet_data vs pet naming
        actual_var = 'pet_data' if variable == 'pet' and 'pet_data' in ds else variable
        
        try:
            output_file = create_variable_plot(ds, actual_var, output_dir, date_str)
            if output_file:
                output_files.append(output_file)
        except Exception as e:
            print(f"   ❌ Failed to create plot for {variable}: {e}")
            import traceback
            traceback.print_exc()
    
    return output_files


def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Create separate PNG plots for each climate variable')
    parser.add_argument('--date', required=True, help='Date in YYYYMMDD format')
    
    args = parser.parse_args()
    
    # Validate date
    try:
        date_obj = datetime.strptime(args.date, '%Y%m%d')
        date_str = args.date
    except ValueError:
        print(f"❌ Invalid date format: {args.date}. Use YYYYMMDD format.")
        return False
    
    print("🎨 Climate Data Variable-Specific Plotting V4")
    print("=" * 80)
    print(f"Date: {date_obj.strftime('%Y-%m-%d')}")
    print(f"Strategy: Separate PNG files per variable with custom plotting strategies")
    print("=" * 80)
    
    start_time = time.time()
    all_output_files = []
    
    # Create output directory
    output_dir = f"climate_plots_{date_str}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Define zarr path (regridded dataset)
    regridded_zarr_path = f"./east_africa_regridded_{date_str}.zarr"
    
    # Process regridded zarr dataset
    if os.path.exists(regridded_zarr_path):
        output_files = process_zarr_dataset(regridded_zarr_path, "regridded", date_str, output_dir)
        all_output_files.extend(output_files)
    else:
        print(f"❌ Regridded zarr file not found: {regridded_zarr_path}")
        return False
    
    total_time = time.time() - start_time
    
    # Summary
    print("\n" + "=" * 80)
    print("🎉 VARIABLE-SPECIFIC PLOTTING V4 COMPLETE")
    print("=" * 80)
    
    if all_output_files:
        print(f"✅ Success! Created {len(all_output_files)} separate PNG files:")
        for i, file_path in enumerate(all_output_files, 1):
            print(f"   {i:2d}. {os.path.basename(file_path)}")
        
        print(f"\n📁 Output directory: {output_dir}")
        print(f"⏱️ Total processing time: {total_time:.1f} seconds")
        
        print(f"\n🎯 Plotting strategies:")
        print(f"   🌡️ PET: Only available data dates (non-null)")
        print(f"   🛰️ IMERG: All available dates (up to 9)")
        print(f"   🌧️ CHIRPS-GEFS: 3 random dates for validity checking")
        
        return True
    else:
        print("❌ No plots were created successfully")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)