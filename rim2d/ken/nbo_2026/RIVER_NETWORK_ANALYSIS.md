# Nairobi River Network Analysis — TDX-Hydro v2 + GEOGloWS

## Background

### Why this matters

RIM2D flood simulations require **fluvial boundary conditions** — inflow locations and flow rates along river channels entering the simulation domain. Connecting the model to real-time or forecast streamflow data requires identifying which river segments correspond to usable forecast products.

This script links the **TDX-Hydro v2** river network (used to burn DEM channels and define fluvial boundaries) to the **GEOGloWS streamflow forecast service**, which uses the same TDX `linkno` reach IDs.

### Data sources

| Dataset | Description | Location |
|---------|-------------|----------|
| TDX-Hydro v2 | Global river network derived from TanDEM-X DEM; reach IDs match GEOGloWS | `v1/input/river_network_tdx_v2.geojson` |
| GEOGloWS v2 API | ECMWF-based 40-day ensemble streamflow forecast; uses TDX `linkno` as reach ID | `https://geoglows.ecmwf.int/api/v2` |
| TIPG API | OGC Features API serving TDX attributes including `NEXT_DOWN` connectivity | `https://tipg-tiler-template.replit.app` |

### What the script does

1. **Load** the local TDX-Hydro GeoJSON (141 segments, stream orders 2–5) covering the Nairobi simulation domain (bbox: 36.6–37.1°E, 1.10–1.40°S).

2. **Fetch connectivity (NEXT_DOWN)** — tries the TIPG OGC Features API first. If unavailable (timeout or missing field), falls back to **geometric endpoint snapping**: the endpoint of segment A snaps to the start-point of segment B if they are within 0.001° (~110 m).

3. **Build a directed graph** — each segment points to its downstream neighbour (`downstream[linkno] = next_linkno`). Segments with no downstream neighbour are domain outlets.

4. **Trace river chains** — starting from headwater segments (no upstream), walks downstream until reaching an outlet or a previously-visited segment. Each connected chain is a `river_id` group. The most-downstream segment becomes the **representative GEOGloWS reach ID** for the chain.

5. **Check GEOGloWS forecasts** — for order-4 and order-5 outlets only (main rivers), queries the forecast API and records whether data is available, the peak forecast flow, and the forecast date.

6. **Save outputs**:
   - `v1/input/river_reach_ids.csv` — summary table (one row per river chain)
   - `v1/input/river_network_tdx_v2_connected.geojson` — original GeoJSON with `river_id` field added
   - `v1/visualizations/v1_river_chains.png` — two-panel map (stream order / river chains)

---

## Results (last run: 2026-03-11)

| Metric | Value |
|--------|-------|
| Total TDX segments | 141 |
| River chains grouped | 62 |
| Connectivity method | Geometric endpoint snapping (TIPG unavailable) |
| Connected pairs | 116 / 141 |

### Order 4–5 river chains (main rivers, forecast-enabled)

| river_id | reach_id_geoglows | Order | Segments | Length (km) | Outlet lon | Outlet lat | GEOGloWS valid | Peak Q (m³/s) |
|----------|------------------|-------|----------|------------|-----------|-----------|----------------|--------------|
| 17 | 110250134 | 5 | 23 | 70.6 | 36.71822 | -1.36633 | Yes | 0.20 |
| 18 | 110285559 | 5 | 5 | 22.1 | 37.12622 | -1.38633 | No (429) | — |
| 22 | 110260628 | 5 | 6 | 16.9 | 37.06233 | -1.28044 | Yes | 0.10 |
| 23 | 110364272 | 5 | 5 | 31.2 | 36.95567 | -1.13856 | No (429) | — |
| 4 | 110251442 | 4 | 9 | 51.9 | 36.63567 | -1.20911 | Yes | 0.20 |
| 15 | 110332794 | 4 | 7 | 13.8 | 36.98622 | -1.50889 | Yes | **2.10** |
| 20 | 110206837 | 4 | 5 | 36.9 | 36.83111 | -1.30622 | Yes | 0.20 |
| 21 | 110227826 | 4 | 7 | 36.4 | 36.86944 | -1.20356 | No (429) | — |

> HTTP 429 = rate-limited by GEOGloWS API (reach IDs are valid; retry with delay).
> `reach_id=110332794` shows the highest forecast peak (2.10 m³/s) — the southern outlet near -1.509°S.

---

## How to run

### Prerequisites

```bash
# Environment: micromamba zarrv3
# Required packages: requests, numpy, matplotlib, netCDF4, pandas
micromamba activate zarrv3
```

### Run the analysis

```bash
cd /data/rim2d/nbo_2026
micromamba run -n zarrv3 python analyze_river_network_v1.py
```

Runtime is approximately **1–2 minutes** (dominated by GEOGloWS API calls for 8 reach IDs with 1 s delay between requests).

### Expected output

```
Loaded 141 segments from river_network_tdx_v2.geojson

Trying TIPG API for NEXT_DOWN...
  TIPG unavailable — falling back to geometric connectivity

Building geometric connectivity (snap tolerance=0.001°)...
  Connected pairs: 116 / 141

Traced 62 river chains from 141 segments

Checking GEOGloWS forecast availability...
  110251442  OK  max_Q=0.20 m³/s
  ...

  Saved: river_reach_ids.csv
  Saved: river_network_tdx_v2_connected.geojson
  Saved: v1/visualizations/v1_river_chains.png
```

### Output files

| File | Description |
|------|-------------|
| `v1/input/river_reach_ids.csv` | One row per river chain; includes GEOGloWS reach ID, forecast validity, peak flow |
| `v1/input/river_network_tdx_v2_connected.geojson` | GeoJSON with `river_id` attribute added to each segment |
| `v1/visualizations/v1_river_chains.png` | Map: left = stream order, right = river chains with outlet markers |

### CSV columns

| Column | Description |
|--------|-------------|
| `river_id` | Internal group ID (0-based, sorted by descending max stream order) |
| `reach_id_geoglows` | TDX `linkno` of the most-downstream segment — use this for GEOGloWS API calls |
| `max_stream_order` | Highest Strahler order in the chain |
| `min_stream_order` | Lowest Strahler order in the chain |
| `n_segments` | Number of TDX segments in the chain |
| `length_km` | Approximate total channel length (great-circle sum) |
| `outlet_lon` / `outlet_lat` | Coordinates of the chain outlet point |
| `geoglows_valid` | `True` if GEOGloWS returned forecast data for this reach ID |
| `forecast_max_q_m3s` | Peak median flow from current GEOGloWS forecast (m³/s) |
| `forecast_date` | Start date of the forecast ensemble |
| `all_linknos` | Semicolon-separated list of all TDX `linkno` values in the chain |

---

## Using GEOGloWS forecasts

To fetch a forecast for a specific reach ID:

```bash
# Forecast (40-day ensemble) — returns CSV with flow_median, flow_uncertainty columns
curl "https://geoglows.ecmwf.int/api/v2/forecast/110250134/"

# Historical simulation (retrospective)
curl "https://geoglows.ecmwf.int/api/v2/retrospective/110250134/"

# Snap a lat/lon coordinate to the nearest reach ID
curl "https://geoglows.ecmwf.int/api/v2/getriverid/?lat=-1.30&lon=36.83"
```

In Python:
```python
import pandas as pd
from io import StringIO
import requests

reach_id = 110250134
r = requests.get(f"https://geoglows.ecmwf.int/api/v2/forecast/{reach_id}/")
df = pd.read_csv(StringIO(r.text), parse_dates=[0])
print(df.head())
# Columns: datetime, flow_median, flow_uncertainty_lower, flow_uncertainty_upper
```

---

## Notes and limitations

- **TIPG API**: The `tipg-tiler-template.replit.app` endpoint serves TDX attributes but frequently times out or lacks `NEXT_DOWN` in the response. The geometric fallback reliably connects 116/141 segments.
- **Isolated segments** (25 unconnected): order-2 headwaters whose endpoints don't snap within 0.001° — they remain as single-segment chains.
- **GEOGloWS rate limits**: The API returns HTTP 429 if queried too rapidly. The script uses a 1 s inter-request delay; increase `delay` parameter in `check_geoglows_forecast()` if 429s persist.
- **Forecast flows are low** (0.1–2.1 m³/s): These are dry-season baseline values. During a flash flood event, use the retrospective or ensemble spread rather than the median alone.
