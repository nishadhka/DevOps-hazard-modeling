# ECMWF SPEI Dataset Download and PET Calculation Note

## Overview

This note summarizes the data acquisition, methodology, and processing approach for calculating the Standardized Precipitation Evapotranspiration Index (SPEI) following the methodology described in the **ECMWF paper** and its relationship to available methods in [**xclim**](https://xclim.readthedocs.io/en/stable/indices.html#xclim.indices.water_budget).

---

## Background

### The SPEI Calculation (per ECMWF paper)

The paper [ERA5–Drought: Global drought indices based on ECMWF reanalysis](https://www.nature.com/articles/s41597-025-04896-y)

The SPEI integrates precipitation (P) and potential evapotranspiration (PET) to capture the combined effect of water supply and atmospheric demand on drought conditions. PET is estimated using the **Penman-Monteith (PM) parameterization**, which requires several meteorological variables:

* Mean daily temperature (T)
* Net radiation at the surface (Rn)
* Soil heat flux (G)
* Wind speed at 2 meters (U)
* Saturation vapor pressure deficit (es - ea)
* Psychrometric constant (γ)
* Slope of the saturation vapor pressure curve (Δ)

The formula is provided in the paper and requires relatively extensive input data that are often unavailable from conventional station observations.

Once PET is computed, the SPEI is obtained by standardizing the climatology of P − PET anomalies using a log-logistic distribution.

---

## Data Acquisition

The dataset required for the SPEI computation was acquired from the **ECMWF Climate Data Store (CDS)** using the attached Python script: `api-download-yearmonth.py`.

### Key characteristics of the download:

* **Dataset:** ECMWF Seasonal Forecast - original single levels
* **Variables Downloaded (11 total):**

  * 10m\_u\_component\_of\_wind
  * 10m\_v\_component\_of\_wind
  * 2m\_temperature
  * evaporation
  * maximum 2m temperature in the last 24 hours
  * minimum 2m temperature in the last 24 hours
  * surface net solar radiation
  * surface net thermal radiation
  * surface solar radiation downwards
  * surface thermal radiation downwards
  * total precipitation
* **Spatial Domain:** East Africa (23°N, 21°E, -12°S, 53°E)
* **Temporal Domain:** 1981 to 2025
* **Temporal Resolution:** 6-hourly forecast steps (860 lead times per monthly initialization)
* **Output Format:** GRIB

Each monthly download produces a file of approximately **250-600 MB per month based on 25 ensemble members upto 2016 or 51 from 2017 onwards and ** due to the large number of variables and temporal steps. The total dataset includes `1981–2025 x 12 months = 540 files`. 

### Download Approach:

* The script allows two modes: either direct download or request submission via CDS API.
* The preferred approach is to initiate the request (option 2 in the script), allow the CDS system to process large multi-year requests, and download later once ready.
* The system is being processed progressively: starting with 1-year chunks, then expanding to larger batches like 5 years, to avoid overload and maintain CDS service stability.

---

## Comparison to xclim Methods

The **xclim** Python library provides several PET estimation methods, as described in their documentation ([xclim PET documentation](https://xclim.readthedocs.io/en/stable/indices.html#xclim.indices.potential_evapotranspiration)):

| Method                   | Name       | Input Requirements                                                       |
| ------------------------ | ---------- | ------------------------------------------------------------------------ |
| Penman-Monteith (FAO-98) | `FAO_PM98` | Requires temperature, relative humidity, solar radiation, and wind speed |
| Hargreaves (1985)        | `HG85`     | Requires only temperature (tasmin, tasmax)                               |
| Thornthwaite (1948)      | `TW48`     | Requires temperature                                                     |
| Baier-Robertson (1965)   | `BR65`     | Requires tasmin, tasmax                                                  |
| McGuinness-Bordne (2005) | `MB05`     | Requires tas and latitude                                                |
| Droogers-Allen (2002)    | `DA02`     | Requires temperature and precipitation                                   |

### Key differences:

* The **ECMWF paper method** uses the fully-physical Penman-Monteith formulation, with the full set of surface energy balance variables, requiring comprehensive meteorological data.
* The **xclim library** provides both physically based (e.g., FAO\_PM98) and empirical methods (e.g., Hargreaves, Thornthwaite) depending on available input.

