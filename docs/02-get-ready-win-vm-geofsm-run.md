# Windows Server Setup for GeoSFM Forecasting

This guide outlines the process of setting up a Windows Server 2016 machine for GeoSFM (Geospatial Stream Flow Model) forecasting. This document covers the initial setup steps including browser installation, 7-Zip installation, and downloading necessary files.

## Prerequisites

- Windows Server 2016 installation with administrative access
- Internet connection
- Basic knowledge of Windows Server administration

## 1. Installing a Browser (Chrome/Chromium)

A modern browser is needed to download files from Google Drive and other sources. While Windows Server comes with Internet Explorer by default, it's recommended to install Chrome or Chromium for better compatibility.

### Method 1: GUI Installation

1. Open Internet Explorer on the Windows Server
2. Navigate to [https://www.google.com/chrome/](https://www.google.com/chrome/)
3. Click "Download Chrome"
4. If you encounter security warnings:
   - Click the gear icon (Tools) in Internet Explorer
   - Select "Internet Options"
   - Go to the "Security" tab
   - Select "Trusted sites" and click "Sites"
   - Add "https://www.google.com" and "https://dl.google.com"
5. Run the downloaded ChromeSetup.exe
6. Follow the installation wizard instructions

### Method 2: PowerShell Installation

1. Open PowerShell as Administrator
2. Run the following command to download the Chrome installer:
   ```powershell
   Invoke-WebRequest -Uri "https://dl.google.com/chrome/install/latest/chrome_installer.exe" -OutFile "$env:USERPROFILE\Downloads\chrome_installer.exe"
   ```
3. Run the installer:
   ```powershell
   Start-Process "$env:USERPROFILE\Downloads\chrome_installer.exe" -Wait
   ```

## 2. Installing 7-Zip

7-Zip is required to extract compressed files used in the GeoSFM forecasting process.

### Method 1: GUI Installation

1. Using your installed browser, go to [https://7-zip.org/download.html](https://7-zip.org/download.html)
2. Download the 64-bit version for Windows x64 (currently 7z2409-x64.exe)
3. Run the downloaded .exe file
4. Follow the installation wizard, accepting the default installation location
5. Click "Install" and then "Close" when finished

### Method 2: PowerShell Installation

1. Open PowerShell as Administrator
2. Run the following commands to download and install 7-Zip silently:
   ```powershell
   # Download 7-Zip
   Invoke-WebRequest -Uri "https://www.7-zip.org/a/7z2409-x64.exe" -OutFile "$env:TEMP\7z-installer.exe"

   # Install 7-Zip silently
   Start-Process -FilePath "$env:TEMP\7z-installer.exe" -ArgumentList "/S" -Wait

   # Verify installation
   if (Test-Path "C:\Program Files\7-Zip\7z.exe") {
       Write-Host "7-Zip installed successfully"
   } else {
       Write-Host "7-Zip installation failed"
   }
   ```

## 3. Downloading and Extracting GeoSFM Files

### Downloading from Google Drive

1. Open Chrome browser
2. Navigate to the provided Google Drive link (to be provided separately)
3. Sign in with your Google account if required
4. Download the required 7z file by clicking on it and selecting "Download"

### Alternative Download Method Using PowerShell (Advanced)

If you have a direct download link to the 7z file, you can use PowerShell:

```powershell
Invoke-WebRequest -Uri "DIRECT_DOWNLOAD_URL" -OutFile "C:\Path\To\Save\GeoSFM.7z"
```

Note: Replace "DIRECT_DOWNLOAD_URL" with the actual direct download URL.

### Extracting the 7z File

#### Using GUI:

1. Right-click on the downloaded .7z file
2. Select "7-Zip" > "Extract Here" or "Extract to [folder name]"
3. Wait for the extraction to complete

#### Using PowerShell:

```powershell
# Extract the 7z file to a specific folder
& "C:\Program Files\7-Zip\7z.exe" x "C:\Path\To\Downloaded\GeoSFM.7z" -o"C:\GeoSFM" -y
```

## Next Steps

Once you have successfully downloaded and extracted the GeoSFM files, proceed to the next steps outlined in the [GeoSFM Configuration and Execution Guide](../path/to/next/markdown/guide.md).

## Troubleshooting

### Common Issues with Chrome Installation

- **Error messages about Windows Server being in server mode**: This is normal. Chrome will still function correctly for downloading files.
- **Security warnings**: Add download sites to your trusted sites as mentioned earlier.

### Common Issues with 7-Zip Installation

- **Access denied errors**: Ensure you're running PowerShell or the installer as Administrator.
- **Installation completes but 7-Zip doesn't appear in the context menu**: Try restarting Explorer or the server.

## Additional Resources

- [Official Chrome Download Page](https://www.google.com/chrome/)
- [Official 7-Zip Website](https://7-zip.org/)
- [GeoSFM Documentation](https://github.com/your-organization/geosfm-docs) (Replace with actual link)
