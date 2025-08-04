#!/usr/bin/env python3
"""
FTP to Google Cloud Storage Synchronization
IGAD-ICPAC Hydrology Data Pipeline

Synchronizes hydrological data files (riverdepth and streamflow) 
from FTP server to Google Cloud Storage with duplicate prevention 
and comprehensive logging.

Author: Hillary Koros - Developer at ICPAC
Version: 2.0.0
"""

import ftplib
import os
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import logging
from google.cloud import storage
from prefect import flow, task, get_run_logger, variables
from prefect.settings import PREFECT_RESULTS_PERSIST_BY_DEFAULT
from typing import Dict, List, Tuple
import os as prefect_os

# Disable result persistence globally to avoid serialization issues
prefect_os.environ["PREFECT_RESULTS_PERSIST_BY_DEFAULT"] = "false"


class HydrologyDataSync:
    """FTP to GCS synchronization for hydrology data"""

    def __init__(self, config_file=".env"):
        """
        Initialize the synchronization tool

        Args:
            config_file (str): Path to environment configuration file
        """
        self.config_file = config_file
        self.temp_dir = None
        self.setup_logging()
        self.setup_directories()
        self.config = self.load_configuration()
        self.setup_gcs_client()

    def setup_logging(self):
        """Configure logging system"""
        try:
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = logs_dir / f"hydrology_sync_{timestamp}.log"
            
            # Configure logging with both file and console output
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                handlers=[
                    logging.FileHandler(log_filename, encoding="utf-8"),
                    logging.StreamHandler(sys.stdout),
                ],
            )
            
            self.logger = logging.getLogger("HydrologyDataSync")
            self.logger.info(f"Logging initialized - Log file: {log_filename}")
            
        except (PermissionError, OSError):
            # In cloud environments, fall back to console-only logging
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                handlers=[logging.StreamHandler(sys.stdout)],
            )
            
            self.logger = logging.getLogger("HydrologyDataSync")
            self.logger.info("Logging initialized - Console only (cloud environment)")

        self.logger.info("Hydrology Data Sync v1.0.0 - Starting session")

    def setup_directories(self):
        """Create necessary directory structure"""
        required_dirs = ["logs", "downloads", "credentials"]

        for dir_name in required_dirs:
            try:
                dir_path = Path(dir_name)
                dir_path.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Directory verified: {dir_path}")
            except (PermissionError, OSError) as e:
                # In cloud environments, we might not have write permissions
                # Use temporary directory instead
                import tempfile
                temp_dir = Path(tempfile.gettempdir()) / dir_name
                temp_dir.mkdir(parents=True, exist_ok=True)
                self.logger.warning(f"Could not create {dir_path}, using {temp_dir}: {e}")
                # Update the path for logs if needed
                if dir_name == "logs" and not hasattr(self, 'logger'):
                    self.logs_dir = temp_dir

    def load_configuration(self):
        """
        Load and validate configuration from environment or Prefect variables

        Returns:
            dict: Configuration dictionary

        Raises:
            ValueError: If required configuration is missing
        """
        # Try loading from .env file first (for local development)
        if Path(self.config_file).exists():
            load_dotenv(self.config_file)
            self.logger.info("Configuration loaded from .env file")

        # Load from environment variables or Prefect variables
        config = {
            # FTP Server Configuration
            "ftp_host": self._get_config_value("FTP_HOST", "ftp-host"),
            "ftp_path": self._get_config_value("FTP_PATH", "ftp-path", "/"),
            "ftp_username": self._get_config_value("FTP_USERNAME", "ftp-username"),
            "ftp_password": self._get_config_value("FTP_PASSWORD", "ftp-password"),
            "ftp_port": int(self._get_config_value("FTP_PORT", "ftp-port", "21")),
            # Google Cloud Storage Configuration
            "gcs_bucket": self._get_config_value("GCS_BUCKET", "gcs-bucket"),
            "gcs_prefix": self._get_config_value(
                "GCS_PREFIX", "gcs-prefix", "hydrology_data"
            ),
            "gcs_credentials": self._get_config_value(
                "GOOGLE_APPLICATION_CREDENTIALS", "gcs-credentials"
            ),
            # Data Processing Configuration
            "file_patterns": ["riverdepth_imerg", "streamflow_imerg"],
            "file_extension": ".txt",
            "skip_existing_files": True,
            "use_temp_storage": True,
        }

        # Validate required configuration
        required_fields = [
            "ftp_host",
            "ftp_username",
            "ftp_password",
            "gcs_bucket",
            "gcs_credentials",
        ]

        missing_fields = [field for field in required_fields if not config[field]]
        if missing_fields:
            raise ValueError(
                f"Missing required configuration: {', '.join(missing_fields)}"
            )

        self.logger.info("Configuration loaded and validated successfully")
        self.logger.info(f"FTP Server: {config['ftp_host']}")
        self.logger.info(f"GCS Bucket: {config['gcs_bucket']}")
        self.logger.info(f"Data patterns: {config['file_patterns']}")

        return config

    def _get_config_value(self, env_var, prefect_var, default=None):
        """Get configuration value from environment or Prefect variables"""
        # First try environment variable
        value = os.getenv(env_var)
        if value:
            return value

        # Then try Prefect variable (for cloud deployment)
        try:
            value = variables.get(prefect_var)
            if value:
                return value
        except Exception:
            pass

        # Return default
        return default

    def setup_gcs_client(self):
        """Initialize and validate Google Cloud Storage client"""
        try:
            # Handle GCS credentials - can be file path or JSON string
            gcs_creds = self.config["gcs_credentials"]

            if gcs_creds.startswith("/"):
                # File path
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = gcs_creds
                self.gcs_client = storage.Client()
            else:
                # JSON string (from Prefect variables)
                import json
                from google.oauth2 import service_account

                credentials_info = json.loads(gcs_creds)
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_info
                )
                self.gcs_client = storage.Client(credentials=credentials)

            self.gcs_bucket = self.gcs_client.bucket(self.config["gcs_bucket"])

            # Validate bucket access
            self.gcs_bucket.reload()

            self.logger.info(f"GCS client initialized successfully")
            self.logger.info(f"Connected to bucket: {self.config['gcs_bucket']}")

        except Exception as e:
            self.logger.error(f"Failed to initialize GCS client: {e}")
            raise

    def establish_ftp_connection(self):
        """Establish and validate FTP connection (not a task - for internal use)"""
        try:
            ftp = ftplib.FTP()
            ftp.connect(self.config["ftp_host"], self.config["ftp_port"])
            ftp.login(self.config["ftp_username"], self.config["ftp_password"])

            if self.config["ftp_path"] and self.config["ftp_path"] != "/":
                ftp.cwd(self.config["ftp_path"])

            return ftp

        except Exception as e:
            raise

    def get_config_dict(self):
        """Return config as a simple dict for task functions"""
        return dict(self.config)

    def check_file_exists_in_gcs(self, gcs_path, local_filepath):
        """
        Check if file already exists in GCS with same content

        Args:
            gcs_path (str): GCS object path
            local_filepath (Path): Local file path

        Returns:
            bool: True if file exists and is identical
        """
        try:
            blob = self.gcs_bucket.blob(gcs_path)

            if not blob.exists():
                return False

            # Compare file sizes first (quick check)
            local_size = local_filepath.stat().st_size
            blob.reload()

            if blob.size != local_size:
                self.logger.debug(
                    f"Size mismatch for {gcs_path}: local={local_size}, gcs={blob.size}"
                )
                return False

            self.logger.debug(f"File exists in GCS with matching size: {gcs_path}")
            return True

        except Exception as e:
            self.logger.warning(
                f"Error checking GCS file existence for {gcs_path}: {e}"
            )
            return False

    def cleanup_temp_directory(self):
        """
        Clean up temporary directory and all its contents
        """
        if self.temp_dir and Path(self.temp_dir).exists():
            try:
                shutil.rmtree(self.temp_dir)
                self.logger.info(f"Cleaned up temporary directory: {self.temp_dir}")
            except Exception as e:
                self.logger.warning(
                    f"Failed to cleanup temp directory {self.temp_dir}: {e}"
                )
            finally:
                self.temp_dir = None

    def run_synchronization(self):
        """Execute the complete synchronization process using Prefect flow"""
        return self.run_synchronization_internal()

    def run_synchronization_internal(self):
        """Execute the complete synchronization process using Prefect flow"""
        logger = get_run_logger()
        logger.info("=" * 60)
        logger.info("STARTING HYDROLOGY DATA SYNCHRONIZATION")
        logger.info("=" * 60)

        sync_results = {
            "status": "failed",
            "start_time": datetime.now(),
            "files_discovered": 0,
            "files_downloaded": 0,
            "download_failures": 0,
            "files_uploaded": 0,
            "upload_failures": 0,
            "files_skipped": 0,
            "errors": [],
        }

        try:
            # Step 1: Connect to FTP and download files
            download_result = ftp_download_task(self.get_config_dict())
            downloaded_files = download_result["downloaded_files"]

            sync_results["files_discovered"] = (
                download_result["download_count"] + download_result["failure_count"]
            )
            sync_results["files_downloaded"] = download_result["download_count"]
            sync_results["download_failures"] = download_result["failure_count"]

            if not downloaded_files:
                logger.warning("No files downloaded - synchronization complete")
                sync_results["status"] = "success"
                return sync_results

            # Step 2: Upload to GCS
            uploaded, upload_failures, skipped = gcs_upload_task(
                self.get_config_dict(), downloaded_files
            )
            sync_results["files_uploaded"] = uploaded
            sync_results["upload_failures"] = upload_failures
            sync_results["files_skipped"] = skipped

            # Step 3: Cleanup temporary files
            self.cleanup_temp_directory()

            sync_results["status"] = "success"

        except Exception as e:
            error_msg = f"Synchronization failed: {e}"
            logger.error(error_msg)
            sync_results["errors"].append(error_msg)

            sync_results["end_time"] = datetime.now()
            sync_results["duration"] = (
                sync_results["end_time"] - sync_results["start_time"]
            )

            self.log_synchronization_summary(sync_results)

        return sync_results

    def log_synchronization_summary(self, results):
        """Log comprehensive synchronization summary"""
        self.logger.info("=" * 60)
        self.logger.info("SYNCHRONIZATION SUMMARY")
        self.logger.info("=" * 60)
        self.logger.info(f"Status: {results['status'].upper()}")
        self.logger.info(f"Duration: {results['duration']}")
        self.logger.info(f"Files discovered: {results['files_discovered']}")
        self.logger.info(f"Files downloaded: {results['files_downloaded']}")
        self.logger.info(f"Download failures: {results['download_failures']}")
        self.logger.info(f"Files uploaded to GCS: {results['files_uploaded']}")
        self.logger.info(f"Upload failures: {results['upload_failures']}")
        self.logger.info(f"Files skipped (duplicates): {results['files_skipped']}")

        if results["errors"]:
            self.logger.error("Errors encountered:")
            for error in results["errors"]:
                self.logger.error(f"  - {error}")

        self.logger.info("=" * 60)


# Standalone Prefect tasks (outside class to avoid serialization issues)
@task(
    name="ftp-download-files",
    retries=3,
    retry_delay_seconds=60,
    description="Connect to FTP, discover and download hydrology files",
    result_storage=None,
    persist_result=False,
)
def ftp_download_task(config):
    """Connect to FTP, discover target files and download them"""
    logger = get_run_logger()

    # Establish FTP connection
    logger.info(
        f"Establishing FTP connection to {config['ftp_host']}:{config['ftp_port']}"
    )

    try:
        ftp = ftplib.FTP()
        ftp.connect(config["ftp_host"], config["ftp_port"])
        ftp.login(config["ftp_username"], config["ftp_password"])

        if config["ftp_path"] and config["ftp_path"] != "/":
            ftp.cwd(config["ftp_path"])

        logger.info("FTP authentication successful")

        # Discover target files
        logger.info("Discovering target hydrology data files...")
        all_files = ftp.nlst()

        target_files = []
        for filename in all_files:
            if filename.endswith(config["file_extension"]) and any(
                pattern in filename for pattern in config["file_patterns"]
            ):
                target_files.append(filename)

        logger.info(f"Discovered {len(target_files)} target files:")
        for filename in sorted(target_files):
            logger.info(f"  - {filename}")

        if not target_files:
            return {
                "downloaded_files": [],
                "failed_downloads": [],
                "download_count": 0,
                "failure_count": 0,
            }

        # Create temporary directory for downloads
        temp_dir = tempfile.mkdtemp(prefix="hydrology_sync_")
        local_dir = Path(temp_dir)

        logger.info(f"Downloading {len(target_files)} files to {local_dir}")

        successful_downloads = []
        failed_downloads = []

        for filename in target_files:
            local_filepath = local_dir / filename

            try:
                logger.info(f"Downloading: {filename}")

                with open(local_filepath, "wb") as local_file:
                    ftp.retrbinary(f"RETR {filename}", local_file.write)

                file_size = local_filepath.stat().st_size
                logger.info(f"Downloaded: {filename} ({file_size:,} bytes)")
                successful_downloads.append(str(local_filepath))

            except Exception as e:
                logger.error(f"Failed to download {filename}: {e}")
                failed_downloads.append(filename)

                if local_filepath.exists():
                    local_filepath.unlink()

        return {
            "downloaded_files": successful_downloads,
            "failed_downloads": failed_downloads,
            "download_count": len(successful_downloads),
            "failure_count": len(failed_downloads),
        }

    finally:
        try:
            ftp.quit()
            logger.info("FTP connection closed")
        except:
            pass


@task(
    name="upload-to-gcs",
    retries=3,
    retry_delay_seconds=30,
    description="Upload files to Google Cloud Storage",
    result_storage=None,
    persist_result=False,
)
def gcs_upload_task(config, downloaded_files):
    """Upload files to Google Cloud Storage with duplicate prevention"""
    logger = get_run_logger()

    # Setup GCS client with flexible credential handling
    gcs_creds = config["gcs_credentials"]

    if gcs_creds.startswith("/"):
        # File path
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = gcs_creds
        client = storage.Client()
    else:
        # JSON string (from Prefect variables)
        import json
        from google.oauth2 import service_account

        credentials_info = json.loads(gcs_creds)
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info
        )
        client = storage.Client(credentials=credentials)

    bucket = client.bucket(config["gcs_bucket"])

    date_str = datetime.now().strftime("%Y%m%d")
    successful_uploads = 0
    failed_uploads = 0
    skipped_uploads = 0

    logger.info(
        f"Uploading {len(downloaded_files)} files to GCS bucket: {config['gcs_bucket']}"
    )

    for file_path_str in downloaded_files:
        local_filepath = Path(file_path_str)

        try:
            gcs_object_path = f"{config['gcs_prefix']}/{date_str}/{local_filepath.name}"

            # Check if file already exists (basic check)
            blob = bucket.blob(gcs_object_path)
            if config["skip_existing_files"] and blob.exists():
                blob.reload()
                local_size = local_filepath.stat().st_size
                if blob.size == local_size:
                    logger.info(f"Skipping existing file: {local_filepath.name}")
                    skipped_uploads += 1
                    continue

            logger.info(f"Uploading: {local_filepath.name}")
            blob.upload_from_filename(str(local_filepath))

            logger.info(f"Uploaded: gs://{config['gcs_bucket']}/{gcs_object_path}")
            successful_uploads += 1

        except Exception as e:
            logger.error(f"Failed to upload {local_filepath.name}: {e}")
            failed_uploads += 1

    return successful_uploads, failed_uploads, skipped_uploads


# Standalone flow function for Prefect Cloud deployment
@flow(
    name="hydrology-data-sync",
    description="IGAD-ICPAC Hydrology Data Synchronization Pipeline",
    retries=2,
    retry_delay_seconds=300,
)
def hydrology_sync_flow():
    """Standalone flow function for Prefect Cloud deployment"""
    sync_tool = HydrologyDataSync()
    return sync_tool.run_synchronization_internal()


def main():
    """Main entry point for the synchronization tool"""
    try:
        # Initialize and run synchronization
        sync_tool = HydrologyDataSync()
        results = sync_tool.run_synchronization()

        # Exit with appropriate code
        exit_code = 0 if results["status"] == "success" else 1
        sys.exit(exit_code)

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
