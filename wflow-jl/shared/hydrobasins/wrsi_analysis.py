"""WRSI from the RWA new-direction gridded run.

Single script, no CLI. Reads runs/rwa_wrsi/output/output_grid_wrsi.nc, derives
the Water Requirement Satisfaction Index (water-balance form, Kc=1):

    WRSI = 100 * sum_season(AET) / sum_season(PET)

Writes to runs/rwa_wrsi/wrsi/:
  - rwa_wrsi_grid.nc          per-pixel WRSI (whole period + per calendar year)
  - rwa_original_output.png   raw Wflow basin-mean series (the model output)
  - rwa_wrsi_output.png       derived WRSI: spatial map(s) + dekadal cumulative
                              basin-mean WRSI with FAO class bands

Context + the Julia 1.12 -> 1.10 / Wflow v1.0.2 issue: see
runs/rwa_wrsi/NEW_DIRECTION.md
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from matplotlib.colors import BoundaryNorm, ListedColormap

RUN = Path(__file__).resolve().parents[2] / "runs" / "rwa_wrsi"
NC = RUN / "output" / "output_grid_wrsi.nc"
CSV = RUN / "output" / "output_rwanda_wrsi.csv"
OUT = RUN / "wrsi"
OUT.mkdir(exist_ok=True)

# FAO WRSI interpretation classes
FAO_BOUNDS = [0, 50, 80, 150]
FAO_COLORS = ["#d7191c", "#fdae61", "#1a9641"]  # failure / stress / no-stress
FAO_LABELS = ["<50 crop-failure likelihood", "50-79 water stress",
              ">=80 no/minimal stress"]


def wrsi_grid(aet: xr.DataArray, pet: xr.DataArray) -> xr.DataArray:
    """100 * sum(AET)/sum(PET) over the time axis, masked where PET~0."""
    sa = aet.sum("time", skipna=True)
    sp = pet.sum("time", skipna=True)
    w = 100.0 * sa / sp.where(sp > 1e-6)
    return w.clip(0, 150)


# ---- load gridded run ----
ds = xr.open_dataset(NC)
aet, pet = ds["aet"], ds["pet"]
years = sorted(set(pd.to_datetime(ds.time.values).year))

# ---- WRSI grids: whole period + per calendar year ----
grids = {"period": wrsi_grid(aet, pet)}
for y in years:
    sel = ds.time.dt.year == y
    grids[str(y)] = wrsi_grid(aet.sel(time=sel), pet.sel(time=sel))

wrsi_ds = xr.Dataset({f"wrsi_{k}": v for k, v in grids.items()})
wrsi_ds.to_netcdf(OUT / "rwa_wrsi_grid.nc")

# ---- basin-mean dekadal cumulative WRSI series (per year) ----
aet_bm = aet.mean(["lat", "lon"], skipna=True).to_series()
pet_bm = pet.mean(["lat", "lon"], skipna=True).to_series()
bm = pd.DataFrame({"aet": aet_bm, "pet": pet_bm})
bm.index = pd.to_datetime(bm.index)
dek = bm.resample("10D").sum()
dek["year"] = dek.index.year
dek["wrsi_cum"] = (
    100 * dek.groupby("year")["aet"].cumsum()
    / dek.groupby("year")["pet"].cumsum()
).clip(0, 150)
dek.to_csv(OUT / "rwa_wrsi_dekadal.csv")

# ---- PLOT 1: original Wflow output (basin-mean model series) ----
df = pd.read_csv(CSV, parse_dates=["time"]).set_index("time")
fig, ax = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
ax[0].plot(df.index, df["Q"], color="#1f77b4")
ax[0].set_ylabel("Q (m³/s)")
ax[0].set_title("Original Wflow output — Rwanda dr_case6 (basin mean), "
                "Wflow v1.0.2 / Julia 1.10")
ax[1].plot(df.index, df["sm_rootzone"], color="#8c564b")
ax[1].set_ylabel("root-zone\nVWC (m³/m³)")
ax[2].plot(df.index, df["pet"], color="#ff7f0e", label="PET")
ax[2].plot(df.index, df["transpiration"], color="#2ca02c", label="transpiration")
ax[2].set_ylabel("flux (mm/day)")
ax[2].legend(loc="upper right", fontsize=8)
ax[2].set_xlabel("date")
for a in ax:
    a.grid(alpha=0.3)
fig.tight_layout()
fig.savefig(OUT / "rwa_original_output.png", dpi=140)
plt.close(fig)

# ---- PLOT 2: derived WRSI ----
cmap = ListedColormap(FAO_COLORS)
norm = BoundaryNorm(FAO_BOUNDS, cmap.N)
ncols = 1 + len(years)
fig = plt.figure(figsize=(6 * ncols, 6.5))

for i, key in enumerate(["period"] + [str(y) for y in years]):
    ax = fig.add_subplot(1, ncols, i + 1)
    g = grids[key]
    im = ax.pcolormesh(g["lon"], g["lat"], g.values, cmap=cmap, norm=norm)
    ax.set_aspect("equal")
    ax.set_title(f"WRSI {key}\nbasin mean = {float(g.mean()):.0f}")
    ax.set_xlabel("lon")
    if i == 0:
        ax.set_ylabel("lat")
cbar = fig.colorbar(im, ax=fig.axes, orientation="horizontal",
                    fraction=0.045, pad=0.08, ticks=[25, 65, 115])
cbar.ax.set_xticklabels(FAO_LABELS)
fig.suptitle("Derived WRSI = 100 x ΣAET/ΣPET (Kc=1) — Rwanda 2016–2017",
             y=1.02)
fig.savefig(OUT / "rwa_wrsi_output.png", dpi=150, bbox_inches="tight")
plt.close(fig)

# ---- console summary ----
print(f"WRSI grid written: {OUT/'rwa_wrsi_grid.nc'}")
for k, g in grids.items():
    v = g.values[np.isfinite(g.values)]
    fail = 100 * (v < 50).mean()
    stress = 100 * ((v >= 50) & (v < 80)).mean()
    ok = 100 * (v >= 80).mean()
    print(f"  WRSI {k:>7}: mean={v.mean():5.1f}  "
          f"<50={fail:4.1f}%  50-79={stress:4.1f}%  >=80={ok:4.1f}%")
print(f"Plots: {OUT/'rwa_original_output.png'}, {OUT/'rwa_wrsi_output.png'}")
