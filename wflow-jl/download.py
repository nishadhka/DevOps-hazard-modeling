import os
from pathlib import Path
import urllib.request

# URLs to TOML and netCDF of the Moselle example model
toml_url = "https://raw.githubusercontent.com/Deltares/Wflow.jl/master/Wflow/test/sbm_config.toml"
staticmaps = "https://github.com/visr/wflow-artifacts/releases/download/v0.3.1/staticmaps-moselle.nc"
forcing = "https://github.com/visr/wflow-artifacts/releases/download/v0.2.6/forcing-moselle.nc"
instates = "https://github.com/visr/wflow-artifacts/releases/download/v0.3.1/instates-moselle.nc"

# Create a "data/input" directory in the current directory
testdir = Path(__file__).parent
inputdir = testdir / "data" / "input"
inputdir.mkdir(parents=True, exist_ok=True)

toml_path = testdir / "sbm_config.toml"

# Download resources to current and input directories
print("Downloading files...")
urllib.request.urlretrieve(staticmaps, inputdir / "staticmaps-moselle.nc")
print(f"Downloaded staticmaps-moselle.nc")

urllib.request.urlretrieve(forcing, inputdir / "forcing-moselle.nc")
print(f"Downloaded forcing-moselle.nc")

urllib.request.urlretrieve(instates, inputdir / "instates-moselle.nc")
print(f"Downloaded instates-moselle.nc")

urllib.request.urlretrieve(toml_url, toml_path)
print(f"Downloaded sbm_config.toml")

print("All files downloaded successfully!")
