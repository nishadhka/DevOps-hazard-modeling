# Hazard Modeling DevOps Setup

This repository contains the configuration for running hazard modeling scripts as a containerized application on Kubernetes, managed by ArgoCD, and deployed locally using Minikube.

## Project Structure

```
.
├── 01-pet-process-1km.py           # Python processing script
├── 02-gef-chirps-process-1km.py    # Python processing script
├── 03-imerg-process-1km.py         # Python processing script
├── data                            # Data directory
│   ├── geofsm-input                # Input data
│   ├── PET                         # PET data
│   ├── WGS                         # Shapefile data
│   └── zone_wise_txt_files         # Zone text files
├── utils.py                        # Utility functions
├── Dockerfile                      # Docker image definition
├── requirements.txt                # Python dependencies
├── k8s                             # Kubernetes manifests
│   ├── deployment.yaml             # CronJob definition
│   ├── namespace.yaml              # Namespace definition
│   ├── pvc.yaml                    # Persistent Volume Claims
│   └── kustomization.yaml          # Kustomize configuration
├── argocd                          # ArgoCD configuration
│   └── application.yaml            # ArgoCD Application
└── deploy-local.sh                 # Deployment script
```

## Prerequisites

- Docker
- Minikube
- kubectl
- Git

## Setup Instructions

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Make the deployment script executable:
   ```bash
   chmod +x deploy-local.sh
   ```

3. Run the deployment script:
   ```bash
   ./deploy-local.sh
   ```
   This will:
   - Start Minikube if it's not running
   - Build the Docker image
   - Configure Kubernetes manifests
   - Apply the manifests to create necessary resources
   - Install ArgoCD if it's not already installed
   - Create the ArgoCD application
   - Trigger an initial job run

4. Access ArgoCD UI:
   The script will output the URL, username, and password for ArgoCD.

## Configuration

### CronJob Schedule

The hazard modeling job is configured to run daily at midnight. You can modify the schedule in `k8s/deployment.yaml`:

```yaml
spec:
  schedule: "0 0 * * *"  # Cron schedule (current: daily at midnight)
```

### Resource Requirements

You can adjust the CPU and memory requirements in the `k8s/deployment.yaml` file:

```yaml
resources:
  requests:
    memory: "2Gi"
    cpu: "500m"
  limits:
    memory: "4Gi"
    cpu: "1000m"
```

### Storage

The application uses two Persistent Volume Claims:
- `hazard-data-pvc`: For input data (10Gi)
- `hazard-output-pvc`: For output data (5Gi)

You can adjust the storage sizes in `k8s/pvc.yaml`.

## Manual Job Execution

To manually trigger the job:

```bash
kubectl create job --from=cronjob/hazard-modeling hazard-modeling-manual -n hazard-modeling
```

## Viewing Logs

To check logs from the most recent job:

```bash
kubectl get pods -n hazard-modeling
kubectl logs <pod-name> -n hazard-modeling
```

## Scaling to Production

For production use:

1. Use a container registry like Docker Hub, GitHub Container Registry, or a private registry
2. Set up a CI/CD pipeline to build and push images automatically
3. Configure proper secrets management for sensitive data
4. Use dedicated persistent storage solutions
5. Consider implementing monitoring and alerting
6. Set up proper backup and disaster recovery procedures
## License

This project is licensed under the MIT License - see the LICENSE file for details.

---

# IGAD-ICPAC Hydrology Data Synchronization

Cloud-native pipeline for synchronizing hydrology data (riverdepth and streamflow) from FTP server to Google Cloud Storage using Prefect orchestration with GitHub-based deployment.

## 🚀 Features

- **Zero Local Storage**: Uses temporary directories with automatic cleanup
- **Smart Duplicate Prevention**: Prevents uploading duplicate files by comparing file sizes
- **Google Cloud Storage Upload**: Uploads files to GCS with organized folder structure
- **GitHub Integration**: Direct deployment from repository
- **Prefect Cloud Native**: Fully managed execution with retry logic
- **Container Ready**: Docker support for consistent environments
- **CI/CD Pipeline**: Automated testing and deployment via GitHub Actions
- **Comprehensive Logging**: Detailed logging for monitoring and debugging
- **Scheduled Execution**: Runs daily at midnight UTC with manual triggers

## 🏗️ Architecture

```
GitHub Repository → Prefect Cloud → Managed Workers
     ↓                    ↓              ↓
FTP Server → Temp Storage → GCS Upload → Cleanup
     ↓              ↓            ↓          ↓
  Discovery    Processing   Organized   No Files
   & Filter    in Memory    Storage     Left Behind
```

## 📁 Project Structure

```
geosfm/gcs_upload/
├── ftp_to_gcs_sync.py    # Main synchronization script
├── prefect.yaml          # Prefect deployment configuration
├── deploy.py             # Deployment automation script
├── Dockerfile            # Container configuration
├── requirements.txt      # Python dependencies
├── README.md             # This file
├── DEPLOYMENT.md         # Detailed deployment guide
└── .env.example          # Environment template
```

## ⚡ Quick Start (Recommended)

### Option 1: GitHub Actions Deployment (Production)

1. **Set up GitHub Secrets** in your repository settings:
   ```
   PREFECT_API_KEY=your_prefect_api_key
   PREFECT_ACCOUNT_ID=your_account_id  
   PREFECT_WORKSPACE_ID=your_workspace_id
   FTP_HOST=your_ftp_server
   FTP_USERNAME=your_username
   FTP_PASSWORD=your_password
   FTP_PATH=/output/
   GCS_BUCKET=your_bucket_name
   GCS_CREDENTIALS={"type":"service_account",...}
   ```

2. **Push to main branch** - GitHub Actions will automatically:
   - Run tests and linting
   - Deploy to Prefect Cloud
   - Build and push Docker image

3. **Monitor** in Prefect Cloud UI

### Option 2: Manual Deployment (Development)

1. **Prerequisites**:
   ```bash
   pip install prefect>=3.4.0 google-cloud-storage python-dotenv
   prefect cloud login
   ```

2. **Set up environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Deploy**:
   ```bash
   python deploy.py
   ```

## 🔧 Configuration

### Required Environment Variables/Secrets

| Variable | Description | Example |
|----------|-------------|---------|
| `FTP_HOST` | FTP server hostname | `ftp.example.com` |
| `FTP_USERNAME` | FTP username | `hydro_user` |
| `FTP_PASSWORD` | FTP password | `secure_password` |
| `FTP_PATH` | FTP directory path | `/output/` |
| `GCS_BUCKET` | GCS bucket name | `icpac-hydrology-data` |
| `GCS_PREFIX` | GCS folder prefix | `hydrology_data` |
| `GCS_CREDENTIALS` | Service account JSON | `{"type":"service_account",...}` |

### Prefect Cloud Variables
The system automatically creates these Prefect variables:
- `ftp-host`, `ftp-username`, `ftp-password`, `ftp-path`
- `gcs-bucket`, `gcs-prefix`, `gcs-credentials`

## 🐳 Container Deployment

Build and run locally:
```bash
docker build -t hydrology-pipeline .
docker run --env-file .env hydrology-pipeline
```

Or use the automated GitHub image:
```bash
docker pull ghcr.io/igad-icpac/devops-hazard-modeling/hydrology-pipeline:latest
```

## 📊 Monitoring & Operations

### Deployment Status
- **Scheduled Flow**: `hydrology-midnight-sync` - Daily at 00:00 UTC
- **Manual Flow**: `hydrology-on-demand` - Trigger anytime
- **Work Pool**: ` geosfm-cloud-pool` (managed infrastructure)

### Logs & Debugging
- **Prefect Cloud UI**: Real-time flow execution logs
- **GitHub Actions**: CI/CD pipeline logs
- **Local Logs**: `logs/` directory (development only)

### Key Metrics
- Files discovered vs downloaded
- Upload success/failure rates  
- Duplicate detection efficiency
- Execution duration and resource usage

## 🚦 What to Do From Here

### Immediate Next Steps:
1. **Set up GitHub Secrets** with your credentials
2. **Test the pipeline** with a manual trigger
3. **Monitor scheduled runs** for the first week
4. **Set up alerting** for failures (optional)

### Production Considerations:
1. **Backup Strategy**: Consider GCS lifecycle policies for cost optimization
2. **Monitoring**: Set up alerts for pipeline failures
3. **Scaling**: Adjust work pool concurrency if needed
4. **Security**: Regular credential rotation

### Development Workflow:
1. **Make changes** in `geosfm/gcs_upload/`
2. **Test locally** using Option 2 deployment
3. **Create PR** - triggers automated testing
4. **Merge to main** - triggers production deployment

## 🔍 Troubleshooting

### Common Issues:
- **Missing credentials**: Check Prefect variables in cloud UI
- **FTP connection**: Verify firewall and network access
- **GCS upload**: Validate service account permissions
- **Work pool**: Ensure ` geosfm-cloud-pool` exists

### Support:
- Check `DEPLOYMENT.md` for detailed instructions
- Review logs in Prefect Cloud UI
- Contact: Hillary Koros <hkoros@icpac.net>

## 🔄 Version History

- **v3.0.0**: GitHub integration, temporary storage, container support
- **v2.0.0**: Prefect Cloud deployment, managed workers
- **v1.0.0**: Initial FTP to GCS synchronization

## 📝 License

Internal use - IGAD-ICPAC
