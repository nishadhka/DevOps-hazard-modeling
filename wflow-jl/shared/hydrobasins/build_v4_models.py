"""Drive the canonical ../hazard-model-api/ pipeline for all 11 v4 bboxes.

Single script, no CLI. For each case in SELECTED (small bbox first):
  bbox  <- shared/hydrobasins/outputs_v4/<stem>_v4.geojson total_bounds
  period<- region_configs.REGIONS[*]['start'/'end']
  out   <- /mnt/wflow-secondary/v4_models/<iso>/
then runs the hazard-model-api steps in STEPS via the wflow-jl venv,
GEE auth from the gitignored .secrets key. Scripts are idempotent
(skip files already on disk); per-case failures are logged and the
batch continues.

Static steps (dem/worldcover/merit/soilgrids/staticmaps/fix_ldd) are
fast (~minutes/case). Forcing (chirps daily HTTPS, era5 daily GEE) is
the long pole for multi-year periods. Set STEPS to control scope.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd

REPO = Path(__file__).resolve().parents[2]                 # wflow-jl/
ROOT = REPO.parent                                          # DevOps-hazard-modeling/
HMA = ROOT / "hazard-model-api"
V4 = REPO / "shared" / "hydrobasins" / "outputs_v4"
OUT_ROOT = Path("/mnt/wflow-secondary/v4_models")
VENV_PY = REPO / ".venv" / "bin" / "python"
SA_KEY = REPO / ".secrets" / "ee-service-account.json"

sys.path.insert(0, str(REPO))
from region_configs import REGIONS  # noqa: E402

ISO_STEM = {
    "BDI": "01_burundi_bdi_v4",   "DJI": "02_djibouti_dji_v4",
    "ERI": "03_eritrea_eri_v4",   "ETH": "04_ethiopia_eth_v4",
    "KEN": "05_kenya_ken_v4",     "RWA": "06_rwanda_rwa_v4",
    "SOM": "07_somalia_som_v4",   "SSD": "08_south_sudan_ssd_v4",
    "SDN": "09_sudan_sdn_v4",     "TZA": "10_tanzania_tza_v4",
    "UGA": "11_uganda_uga_v4",    "MWI": "12_malawi_mwi_v4",
}
PERIOD = {c["country_iso"]: (c["start"], c["end"]) for c in REGIONS.values()}

# smallest bbox first so tractable cases validate the chain early
SELECTED = ["BDI", "ERI", "DJI", "RWA", "TZA", "UGA",
            "KEN", "SDN", "ETH", "SSD", "SOM", "MWI"]

# (script, needs_period, extra args).
# STATIC-ONLY phase: forcing (download_chirps/era5) is deferred — it is the
# multi-hour bottleneck and prepare_wflow_staticmaps does not depend on it
# (validated on BDI). Re-add the two forcing lines for the forcing phase.
STEPS = [
    ("download_dem.py",        False, ["--scale", "1000", "--target", "merit"]),
    ("download_worldcover.py", False, ["--scale", "1000"]),
    ("download_merit_hydro.py", False, []),
    ("download_soilgrids.py",  False, ["--scale", "1000"]),
    # ("download_chirps.py",   True,  []),   # deferred (forcing phase)
    # ("download_era5.py",     True,  []),   # deferred (forcing phase)
    ("prepare_wflow_staticmaps.py", True, []),  # requires --start/--end
]


def bbox_str(stem: str) -> str:
    w, s, e, n = gpd.read_file(V4 / f"{stem}.geojson").total_bounds
    return f"{w:.4f},{s:.4f},{e:.4f},{n:.4f}"


def run(cmd: list[str], log) -> bool:
    log.write("  $ " + " ".join(cmd) + "\n"); log.flush()
    p = subprocess.run(cmd, cwd=HMA, env={**os.environ,
                        "GEE_SA_KEY": str(SA_KEY)},
                        capture_output=True, text=True)
    log.write(p.stdout[-4000:]);
    if p.returncode != 0:
        log.write("  !! stderr:\n" + p.stderr[-4000:] + "\n")
    log.flush()
    return p.returncode == 0


if __name__ == "__main__":
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Selected: {SELECTED}")
    for iso in SELECTED:
        out = OUT_ROOT / iso.lower()
        out.mkdir(parents=True, exist_ok=True)
        bb = bbox_str(ISO_STEM[iso])
        start, end = PERIOD[iso]
        logf = out / "build.log"
        with open(logf, "a") as log:
            log.write(f"\n==== {iso}  bbox={bb}  {start}..{end} ====\n")
            print(f"\n=== {iso}  bbox={bb}  {start}..{end} ===")
            ok = True
            for script, needs_t, extra in STEPS:
                cmd = [str(VENV_PY), script, "--bbox", bb,
                       "--out", str(out)] + extra
                if needs_t:
                    cmd += ["--start", start, "--end", end]
                if not run(cmd, log):
                    print(f"  [{iso}] {script} FAILED (see {logf})")
                    ok = False
                    if script == "prepare_wflow_staticmaps.py":
                        break
                else:
                    print(f"  [{iso}] {script} ok")
            sm = out / "staticmaps.nc"
            if sm.exists():
                cmd = [str(VENV_PY), "fix_ldd_pyflwdir.py",
                       "--staticmaps", str(sm)]
                run(cmd, log)
                print(f"  [{iso}] fix_ldd "
                      f"{'ok' if sm.exists() else 'FAILED'}; "
                      f"staticmaps={sm.stat().st_size/1e6:.1f}MB")
            else:
                print(f"  [{iso}] no staticmaps.nc — build incomplete")
    print("\nDone.")
