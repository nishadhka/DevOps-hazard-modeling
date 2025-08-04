#!/usr/bin/env python3
"""
Prefect Cloud Deployment Script
IGAD-ICPAC Hydrology Data Pipeline

Deploys the hydrology data synchronization flow to Prefect Cloud
with proper environment configuration and error handling.

Author: Hillary Koros - Developer at ICPAC
"""

import os
import sys
from pathlib import Path
import subprocess
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PrefectDeployment:
    """Handle Prefect Cloud deployment operations"""

    def __init__(self):
        self.load_environment()
        self.validate_prerequisites()

    def load_environment(self):
        """Load environment variables"""
        if Path(".env").exists():
            load_dotenv(".env")
            logger.info("Environment variables loaded from .env")
        else:
            logger.warning("No .env file found - using system environment")

    def validate_prerequisites(self):
        """Validate deployment prerequisites"""
        logger.info("Validating deployment prerequisites...")

        # Check if prefect is installed
        try:
            result = subprocess.run(
                ["prefect", "version"], capture_output=True, text=True
            )
            if result.returncode != 0:
                raise Exception("Prefect CLI not available")
            logger.info(f"Prefect CLI available: {result.stdout.strip()}")
        except Exception as e:
            logger.error(f"Prefect CLI not found: {e}")
            sys.exit(1)

        # Check Prefect Cloud authentication
        try:
            result = subprocess.run(
                ["prefect", "cloud", "workspace", "ls"], capture_output=True, text=True
            )
            if result.returncode != 0:
                logger.error("Not authenticated with Prefect Cloud")
                logger.info("Run: prefect cloud login")
                sys.exit(1)
            logger.info("Prefect Cloud authentication verified")
        except Exception as e:
            logger.error(f"Failed to verify Prefect Cloud auth: {e}")
            sys.exit(1)

        # Check required files
        required_files = ["ftp_to_gcs_sync.py", ".env", "prefect.yaml"]
        for file_path in required_files:
            if not Path(file_path).exists():
                logger.error(f"Required file missing: {file_path}")
                sys.exit(1)

        logger.info("All prerequisites validated successfully")

    def setup_secrets(self):
        """Set up secrets and blocks in Prefect Cloud"""
        logger.info("Setting up secrets and blocks in Prefect Cloud...")

        # Set up regular variables (non-sensitive)
        variables_to_create = [
            ("ftp-host", os.getenv("FTP_HOST")),
            ("ftp-path", os.getenv("FTP_PATH", "/output/")),
            ("gcs-bucket", os.getenv("GCS_BUCKET")),
            ("gcs-prefix", os.getenv("GCS_PREFIX", "hydrology_data")),
        ]

        for var_name, var_value in variables_to_create:
            if not var_value:
                logger.warning(f"No value found for variable: {var_name}")
                continue

            try:
                cmd = ["prefect", "variable", "set", var_name, var_value]
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    logger.info(f"Variable '{var_name}' configured successfully")
                else:
                    logger.error(
                        f"Failed to set variable '{var_name}': {result.stderr}"
                    )
            except Exception as e:
                logger.error(f"Error setting variable '{var_name}': {e}")

        # Set up sensitive variables (credentials)
        sensitive_vars = [
            ("ftp-username", os.getenv("FTP_USERNAME")),
            ("ftp-password", os.getenv("FTP_PASSWORD")),
        ]

        for var_name, var_value in sensitive_vars:
            if not var_value:
                logger.warning(f"No value found for sensitive variable: {var_name}")
                continue

            try:
                cmd = ["prefect", "variable", "set", var_name, var_value]
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    logger.info(
                        f"Sensitive variable '{var_name}' configured successfully"
                    )
                else:
                    logger.error(
                        f"Failed to set sensitive variable '{var_name}': {result.stderr}"
                    )
            except Exception as e:
                logger.error(f"Error setting sensitive variable '{var_name}': {e}")

        # Handle GCS credentials
        self.setup_gcs_credentials()

    def setup_gcs_credentials(self):
        """Set up GCS credentials as a variable"""
        logger.info("Setting up GCS credentials...")

        gcs_creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if gcs_creds_path and Path(gcs_creds_path).exists():
            try:
                with open(gcs_creds_path, "r") as f:
                    gcs_creds_content = f.read()

                cmd = [
                    "prefect",
                    "variable",
                    "set",
                    "gcs-credentials",
                    gcs_creds_content,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    logger.info("GCS credentials configured successfully")
                else:
                    logger.error(f"Failed to set GCS credentials: {result.stderr}")
            except Exception as e:
                logger.error(f"Error reading GCS credentials: {e}")
        else:
            logger.warning("GCS credentials file not found or not specified")
            logger.info(
                "For production deployment, ensure GCS credentials are set via environment variables or Prefect variables"
            )

    def create_work_pool(self):
        """Create work pool if it doesn't exist"""
        logger.info("Using existing work pool...")

        work_pool_name = " geosfm-cloud-pool"

        try:
            # Check if work pool exists
            result = subprocess.run(
                ["prefect", "work-pool", "ls"], capture_output=True, text=True
            )

            if work_pool_name not in result.stdout:
                logger.error(f"Work pool '{work_pool_name}' not found in Prefect Cloud")
                logger.info("Available work pools:")
                logger.info(result.stdout)
                return False
            else:
                logger.info(f"Using existing work pool '{work_pool_name}'")

            return True

        except Exception as e:
            logger.error(f"Error managing work pool: {e}")
            return False

    def deploy_flows(self):
        """Deploy flows to Prefect Cloud"""
        logger.info("Deploying flows to Prefect Cloud...")

        try:
            # Deploy using prefect.yaml - we know it works now
            result = subprocess.run(
                ["prefect", "deploy", "--all"], capture_output=True, text=True
            )

            if result.returncode == 0:
                logger.info("Flows deployed successfully!")
                logger.info("Deployment output:")
                logger.info(result.stdout)

                # Extract deployment URLs from output
                lines = result.stdout.split("\n")
                for line in lines:
                    if "View Deployment in UI:" in line:
                        logger.info(
                            f"Deployment UI: {line.split('View Deployment in UI: ')[1]}"
                        )

                return True
            else:
                logger.error(f"Deployment failed: {result.stderr}")
                logger.error(f"Stdout: {result.stdout}")
                return False

        except Exception as e:
            logger.error(f"Error during deployment: {e}")
            return False

    def start_worker(self):
        """Instructions for starting a worker"""
        logger.info("\n" + "=" * 60)
        logger.info("DEPLOYMENT COMPLETE!")
        logger.info("=" * 60)
        logger.info("\nTo run the deployed flows, start a worker:")
        logger.info("Since you're using a managed work pool, no worker is needed!")
        logger.info("The flows will run automatically on Prefect Cloud infrastructure.")
        logger.info("\nIf you want to run a local worker instead:")
        logger.info('prefect worker start --pool " geosfm-cloud-pool"')
        logger.info("\nThe flow is scheduled to run daily at midnight UTC.")
        logger.info("You can also trigger it manually from the Prefect Cloud UI.")
        logger.info("=" * 60)


def main():
    """Main deployment function"""
    logger.info("Starting Prefect Cloud deployment...")

    deployment = PrefectDeployment()

    # Setup secrets
    deployment.setup_secrets()

    # Create work pool
    if not deployment.create_work_pool():
        logger.error("Failed to setup work pool")
        sys.exit(1)

    # Deploy flows
    if not deployment.deploy_flows():
        logger.error("Failed to deploy flows")
        sys.exit(1)

    # Show worker instructions
    deployment.start_worker()


if __name__ == "__main__":
    main()
