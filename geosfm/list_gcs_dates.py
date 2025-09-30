#!/usr/bin/env python3
"""
List available dates in GCS bucket for July, August, September 2025
"""

import os
from google.cloud import storage

# Configuration
SERVICE_ACCOUNT_PATH = "coiled-data-e4drr_202505.json"
GCS_BUCKET = "geosfm"
GCS_BASE_PREFIX = "geosfm_output_icpac_pc/"

def setup_gcs_client():
    """Setup GCS client with service account credentials"""
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = SERVICE_ACCOUNT_PATH
    return storage.Client()

def list_available_dates():
    """List available dates in GCS bucket for July, August, September 2025"""

    client = setup_gcs_client()
    bucket = client.bucket(GCS_BUCKET)

    print('Listing available dates in GCS bucket...')
    dates = set()

    try:
        # List all blobs with the base prefix
        blobs = bucket.list_blobs(prefix=GCS_BASE_PREFIX, delimiter='/')

        # Get prefixes (folder names)
        for prefix_name in blobs.prefixes:
            folder_name = prefix_name.rstrip('/').split('/')[-1]
            # Check if folder name is in YYYYMMDD format
            if len(folder_name) == 8 and folder_name.isdigit():
                year = folder_name[:4]
                month = folder_name[4:6]
                # Filter for 2025 July, August, September
                if year == '2025' and month in ['07', '08', '09']:
                    dates.add(folder_name)

        print(f'Found {len(dates)} dates for Jul/Aug/Sep 2025')

        # Separate by month
        july_dates = sorted([d for d in dates if d[4:6] == '07'])
        august_dates = sorted([d for d in dates if d[4:6] == '08'])
        september_dates = sorted([d for d in dates if d[4:6] == '09'])

        print(f'\nJuly dates ({len(july_dates)}):')
        if len(july_dates) > 10:
            print(f'  First 5: {july_dates[:5]}')
            print(f'  Last 5: {july_dates[-5:]}')
        else:
            print(f'  All: {july_dates}')

        print(f'\nAugust dates ({len(august_dates)}):')
        if len(august_dates) > 10:
            print(f'  First 5: {august_dates[:5]}')
            print(f'  Last 5: {august_dates[-5:]}')
        else:
            print(f'  All: {august_dates}')

        print(f'\nSeptember dates ({len(september_dates)}):')
        if len(september_dates) > 10:
            print(f'  First 5: {september_dates[:5]}')
            print(f'  Last 5: {september_dates[-5:]}')
        else:
            print(f'  All: {september_dates}')

        # Select sample dates (one from each month)
        sample_dates = []
        if july_dates:
            sample_dates.append(july_dates[len(july_dates)//2])  # Middle date
        if august_dates:
            sample_dates.append(august_dates[len(august_dates)//2])
        if september_dates:
            sample_dates.append(september_dates[len(september_dates)//2])

        print(f'\nRecommended sample dates to process: {sample_dates}')

        return {
            'july': july_dates,
            'august': august_dates,
            'september': september_dates,
            'sample_dates': sample_dates
        }

    except Exception as e:
        print(f'Error: {e}')
        return None

def main():
    """Main function"""
    result = list_available_dates()

    if result:
        print(f"\nSummary:")
        print(f"- July: {len(result['july'])} dates")
        print(f"- August: {len(result['august'])} dates")
        print(f"- September: {len(result['september'])} dates")
        print(f"- Total: {len(result['july']) + len(result['august']) + len(result['september'])} dates")

if __name__ == "__main__":
    main()
