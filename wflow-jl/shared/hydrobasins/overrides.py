"""Outlet overrides for HydroBASINS contributing-area analysis.

Why this exists
---------------
`region_configs.REGIONS[*]["outlet"]` records the *wflow-pixel* outlet that was
used when each case's wflow model was built — derived from MERIT-Hydro flow
accumulation at 1 km. Those points are fine for wflow but are not always good
seeds for HydroBASINS upstream-walk:

* Some outlets sit on a small tributary, not the basin mouth (RWA, TZA, BDI).
* Some outlets are offshore or right at the coast and don't fall inside any
  HydroBASINS land polygon (DJI).
* Some outlets are on a different river system than the storyline title
  implies (KEN was on the Juba/Shabelle side, not the Tana mouth).
* Some outlets are downstream of where the storyline focuses (ETH was at the
  Blue Nile in Sudan, not at the Ethiopia–Sudan crossing).

This module supplies a corrected (lon, lat) per case for HydroBASINS analysis
only. region_configs.py is **not** modified — the wflow builds keep their
original outlets, which were tied to the rasters they were built on.

For the three planned cases without any outlet (SOM, SSD, SDN), tentative
river-mouth outlets are provided so they get a real contributing-area polygon
instead of the country-bbox fallback.
"""
from __future__ import annotations

# (lon, lat, short note)
HYDROBASINS_OUTLETS: dict[str, tuple[float, float, str]] = {
    "BDI": (29.36, -3.40,
            "Ruzizi River mouth at Lake Tanganyika, just south of Bujumbura"),
    "DJI": (42.95, 11.50,
            "Inner Gulf of Tadjoura coast (Djibouti has no perennial river — "
            "this is a wadi-system proxy; treat result as approximate)"),
    "RWA": (30.79, -2.38,
            "Akagera at Rusumo Falls — Rwanda's downstream exit to Tanzania"),
    "KEN": (40.52, -2.55,
            "Tana River mouth at the Indian Ocean (Kipini, Lamu County)"),
    "TZA": (31.78, -1.31,
            "Kagera River mouth at Lake Victoria, Sango Bay (TZA/UGA border)"),
    "ETH": (34.95, 11.13,
            "Blue Nile (Abay) at the Ethiopia–Sudan border crossing — "
            "the natural lower limit of the 'Blue Nile headwaters' storyline"),
    # ERI and UGA already match storyline area well — no override needed.
    "SOM": (42.55, -0.36,
            "Juba River mouth at Kismayo (Indian Ocean)"),
    "SSD": (31.65, 9.55,
            "White Nile / Sobat confluence near Malakal (Upper Nile state)"),
    "SDN": (33.97, 17.67,
            "Atbara River mouth at the Nile near Atbara town (eastern Sudan)"),
}


def get(iso: str) -> tuple[float, float] | None:
    """Return (lon, lat) override for an ISO, or None if no override exists."""
    entry = HYDROBASINS_OUTLETS.get(iso.upper())
    return (entry[0], entry[1]) if entry else None


def note(iso: str) -> str | None:
    entry = HYDROBASINS_OUTLETS.get(iso.upper())
    return entry[2] if entry else None
