"""v2_cdi: Combined Drought Indicator analysis over the 11 ICPAC case extents.

Single script — top-to-bottom, no CLI. Reads the CDI icechunk store published
by ICPAC at source.coop, subsets per case (event period + bounding box from
region_configs), and writes:

  - <iso>_cdi_stats.png       : 3-panel mean / max / min CDI over the period
                                 inside the case bbox.
  - <iso>_basins_labelled.png : HydroBASINS lvl-8 polygons over the mean CDI
                                 for ERI / SDN / SSD / SOM — the cases where
                                 the storyline area covers a large country
                                 extent and the right sub-basin has to be
                                 chosen manually. Labels show the last 6
                                 digits of each HYBAS_ID; the top 30 polygons
                                 by area are labelled to keep the plot
                                 readable.
  - <iso>_basins.geojson      : the labelled polygons exported for QGIS so
                                 you can open the same set and pick by ID.

PNGs + GeoJSONs are pushed to E4DRR/wflow.jl-simulations under
hydrobasins/v2_cdi/ via shared.hydrobasins.upload_to_hf.

Source.coop CDI store:
    s3://us-west-2.opendata.source.coop/e4drr-project/observations/icpac_cdi_dekadal_icechunk
"""
from pathlib import Path
import sys

import geopandas as gpd
import icechunk as ic
import matplotlib.pyplot as plt
import xarray as xr
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from region_configs import REGIONS
from shared.hydrobasins.download import ensure_level, ensure_natural_earth

OUT_DIR = HERE / "outputs_v2_cdi"
OUT_DIR.mkdir(exist_ok=True)

# Cases where the storyline basin isn't obvious from the bbox and needs manual
# selection by HYBAS_ID. The labelled basin plot is generated only for these.
NEEDS_BASIN_LABELS = {"ERI", "SDN", "SSD", "SOM"}

# -- 1. Open the CDI icechunk store from source.coop --
print("Opening CDI icechunk store from source.coop ...")
storage = ic.s3_storage(
    bucket="us-west-2.opendata.source.coop",
    prefix="e4drr-project/observations/icpac_cdi_dekadal_icechunk",
    region="us-west-2",
    anonymous=True,
)
repo = ic.Repository.open(storage)
session = repo.readonly_session("main")
cdi = xr.open_zarr(session.store, consolidated=False, zarr_format=3)["cdi"]
print(f"CDI: {dict(cdi.sizes)}, {cdi.time.values[0]} → {cdi.time.values[-1]}")

# -- 2. HydroBASINS lvl 8 + Natural Earth admin --
print("Loading HydroBASINS lvl 8 + admin polygons ...")
hb = gpd.read_file(ensure_level(8), engine="pyogrio")
admin = gpd.read_file(ensure_natural_earth(), engine="pyogrio")

# -- 3. Per-case analysis --
for case_name, cfg in REGIONS.items():
    iso = cfg["country_iso"]
    start, end = cfg["start"], cfg["end"]
    b = cfg["bounds"]

    # latitude descends in this dataset, so slice north → south
    cdi_sub = cdi.sel(
        time=slice(start, end),
        lat=slice(b["north"], b["south"]),
        lon=slice(b["west"], b["east"]),
    )
    n_steps = cdi_sub.sizes["time"]
    if n_steps == 0:
        print(f"  [{iso}] no CDI data in {start}–{end}, skipping")
        continue
    print(f"  [{iso}] {case_name}: {n_steps} dekads × "
          f"{cdi_sub.sizes['lat']}×{cdi_sub.sizes['lon']} px — computing stats")

    mean_da = cdi_sub.mean("time", skipna=True).compute()
    max_da = cdi_sub.max("time", skipna=True).compute()
    min_da = cdi_sub.min("time", skipna=True).compute()

    # --- Plot A: mean / max / min ---
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.5), sharey=True)
    vmin = float(min_da.min())
    vmax = float(max_da.max())
    last_im = None
    for ax, da, title in zip(axes, [mean_da, max_da, min_da],
                             ["mean", "max", "min"]):
        last_im = da.plot(ax=ax, cmap="RdYlBu", vmin=vmin, vmax=vmax,
                          add_colorbar=False)
        admin.boundary.plot(ax=ax, color="#444", linewidth=0.4)
        ax.set_xlim(b["west"], b["east"])
        ax.set_ylim(b["south"], b["north"])
        ax.set_aspect("equal")
        ax.set_title(f"{title} CDI")
    fig.colorbar(last_im, ax=axes, orientation="horizontal",
                 fraction=0.04, pad=0.08, label="CDI")
    fig.suptitle(
        f"{case_name} {iso} — CDI {start} to {end}  ({n_steps} dekads)"
    )
    fig.savefig(OUT_DIR / f"{iso.lower()}_cdi_stats.png",
                dpi=140, bbox_inches="tight")
    plt.close(fig)

    # --- Plot B: labelled basins (only for the ambiguous cases) ---
    if iso in NEEDS_BASIN_LABELS:
        bbox_geom = box(b["west"], b["south"], b["east"], b["north"])
        nearby = hb[hb.intersects(bbox_geom)].copy()
        nearby_proj = nearby.to_crs("ESRI:54009")
        nearby["area_km2"] = nearby_proj.area.values / 1e6
        # Label only the 30 largest polygons to keep the plot legible
        labelled = nearby.sort_values("area_km2", ascending=False).head(30)

        fig, ax = plt.subplots(figsize=(13, 12))
        mean_da.plot(ax=ax, cmap="RdYlBu", alpha=0.7,
                     cbar_kwargs={"label": "mean CDI"})
        nearby.boundary.plot(ax=ax, color="black", linewidth=0.4)
        admin.boundary.plot(ax=ax, color="#222", linewidth=1.0)
        for _, row in labelled.iterrows():
            c = row.geometry.representative_point()
            ax.annotate(str(int(row["HYBAS_ID"]))[-6:],
                        xy=(c.x, c.y), fontsize=5.5, ha="center",
                        color="black",
                        bbox=dict(facecolor="white", alpha=0.5,
                                  edgecolor="none", pad=0.4))
        ax.set_xlim(b["west"], b["east"])
        ax.set_ylim(b["south"], b["north"])
        ax.set_aspect("equal")
        ax.set_title(
            f"{case_name} {iso} — HydroBASINS lvl 8 over mean CDI "
            f"{start}–{end}\n(labels show last 6 digits of HYBAS_ID for "
            f"the top 30 polygons by area; {len(nearby)} total in extent)"
        )
        fig.savefig(OUT_DIR / f"{iso.lower()}_basins_labelled.png",
                    dpi=160, bbox_inches="tight")
        plt.close(fig)

        # Export the same polygons as GeoJSON for QGIS-side selection
        nearby[["HYBAS_ID", "NEXT_DOWN", "area_km2", "geometry"]].to_file(
            OUT_DIR / f"{iso.lower()}_basins.geojson", driver="GeoJSON"
        )

print(f"\nDone. Outputs in {OUT_DIR}")
