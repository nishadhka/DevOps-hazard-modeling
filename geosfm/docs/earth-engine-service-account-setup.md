# Google Earth Engine Service Account Setup Guide

This guide provides step-by-step instructions for creating and configuring a Google Cloud service account with the necessary permissions for Google Earth Engine (GEE) access.

## Prerequisites

- Google Cloud Project with Earth Engine API enabled
- `gcloud` CLI installed and authenticated
- Earth Engine access permissions for your Google account

## Environment Variables

Before starting, set up these environment variables for easier reference:

```bash
export PROJECT_NAME="your-project-id"
export SERVICE_ACCOUNT_NAME="earthengine-sa"
export SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_NAME}.iam.gserviceaccount.com"
export KEY_FILE="ee-service-account.json"
```

## Step 1: Configure gcloud CLI

### Set Active Project
```bash
gcloud config set project $PROJECT_NAME
```

### Verify Configuration
```bash
gcloud config configurations list
gcloud auth list
gcloud projects list
```

## Step 2: Create Service Account

Create a dedicated service account for Earth Engine operations:

```bash
gcloud iam service-accounts create $SERVICE_ACCOUNT_NAME \
  --description="Service account for Earth Engine access" \
  --display-name="Earth Engine Service Account"
```

## Step 3: Assign Required IAM Roles

Grant the necessary Earth Engine permissions to the service account:

```bash
# Earth Engine Viewer (read access to EE datasets)
gcloud projects add-iam-policy-binding $PROJECT_NAME \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/earthengine.viewer"

# Earth Engine Writer (write access to EE assets)
gcloud projects add-iam-policy-binding $PROJECT_NAME \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/earthengine.writer"

# Earth Engine Admin (full administrative access)
gcloud projects add-iam-policy-binding $PROJECT_NAME \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/earthengine.admin"

# Earth Engine Apps Publisher (for publishing apps)
gcloud projects add-iam-policy-binding $PROJECT_NAME \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/earthengine.appsPublisher"
```

### Optional Additional Roles

If your application requires access to other Google Cloud services:

```bash
# For Google Cloud Storage access
gcloud projects add-iam-policy-binding $PROJECT_NAME \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/storage.objectViewer"

# For BigQuery access
gcloud projects add-iam-policy-binding $PROJECT_NAME \
  --member="serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role="roles/bigquery.dataViewer"
```

## Step 4: Generate Service Account Key

Create and download the JSON credentials file:

```bash
gcloud iam service-accounts keys create $KEY_FILE \
  --iam-account=$SERVICE_ACCOUNT_EMAIL
```

**Important Security Notes:**
- Store the JSON key file securely
- Never commit credentials to version control
- Consider using environment variables or secret management services in production

## Step 5: Test Service Account Authentication

### Python Implementation

```python
import ee

# Service account configuration
service_account = 'earthengine-sa@your-project-id.iam.gserviceaccount.com'
credentials = ee.ServiceAccountCredentials(service_account, 'ee-service-account.json')

# Initialize Earth Engine
ee.Initialize(credentials, opt_url="https://earthengine-highvolume.googleapis.com")

# Test access
print("Earth Engine initialized successfully!")
print(f"Available datasets: {len(ee.data.getList())}")
```

### Verification Commands

```bash
# List service accounts
gcloud iam service-accounts list

# Check IAM policy bindings
gcloud projects get-iam-policy $PROJECT_NAME

# Verify service account keys
gcloud iam service-accounts keys list --iam-account=$SERVICE_ACCOUNT_EMAIL
```

## References

- [Earth Engine Service Account Documentation](https://developers.google.com/earth-engine/guides/service_account)
- [Google Cloud IAM Documentation](https://cloud.google.com/iam/docs)
- [gcloud CLI Reference](https://cloud.google.com/sdk/gcloud/reference)