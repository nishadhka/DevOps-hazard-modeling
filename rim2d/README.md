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

## Active cases

| Country | Case | Versions | Notes |
|---------|------|----------|-------|
| Sudan (`sdn`) | `nile_2024` | v11–v24 | Aug 2024 Abu Hamad flash flood |
