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

        self.logger.info("Hydrology Data Sync v2.0.0 - Starting session")

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
            # Check if we're in a Prefect context
            from prefect import get_run_context
            get_run_context()
            value = variables.get(prefect_var)
            if value:
                return value
        except Exception:
            # Not in Prefect context or variable doesn't exist
            pass

        # Return default
        return default

    def setup_gcs_client(self):
        """Initialize and validate Google Cloud Storage client"""
        try:
            # Handle GCS credentials - can be file path, JSON string, or dict
            gcs_creds = self.config["gcs_credentials"]
            
            self.logger.info(f"GCS credentials type: {type(gcs_creds)}")

            if not gcs_creds:
                raise ValueError("GCS credentials are missing. Please check the 'gcs-credentials' Prefect variable.")

            if isinstance(gcs_creds, str) and gcs_creds.startswith("/"):
                # File path
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = gcs_creds
                self.gcs_client = storage.Client()
            elif isinstance(gcs_creds, dict):
                # Already parsed dict (from Prefect variables)
                from google.oauth2 import service_account
                
                credentials = service_account.Credentials.from_service_account_info(gcs_creds)
                self.gcs_client = storage.Client(credentials=credentials)
            else:
                # JSON string (from Prefect variables or env)
                import json
                from google.oauth2 import service_account

                if isinstance(gcs_creds, str) and (gcs_creds == '"{' or len(gcs_creds) < 10):
                    self.logger.error(f"GCS credentials appear incomplete: '{gcs_creds}'")
                    raise ValueError("GCS credentials are incomplete. Please check the 'gcs-credentials' Prefect variable.")

                try:
                    # Try to parse as JSON
                    credentials_info = json.loads(gcs_creds)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Failed to parse GCS credentials as JSON. Error: {e}")
                    raise ValueError(
                        "GCS credentials must be valid JSON. Please ensure the 'gcs-credentials' "
                        "Prefect variable contains the complete service account JSON key."
                    )
                
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

        except Exception:
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
        try:
            logger = get_run_logger()
        except:
            # Not in Prefect context, use regular logger
            logger = self.logger
            
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

    def connect_ftp_with_retry():
        """Connect to FTP with comprehensive connection strategies"""
        import socket
        import time
        
        connection_strategies = [
            # Strategy 1: Passive mode with standard timeout
            {"pasv": True, "timeout": 30, "encoding": "utf-8"},
            # Strategy 2: Passive mode with longer timeout 
            {"pasv": True, "timeout": 60, "encoding": "utf-8"},
            # Strategy 3: Active mode with standard timeout
            {"pasv": False, "timeout": 30, "encoding": "utf-8"},
            # Strategy 4: Active mode with longer timeout
            {"pasv": False, "timeout": 60, "encoding": "utf-8"},
            # Strategy 5: Passive mode with latin-1 encoding (some servers need this)
            {"pasv": True, "timeout": 45, "encoding": "latin-1"},
            # Strategy 6: Active mode with no data timeout (last resort)
            {"pasv": False, "timeout": 90, "encoding": "utf-8", "no_data_timeout": True},
        ]
        
        for i, strategy in enumerate(connection_strategies, 1):
            ftp = None
            try:
                logger.info(f"FTP connection attempt {i}/{len(connection_strategies)}: "
                          f"pasv={strategy['pasv']}, timeout={strategy['timeout']}s, "
                          f"encoding={strategy['encoding']}")
                
                # Create FTP instance with specific settings
                ftp = ftplib.FTP()
                
                # Set socket timeout for connection
                ftp.sock = None
                
                # Connect with timeout
                logger.info(f"Connecting to {config['ftp_host']}:{config['ftp_port']}...")
                ftp.connect(config["ftp_host"], config["ftp_port"], timeout=strategy['timeout'])
                
                # Set encoding
                ftp.encoding = strategy['encoding']
                
                # Login
                logger.info("Logging in...")
                ftp.login(config["ftp_username"], config["ftp_password"])
                
                # Set passive/active mode
                logger.info(f"Setting {'passive' if strategy['pasv'] else 'active'} mode...")
                ftp.set_pasv(strategy['pasv'])
                
                # For problematic servers, try setting socket options
                if hasattr(ftp, 'sock') and ftp.sock:
                    try:
                        ftp.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                        ftp.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    except:
                        pass  # Ignore if not supported
                
                # Change to target directory
                if config["ftp_path"] and config["ftp_path"] != "/":
                    logger.info(f"Changing to directory: {config['ftp_path']}")
                    ftp.cwd(config["ftp_path"])
                
                # Test connection with PWD command
                logger.info("Testing connection...")
                current_dir = ftp.pwd()
                logger.info(f"Current directory: {current_dir}")
                
                # Try a simple list command to test data connection
                logger.info("Testing data connection...")
                try:
                    # Use a timeout wrapper for data operations if needed
                    if strategy.get('no_data_timeout'):
                        # For problematic servers, try without explicit timeouts
                        test_files = ftp.nlst('.')[:1]  # Just get one file
                    else:
                        # Set a reasonable timeout for data connections
                        old_timeout = ftp.sock.gettimeout() if ftp.sock else None
                        if ftp.sock:
                            ftp.sock.settimeout(strategy['timeout'])
                        test_files = ftp.nlst('.')[:1]  # Just get one file
                        if ftp.sock and old_timeout:
                            ftp.sock.settimeout(old_timeout)
                    
                    logger.info(f"Data connection test successful - found {len(test_files)} test files")
                    
                except Exception as data_e:
                    logger.warning(f"Data connection test failed: {data_e}")
                    # For some servers, data connection might fail initially but work later
                    # Don't fail immediately, but log the issue
                
                logger.info(f"FTP connection successful with strategy {i}")
                return ftp
                
            except Exception as e:
                logger.warning(f"FTP strategy {i} failed: {type(e).__name__}: {e}")
                try:
                    if ftp:
                        ftp.quit()
                except:
                    try:
                        if ftp:
                            ftp.close()
                    except:
                        pass
                
                # Add delay between attempts to avoid overwhelming the server
                if i < len(connection_strategies):
                    time.sleep(2)
                    
                if i == len(connection_strategies):
                    raise ConnectionError(f"All FTP connection strategies failed. Last error: {e}")
                continue
    
    try:
        ftp = connect_ftp_with_retry()

        # Discover target files with multiple methods
        logger.info("Discovering target hydrology data files...")
        all_files = []
        
        # Try different listing methods
        listing_methods = [
            ("nlst()", lambda: ftp.nlst()),
            ("LIST parsing", lambda: [line.split()[-1] for line in ftp.nlst() if line.strip()]),
        ]
        
        for method_name, method_func in listing_methods:
            try:
                logger.info(f"Trying {method_name}...")
                all_files = method_func()
                if all_files:
                    logger.info(f"Successfully got file list using {method_name}")
                    break
            except Exception as e:
                logger.warning(f"{method_name} failed: {e}")
                continue
        
        if not all_files:
            # Last resort: try to get files one by one using common patterns
            logger.info("Trying pattern-based file discovery...")
            patterns = config["file_patterns"]
            for pattern in patterns:
                try:
                    test_files = ftp.nlst(f"*{pattern}*")
                    all_files.extend(test_files)
                except:
                    pass

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

    if isinstance(gcs_creds, str) and gcs_creds.startswith("/"):
        # File path
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = gcs_creds
        client = storage.Client()
    elif isinstance(gcs_creds, dict):
        # Already parsed dict
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_info(gcs_creds)
        client = storage.Client(credentials=credentials)
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


def list_ftp_files():
    """List all files on FTP server for debugging"""
    from dotenv import load_dotenv
    load_dotenv()
    
    try:
        print("=== FTP FILE LISTING ===")
        ftp_host = os.getenv("FTP_HOST")
        ftp_port = int(os.getenv("FTP_PORT", "21"))
        ftp_username = os.getenv("FTP_USERNAME")
        ftp_password = os.getenv("FTP_PASSWORD")
        ftp_path = os.getenv("FTP_PATH", "/")
        
        print(f"Connecting to {ftp_host}:{ftp_port}")
        print(f"Path: {ftp_path}")
        
        # Use robust connection with multiple strategies
        connection_strategies = [
            {"pasv": True, "timeout": 30, "encoding": "utf-8"},
            {"pasv": True, "timeout": 60, "encoding": "utf-8"}, 
            {"pasv": False, "timeout": 30, "encoding": "utf-8"},
            {"pasv": False, "timeout": 60, "encoding": "utf-8"},
            {"pasv": True, "timeout": 45, "encoding": "latin-1"},
        ]
        
        ftp = None
        for i, strategy in enumerate(connection_strategies, 1):
            try:
                print(f"Connection attempt {i}/{len(connection_strategies)}: "
                      f"pasv={strategy['pasv']}, timeout={strategy['timeout']}s")
                
                ftp = ftplib.FTP()
                ftp.connect(ftp_host, ftp_port, timeout=strategy['timeout'])
                ftp.encoding = strategy['encoding']
                ftp.login(ftp_username, ftp_password)
                ftp.set_pasv(strategy['pasv'])
                
                # Test connection
                ftp.pwd()
                print(f"Connection successful with strategy {i}")
                break
                
            except Exception as e:
                print(f"Strategy {i} failed: {e}")
                if ftp:
                    try:
                        ftp.quit()
                    except:
                        try:
                            ftp.close()
                        except:
                            pass
                ftp = None
                if i == len(connection_strategies):
                    raise
                continue
        
        if not ftp:
            raise ConnectionError("All connection strategies failed")
        
        if ftp_path and ftp_path != "/":
            ftp.cwd(ftp_path)
            
        print(f"Current directory: {ftp.pwd()}")
        
        # Try different connection modes with robust error handling
        modes = [
            ("passive", True, 30), 
            ("passive (extended timeout)", True, 60),
            ("active", False, 30),
            ("active (extended timeout)", False, 60)
        ]
        
        for mode_name, pasv_mode, timeout in modes:
            try:
                print(f"\nTrying {mode_name} mode (timeout: {timeout}s)...")
                ftp.set_pasv(pasv_mode)
                
                # Set socket timeout if available
                if hasattr(ftp, 'sock') and ftp.sock:
                    ftp.sock.settimeout(timeout)
                
                # Quick test with pwd
                pwd_result = ftp.pwd()
                print(f"PWD works: {pwd_result}")
                
                # Try file listing with multiple methods and fallback strategies
                files = []
                
                def parse_list_output():
                    """Parse LIST command output to get filenames"""
                    lines = []
                    ftp.retrlines('LIST', lines.append)
                    filenames = []
                    for line in lines:
                        if line.strip() and not line.startswith('total'):
                            parts = line.split()
                            if len(parts) >= 9 and not line.startswith('d'):  # Not a directory
                                filename = ' '.join(parts[8:])  # Handle filenames with spaces
                                if filename not in ['.', '..']:
                                    filenames.append(filename)
                    return filenames
                
                listing_methods = [
                    ("nlst()", lambda: ftp.nlst()),
                    ("nlst('.')", lambda: ftp.nlst('.')),  
                    ("nlst('*')", lambda: ftp.nlst('*')),
                    ("LIST parsing", parse_list_output),
                    ("DIR command", lambda: [line.split()[-1] for line in ftp.nlst() if line.strip()]),
                ]
                
                for method_name, method_func in listing_methods:
                    try:
                        print(f"  Trying {method_name}...")
                        
                        # For data connection issues, try switching modes temporarily
                        original_pasv = None
                        try:
                            files = method_func()
                            if files:
                                print(f"  Success with {method_name}")
                                break
                        except (ConnectionResetError, BrokenPipeError, OSError) as data_err:
                            print(f"  Data connection failed with {method_name}: {data_err}")
                            # Try switching passive/active mode for this operation
                            if hasattr(ftp, '_pasv'):
                                original_pasv = ftp._pasv
                                try:
                                    ftp.set_pasv(not original_pasv)
                                    print(f"    Retrying with {'passive' if not original_pasv else 'active'} mode...")
                                    files = method_func()
                                    if files:
                                        print(f"  Success with {method_name} after mode switch")
                                        break
                                except Exception as retry_e:
                                    print(f"    Mode switch retry failed: {retry_e}")
                                finally:
                                    # Restore original mode
                                    if original_pasv is not None:
                                        try:
                                            ftp.set_pasv(original_pasv)
                                        except:
                                            pass
                        
                    except Exception as list_e:
                        print(f"  {method_name} failed: {type(list_e).__name__}: {list_e}")
                        continue
                
                if files:
                    print(f"Found {len(files)} files:")
                    for f in files[:10]:  # Show first 10 files
                        print(f"  {f}")
                    if len(files) > 10:
                        print(f"  ... and {len(files) - 10} more files")
                else:
                    print("No files found with any listing method")
                    
                break  # Success, exit loop
                
            except Exception as e:
                print(f"{mode_name} mode failed: {type(e).__name__}: {e}")
                continue
            
        ftp.quit()
        
    except Exception as e:
        print(f"Error: {e}")

def main():
    """Main entry point for the synchronization tool"""
    import sys
    
    # Check if we want to list files
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        list_ftp_files()
        return
        
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
