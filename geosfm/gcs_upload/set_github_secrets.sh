#!/bin/bash

# Script to set GitHub secrets for Hydrology Pipeline deployment
# Usage: ./set_github_secrets.sh

echo "==================================="
echo "GitHub Secrets Setup for Hydrology Pipeline"
echo "==================================="
echo ""
echo "This script will help you set up the required GitHub secrets."
echo "Make sure you have the GitHub CLI (gh) installed and authenticated."
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "ERROR: GitHub CLI (gh) is not installed."
    echo "Install it from: https://cli.github.com/"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "ERROR: Not authenticated with GitHub CLI."
    echo "Run: gh auth login"
    exit 1
fi

echo "Setting secrets for repository: icpac-igad/DevOps-hazard-modeling"
echo ""

# Function to set a secret
set_secret() {
    local secret_name=$1
    local prompt_text=$2
    local is_required=$3
    
    echo "----------------------------------------"
    echo "Setting: $secret_name"
    echo "$prompt_text"
    
    if [ "$is_required" = "required" ]; then
        echo "(Required)"
    else
        echo "(Optional - press Enter to skip)"
    fi
    
    echo -n "Enter value: "
    read -s secret_value
    echo ""
    
    if [ -n "$secret_value" ]; then
        echo "$secret_value" | gh secret set "$secret_name" --repo icpac-igad/DevOps-hazard-modeling
        echo "✓ $secret_name set successfully"
    elif [ "$is_required" = "required" ]; then
        echo "ERROR: $secret_name is required!"
        exit 1
    else
        echo "⊘ $secret_name skipped"
    fi
}

# Set Prefect secrets
echo "=== PREFECT CLOUD CONFIGURATION ==="
set_secret "PREFECT_API_KEY" "Your Prefect Cloud API key (starts with pnu_)" "required"
set_secret "PREFECT_ACCOUNT_ID" "Your Prefect account UUID (find in Prefect Cloud URL)" "required"
set_secret "PREFECT_WORKSPACE_ID" "Your Prefect workspace UUID (find in Prefect Cloud URL)" "required"

echo ""
echo "=== FTP SERVER CONFIGURATION ==="
set_secret "FTP_HOST" "FTP server hostname (e.g., ftp.example.com)" "required"
set_secret "FTP_USERNAME" "FTP username" "required"
set_secret "FTP_PASSWORD" "FTP password" "required"
set_secret "FTP_PATH" "FTP path (default: /output/)" "optional"

echo ""
echo "=== GOOGLE CLOUD STORAGE CONFIGURATION ==="
set_secret "GCS_BUCKET" "GCS bucket name" "required"
set_secret "GCS_PREFIX" "GCS prefix (default: hydrology_data)" "optional"

echo ""
echo "=== GCS SERVICE ACCOUNT CREDENTIALS ==="
echo "For GCS_CREDENTIALS, you need to paste the entire service account JSON."
echo "You can either:"
echo "1. Paste it directly (multiline input)"
echo "2. Save it to a file and use: gh secret set GCS_CREDENTIALS < path/to/credentials.json"
echo ""
echo "Choose option (1 or 2): "
read option

if [ "$option" = "1" ]; then
    echo "Paste the JSON content (press Ctrl+D when done):"
    gh secret set GCS_CREDENTIALS --repo icpac-igad/DevOps-hazard-modeling
elif [ "$option" = "2" ]; then
    echo -n "Enter path to credentials JSON file: "
    read creds_file
    if [ -f "$creds_file" ]; then
        gh secret set GCS_CREDENTIALS < "$creds_file" --repo icpac-igad/DevOps-hazard-modeling
        echo "✓ GCS_CREDENTIALS set successfully"
    else
        echo "ERROR: File not found: $creds_file"
        exit 1
    fi
else
    echo "Invalid option"
    exit 1
fi

echo ""
echo "==================================="
echo "✓ GitHub secrets setup complete!"
echo "==================================="
echo ""
echo "To verify, run:"
echo "gh secret list --repo icpac-igad/DevOps-hazard-modeling"
echo ""
echo "To trigger the deployment, push changes to the main branch."