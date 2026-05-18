# v4 Finalised Basin Selection (current)

Source of truth: `shared/hydrobasins/v4_recommended.py` (RECS).
Verified **current** — the built `staticmaps.nc` grids on
`/mnt/wflow-secondary/v4_models/<iso>/` match these selections (ERI lev-6
Anseba, BDI Ruvubu, SSD Bahr el Ghazal, SDN Lower Blue Nile, TZA Pangani).
Geojsons on HF: `E4DRR/wflow.jl-simulations/hydrobasins/v4/` —
`<ev>_<iso>_v4.geojson` = bbox run-extent, `_v4_basin.geojson` = basin mask.

| # | ISO | Basin (v4) | HydroBASINS lvl | mode | seed (lon,lat) | target km² | selected km² | built grid (lat×lon) | wflow→WRSI |
|--|--|--|--|--|--|--|--|--|--|
| 01 | BDI | Ruvubu (S Burundi Kagera trib.) | 6 | basin | 30.30,-3.10 | 12,000 | 12,231 | 171×158 | ✅ |
| 02 | DJI | Lake Asal–Lake Abbé endorheic (Afar) | 4 | basin | 41.80,11.16 | 23,000 | 16,877 | 180×174 | ✅ |
| 03 | ERI | Anseba / Red Sea coastal | 6 | basin | 38.45,15.78 | 15,000 | 16,392 | 142×210 | ✅ |
| 04 | ETH | Blue Nile / Abbay | 4 | basin | 34.95,11.13 | 200,000 | 308,197 | 928×815 | ⏳ running |
| 05 | KEN | Tana | 4 | basin | 40.30,-2.40 | 95,000 | 95,249 | 393×446 | ✅ |
| 06 | RWA | Lower Akagera | 6 | basin | 30.79,-2.38 | 25,000 | 18,488 | 186×173 | ✅ |
| 07 | SOM | Juba-Shabelle (combined) | 4 | basin | 42.55,-0.36 | 810,000 | 797,881 | 1119×1096 | ⏳ running |
| 08 | SSD | Bahr el Ghazal (SSD-internal) | 4 | basin | 27.40,8.77 | 520,000 | 615,820 | 1235×818 | ✅ |
| 09 | SDN | Lower Blue Nile (Sennar reach) | 5 | unit | 33.63,13.55 | 80,000 | 67,122 | 591×420 | ✅ |
| 10 | TZA | Pangani (EM-DAT NE) | 5 | unit | 37.80,-4.30 | 43,000 | 51,383 | 289×291 | ✅ |
| 11 | UGA | Lake Kyoga drainage (S Karamoja) | 5 | unit | 34.00,2.00 | 75,000 | 43,183 | 372×245 | ✅ |

**v4 changes vs v3** (reviewed/approved on HF): BDI→Ruvubu (moved S),
ERI→Anseba/Red-Sea lev-6 (moved E, refined), SSD→Bahr el Ghazal
(SSD-internal, no Uganda), SDN→Lower Blue Nile (2nd option),
TZA→Pangani (2nd option). Other 6 carried from v3.

**Run status (2026-05-18):** 9/11 WRSI grids complete
(`<iso>/output/output_grid_wrsi.nc`); ETH + SOM running (largest grids).
The 5 large/endorheic cases needed: median-fill repair of soil/river
NaN + `pyflwdir.from_dem` ldd rebuild (cycle-free) before wflow ran.

`mode`: **basin** = BFS-upstream from snapped outlet; **unit** = single
HydroBASINS tile at the seed.
