# Sudan — Nile Flash Flood 2024 (Abu Hamad)
## RIM2D simulation case

**Event**: August 2024 flash flood, Abu Hamad, River Nile State, Sudan
**Domain**: MERIT DEM 30 m, 297 × 386 cells, EPSG:32636 (UTM Zone 36N)
**Rainfall**: IMERG v7 satellite-derived, Aug 25–31 2024
**Model**: RIM2D GPU-accelerated 2D hydraulic inundation (flex .def format)

---

## Version history

| Version | Key change | Status |
|---------|-----------|--------|
| v11 | Initial domain setup, synthetic flood test, sensitivity runs | baseline |
| v12 | Depression-fill fix (pysheds), corrected Nile floodplain burn | improved |
| v13 | TDX-Hydro GeoJSON stream burns added | tested |
| v14 | Culvert1 + Culvert2 hardcoded burns | tested |
| v15 | Inflowlocs from IMERG hydrograph, full Aug 25–31 simulation | first full sim |
| v16–v18 | Roughness, boundary, and rainfall adjustments | calibration |
| v19–v20 | Depression-fill diagnosis — 4,255 pits found, inflows stall | diagnosis |
| v21 | 2-pass pysheds float64 fill — all 4 inflows reach Nile | fixed |
| v22 | HospitalWadi→Nile connectivity burn (3-cell-wide channel) | fixed |
| v23 | Fresh v10 base + cor1/cor2 KML burns (Bresenham) + pysheds | **recommended** |
| v24 | 4-connected Bresenham fix + corr3.kml shallow channel | **latest** |

---

## DEM conditioning pipeline (v23/v24)

1. **Fix A** — Nile floodplain burn: cells with DEM < 308 m → 294 m
2. **Fix B** — TDX-Hydro GeoJSON stream burns (skip linkno=160245676 — wrong position)
3. **Fix C** — cor1.kml corrected western tributary (dem − 8 m, Bresenham rasterized)
4. **Fix D** — cor2.kml corrected HospitalWadi/culvert channel (dem − 8 m, Bresenham)
5. **Fix E** — Gap bridge between GeoJSON features F18→F19
6. **Fix G** *(v24 only)* — corr3.kml railway-zone channel (dem − 1 m)
7. **Fix F** — Pysheds 2-pass depression fill + resolve_flats (float64)

**Key lesson**: use 4-connected Bresenham rasterization for channel burns.
Standard Bresenham produces diagonal cell pairs that pysheds accepts (8-directional)
but RIM2D cannot route through (4-directional). See `v24/analysis/BRESENHAM_4CONNECTED_NOTE.md`.

---

## File structure

```
nile_2024/
├── v11/                        baseline + sensitivity runs
│   ├── simulation_v11.def
│   ├── run_v11_synthetic_flood.py
│   ├── visualize_v11.py
│   ├── sensitivity/            5 sensitivity .def files
│   └── analysis/
├── v12/ … v20/                 incremental fixes (setup + def + analysis scripts)
├── v21/
│   ├── simulation_v21.def
│   ├── run_v21_setup.py
│   └── analysis/
│       ├── DEM_CONDITIONING_REPORT.md
│       ├── dem_diagnostic.py
│       ├── plot_dem_comparison.py
│       └── visualize_v21.py
├── v22/                        HospitalWadi connectivity fix
├── v23/                        fresh KML-based DEM (recommended)
│   ├── simulation_v23.def
│   ├── run_v23_setup.py
│   └── analysis/
│       ├── dem_diagnostic.py
│       └── visualize_v23.py
└── v24/                        4-connected Bresenham + corr3.kml
    ├── simulation_v24.def
    ├── run_v24_setup.py
    └── analysis/
        ├── BRESENHAM_4CONNECTED_NOTE.md
        ├── bresenham_4connected_demo.py
        └── visualize_v24.py
```

---

## Running a simulation

```bash
# Setup DEM and inputs (example: v24)
micromamba run -n zarrv3 python v24/run_v24_setup.py

# Run simulation (from the version directory)
cd v24
export LD_LIBRARY_PATH=/data/rim2d/lib:$LD_LIBRARY_PATH
/data/rim2d/bin/RIM2D simulation_v24.def --def flex

# Visualize output
micromamba run -n zarrv3 python v24/analysis/visualize_v24.py
```

Input data (DEM, rainfall NC files, boundary masks) are stored separately at
`/data/rim2d/nile_highres/` on the local compute server.
