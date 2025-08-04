# GitHub Repository Secrets Configuration

To deploy the Hydrology Pipeline via GitHub Actions, you need to configure the following secrets in your GitHub repository settings.

## Required Secrets

Navigate to your repository → Settings → Secrets and variables → Actions, then add:

### 1. **PREFECT_API_KEY** (Required)
- Your Prefect Cloud API key
- Get it from: https://app.prefect.cloud/my/api-keys
- Example: `pnu_abcd1234567890abcdef1234567890abcdef`

### 2. **PREFECT_ACCOUNT_ID** (Required)
- Your Prefect Cloud account UUID
- Find it in your Prefect Cloud URL or account settings
- Example: `12345678-1234-1234-1234-123456789012`

### 3. **PREFECT_WORKSPACE_ID** (Required)
- Your Prefect Cloud workspace UUID
- Find it in your Prefect Cloud URL or workspace settings
- Example: `87654321-4321-4321-4321-210987654321`

### 4. **FTP_HOST** (Required)
- FTP server hostname
- Example: `ftp.example.com`

### 5. **FTP_USERNAME** (Required)
- FTP server username
- Example: `hydrology_user`

### 6. **FTP_PASSWORD** (Required)
- FTP server password

### 7. **FTP_PATH** (Optional)
- FTP directory path
- Default: `/output/`
- Example: `/data/hydrology/output/`

### 8. **GCS_BUCKET** (Required)
- Google Cloud Storage bucket name
- Example: `my-hydrology-data`

### 9. **GCS_PREFIX** (Optional)
- GCS path prefix
- Default: `hydrology_data`
- Example: `production/hydrology_data`

### 10. **GCS_CREDENTIALS** (Required)
- Google Cloud service account JSON credentials
- Paste the entire JSON content as a secret
- Example:
```json
{
  "type": "service_account",
  "project_id": "my-project",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "hydrology@my-project.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "..."
}
```

## Optional Configuration

### Docker Build (Optional)
To enable Docker image building, create a repository variable (not secret):
- Name: `ENABLE_DOCKER_BUILD`
- Value: `true`

Without this variable, the Docker build step will be skipped.

## Verification

After adding all secrets, trigger a workflow run by pushing changes to the `main` branch. Check the Actions tab to ensure all steps pass successfully.

## Troubleshooting

1. **"Option '--key' requires an argument"**: The PREFECT_API_KEY secret is not set
2. **"Missing required configuration"**: One or more required secrets are missing
3. **Authentication errors**: Verify your Prefect API key and workspace IDs are correct
4. **GCS errors**: Ensure the service account has proper permissions and the JSON is valid