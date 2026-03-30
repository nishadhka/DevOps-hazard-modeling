# DJI — Djibouti City
## RIM2D simulation case

**Event**: Flash flood, Djibouti City urban area
**Period**: 2019-11-21 to 2019-11-23
**Country**: DJI
**Domain**: lon [42.5, 43.3]  lat [11.4, 11.8]
**Resolution**: MERIT DEM 30 m (target)
**Rainfall**: IMERG v7 Final, 2019-11-21 – 2019-11-23
**Model**: RIM2D GPU-accelerated 2D hydraulic inundation (flex .def format)

---

## Version history

| Version | Description | Status |
|---------|-------------|--------|
| v1 | Initial domain setup — DEM clip, IMERG download, inflowlocs | planned |

---

## Setup

```bash
# Prepare inputs
micromamba run -n zarrv3 python run_v1_setup.py

# Run simulation
export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
/data/rim2d/bin/RIM2D simulation_v1.def --def flex

# Visualize
micromamba run -n zarrv3 python analysis/visualize_v1.py
```

---

## DEM conditioning reference

See `../../sdn/nile_2024/v24/` for the full reference pipeline including:
- 4-connected Bresenham channel burn rasterization
- Pysheds 2-pass depression fill (float64)
- Pysheds 8-dir vs RIM2D 4-dir routing mismatch documentation:
  `../../sdn/nile_2024/v24/analysis/BRESENHAM_4CONNECTED_NOTE.md`
