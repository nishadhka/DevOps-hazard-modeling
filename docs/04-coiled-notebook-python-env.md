# Setting Up Coiled Notebook for GeoSFM Processing

This guide explains how to set up and use Coiled for running GeoSFM-related processing notebooks. Coiled provides a managed cloud environment for data science workflows, allowing you to easily spin up notebooks with pre-configured environments.

## Prerequisites

- A Coiled account with access to the `geosfm` workspace
- Basic familiarity with Jupyter notebooks
- GCP account credentials (if using GCP integration)

## Joining the Coiled Team

Before you can use the GeoSFM workspace in Coiled, you'll need to accept the team invitation:

1. Check your email for a Coiled team invitation
2. Click on the invitation link
3. Follow the prompts to create an account or sign in to your existing account
4. Verify that you have access to the `geosfm` workspace after logging in

## Starting a Coiled Notebook

### Using the Command Line

To start a Coiled notebook using the pre-configured environment, open a terminal and run:

```bash
coiled notebook start --name  --vm-type n2-standard-2 --software itt-jupyter-env-v20250318 --workspace=geosfm
```

This command:
- Starts a notebook called `geosfm-input`
- Uses a GCP n2-standard-2 virtual machine (2 vCPUs, 8GB RAM)
- Uses the pre-configured software environment `itt-jupyter-env-v20250318`
- Runs in the `geosfm` workspace

After running this command, Coiled will provide a URL to access your Jupyter notebook in the browser.

### Using the Coiled Web Interface

Alternatively, you can start a notebook through the Coiled web interface:

1. Log in to [Coiled](https://cloud.coiled.io/)
2. Navigate to the `geosfm` workspace
3. Click "Start Notebook"
4. Configure your notebook:
   - Name: `geosfm-input` (or any descriptive name)
   - VM Type: `n2-standard-2`
   - Software environment: `itt-jupyter-env-v20250318`
5. Click "Start"

## Installing Additional Required Packages

The `flox` package, which is important for efficient grouped operations in xarray, might not be included in the pre-configured environment. To install it:

1. Open a new notebook or terminal in your Coiled Jupyter environment
2. Run the following command:

```bash
micromamba install flox -c conda-forge
```

3. Restart the kernel to ensure the package is properly loaded

## Uploading Shapefiles

Shapefiles are essential for GeoSFM spatial analysis. To upload shapefiles to your Coiled notebook:

1. In the Jupyter interface, click on the "Upload" button (↑) in the file browser panel
2. Select all components of your shapefile (typically including .shp, .shx, .dbf, .prj files)
3. Click "Upload" to transfer the files to your Coiled environment

Alternatively, if your shapefiles are stored in cloud storage:

```python
# For GCP Cloud Storage
!gsutil cp gs://your-bucket/path/to/shapefile/* ./shapefiles/

# For AWS S3
!aws s3 cp s3://your-bucket/path/to/shapefile/ ./shapefiles/ --recursive
```

## Best Practices for GeoSFM Processing in Coiled

1. **Memory Management**: GeoSFM processing can be memory-intensive. If you encounter memory issues:
   - Restart with a larger VM type (e.g., `n2-standard-4` or `n2-standard-8`)
   - Process zones sequentially rather than in parallel
   - Use Dask for distributed computing on larger datasets

2. **Persistence**: Coiled notebooks will shut down after a period of inactivity. To preserve your work:
   - Save notebooks frequently
   - Store important data and results in cloud storage
   - Use the `%autosave` magic command to enable automatic notebook saving

3. **Environment Management**: If you need a custom environment beyond `itt-jupyter-env-v20250318`:
   - Create a new software environment in Coiled
   - Include all required dependencies in your environment specification

## Common Coiled Commands

```bash
# List running notebooks
coiled notebook list

# Stop a notebook
coiled notebook stop geosfm-input

# Get information about a notebook
coiled notebook info geosfm-input

# List available software environments
coiled software list --workspace=geosfm
```

## Troubleshooting

- **Connection issues**: If you cannot connect to your notebook, try stopping it with `coiled notebook stop` and starting it again
- **Package installation failures**: If `micromamba install` fails, try using `pip install flox` as an alternative
- **Resource limitations**: If you encounter "out of memory" errors, restart with a larger VM type

## Next Steps

After setting up your Coiled notebook environment, proceed to:

1. Import your GeoSFM data
2. Run your analysis notebooks
3. Generate visualization outputs for flood forecasting

For detailed instructions on running the GeoSFM model itself, refer to the [Guide to Running the GeoSFM Forecast Model for East Africa](geosfm-guide.md).
