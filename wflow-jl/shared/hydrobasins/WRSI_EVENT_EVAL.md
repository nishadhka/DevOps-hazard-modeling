# v4 WRSI vs documented drought events — representativeness eval

**Question:** does each v4 wflow→WRSI run reproduce the drought loss-and-damage
event documented for its country (icpac-igad/DevOps-hazard-modeling#drought-events)?

**Method:** `eval_wrsi_events.py` → `_eval_wrsi_events.json` (+ `_eval_som_ssd.json`).
For each case, clipped to its `_v4_basin.geojson`, we compute **per-year**
basin-mean WRSI = `100·ΣAET/ΣPET` (Kc=1 water-balance form) plus ΣAET / ΣPET
(mm/yr). Run windows are **event-tailored per case** (not a uniform period).

The meaningful drought signal is the **year-over-year drop within a basin**
(a dry year suppresses AET relative to PET). Absolute WRSI *between* countries
mostly reflects **aridity**, not severity — so each case is judged on its own
inter-annual change. All 11 grids are valid as of 2026-06-06 (SOM/SSD re-run).

## Per-year basin-mean WRSI (event years marked ◀)

| ISO | Event (period) | Run window | 2016 | 2017 | 2020 | 2021 | 2022 | 2023 | Full |
|-----|----------------|-----------|------|------|------|------|------|------|------|
| BDI | Burundi 2021-22 | 2021-22 | | | | 74◀ | 70◀ | | 72 |
| DJI | Djibouti 2022 | 2021-23 | | | | 26 | **9◀** | 10 | 15 |
| ERI | Central Highlands 2021-23 | 2021-23 | | | | 23◀ | 14◀ | 7◀ | 14 |
| ETH | Blue Nile HW 2021-22 | 2020-23 | | | 51 | 39◀ | 36◀ | 39 | 41 |
| KEN | Tana/ASAL 2020-23 | 2020-23 | | | 47◀ | 22◀ | 18◀ | 23◀ | 27 |
| RWA | Akagera 2016-17 | 2016-17 | 70◀ | 68◀ | | | | | 69 |
| SOM | South-Central 2020-23 | 2020-23 | | | 36◀ | 14◀ | **12◀** | 29◀ | 22 |
| SSD | Upper Nile 2021-23 | 2021-23 | | | | 36◀ | 29◀ | 25◀ | 30 |
| SSD·upper_nile | Upper Nile 2021-23 (corrected) | 2020-23 | | | 42 | 28◀ | 28◀ | 21◀ | 30 |
| SDN | Eastern States 2022 | 2021-23 | | | | 43 | 32◀ | 28 | 34 |
| TZA | Kagera 2021-22 | 2022-23 | | | | — | 40◀ | 37 | 39 |
| TZA·kagera | Kagera 2021-22 (corrected) | 2020-23 | | | 75 | 56◀ | 53◀ | 61 | 61 |
| UGA | Karamoja 2022 | 2021-22 | | | | 68 | 63◀ | | 65 |
| UGA·karamoja | Karamoja 2022 (corrected) | 2020-23 | | | 79 | 30 | 33◀ | 29 | 41 |
| BDI·baseline | Burundi 2021-22 (+baseline) | 2020-23 | | | 74 | 72◀ | 71◀ | 76 | 73 |
| RWA·baseline | Akagera 2016-17 (+baseline) | 2014-17 | 67◀ | 67◀ | | | | | 70 |

(WRSI bands, FAO: <50 crop-failure, 50–79 water-stress, ≥80 no/min-stress.)

## Verdicts

**Strong / representative** — correctly-timed AET/WRSI collapse in event years:
- **DJI** 2022: 26→**9.4** (ΣAET 454→162) — sharp single-year drought.
- **KEN** Tana: 47→22→18→23, worst 2021-22 — matches the real 2020-23 Horn of
  Africa drought (worst in 40 yrs).
- **ERI**: monotonic 23→14→7 — deepening multi-year drought.
- **SOM** South-Central (Juba-Shabelle): 36→14→**12**→29 (ΣAET 728→242→584) —
  textbook famine-threat trajectory, 2021-22 minimum, 2023 recovery.
- **ETH** Blue Nile: event yrs 2021-22 (39/36) clearly below the 2020 baseline (51).

**Moderate:**
- **SDN**: 2022 dip 43→32, but dryness persists into 2023; basin (Sennar/Lower
  Blue Nile) is adjacent to — not the same as — the "Eastern States" event.
- **SSD** (original): temporally a deepening drought (36→29→25, ΣAET
  645→454→340), BUT **spatial mismatch** — modeled basin is **Bahr el Ghazal
  (NW)** while the event is **Upper Nile (NE)**. → **corrected below.**

**Weak** — humid Great-Lakes basins, WRSI stays 60-74, only mild dips:
- **BDI** 74→70, **RWA** 70→68 (window correctly event-tailored to 2016-17),
  **UGA** 68→63 (signal diluted — basin = Lake Kyoga, wetter than Karamoja proper).

**Poor:**
- **TZA** (original) — modeled basin is **Pangani (NE)** but the event is
  **Kagera (NW)**: wrong basin; run window 2022-23 also misses 2021 of the
  2021-22 event. Flat 40→37.

**Corrected — TZA·kagera (2026-06-08):** rebuilt on the **Kagera NW basin**
(lev-6, seed 31.30,-1.60, ~6,750 km², NW Tanzania) over **2020-23**. WRSI
**2020=75 → 2021=56 → 2022=53 → 2023=61** (ΣAET 1082→839→793→907): a clear
~20-pt dip in the event years below the 2020 baseline, with 2023 recovery —
now **representative** of the Kagera 2021-22 drought (vs the flat, wrong-basin
Pangani run). Built alongside Pangani as case `tza_kagera`; magnitude is
moderate because Kagera is a semi-humid highland basin.

**Corrected — SSD·upper_nile (2026-06-09):** rebuilt on the **Upper Nile /
Sobat basin** (lev-5 unit, seed 33.00,9.30, ~42,000 km², E Upper Nile state)
over **2020-23**. WRSI **2020=42 → 2021=28 → 2022=28 → 2023=21** (ΣAET
991→691→678→531): a clear deepening multi-year drought below the 2020 baseline
— now **representative** of the Upper Nile 2021-23 event AND in the right
region (Sobat/NE) vs the original Bahr el Ghazal (NW). Built alongside as case
`ssd_upper_nile` (hot semi-arid lowland: PET ~2500 mm/yr, T 28°C).

**Corrected — UGA·karamoja (2026-06-10):** the original UGA used a lev-5 unit
that lumps semi-arid Karamoja with the wetter Lake Kyoga drainage, diluting the
signal (68→63). Rebuilt on **Karamoja proper** (lev-6 unit, seed 34.65,2.53,
~6.7k km², NE Uganda) over 2020-23: WRSI **79 → 30 → 33 → 29** (ΣAET
1567→685) — a dramatic collapse from the 2020 baseline into the 2021-23
Karamoja food-crisis years. **Now strongly representative** (the single most
improved correction). Case `uga_karamoja`.

**Baseline re-runs — BDI / RWA (2026-06-10):** to test whether the humid
Great-Lakes weakness is real or a missing-baseline artifact, re-ran both with a
pre-event baseline year. **BDI·baseline** (Ruvubu, 2020-23): 74→72→71→76 —
**flat**, confirming no water-balance drought in 2021-22 (ERA5 has no deficit
there); genuinely weak, not an artifact. **RWA·baseline** (Lower Akagera,
2014-17): 76→69→67→67 — a **mild ~8-pt** dip below the 2014 baseline (the
2015-16 El Niño drought, muted in this humid basin). Both confirm the humid-GL
signals are real magnitude limits.

**Corrected — SDN·eastern (2026-06-10):** rebuilt on the **Kassala/Gash basin**
(lev-5 unit, seed 36.40,15.45, ~73k km², E Sudan toward the Red Sea) over
2020-23: WRSI **25 → 9 → 9 → 7** (ΣAET 463→128) — severe sustained water
stress in 2021-23 vs the 2020 baseline, in the correct Eastern-States region
(vs the original Sennar/Lower Blue Nile). Hyper-arid (P ~0.5 mm/d) so WRSI is
always very low. Case `sdn_eastern`. (NOTE: needed an ldd 255→pit fix — a
unit-basin in a large bbox leaves nodata-ldd edge cells that Wflow's
`NetworkLand` includes because `repair_v4_staticmaps` strips `_FillValue`;
build_v4_correction.py / phase3 should set ldd 255→5.)

## Caveats
1. Annualized water-balance WRSI (Kc=1), **not** FAO season-based WRSI —
   relative inter-annual change is the reliable signal; seasonal (OND/MAM) WRSI
   would sharpen the bimodal-rainfall cases (KEN/SOM/ETH).
2. The drought signal is **bounded by ERA5 forcing** — if ERA5 misses a rainfall
   deficit, wflow cannot show it (ERA5 under-resolves parts of the HoA drought).
3. WRSI is an **agricultural/crop-water-stress** proxy; the L&D events also
   involve livestock, displacement, etc., which WRSI does not capture.
4. WRSI is averaged over the **hydrological basin**, which for TZA/SSD (and
   partly SDN/UGA) ≠ the event's named administrative region.

## Recommended follow-ups
- Fix **TZA** (run the Kagera basin over 2021-22) and reconcile **SSD**
  (Upper Nile vs Bahr el Ghazal) so the basin matches the event region.
- Optionally compute **seasonal** WRSI for the bimodal cases.
