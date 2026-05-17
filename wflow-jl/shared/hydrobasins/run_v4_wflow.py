"""Run Wflow SBM for all 11 v4 cases (Julia 1.10 / Wflow v1.0.2).

Each /mnt/wflow-secondary/v4_models/<iso>/ now has staticmaps.nc (23 vars,
hazard-model-api schema) + forcing.nc (precip/temp/pet, single-source EDH
ERA5). Per case this writes a Wflow v1.0.2 TOML mapping those vars to the
v1 standard names (snow OFF — v4 staticmaps carries no snow params),
WRSI-minimal gridded output (aet + pet), and runs it on the pinned
toolchain. Idempotent (skips a finished output_grid.nc); small→large;
continue-on-error.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
JULIA = Path.home() / ".juliaup" / "bin" / "julia"
JPROJ = REPO / "julia_env"
MODELS = Path("/mnt/wflow-secondary/v4_models")

sys.path.insert(0, str(REPO))
from region_configs import REGIONS  # noqa: E402

PERIOD = {c["country_iso"]: (c["start"], c["end"]) for c in REGIONS.values()}
SELECTED = ["BDI", "ERI", "DJI", "RWA", "TZA", "UGA",
            "KEN", "SDN", "ETH", "SSD", "SOM"]

TOML = '''\
# Wflow SBM v1.0.2 — v4 case {iso} (auto-generated)
dir_input = "{d}"
dir_output = "{d}/output"

[time]
calendar = "standard"
starttime = {start}T00:00:00
endtime = {end}T00:00:00
timestepsecs = 86400

[logging]
loglevel = "info"
path_log = "log.txt"

[input]
path_forcing = "forcing.nc"
path_static = "staticmaps.nc"
basin__local_drain_direction = "wflow_ldd"
river_location__mask = "wflow_river"
subbasin_location__count = "wflow_subcatch"

[input.forcing]
atmosphere_water__precipitation_volume_flux = "precip"
land_surface_water__potential_evaporation_volume_flux = "pet"
atmosphere_air__temperature = "temp"

[input.static]
soil_layer_water__brooks_corey_exponent = "c"
soil_surface_water__vertical_saturated_hydraulic_conductivity = "KsatVer"
soil_water__vertical_saturated_hydraulic_conductivity_scale_parameter = "f"
soil_water__residual_volume_fraction = "thetaR"
soil_water__saturated_volume_fraction = "thetaS"
soil__thickness = "SoilThickness"
vegetation_root__depth = "RootingDepth"
land_surface__slope = "Slope"
river__slope = "RiverSlope"
river__length = "RiverLength"
river__width = "RiverWidth"
river_bank_water__depth = "RiverDepth"
river_water_flow__manning_n_parameter = "N_River"
land_surface_water_flow__manning_n_parameter = "N"

# v4 staticmaps carries no LAI/canopy params → supply Wflow's required
# canopy inputs as uniform constants (interception is a minor term for
# the ΣAET/ΣPET WRSI; values are typical vegetated-surface defaults).
[input.static.vegetation_canopy__gap_fraction]
value = 0.1

[input.static.vegetation_water__storage_capacity]
value = 1.5

[input.static.compacted_soil__area_fraction]
value = 0.01

[input.static.soil_surface_water__infiltration_reduction_parameter]
value = 0.038

[input.static.compacted_soil_surface_water__infiltration_capacity]
value = 10.0

[input.static.soil_water_saturated_zone_bottom__max_leakage_volume_flux]
value = 0.0

[input.static.soil_wet_root__sigmoid_function_shape_parameter]
value = -500.0

[input.static.subsurface_water__horizontal_to_vertical_saturated_hydraulic_conductivity_ratio]
value = 100.0

[model]
soil_layer__thickness = [100, 300, 800]
type = "sbm"
reservoir__flag = false
snow__flag = false

[output.netcdf_grid]
path = "output_grid_wrsi.nc"
compressionlevel = 1

[output.netcdf_grid.variables]
land_surface__evapotranspiration_volume_flux = "aet"
land_surface_water__potential_evaporation_volume_flux = "pet"

[output.csv]
path = "output_{isol}.csv"

[[output.csv.column]]
header = "aet"
parameter = "land_surface__evapotranspiration_volume_flux"
reducer = "mean"

[[output.csv.column]]
header = "pet"
parameter = "land_surface_water__potential_evaporation_volume_flux"
reducer = "mean"
'''


def main():
    print(f"Selected: {SELECTED}")
    for iso in SELECTED:
        d = MODELS / iso.lower()
        sm, fc = d / "staticmaps.nc", d / "forcing.nc"
        if not (sm.exists() and fc.exists()):
            print(f"  [{iso}] missing staticmaps/forcing — skip"); continue
        outnc = d / "output" / "output_grid_wrsi.nc"
        if outnc.exists():
            print(f"  [{iso}] output_grid_wrsi.nc exists — skip"); continue
        start, end = PERIOD[iso]
        tp = d / "wflow_v4.toml"
        tp.write_text(TOML.format(iso=iso, isol=iso.lower(), d=str(d),
                                  start=start, end=end))
        (d / "output").mkdir(exist_ok=True)
        print(f"  [{iso}] running wflow {start}..{end} ...", flush=True)
        r = subprocess.run(
            [str(JULIA), "+1.10", f"--project={JPROJ}",
             "-e", f'using Wflow; Wflow.run("{tp}")'],
            cwd=d, env={**os.environ, "JULIA_NUM_THREADS": "4"},
            capture_output=True, text=True)
        if r.returncode == 0 and outnc.exists():
            print(f"  [{iso}] OK  output_grid_wrsi.nc "
                  f"{outnc.stat().st_size/1e6:.0f} MB", flush=True)
        else:
            tail = (r.stderr or r.stdout)[-1200:]
            print(f"  [{iso}] FAILED rc={r.returncode}\n{tail}", flush=True)
    print("Done.")


if __name__ == "__main__":
    main()
