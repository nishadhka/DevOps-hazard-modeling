#!/usr/bin/env python3
"""
Download GEOGlows v2 retrospective hourly streamflow for Nile region rivers.

River IDs: 160308747, 160245676, 160437229
Period:    July–August 2024

Usage:
    micromamba run -n zarrv3 python download_geoglows_rivers.py
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

OUT_DIR = Path("/data/rim2d/nile_highres/visualizations")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ZARR_URI = "s3://geoglows-v2/retrospective/hourly.zarr"

# Unique river IDs (160245676 appears twice in original list)
RIVER_IDS = [160308747, 160245676, 160437229]

START = "2024-07-01"
END   = "2024-09-01"   # exclusive

# Short descriptive names for plotting
RIVER_NAMES = {
    160308747: "River 160308747",
    160245676: "River 160245676",
    160437229: "River 160437229",
}


def main():
    print("=" * 60)
    print("GEOGlows v2 — Retrospective Hourly Streamflow")
    print(f"  Rivers: {RIVER_IDS}")
    print(f"  Period: {START} → {END}")
    print("=" * 60)

    # ── Open Zarr store directly (avoid xarray loading 6.8M river_id index) ──
    import s3fs, zarr, numpy as np

    print("\nOpening GEOGlows Zarr store (anonymous S3, direct zarr access)...")
    fs    = s3fs.S3FileSystem(anon=True)
    store = s3fs.S3Map(ZARR_URI, s3=fs)
    z     = zarr.open(store, mode="r")

    print(f"  Q shape: {z['Q'].shape}  chunks: {z['Q'].chunks}")
    print(f"  time shape: {z['time'].shape}")

    # ── Load time coordinate and find Jul–Aug 2024 indices ───────────────────
    print("  Loading time coordinate...")
    time_raw = z["time"][:]                  # int64 nanoseconds since epoch
    times    = pd.to_datetime(time_raw, unit="ns")
    t_mask   = (times >= START) & (times < END)
    t_idx    = np.where(t_mask)[0]
    print(f"  Time slice: {times[t_idx[0]]} → {times[t_idx[-1]]}  ({len(t_idx)} steps)")

    # ── Load river_id and find indices for our rivers ─────────────────────────
    print("  Loading river_id coordinate...")
    river_ids_all = z["river_id"][:]
    r_idx = []
    found = []
    for rid in RIVER_IDS:
        matches = np.where(river_ids_all == rid)[0]
        if len(matches):
            r_idx.append(int(matches[0]))
            found.append(rid)
        else:
            print(f"  WARNING: river_id {rid} not found in store")
    print(f"  Found rivers: {found} at indices {r_idx}")

    # ── Slice Q[time_idx, river_idx] ─────────────────────────────────────────
    # Zarr requires sorted integer indices for oindex
    print("  Fetching Q data (direct zarr slice)...")
    Q_sub = z["Q"].oindex[t_idx, r_idx]     # shape: (n_time, n_rivers)

    # ── Build tidy DataFrame ──────────────────────────────────────────────────
    rows = []
    for j, rid in enumerate(found):
        for i, ti in enumerate(t_idx):
            rows.append({"time": times[ti], "river_id": rid, "Q": float(Q_sub[i, j])})
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values(["river_id", "time"]).reset_index(drop=True)

    print(f"  Records: {len(df)}")
    print(f"  Time:    {df['time'].min()} → {df['time'].max()}")

    # ── Print stats per river ─────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("STREAMFLOW STATISTICS (m³/s)")
    print(f"{'='*60}")
    print(f"{'River ID':<14} {'Mean':>8} {'Min':>8} {'Max':>8} {'Peak date'}")
    print("-" * 60)
    for rid in RIVER_IDS:
        sub = df[df["river_id"] == rid]
        if sub.empty:
            print(f"{rid:<14}  No data")
            continue
        q = sub["Q"]
        peak_time = sub.loc[q.idxmax(), "time"]
        print(f"{rid:<14} {q.mean():>8.2f} {q.min():>8.2f} {q.max():>8.2f}"
              f"  {str(peak_time)[:16]}")

    # ── Save CSV ──────────────────────────────────────────────────────────────
    csv_path = OUT_DIR / "geoglows_rivers_jul_aug2024.csv"
    # Pivot to wide format: one column per river
    df_wide = df.pivot(index="time", columns="river_id", values="Q")
    df_wide.columns = [f"Q_{rid}_m3s" for rid in df_wide.columns]
    df_wide.to_csv(csv_path)
    print(f"\nSaved CSV: {csv_path}")

    # ── Plot ──────────────────────────────────────────────────────────────────
    colors = ["#1976D2", "#E53935", "#2E7D32"]
    fig, axes = plt.subplots(len(RIVER_IDS), 1, figsize=(14, 4 * len(RIVER_IDS)),
                             sharex=True)
    if len(RIVER_IDS) == 1:
        axes = [axes]

    for ax, rid, color in zip(axes, RIVER_IDS, colors):
        sub = df[df["river_id"] == rid].set_index("time")
        if sub.empty:
            ax.text(0.5, 0.5, f"No data for {rid}", transform=ax.transAxes,
                    ha="center", va="center")
            continue

        q = sub["Q"]
        ax.fill_between(q.index, q.values, alpha=0.25, color=color)
        ax.plot(q.index, q.values, color=color, linewidth=1.0)

        # Peak annotation
        peak_idx = q.idxmax()
        ax.annotate(
            f"Peak: {q.max():.1f} m³/s\n{str(peak_idx)[:13]}",
            xy=(peak_idx, q.max()),
            xytext=(10, 10), textcoords="offset points",
            fontsize=8, color=color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
            arrowprops=dict(arrowstyle="->", color=color, lw=1),
        )

        # Month separator
        aug1 = pd.Timestamp("2024-08-01")
        ax.axvline(aug1, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.text(aug1, ax.get_ylim()[1] * 0.95, " Aug", fontsize=8, color="gray")

        ax.set_ylabel("Q (m³/s)", fontsize=10)
        ax.set_title(f"{RIVER_NAMES[rid]}  (ID: {rid})", fontsize=11,
                     fontweight="bold", color=color)
        ax.grid(True, alpha=0.3, linestyle="--")
        ax.set_facecolor("#f9f9f9")

        # Stats box
        stats = (f"Mean: {q.mean():.2f}  Max: {q.max():.2f}  "
                 f"Min: {q.min():.2f} m³/s")
        ax.text(0.01, 0.97, stats, transform=ax.transAxes,
                fontsize=8, va="top",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=5))
    plt.setp(axes[-1].xaxis.get_majorticklabels(), rotation=45, ha="right")
    axes[-1].set_xlabel("Date", fontsize=10)

    fig.suptitle("GEOGlows v2 Retrospective Streamflow — July & August 2024\n"
                 "Nile Region Rivers", fontsize=13, fontweight="bold")
    plt.tight_layout()

    png_path = OUT_DIR / "geoglows_rivers_jul_aug2024.png"
    plt.savefig(png_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved PNG: {png_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
