# Windows VM in GCP Deployment and Acess Guide

This guide will walk you through deploying a Windows Server VM on Google Cloud Platform using Terraform.

## Prerequisites

- [Terraform](https://www.terraform.io/downloads.html) (v1.0.0+) installed on your local machine
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed and configured
- A Google Cloud Platform account with billing enabled
- A GCP service account with appropriate permissions
- Service account credentials in JSON format

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/icpac-igad/DevOps-hazard-modeling.git 
cd DevOps-hazard-modeling/devops/
```

### 2. Configure Your Credentials

Create a `terraform.tfvars` file in the project directory with your specific values:

```hcl
credentials_file = "/path/to/your/service-account-key.json"
project_id       = "your-gcp-project-id"
region           = "us-central1-a"
vm_name          = "windows-vm-geofsm"
machine_type     = "n1-standard-2"
windows_image    = "windows-server-2016-dc-v20240516"
network          = "default"
tags             = ["ftp"]
ftp_source_ranges = ["0.0.0.0/0"]  # For production, restrict this to specific IP ranges
```

> **Important Security Note**: Never commit the `terraform.tfvars` file to version control. It contains sensitive information.

### 3. Initialize Terraform

Initialize Terraform to download the necessary providers:

```bash
terraform init
```

### 4. Plan Your Deployment

Create an execution plan to preview the changes Terraform will make:

```bash
terraform plan
```

Review the output carefully to ensure it aligns with your expectations.

### 5. Apply the Configuration

Deploy the infrastructure:

```bash
terraform apply
```

Type `yes` when prompted to confirm.

### 6. Access Your Windows VM

Once deployment is complete, Terraform will output information about your new VM. To connect to your Windows VM:

1. Go to the Google Cloud Console
2. Navigate to Compute Engine > VM instances
3. Find your VM named "windows-vm-geofsm" (or your custom name)
4. Click on "Set Windows password" to generate RDP credentials
5. Use an RDP client to connect to the VM's external IP address

#### Connecting with Remmina from Linux

[Remmina](https://remmina.org/) is a feature-rich remote desktop client for Linux. Here's how to connect to your Windows VM using Remmina:

1. **Install Remmina** (if not already installed):
   
   For Ubuntu/Debian:
   ```bash
   sudo apt update
   sudo apt install remmina remmina-plugin-rdp
   ```
   
   For Fedora:
   ```bash
   sudo dnf install remmina remmina-plugins-rdp
   ```
   
   For Arch Linux:
   ```bash
   sudo pacman -S remmina freerdp
   ```

2. **Launch Remmina** from your applications menu or terminal:
   ```bash
   remmina
   ```

3. **Create a new RDP connection**:
   - Click the "+" button to create a new connection
   - Select "RDP - Remote Desktop Protocol"
   
4. **Configure the connection**:
   - Name: Enter a descriptive name (e.g., "Windows-VM-GeoFSM")
   - Server: Enter your VM's external IP address
   - Username: Enter the Windows username (usually "Administrator" or the username you set)
   - Password: Enter the password generated from GCP Console
   - Domain: Leave blank (unless your VM is domain-joined)
   - Resolution: Choose your preferred resolution or set to "Use client resolution"
   - Color depth: Choose your preferred color depth (typically 16 or 32 bit)
   - Share folder: Optionally configure a local folder to share with the remote VM
   
5. **Advanced Settings** (optional):
   - Click on the "Advanced" tab
   - Security: Set to "Negotiate" or "TLS" for better security
   - Gateway server: Leave blank (unless you're using an RD Gateway)
   - Connect automatically: Check this if you want to connect immediately when opening this profile
   
6. **Save and Connect**:
   - Click "Save" to store this connection profile
   - Click "Connect" to establish the RDP connection to your Windows VM

### 7. Verify FTP Server Installation

The FTP server should be automatically installed via the startup script. To verify:

1. Connect to the VM via RDP
2. Open PowerShell as Administrator
3. Run the following command to check if the FTP service is running:
   ```powershell
   Get-Service ftpsvc
   ```

4. If needed, configure additional FTP settings using IIS Manager:
   ```powershell
   Import-Module WebAdministration
   Start-Process "C:\Windows\System32\inetsrv\InetMgr.exe"
   ```

### 8. Accessing the FTP Server

The FTP server will be accessible on the standard port 21. Use an FTP client to connect:
- FTP Server: [Your VM's External IP]
- Port: 21
- Username/Password: [Windows credentials]

> **Note**: For production use, configure secure FTP (FTPS) and proper authentication.

## Customization Options

### Changing VM Specifications

To modify the VM's specifications, update the following variables in your `terraform.tfvars` file:

- `machine_type`: Change to a different [GCP machine type](https://cloud.google.com/compute/docs/machine-types)
- `windows_image`: Use a different Windows Server image

### Adding Data Disks

To add persistent data storage, uncomment the disk-related sections in `main.tf`:

1. Uncomment the `google_compute_disk` resource
2. Uncomment the `attached_disk` block in the VM resource
3. Uncomment the `depends_on` attribute

Then add disk configurations to your `terraform.tfvars`:

```hcl
data_disk_size = 100  # Size in GB
data_disk_type = "pd-ssd"
```

### Firewall Configurations

For production environments, restrict FTP access by modifying:

```hcl
ftp_source_ranges = ["203.0.113.0/24", "198.51.100.0/24"]  # Your trusted IP ranges
```

## Cleanup

To destroy the infrastructure when no longer needed:

```bash
terraform destroy
```

Type `yes` when prompted to confirm.

## Troubleshooting

### Common Issues

1. **Authentication Failed**:
   - Verify the path to your credentials file
   - Ensure the service account has appropriate permissions

2. **VM Creation Failed**:
   - Check quota limits in your GCP project
   - Verify the specified region has the requested resources available

4. **Remmina Connection Issues**:
   - **"Unable to connect" error**: Verify the VM's external IP address and ensure the VM is running
   - **Authentication failures**: Double-check username and password
   - **Black screen**: Try changing the color depth or resolution settings
   - **Slow connection**: Adjust the quality settings under Performance tab
   - **Certificate warnings**: Accept the certificate or adjust TLS security settings
   - **Protocol negotiation failed**: Try different security modes (NLA, TLS, RDP)


