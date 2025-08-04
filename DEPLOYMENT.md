# Prefect Cloud Deployment Guide

## Prerequisites

1. **Prefect Cloud Account**: Sign up at [https://cloud.prefect.io](https://cloud.prefect.io)
2. **Prefect CLI**: Already installed with your current setup
3. **Git Repository**: Your code should be in a Git repository for cloud deployment

## Quick Deployment Steps

### 1. Authenticate with Prefect Cloud
```bash
prefect cloud login
```
Follow the prompts to authenticate with your Prefect Cloud account.

### 2. Run the Deployment Script
```bash
python deploy.py
```

This script will:
- Validate prerequisites
- Set up environment variables as Prefect variables
- Create a work pool named "hydrology-pool"
- Deploy both scheduled and on-demand flows

### 3. Start a Worker
```bash
prefect worker start --pool hydrology-pool
```

Or run in the background:
```bash
nohup prefect worker start --pool hydrology-pool > worker.log 2>&1 &
```

## Deployment Configuration

### Scheduled Flow
- **Name**: `hydrology-midnight-sync`
- **Schedule**: Daily at midnight UTC (`0 0 * * *`)
- **Purpose**: Automatic daily synchronization

### On-Demand Flow
- **Name**: `hydrology-on-demand` 
- **Schedule**: None (manual trigger only)
- **Purpose**: Manual synchronization when needed

## Environment Variables

The deployment script will create Prefect variables from your `.env` file:
- `ftp-host`
- `ftp-username` 
- `ftp-password`
- `ftp-path`
- `gcs-bucket`
- `gcs-prefix`
- `gcs-credentials`

## Worker Deployment Options

### Option 1: Local Worker
Run the worker on your local machine or server:
```bash
prefect worker start --pool hydrology-pool
```

### Option 2: Cloud Worker (Recommended)
Deploy to cloud infrastructure like AWS, GCP, or Azure using Prefect's infrastructure blocks.

### Option 3: Docker Worker
Create a Dockerfile and deploy as a container:
```dockerfile
FROM python:3.9-slim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["prefect", "worker", "start", "--pool", "hydrology-pool"]
```

## Monitoring

1. **Prefect Cloud UI**: Monitor flow runs at [https://cloud.prefect.io](https://cloud.prefect.io)
2. **Logs**: Check logs in the Prefect UI or local worker logs
3. **Notifications**: Set up notifications for flow failures in Prefect Cloud

## Troubleshooting

### Common Issues

1. **Authentication Error**
   ```bash
   prefect cloud login
   ```

2. **Missing Environment Variables**
   - Ensure `.env` file exists with all required variables
   - Run `python deploy.py` again to update variables

3. **Worker Not Picking Up Jobs**
   - Verify worker is connected: `prefect worker ls`
   - Check work pool exists: `prefect work-pool ls`

4. **Flow Fails**
   - Check logs in Prefect Cloud UI
   - Verify GCS credentials are valid
   - Test FTP connection manually

### Manual Deployment Commands

If you prefer manual deployment:

```bash
# Create work pool
prefect work-pool create hydrology-pool --type process

# Deploy flows
prefect deploy --all

# Start worker
prefect worker start --pool hydrology-pool
```

## Security Notes

- Environment variables are stored as Prefect variables (not secrets)
- For production, consider using Prefect Blocks for sensitive data
- Ensure your worker has appropriate network access to FTP and GCS