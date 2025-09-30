#!/usr/bin/env python3
"""
Extract Forecast Period from GeoSFM Model Outputs

This script extracts the forecast period (source date + 15-18 days) from each
date's CSV files. The GeoSFM hydrological model provides daily forecast outputs
where each model run includes both hindcast and forecast data.

Key Concepts:
- Source Date: The date when the model run was created (e.g., 20250721)
- Hindcast: Historical data before the source date (~295-300 days)
- Forecast: Future predictions after the source date (~15-18 days)

This script focuses on extracting only the FORECAST period, which represents
the actual predictive capability of the model for the coming 2-3 weeks.

Usage:
    python extract_forecast_period.py
    python extract_forecast_period.py --days 15  # Extract specific number of days
    python extract_forecast_period.py --run-date 20250721  # Process specific date
"""

import pandas as pd
import os
import argparse
from datetime import datetime, timedelta

def extract_forecast_for_date(source_date_str, forecast_days=18, output_folder="forecast_extracts"):
    """
    Extract forecast period for a specific source date

    Args:
        source_date_str (str): Source date in YYYYMMDD format (e.g., '20250721')
        forecast_days (int): Number of forecast days to extract (default: 18)
        output_folder (str): Folder to save extracted forecast files

    Returns:
        dict: Results summary for this source date
    """

    print(f"\n{'='*60}")
    print(f"EXTRACTING FORECAST FOR SOURCE DATE: {source_date_str}")
    print(f"{'='*60}")

    # Parse source date
    try:
        source_date = datetime.strptime(source_date_str, '%Y%m%d')
        source_readable = source_date.strftime('%Y-%m-%d (%B %d, %Y)')
        print(f"Source Date: {source_readable}")
        print(f"Extracting {forecast_days} days of forecast data")
    except ValueError:
        print(f"Error: Invalid source date format '{source_date_str}'. Use YYYYMMDD format.")
        return None

    # Create output folder
    os.makedirs(output_folder, exist_ok=True)

    # Calculate forecast date range
    forecast_start = source_date
    forecast_end = source_date + timedelta(days=forecast_days - 1)

    print(f"Forecast period: {forecast_start.strftime('%Y-%m-%d')} to {forecast_end.strftime('%Y-%m-%d')}")

    # Generate expected forecast gtimes
    expected_gtimes = []
    current_date = forecast_start
    while current_date <= forecast_end:
        expected_gtimes.append(current_date.strftime('%Y%m%dT00'))
        current_date += timedelta(days=1)

    print(f"Expected forecast gtimes: {len(expected_gtimes)} days")
    print(f"First few: {expected_gtimes[:3]}")
    print(f"Last few: {expected_gtimes[-3:]}")

    results = {
        'source_date': source_date_str,
        'forecast_days': forecast_days,
        'expected_gtimes': expected_gtimes,
        'variables': {}
    }

    # Process each variable
    base_folder = "geosfm_txt_files"

    for variable in ['riverdepth', 'streamflow']:
        print(f"\n  Processing {variable.upper()}:")

        # Input CSV path
        csv_path = f"{base_folder}/{source_date_str}/{variable}_long_table_{source_date_str}.csv"

        if not os.path.exists(csv_path):
            print(f"    Error: File not found - {csv_path}")
            results['variables'][variable] = {'error': 'File not found'}
            continue

        # Read the full CSV
        print(f"    Reading {csv_path}...")
        df = pd.read_csv(csv_path)

        print(f"    Original data: {len(df):,} records")
        print(f"    Date range: {df['gtime'].min()} to {df['gtime'].max()}")

        # Filter for forecast period
        forecast_df = df[df['gtime'].isin(expected_gtimes)].copy()

        print(f"    Forecast data: {len(forecast_df):,} records")

        if len(forecast_df) == 0:
            print(f"    Warning: No forecast data found for the expected period")
            results['variables'][variable] = {'error': 'No forecast data found'}
            continue

        # Analyze what we actually got
        actual_gtimes = sorted(forecast_df['gtime'].unique())
        missing_gtimes = [gt for gt in expected_gtimes if gt not in actual_gtimes]
        extra_gtimes = [gt for gt in actual_gtimes if gt not in expected_gtimes]

        print(f"    Actual forecast dates: {len(actual_gtimes)}")
        print(f"    Missing dates: {len(missing_gtimes)}")
        if missing_gtimes:
            print(f"      Missing: {missing_gtimes[:5]}" + ("..." if len(missing_gtimes) > 5 else ""))

        # Save forecast extract
        output_filename = f"{output_folder}/{variable}_forecast_{source_date_str}_{forecast_days}days.csv"
        forecast_df.to_csv(output_filename, index=False)

        print(f"    Saved: {output_filename} ({os.path.getsize(output_filename) / 1024 / 1024:.2f} MB)")

        # Store results
        results['variables'][variable] = {
            'original_records': len(df),
            'forecast_records': len(forecast_df),
            'actual_gtimes': actual_gtimes,
            'missing_gtimes': missing_gtimes,
            'output_file': output_filename,
            'file_size_mb': round(os.path.getsize(output_filename) / 1024 / 1024, 2)
        }

    return results

def extract_all_forecasts(forecast_days=18, output_folder="forecast_extracts"):
    """Extract forecast periods for all available source dates"""

    print("="*80)
    print("GEOSFM FORECAST PERIOD EXTRACTION")
    print("="*80)
    print(f"Extracting {forecast_days} days of forecast data for each source date")
    print(f"Output folder: {output_folder}")

    # Find all source date folders
    base_folder = "geosfm_txt_files"
    source_dates = []

    if os.path.exists(base_folder):
        for item in os.listdir(base_folder):
            item_path = os.path.join(base_folder, item)
            if os.path.isdir(item_path) and len(item) == 8 and item.isdigit():
                source_dates.append(item)

    source_dates.sort()
    print(f"Found {len(source_dates)} source dates: {source_dates}")

    if not source_dates:
        print("Error: No source date folders found")
        return

    # Process each source date
    all_results = []

    for source_date in source_dates:
        result = extract_forecast_for_date(source_date, forecast_days, output_folder)
        if result:
            all_results.append(result)

    # Create summary report
    print(f"\n{'='*80}")
    print("FORECAST EXTRACTION SUMMARY")
    print(f"{'='*80}")

    summary_data = []

    for result in all_results:
        source_date = result['source_date']
        source_readable = datetime.strptime(source_date, '%Y%m%d').strftime('%Y-%m-%d')

        print(f"\nSource Date: {source_readable}")

        for variable in ['riverdepth', 'streamflow']:
            if variable in result['variables'] and 'error' not in result['variables'][variable]:
                var_result = result['variables'][variable]
                forecast_records = var_result['forecast_records']
                actual_dates = len(var_result['actual_gtimes'])
                missing_dates = len(var_result['missing_gtimes'])
                file_size = var_result['file_size_mb']

                print(f"  {variable}: {forecast_records:,} records, {actual_dates} dates ({missing_dates} missing), {file_size} MB")

                summary_data.append({
                    'source_date': source_date,
                    'source_readable': source_readable,
                    'variable': variable,
                    'forecast_records': forecast_records,
                    'actual_dates': actual_dates,
                    'missing_dates': missing_dates,
                    'file_size_mb': file_size,
                    'output_file': var_result['output_file']
                })

    # Save summary as CSV
    if summary_data:
        summary_df = pd.DataFrame(summary_data)
        summary_file = f"{output_folder}/forecast_extraction_summary.csv"
        summary_df.to_csv(summary_file, index=False)
        print(f"\nSummary saved: {summary_file}")

        # Print final stats
        total_files = len(summary_data)
        total_records = summary_df['forecast_records'].sum()
        total_size = summary_df['file_size_mb'].sum()

        print(f"\nFINAL STATISTICS:")
        print(f"  Total forecast files created: {total_files}")
        print(f"  Total forecast records: {total_records:,}")
        print(f"  Total size: {total_size:.2f} MB")

    return all_results

def main():
    """Main function with command line argument parsing"""

    parser = argparse.ArgumentParser(
        description='Extract forecast periods from GeoSFM model outputs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python extract_forecast_period.py                    # Extract 18 days for all dates
    python extract_forecast_period.py --days 15          # Extract 15 days for all dates
    python extract_forecast_period.py --run-date 20250721 --days 15  # Extract specific date
        """
    )

    parser.add_argument('--days', type=int, default=18,
                        help='Number of forecast days to extract (default: 18)')
    parser.add_argument('--run-date', type=str,
                        help='Extract forecast for specific GeoSFM model run date (YYYYMMDD format)')
    parser.add_argument('--output-folder', type=str, default='forecast_extracts',
                        help='Output folder for extracted forecast files (default: forecast_extracts)')

    args = parser.parse_args()

    # Validate arguments
    if args.days < 1 or args.days > 30:
        print("Error: Forecast days must be between 1 and 30")
        return

    if args.run_date:
        # Process single GeoSFM run date
        try:
            datetime.strptime(args.run_date, '%Y%m%d')
        except ValueError:
            print("Error: GeoSFM run date must be in YYYYMMDD format (e.g., 20250721)")
            return

        result = extract_forecast_for_date(args.run_date, args.days, args.output_folder)

        if result:
            print(f"\nExtraction complete for GeoSFM run date {args.run_date}")
        else:
            print(f"Extraction failed for GeoSFM run date {args.run_date}")
    else:
        # Process all source dates
        results = extract_all_forecasts(args.days, args.output_folder)

        if results:
            print(f"\nExtraction complete for all source dates")
        else:
            print("No extractions completed")

if __name__ == "__main__":
    main()
