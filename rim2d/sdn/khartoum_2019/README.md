# SDN — Khartoum Omdurman
## RIM2D simulation case

**Event**: Flash flood, Khartoum / Omdurman / Bahri
**Period**: 2019-08-01 to 2019-09-10
**Country**: SDN
**Domain**: lon [32.2, 32.8]  lat [15.3, 15.9]
**Resolution**: MERIT DEM 30 m (target)
**Rainfall**: IMERG v7 Final, 2019-08-01 – 2019-09-10
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
