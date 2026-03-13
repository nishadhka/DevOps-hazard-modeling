# Complete CI/CD Pipeline Deployment Guide

## Workflow: GitHub → Actions → Staging → Prefect Cloud → GCS

```mermaid
flowchart TD
    A[GitHub Repository] --> B[GitHub Actions]
    B --> C[Deploy to Staging Server]
    C --> D[Prefect Worker]
    D --> E[Prefect Cloud]
    E --> F[Execute Flow]
    F --> G[FTP Server]
    F --> H[Google Cloud Storage]
    
    style A fill:#f9f9f9
    style E fill:#4285f4,color:#fff
    style H fill:#34a853,color:#fff
```

## Quick Setup (30 minutes)

### 1. Staging Server Setup
```bash
# Run this on your staging server
curl -sSL https://raw.githubusercontent.com/icpac-igad/DevOps-hazard-modeling/gcs_upload/scripts/setup-staging-worker.sh | bash
```

### 2. GitHub Secrets Configuration
Add these secrets in GitHub Settings → Secrets and Variables → Actions:

```
STAGING_HOST=your.staging.server.ip
STAGING_USER=hydrology-pipeline
STAGING_SSH_KEY=-----BEGIN OPENSSH PRIVATE KEY-----...
PREFECT_API_KEY=pnu_xxxxxxxxxxxxxxxxxxxx
```

### 3. Prefect Cloud Setup
1. Create work pool: `staging-hydrology-pool` (Process type)
2. Get API key from Account Settings → API Keys

### 4. Deploy
```bash
git push origin gcs_upload
# GitHub Actions will automatically deploy!
```

## Detailed Implementation

### GitHub Actions Pipeline (`.github/workflows/deploy-staging.yml`)

**Triggers:**
- Push to `main` or `gcs_upload` branches
- Manual workflow dispatch

**Steps:**
1. **Test Phase**
   - Code quality checks (flake8)
   - Import validation
   - Basic functionality tests

2. **Deploy Phase**
   - SSH to staging server
   - Pull latest code
   - Update dependencies
   - Test deployment

3. **Update Phase**
   - Update Prefect deployment
   - Restart worker service
   - Health checks

4. **Notify Phase**
   - Deployment status
   - Summary report

### Staging Server Architecture

```
/home/hydrology-pipeline/
├── hydrology-sync/
│   ├── venv/                    # Python virtual environment
│   ├── DevOps-hazard-modeling/  # Your code repository
│   ├── health-check.sh          # Monitoring script
│   └── backups/                 # Deployment backups
├── .config/hydrology-sync/
│   └── gcs-key.json            # GCS credentials
└── .bashrc                     # Environment variables
```

### Prefect Worker Service

**Service:** `prefect-hydrology-worker.service`
- **Type:** systemd service
- **Auto-restart:** Yes
- **Logs:** `journalctl -u prefect-hydrology-worker -f`

### Flow Execution Process

1. **Scheduled Trigger** (every 4 hours in staging)
2. **Prefect Cloud** dispatches work to staging pool
3. **Staging Worker** receives and executes flow
4. **Flow Steps:**
   - Connect to FTP server
   - Download hydrology files
   - Upload to GCS bucket
   - Clean up temporary files
   - Log results

## Monitoring & Maintenance

### Health Checks
```bash
# Manual health check
~/hydrology-sync/health-check.sh

# Check worker status
sudo systemctl status prefect-hydrology-worker

# View recent logs
sudo journalctl -u prefect-hydrology-worker --since "1 hour ago"
```

### Monitoring Dashboard
- **Prefect Cloud:** Flow run history and metrics
- **GCS Console:** File upload verification
- **Server Logs:** System-level monitoring

### Troubleshooting

**Common Issues:**

1. **Worker Not Starting**
   ```bash
   # Check service status
   sudo systemctl status prefect-hydrology-worker
   
   # Check logs
   sudo journalctl -u prefect-hydrology-worker -n 50
   
   # Restart service
   sudo systemctl restart prefect-hydrology-worker
   ```

2. **Flow Failures**
   ```bash
   # Check flow logs in Prefect Cloud
   # Or check local logs
   tail -f ~/hydrology-sync/DevOps-hazard-modeling/logs/*.log
   ```

3. **Deployment Failures**
   - Check GitHub Actions logs
   - Verify SSH connectivity
   - Ensure secrets are properly set

## Environment-Specific Configurations

### Staging (.env.staging)
- **Schedule:** Every 4 hours
- **Retries:** 2 attempts
- **Log Level:** INFO
- **Bucket:** staging-bucket

### Production (Future)
- **Schedule:** Daily at midnight
- **Retries:** 3 attempts
- **Log Level:** WARNING
- **Bucket:** production-bucket

## Security Best Practices

1. **Credentials Management**
   - GCS key stored in protected directory (`chmod 600`)
   - Prefect API key in GitHub secrets
   - SSH keys with proper permissions

2. **Network Security**
   - SSH key authentication only
   - Firewall rules for FTP access
   - VPN or private network recommended

3. **Code Security**
   - No secrets in code repository
   - Environment variable usage
   - Regular dependency updates

## Cost Optimization

**Staging Server Benefits:**
- Fixed monthly cost vs pay-per-execution
- No cold start delays
- Persistent storage for caching
- Full debugging capabilities

**Estimated Costs:**
- **Small VPS:** $10-20/month
- **Cloud Run:** $5-50/month (variable)
- **GCS Storage:** $0.02/GB/month

## Next Steps

1. **Production Deployment**
   - Create production work pool
   - Set up production server
   - Configure production schedule

2. **Enhanced Monitoring**
   - Grafana dashboard
   - Alerting system
   - Performance metrics

3. **Advanced Features**
   - Multi-region deployment
   - Auto-scaling workers
   - Data validation pipelines

## Support

- **Repository:** https://github.com/icpac-igad/DevOps-hazard-modeling
- **Issues:** Create GitHub issues for problems
- **Documentation:** This file and code comments