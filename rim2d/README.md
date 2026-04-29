# RIM2D — ICPAC Country Cases

RIM2D simulation scripts and definition files for the 11 ICPAC member states.
Each country folder uses the ISO 3166-1 alpha-3 code (lowercase).
Large input data (DEM, rainfall, boundary NetCDF files) are stored separately
on the compute server and are not tracked here.

## Structure

```
rim2d/
├── bdi/    Burundi
├── dji/    Djibouti
├── eri/    Eritrea
├── eth/    Ethiopia
├── ken/    Kenya
├── rwa/    Rwanda
├── sdn/    Sudan
│   └── nile_2024/   Aug 2024 flash flood, Abu Hamad
├── som/    Somalia
├── ssd/    South Sudan
├── tza/    Tanzania
└── uga/    Uganda
```

## Contents per case

Only code and configuration files are committed:
- `run_vXX_setup.py` — DEM conditioning and input preparation
- `simulation_vXX.def` — RIM2D flex-format definition file
- `analysis/*.py` — visualization and diagnostic scripts
- `analysis/*.md` — methodology notes and conditioning reports

### To get the source code of RIM2D model

RIM2D is a 2D hydraulic inundation model specifically designed for fluvial and
pluvial flood simulation. RIM2D has simplified approaches implemented for
simulating sewer system, roof drainage and infiltration. Thus it is well suited
for fast urban inundation simulation. RIM2D is coded in Fortran90 and runs the
simulations on GPUs. Compiling thus requires a NVIDIA CUDA enabled Fortran
compiler.

Developed by Section 4.4 Hydrology of the GFZ German Research Centre for
Geoscience

Repository created by Dr. Heiko Apel, heiko.apel@gfz-potsdam.de

Helmholtz Centre Potsdam GFZ German Research Centre for Geosciences, Section
4.4 Hydrology, 14473 Potsdam, Germany
