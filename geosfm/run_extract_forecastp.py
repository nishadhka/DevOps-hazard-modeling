import os
import re
import subprocess

BASE_DIR = "geosfm_txt_files/"
pattern = re.compile(r"^\d{8}$")  # YYYYMMDD

for folder in sorted(os.listdir(BASE_DIR)):
    if pattern.match(folder):
        print(f"Processing {folder} ...")
        subprocess.run(["python", "extract_forecast_period.py", "--run-date", folder])

