# Prefect Cloud Deployment Guide

This guide explains how to deploy the Hydrology Data Sync pipeline to Prefect Cloud.

## Overview

- **GitHub**: Version control and automated deployment via GitHub Actions
- **Prefect Cloud**: Handles scheduling, secrets, execution, and infrastructure

## Prerequisites

1. Prefect Cloud account with workspace
2. Work pool named `geosfm-cloud-pool` (or create a new one)
3. GitHub repository with the code
4. GitHub Secrets configured (see below)

## Step 1: Configure Prefect Variables

In your Prefect Cloud workspace, go to Variables and create the following:

### FTP Configuration
- **Variable Name**: `ftp-host`
  **Value**: `41.215.21.156`

- **Variable Name**: `ftp-port`
  **Value**: `21`

- **Variable Name**: `ftp-path`
  **Value**: `/output/`

- **Variable Name**: `ftp-username`
  **Value**: `moha`

- **Variable Name**: `ftp-password`
  **Value**: `[YOUR_FTP_PASSWORD]`
  **Secret**: ✓ (mark as secret)

### Google Cloud Storage Configuration
- **Variable Name**: `gcs-bucket`
  **Value**: `geosfm`

- **Variable Name**: `gcs-prefix`
  **Value**: `hydrology_data`

- **Variable Name**: `gcs-credentials`
  **Value**: `[PASTE_ENTIRE_GCS_JSON_KEY_HERE]`
  **Secret**: ✓ (mark as secret)
  
  > **Important**: Copy the entire content of your `gcs-key.json` file and paste it as the value. It should start with `{"type":"service_account"...`

## Step 2: Configure GitHub Secrets

In your GitHub repository, go to Settings → Secrets and variables → Actions, and add:

- **Secret Name**: `PREFECT_API_KEY`
  **Value**: Your Prefect Cloud API key
  
  To get this:
  1. Go to Prefect Cloud
  2. Click on your profile → API Keys
  3. Create a new API key or use existing one

- **Secret Name**: `PREFECT_API_URL`
  **Value**: Your Prefect Cloud API URL
  
  Format: `https://api.prefect.cloud/api/accounts/[ACCOUNT_ID]/workspaces/[WORKSPACE_ID]`
  
  You can find this in Prefect Cloud under Settings → API URL

## Step 3: Automated Deployment via GitHub Actions

The deployment happens automatically when you push to the `gcs_upload` branch:

1. Push your changes:
   ```bash
   git add .
   git commit -m "Update hydrology sync"
   git push origin gcs_upload
   ```

2. GitHub Actions will:
   - Run tests to validate the code
   - Build and validate the deployment configuration
   - Deploy to Prefect Cloud automatically

3. Monitor the deployment in GitHub Actions tab

## Step 4: Manual Deployment (Alternative)

1. Install Prefect CLI:
   ```bash
   pip install prefect
   ```

2. Authenticate with Prefect Cloud:
   ```bash
   prefect cloud login
   ```

3. Deploy the flow:
   ```bash
   prefect deploy --all
   ```

## Step 3: Verify Deployment

1. Go to Prefect Cloud UI
2. Navigate to Deployments
3. You should see `hydrology-data-sync/hydrology-midnight-sync`
4. Check that it's scheduled to run daily at midnight UTC

## Step 4: Test Run

1. In Prefect Cloud UI, go to your deployment
2. Click "Run" to trigger a manual execution
3. Monitor the logs to ensure it's working correctly

## Deployment Details

- **Schedule**: Daily at 00:00 UTC
- **Work Pool**: `geosfm-cloud-pool`
- **Docker Image**: `prefecthq/prefect:3-python3.11`
- **Retries**: 2 (with 5-minute delay)

## Monitoring

- Check Prefect Cloud dashboard for run history
- Failed runs will automatically retry
- Logs are available in Prefect Cloud UI

## Updating the Code

1. Make changes in your local repository
2. Push to GitHub:
   ```bash
   git add .
   git commit -m "Update sync logic"
   git push origin gcs_upload
   ```
3. Redeploy to Prefect:
   ```bash
   prefect deploy --all
   ```

## Troubleshooting

### Authentication Errors
- Ensure all Prefect variables are set correctly
- Check that GCS credentials JSON is valid
- Verify FTP credentials

### Connection Issues
- The script has robust FTP connection retry logic
- Check Prefect Cloud logs for specific error messages

### File Not Syncing
- Script skips files that already exist in GCS with same size
- Check the date-based folder structure in GCS

## Notes

- No GitHub Actions needed - Prefect Cloud handles everything
- Secrets stay in Prefect Cloud, not in code
- Deployment pulls latest code from GitHub automatically