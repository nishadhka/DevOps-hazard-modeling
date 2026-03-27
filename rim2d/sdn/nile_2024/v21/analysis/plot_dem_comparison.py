#!/usr/bin/env python3
"""
Before/after DEM comparison: v10 original vs v21 conditioned.

Shows the effect of:
  - Fix 5a: Nile floodplain burn (dem<308m → 294m)
  - Fix 6a/b/c: GeoJSON stream burns + gap bridge + culvert
  - Fix 7: Pysheds depression filling + resolve_flats (two passes)

Usage:
    micromamba run -n zarrv3 python v21/analysis/plot_dem_comparison.py
"""

from pathlib import Path
import numpy as np
import netCDF4
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

WORK_DIR = Path("/data/rim2d/nile_highres")
V10_NC   = WORK_DIR / "v10" / "input" / "dem.nc"
V21_NC   = WORK_DIR / "v21" / "input" / "dem_v21.nc"
VIZ_DIR  = WORK_DIR / "v21" / "analysis" / "visualizations"
VIZ_DIR.mkdir(parents=True, exist_ok=True)
DPI = 150

INFLOW_DEFS = {
    "Culvert1":    {"row": 212, "col": 312, "sill": 321.1, "color": "red"},
    "Culvert2":    {"row": 222, "col": 266, "sill": 320.0, "color": "orange"},
    "WesternWadi": {"row": 222, "col": 175, "sill": 318.9, "color": "green"},
    "HospitalWadi":{"row": 183, "col": 281, "sill": 316.1, "color": "purple"},
}

# ── Load DEMs ──────────────────────────────────────────────────────────────────
def load_nc(path):
    ds = netCDF4.Dataset(str(path))
    var = [v for v in ds.variables if v not in ("x","y")][0]
    d = np.array(ds[var][:]).squeeze().astype(float)
    x = np.array(ds["x"][:])
    y = np.array(ds["y"][:])
    d[d < -9000] = np.nan
    ds.close()
    return d, x, y

print("Loading DEMs ...")
dem_orig, x, y = load_nc(V10_NC)
dem_v21,  _, _ = load_nc(V21_NC)
nrows, ncols = dem_orig.shape

# ── Compute difference ─────────────────────────────────────────────────────────
diff = dem_v21 - dem_orig
lowered  = diff < -0.1    # burned channels / Nile
raised   = diff >  0.1    # filled depressions
n_low  = int(lowered.sum())
n_raise = int(raised.sum())
print(f"  Cells lowered (burns):  {n_low:,}")
print(f"  Cells raised (fill):    {n_raise:,}")
print(f"  Max lowering: {-np.nanmin(diff[lowered]):.1f}m" if n_low else "")
print(f"  Max raising:  {np.nanmax(diff[raised]):.1f}m"   if n_raise else "")


# ══════════════════════════════════════════════════════════════════════════════
# Figure 1: Side-by-side DEM terrain comparison
# ══════════════════════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 3, figsize=(22, 8))

terrain_kw = dict(origin="lower", cmap="terrain", vmin=290, vmax=380, aspect="auto")

# Panel 1: Original DEM
ax = axes[0]
im = ax.imshow(dem_orig, **terrain_kw)
for name, d in INFLOW_DEFS.items():
    ax.plot(d["col"], d["row"], "^", color=d["color"], ms=8, mec="white", mew=0.8)
    ax.text(d["col"]+3, d["row"], name, fontsize=6, color=d["color"])
ax.set_title("v10 Original DEM\n(before any corrections)", fontweight="bold")
ax.set_xlabel("Column"); ax.set_ylabel("Row")
plt.colorbar(im, ax=ax, label="Elevation (m)", shrink=0.8)

# Panel 2: v21 conditioned DEM
ax = axes[1]
im2 = ax.imshow(dem_v21, **terrain_kw)
for name, d in INFLOW_DEFS.items():
    ax.plot(d["col"], d["row"], "^", color=d["color"], ms=8, mec="white", mew=0.8)
    ax.text(d["col"]+3, d["row"], name, fontsize=6, color=d["color"])
ax.set_title("v21 Conditioned DEM\n(burns + depression filling)", fontweight="bold")
ax.set_xlabel("Column")
plt.colorbar(im2, ax=ax, label="Elevation (m)", shrink=0.8)

# Panel 3: Difference map
ax = axes[2]
diff_plot = diff.copy()
diff_plot[np.isnan(diff)] = 0
cmap_diff = plt.cm.RdBu_r
norm_diff = mcolors.TwoSlopeNorm(vmin=-20, vcenter=0, vmax=20)
im3 = ax.imshow(diff_plot, origin="lower", cmap=cmap_diff, norm=norm_diff, aspect="auto")
for name, d in INFLOW_DEFS.items():
    ax.plot(d["col"], d["row"], "^", color=d["color"], ms=8, mec="white", mew=0.8)
    ax.text(d["col"]+3, d["row"], name, fontsize=6, color=d["color"])
ax.set_title(f"Elevation Change (v21 − v10)\nBlue=lowered ({n_low:,} cells)  Red=raised ({n_raise:,} cells)",
             fontweight="bold")
ax.set_xlabel("Column")
plt.colorbar(im3, ax=ax, label="Δ Elevation (m)", shrink=0.8)

fig.suptitle("DEM Corrections: Before vs After Hydrologic Conditioning",
             fontsize=14, fontweight="bold")
fig.tight_layout()
out1 = VIZ_DIR / "v21_dem_comparison_overview.png"
fig.savefig(out1, dpi=DPI, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(f"  Saved: {out1.name}")


# ══════════════════════════════════════════════════════════════════════════════
# Figure 2: Change type map — what was done where
# ══════════════════════════════════════════════════════════════════════════════
fig, axes = plt.subplots(1, 2, figsize=(18, 8))

# Panel 1: Change categories
ax = axes[0]
category = np.zeros(dem_orig.shape, dtype=int)  # 0 = unchanged
# Nile burn (lowered ≥ 5m — large burn from 308m → 294m)
nile_burn = lowered & (diff < -5)
# Channel burn (lowered < 5m — stream burns, culvert, gap bridge)
channel_burn = lowered & (diff >= -5)
# Depression fill (raised)
dep_fill = raised

category[nile_burn]    = 1
category[channel_burn] = 2
category[dep_fill]     = 3

cmap_cat = mcolors.ListedColormap(["#e8e8e8", "#2166ac", "#4dac26", "#d7191c"])
ax.imshow(category, origin="lower", cmap=cmap_cat, vmin=0, vmax=3, aspect="auto",
          interpolation="nearest")
for name, d in INFLOW_DEFS.items():
    ax.plot(d["col"], d["row"], "^", color="gold", ms=9, mec="k", mew=0.8, zorder=5)
    ax.text(d["col"]+3, d["row"], name, fontsize=6.5, color="k",
            bbox=dict(facecolor="white", alpha=0.6, pad=1, edgecolor="none"))

legend_elements = [
    Patch(facecolor="#e8e8e8", label="Unchanged"),
    Patch(facecolor="#2166ac", label=f"Nile floodplain burn ({int(nile_burn.sum()):,} cells)"),
    Patch(facecolor="#4dac26", label=f"Channel/culvert burn ({int(channel_burn.sum()):,} cells)"),
    Patch(facecolor="#d7191c", label=f"Depression fill raised ({n_raise:,} cells)"),
    Line2D([0],[0], marker="^", color="w", markerfacecolor="gold",
           markeredgecolor="k", ms=9, label="Inflow boundaries"),
]
ax.legend(handles=legend_elements, loc="upper left", fontsize=8, framealpha=0.85)
ax.set_title("Correction Type Map\n(what changed and where)", fontweight="bold")
ax.set_xlabel("Column"); ax.set_ylabel("Row")

# Panel 2: Flow path before vs after
# Steepest descent on both DEMs
def path_profile(dem, start_r, start_c, n_steps=400):
    nrows, ncols = dem.shape
    r, c = start_r, start_c
    rows, cols = [r], [c]
    for _ in range(n_steps):
        neighbors = []
        for dr in [-1,0,1]:
            for dc in [-1,0,1]:
                if dr==0 and dc==0: continue
                nr, nc = r+dr, c+dc
                if 0<=nr<nrows and 0<=nc<ncols and not np.isnan(dem[nr,nc]):
                    neighbors.append((dem[nr,nc], nr, nc))
        if not neighbors: break
        min_e, nr, nc = min(neighbors)
        if min_e >= dem[r,c]: break
        r, c = nr, nc
        rows.append(r); cols.append(c)
    return np.array(rows), np.array(cols)

ax = axes[1]
ax.imshow(dem_v21, origin="lower", cmap="terrain", vmin=290, vmax=380,
          aspect="auto", alpha=0.7)

for name, d in INFLOW_DEFS.items():
    # Before (original DEM)
    ro, co = path_profile(dem_orig, d["row"], d["col"])
    ax.plot(co, ro, "--", color=d["color"], lw=1.2, alpha=0.6,
            label=f"{name} before ({len(ro)*30:.0f}m)")
    # After (v21 DEM)
    rv, cv = path_profile(dem_v21, d["row"], d["col"])
    ax.plot(cv, rv, "-", color=d["color"], lw=2.0,
            label=f"{name} after ({len(rv)*30:.0f}m)")
    # Mark inflow
    ax.plot(d["col"], d["row"], "^", color=d["color"], ms=10, mec="white", mew=1, zorder=5)

ax.set_title("Steepest-Descent Flow Paths\nDashed=before, Solid=after conditioning",
             fontweight="bold")
ax.set_xlabel("Column"); ax.set_ylabel("Row")
ax.legend(loc="upper left", fontsize=7, framealpha=0.85, ncol=2)

fig.suptitle("DEM Conditioning Effect: Flow Path Connectivity",
             fontsize=14, fontweight="bold")
fig.tight_layout()
out2 = VIZ_DIR / "v21_dem_comparison_flowpaths.png"
fig.savefig(out2, dpi=DPI, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(f"  Saved: {out2.name}")


# ══════════════════════════════════════════════════════════════════════════════
# Figure 3: Cross-section profiles at key columns — before vs after
# ══════════════════════════════════════════════════════════════════════════════
key_cols = [175, 237, 253, 266, 281, 312]
col_labels = {175: "WesternWadi\ncol=175",
              237: "Nile center\ncol=237",
              253: "Culvert\ncol=253",
              266: "Culvert2\ncol=266",
              281: "HospitalWadi\ncol=281",
              312: "Culvert1\ncol=312"}

fig, axes = plt.subplots(2, 3, figsize=(20, 10))
y_km = np.arange(nrows) * 30 / 1000

for ax, col in zip(axes.ravel(), key_cols):
    orig_col = dem_orig[:, col]
    v21_col  = dem_v21[:, col]
    ax.plot(y_km, orig_col, color="grey",  lw=1.5, ls="--", label="v10 original", alpha=0.8)
    ax.plot(y_km, v21_col,  color="steelblue", lw=2.0, label="v21 conditioned")
    ax.fill_between(y_km, orig_col, v21_col,
                    where=(v21_col < orig_col - 0.1), alpha=0.3, color="blue",
                    label="Lowered (burns)")
    ax.fill_between(y_km, orig_col, v21_col,
                    where=(v21_col > orig_col + 0.1), alpha=0.3, color="red",
                    label="Raised (fill)")
    ax.axhline(294, color="navy", lw=1, ls=":", label="Nile 294m")
    # Mark inflow at this column if any
    for name, d in INFLOW_DEFS.items():
        if d["col"] == col:
            ax.axvline(d["row"]*30/1000, color=d["color"], lw=1.5, ls="-.",
                       label=f"{name} row={d['row']}")
    ax.set_xlim(0, nrows*30/1000)
    ax.set_ylim(280, 390)
    ax.set_xlabel("Distance from south (km)")
    ax.set_ylabel("Elevation (m)")
    ax.set_title(col_labels.get(col, f"col={col}"), fontweight="bold")
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(alpha=0.3)

fig.suptitle("DEM Cross-Sections: Before vs After Conditioning\n"
             "(Blue fill = lowered by burns, Red fill = raised by depression fill)",
             fontsize=13, fontweight="bold")
fig.tight_layout()
out3 = VIZ_DIR / "v21_dem_comparison_crosssections.png"
fig.savefig(out3, dpi=DPI, bbox_inches="tight", facecolor="white")
plt.close(fig)
print(f"  Saved: {out3.name}")

print(f"\nAll plots → {VIZ_DIR}")
print(f"\nSummary of DEM changes:")
print(f"  Nile floodplain burns:   {int(nile_burn.sum()):,} cells (avg change: {diff[nile_burn].mean():.1f}m)")
print(f"  Channel/culvert burns:   {int(channel_burn.sum()):,} cells (avg change: {diff[channel_burn].mean():.1f}m)")
print(f"  Depression fill raised:  {n_raise:,} cells (avg change: +{diff[raised].mean():.2f}m)")
