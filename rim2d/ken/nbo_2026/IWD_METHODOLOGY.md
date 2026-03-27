# Initial Water Depth (IWD) — Nairobi RIM2D Simulation

## What is IWD?

The **Initial Water Depth (IWD)** is a 2D raster (same grid as the DEM) that seeds every river channel cell with a pre-existing water depth before the simulation starts. Without it, a RIM2D simulation begins with completely dry channels and spends the first hours "filling up" rather than representing a physically realistic pre-event state. A well-constructed IWD:

- Provides hydraulic continuity — channels are connected and water is free to route downstream from time zero
- Reduces the numerical spin-up time
- Ensures that baseline channel storage is correctly represented before any storm rainfall or fluvial inflow is applied

IWD is specified in the RIM2D definition file as:

```
**IWD**
file
input/iwd.nc
```

where `iwd.nc` is a `NETCDF3_CLASSIC` file with the same `x`, `y` grid as `dem.nc`, values in metres (0 = dry land, >0 = water depth).

---

## Evolution across versions

| Version | IWD method | Channel source | Burn depth | Cells wet | Notes |
|---------|-----------|---------------|-----------|----------|-------|
| v1 | Uniform depth at WorldCover water pixels | ESA WorldCover class 80 (permanent water) | 3.0 m | ~14k | Overestimates depth, misses small streams |
| v3 | Same as v1 (WorldCover mask) | ESA WorldCover class 80 | 3.0 m | ~14k | Script refactored; roughness from WorldCover |
| v3b | Same IWD as v3 (copied) | ESA WorldCover class 80 | 3.0 m | ~14k | Only roughness changed (Dynamic World) |
| v4 | Steady-state pre-run output | v3 IWD as seed → 12h equilibration | variable | ~14k | First steady-state attempt |
| v5 | TDX-Hydro geometry burn | TDX-Hydro v2 river network (141 segs) | 0.5–2.5 m by order | ~19k | Width/depth assigned by stream order |
| **v6** | **TDX geometry + MERIT HND gap-fill** | **TDX-Hydro + MERIT HND = 0 cells** | **0.5–2.5 m (TDX) + 0.3 m (HND)** | **~131k** | **Current best** |
| **v6-SS** | **v6 equilibrated via 12h steady-state run** | Derived from v6 IWD after 12h RIM2D run | variable | **~178k** | **IWD used in production event simulation** |

---

## Detailed methodology per version

### v1 — ESA WorldCover uniform burn

**Script:** `setup_v1.py`

**Method:**
1. Download ESA WorldCover v200 (2021) at 10m from Google Earth Engine, reproject to 30m simulation grid
2. Extract class 80 (permanent water bodies) as binary `channel_mask`
3. Lower DEM by `BURN_DEPTH = 3.0 m` at all channel cells
4. Set `IWD = 3.0 m` at all channel cells (fills the carved channel exactly)

**Key parameters:**
```python
BURN_DEPTH   = 3.0   # m — how deep to carve the DEM at water pixels
NORMAL_DEPTH = 3.0   # m — IWD at channel cells (equals burn depth)
```

**Limitation:** WorldCover class 80 only captures visible permanent water bodies (wide rivers, reservoirs). Narrow streams and seasonal channels are missed. The uniform 3m depth is physically unrealistic — a narrow headwater stream should not have the same depth as the Nairobi River main stem.

---

### v3 — WorldCover mask (refactored)

**Script:** `setup_v3.py`

Same IWD approach as v1. The script was rewritten to modularise steps but the channel mask source (WorldCover class 80) and depth (3.0 m) are identical. The improvement was in roughness (Manning's n from WorldCover classes rather than a uniform value).

---

### v5 — TDX-Hydro geometry burn

**Script:** `setup_v5.py`

**Method:**
1. Load TDX-Hydro v2 river network from `v1/input/river_network_tdx_v2.geojson` (141 segments, Strahler orders 2–5)
2. Assign width and depth to each segment by stream order:

   | Stream order | Width (m) | Burn depth (m) |
   |-------------|-----------|---------------|
   | 2 | 15 | 0.5 |
   | 3 | 30 | 1.0 |
   | 4 | 60 | 1.5 |
   | 5 | 120 | 2.5 |

3. Buffer each centreline by `width/2` → rasterize to simulation grid
4. Lower DEM by the assigned depth at all buffered cells
5. `IWD = original DEM − burned DEM` (clipped to ≥ 0)

**Result:** 18,867 wet cells (0.9% of domain), IWD 0.5–2.5 m

**Improvement over v1:** Physically scaled widths and depths replace a single arbitrary 3m value. However, it only captures the 141 mapped TDX segments — small headwater channels between segments remain dry at t=0.

---

### v6 — TDX geometry + MERIT HND gap-fill (current baseline)

**Script:** `setup_v6.py`

This is the current production IWD. It combines two complementary layers:

#### Layer A — TDX-Hydro geometry burn

Identical to v5: 141 segments with width/depth by stream order, rasterized and burned into the DEM.

#### Layer B — MERIT HND headwater gap-fill

MERIT HND (Height above Nearest Drainage) is a 30m raster where **cells with HND = 0 sit exactly on a modelled drainage line**. These cells fill the gaps between mapped TDX segments — headwater channels, ephemeral streams, and small tributaries that TDX-Hydro does not include.

Gap-fill rule:
- If a cell has HND = 0 **and** is **not** already covered by a TDX channel footprint → burn by `HND_BURN_DEPTH = 0.3 m`
- TDX footprint always wins (priority rule)

```python
HND_BURN_DEPTH = 0.3   # m — shallow seed depth for headwater/gap cells
```

#### Merge and burn

```
combined_depth = max(layer_A_depth, layer_B_depth)   # TDX wins where overlap
burned_dem     = dem - combined_depth
IWD            = dem - burned_dem   (≥ 0)
```

**Result:**
- Layer A (TDX): 18,867 cells
- Layer B (HND gap-fill): 111,798 cells
- Total wet cells: 130,665 (~6.1% of domain)
- IWD range: 0.3–2.5 m

**Improvement over v5:** The HND gap-fill restores drainage connectivity across the entire watershed. Without it, isolated TDX segments produce disconnected pockets of initial water that cannot route downstream.

---

### v6-SS — Steady-state equilibrated IWD (production)

**Concept:** Even with a physically-derived IWD, the initial water distribution may not be in hydraulic equilibrium — water placed in headwater cells will flow downhill and accumulate at confluences during the first timesteps, creating a transient that is numerical rather than physical. The steady-state pre-run removes this by:

1. Running RIM2D for **12 hours (43,200 s)** with no rainfall and no inflows
2. Letting water redistribute until it reaches a quasi-steady state
3. Taking the **final timestep water depth** as the IWD for the actual event simulation

#### Step 1 — Run the steady-state pre-simulation

**Definition file:** `v6/simulation_v6ss.def`

```
**IWD**
file
input/iwd.nc          ← v6 geometric IWD as starting point

**pluvial_raster_nr**
0                     ← no rainfall

**sim_dur**
43200                 ← 12 hours

**output_base_fn**
output/nbo_v6ss_
```

**Command:**
```bash
cd /data/rim2d/nbo_2026/v6
export LD_LIBRARY_PATH="/data/rim2d/lib:$LD_LIBRARY_PATH"
../bin/RIM2D simulation_v6ss.def --def flex
```

Outputs 24 water-depth snapshots: `output/nbo_v6ss_wd_1800.nc`, `nbo_v6ss_wd_3600.nc`, …, `nbo_v6ss_wd_43200.nc`

#### Step 2 — Extract equilibrated IWD

**Script:** `v6/extract_v6ss_iwd.py`

```bash
cd /data/rim2d/nbo_2026/v6
micromamba run -n zarrv3 python extract_v6ss_iwd.py
```

What it does:
1. Finds all `nbo_v6ss_wd_*.nc` output files, sorts by timestep number
2. Reads the final timestep (`nbo_v6ss_wd_43200.nc`)
3. Clips negative values to 0 and NaN to 0
4. Backs up `input/iwd.nc` → `input/iwd_geometric.nc`
5. Writes the equilibrated depth as `input/iwd_ss.nc`

**Result:** 178,252 wet cells, mean depth 0.30 m, max depth 8.74 m (confluence accumulation on main stem)

#### Step 3 — Use in event simulation

Update the event simulation definition file to point to the steady-state IWD:

```
**IWD**
file
input/iwd_ss.nc
```

---

## File inventory

| File | Description |
|------|-------------|
| `v6/input/iwd.nc` | Active IWD (currently = iwd_ss.nc, the equilibrated version) |
| `v6/input/iwd_geometric.nc` | v6 geometric IWD before steady-state (Layer A + B combined) |
| `v6/input/iwd_ss.nc` | v6 steady-state equilibrated IWD — **production input** |
| `v1/input/iwd.nc` | v1 WorldCover uniform IWD (kept for comparison) |
| `v5/input/iwd.nc` | v5 TDX-only IWD |

---

## Comparison visualisation

The script `compare_iwd_v1_v6.py` produces a 3×3 panel comparison of v1, v6-geometric, and v6-SS:

```bash
cd /data/rim2d/nbo_2026
micromamba run -n zarrv3 python compare_iwd_v1_v6.py
```

Output: `visualizations/iwd_comparison_v1_v6geom_v6ss.png`

Panels: IWD maps (row 1), difference maps + wet-extent agreement (row 2), wet cell count bar chart + depth histogram (row 3).

---

## Quick reference — commands to regenerate IWD from scratch

```bash
# 1. Generate v6 geometric IWD (TDX + HND)
cd /data/rim2d/nbo_2026
micromamba run -n zarrv3 python setup_v6.py

# 2. Run 12h steady-state pre-simulation
cd /data/rim2d/nbo_2026/v6
export LD_LIBRARY_PATH="/data/rim2d/lib:$LD_LIBRARY_PATH"
../bin/RIM2D simulation_v6ss.def --def flex

# 3. Extract equilibrated IWD from final timestep
micromamba run -n zarrv3 python extract_v6ss_iwd.py

# 4. Compare v1 / v6-geom / v6-SS
cd /data/rim2d/nbo_2026
micromamba run -n zarrv3 python compare_iwd_v1_v6.py
```

---

## Key data dependencies

```
Google Earth Engine (setup_v1.py)
  └── MERIT Hydro (90m) → hnd_30m.nc        ← used by setup_v6.py Layer B
  └── ESA WorldCover v200 → roughness.nc     ← used by all versions

TDX-Hydro v2 GeoJSON (download_river_network_v1.py)
  └── v1/input/river_network_tdx_v2.geojson  ← used by setup_v5.py, setup_v6.py Layer A

RIM2D binary (/data/rim2d/bin/RIM2D)
  └── v6/simulation_v6ss.def                 ← produces output/nbo_v6ss_wd_*.nc

extract_v6ss_iwd.py
  └── v6/input/iwd_ss.nc                     ← final production IWD
```
