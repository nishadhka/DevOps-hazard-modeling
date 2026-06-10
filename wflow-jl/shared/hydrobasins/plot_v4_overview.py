"""Overview map of the 11 ICPAC drought-event basins — FINAL/CORRECTED set.

Plots each country's final basin polygon (corrected where a correction was built
this session) over a Natural Earth admin base, with an ISO label at each basin
centroid and a country·basin legend. `*` in the legend = basin corrected to
match the event region (SSD/SDN/TZA/UGA).

Output: runs/v4_wrsi_plots/overview_v4_corrected.png (HF: v4_wrsi_plots/).
Run: `uv run python -m shared.hydrobasins.plot_v4_overview`.

Companion to v4_recommended.py's overview_v4.png (which draws the *original*
selections); see WRSI_EVENT_EVAL.md / WRSI_CORRECTION_STEPS.md.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.cm as cm           # noqa: E402
import matplotlib.pyplot as plt      # noqa: E402
import numpy as np                   # noqa: E402
import geopandas as gpd              # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from shared.hydrobasins.download import ensure_natural_earth  # noqa: E402

GEO = Path(__file__).resolve().parent / "outputs_v4"
OUT = REPO / "runs" / "v4_wrsi_plots" / "overview_v4_corrected.png"

# (ISO, basin-geojson stem, legend label). `*` = corrected basin.
# BDI/RWA use their *_baseline geojson (identical polygon to the original).
CASES = [
    ("BDI", "01b_burundi_ruvubu_baseline_v4_basin", "BDI Ruvubu"),
    ("DJI", "02_djibouti_dji_v4_basin", "DJI Afar"),
    ("ERI", "03_eritrea_eri_v4_basin", "ERI Anseba"),
    ("ETH", "04_ethiopia_eth_v4_basin", "ETH Blue Nile"),
    ("KEN", "05_kenya_ken_v4_basin", "KEN Tana"),
    ("RWA", "06b_rwanda_akagera_baseline_v4_basin", "RWA L.Akagera"),
    ("SOM", "07_somalia_som_v4_basin", "SOM Juba-Shabelle"),
    ("SSD", "08b_south_sudan_upper_nile_v4_basin", "SSD Upper Nile/Sobat *"),
    ("SDN", "09b_sudan_kassala_v4_basin", "SDN Kassala/Gash *"),
    ("TZA", "10b_tanzania_kagera_v4_basin", "TZA Kagera NW *"),
    ("UGA", "11b_uganda_karamoja_v4_basin", "UGA Karamoja *"),
]


def main():
    colors = cm.tab20(np.linspace(0, 1, len(CASES)))
    admin = gpd.read_file(ensure_natural_earth(), engine="pyogrio")
    fig, ax = plt.subplots(figsize=(13, 12))
    admin.boundary.plot(ax=ax, color="#999", linewidth=0.4)
    for (iso, stem, lab), c in zip(CASES, colors):
        g = gpd.read_file(GEO / f"{stem}.geojson").to_crs(4326).dissolve()
        g.plot(ax=ax, color=c, alpha=0.6, edgecolor="black", linewidth=0.5,
               label=lab)
        cen = g.geometry.iloc[0].representative_point()
        ax.annotate(iso, (cen.x, cen.y), ha="center", va="center",
                    fontsize=8, fontweight="bold")
    ax.set_xlim(20, 52)
    ax.set_ylim(-13, 23)
    ax.set_aspect("equal")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.set_title("v4 WRSI — final/corrected basins for the 11 ICPAC drought "
                 "events\n(* = basin corrected to match the event region)")
    ax.legend(loc="lower left", fontsize=8, frameon=True, ncol=2,
              title="country · basin")
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
