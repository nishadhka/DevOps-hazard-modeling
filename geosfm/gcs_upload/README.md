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
