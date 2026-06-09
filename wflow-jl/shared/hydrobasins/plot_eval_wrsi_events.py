"""Visualise the v4 WRSI-vs-drought-event eval (eval_wrsi_events.py).

Reads `_eval_wrsi_events.json` and renders:
  - one bar-per-year WRSI panel per case (event years marked with a thick
    red edge), with ΣAET on a secondary line;
  - a combined 3×4 grid (all 11 cases + a verdict-legend slot);
  - a horizontal "drought response" summary chart: per-case "event-year
    WRSI drop" = (mean of non-event-year WRSI) − (mean of event-year WRSI);
    a bigger drop = stronger drought capture.

Verdicts (from WRSI_EVENT_EVAL.md) are baked in so each panel shows the
classification (Strong / Moderate / Weak / Poor).

  uv run python -m shared.hydrobasins.plot_eval_wrsi_events

Outputs (runs/eval_wrsi_events/):
  {iso}_wrsi_events.png        — per-case panel (12 files: 11 + summary)
  grid_wrsi_events.png         — 3×4 combined panel
  drought_response_summary.png — horizontal bar chart of event-year drop
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
JSON = HERE / "_eval_wrsi_events.json"
JSON_PATCH = HERE / "_eval_som_ssd.json"   # SOM/SSD re-run (overrides main)
OUT = HERE.parents[1] / "runs" / "eval_wrsi_events"

FAO_BANDS = [(0, 50, "#d7191c", "<50 crop-failure"),
             (50, 80, "#fdae61", "50-79 water-stress"),
             (80, 200, "#1a9641", "≥80 no/min stress")]


def band_color(w: float) -> str:
    for lo, hi, c, _ in FAO_BANDS:
        if lo <= w < hi:
            return c
    return "#888888"


# Hand-coded verdicts mirroring WRSI_EVENT_EVAL.md (so the chart is
# self-contained and the categories drive the summary plot).
VERDICTS = {
    "dji": ("Strong",   "single-year drought captured (26→9 in 2022)"),
    "ken": ("Strong",   "Tana 2020-23 deep collapse (47→18, worst 40 yr)"),
    "eri": ("Strong",   "deepening multi-year (23→14→7)"),
    "som": ("Strong",   "South-Central famine arc (36→14→12→29)"),
    "eth": ("Strong",   "Blue Nile HW event yrs clearly below baseline (51→39/36)"),
    "sdn": ("Moderate", "2022 dip 43→32 but basin adjacent to event region"),
    "ssd": ("Moderate", "deepening (36→29→25) BUT basin = Bahr el Ghazal not Upper Nile"),
    "bdi": ("Weak",     "humid Great-Lakes — only mild dip 74→70"),
    "rwa": ("Weak",     "humid Akagera 70→68 (window 2016-17)"),
    "uga": ("Weak",     "Lake Kyoga is wetter than Karamoja proper, 68→63"),
    "tza": ("Poor",     "wrong basin (Pangani vs Kagera event) + window miss"),
}
VERDICT_COLORS = {"Strong": "#1a9641", "Moderate": "#fdae61",
                  "Weak":   "#f6d77f", "Poor":     "#d7191c"}


def _draw_panel(ax, rec: dict, *, fontsize_title=10.5,
                show_ylabel=True, show_legend=False) -> dict:
    """One per-case bar chart of per-year WRSI; returns the metrics."""
    iso = rec["iso"]
    years = sorted(int(y) for y in rec["years"])
    wrsi = [rec["years"][str(y)]["wrsi"] for y in years]
    aet  = [rec["years"][str(y)]["aet_mm"] for y in years]
    pet  = [rec["years"][str(y)]["pet_mm"] for y in years]
    ev   = set(rec["event_years"])

    colors = [band_color(w) for w in wrsi]
    bars = ax.bar(years, wrsi, color=colors, edgecolor="#333", linewidth=0.4,
                  zorder=2, width=0.7)
    for b, y in zip(bars, years):
        if y in ev:
            b.set_edgecolor("#b30000")
            b.set_linewidth(2.4)

    # FAO band lines
    for thr, label in [(50, "crop-failure"), (80, "no-stress")]:
        ax.axhline(thr, color="#555", linewidth=0.5, linestyle=":")
    ax.set_ylim(0, max(110, max(wrsi) + 10))

    # AET secondary axis (subtle)
    ax2 = ax.twinx()
    ax2.plot(years, aet, "o-", color="#1f5fa6", linewidth=1.2,
             markersize=4, alpha=0.85, zorder=3)
    ax2.set_ylim(0, max(aet) * 1.25)
    ax2.tick_params(axis="y", colors="#1f5fa6", labelsize=7)
    if show_ylabel:
        ax2.set_ylabel("ΣAET mm/yr", color="#1f5fa6", fontsize=8)

    verdict, _ = VERDICTS.get(iso, ("—", ""))
    full = rec.get("wrsi_full", float("nan"))
    title = (f"{iso.upper()} · {rec['event']}\n"
             f"verdict: {verdict}  ·  full-period WRSI {full:.1f}")
    ax.set_title(title, fontsize=fontsize_title, fontweight="bold")
    if show_ylabel:
        ax.set_ylabel("basin-mean WRSI", fontsize=8)
    ax.set_xticks(years)
    ax.set_xticklabels(years, fontsize=8)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", linestyle=":", linewidth=0.4, color="#aaa", zorder=0)

    if show_legend:
        handles = [mpatches.Patch(color=c, label=lbl)
                   for _, _, c, lbl in FAO_BANDS]
        handles.append(mpatches.Patch(facecolor="white", edgecolor="#b30000",
                                      linewidth=2.4, label="event year"))
        ax.legend(handles=handles, loc="lower right", fontsize=6.5,
                  framealpha=0.85)

    ev_years = [y for y in years if y in ev]
    non_ev = [w for y, w in zip(years, wrsi) if y not in ev]
    ev_w   = [w for y, w in zip(years, wrsi) if y in ev]
    if non_ev and ev_w:
        drop = float(np.mean(non_ev) - np.mean(ev_w))
        drop_metric = "non-event mean − event mean"
    elif ev_w:
        # Event spans the whole run window — fall back to within-event range
        # (best year − worst year inside the event).
        drop = float(max(ev_w) - min(ev_w))
        drop_metric = "within-event range (best − worst)"
    else:
        drop = float("nan"); drop_metric = "n/a"
    return {"iso": iso, "wrsi_full": full, "drop": drop,
            "drop_metric": drop_metric, "min_wrsi": min(wrsi),
            "verdict": verdict, "event_years": ev_years}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # main JSON, then overlay the SOM/SSD re-run patch (status=OK supersedes)
    by_iso = {r["iso"]: r for r in json.loads(JSON.read_text())}
    if JSON_PATCH.exists():
        for r in json.loads(JSON_PATCH.read_text()):
            by_iso[r["iso"]] = r
    data = [r for r in by_iso.values() if r.get("status") == "OK"]
    data.sort(key=lambda r: (-{"Strong": 4, "Moderate": 3, "Weak": 2,
                              "Poor": 1, "—": 0}.get(
        VERDICTS.get(r["iso"], ("—", ""))[0], 0),
        r["wrsi_full"]))

    # -- per-case PNGs -------------------------------------------------------
    metrics = []
    for rec in data:
        fig, ax = plt.subplots(figsize=(7, 4.2))
        m = _draw_panel(ax, rec, fontsize_title=11,
                        show_ylabel=True, show_legend=True)
        metrics.append(m)
        fig.tight_layout()
        fig.savefig(OUT / f"{rec['iso']}_wrsi_events.png", dpi=150,
                    bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"  {rec['iso']}: drop={m['drop']:+.1f}  min={m['min_wrsi']:.1f}"
              f"  verdict={m['verdict']}")

    # -- 3×4 grid panel -------------------------------------------------------
    ncols = 4
    nrows = int(np.ceil(len(data) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.6 * ncols, 3.6 * nrows))
    axes = np.array(axes).reshape(-1)
    for i, rec in enumerate(data):
        _draw_panel(axes[i], rec, fontsize_title=9,
                    show_ylabel=(i % ncols == 0),
                    show_legend=(i == 0))
    for j in range(len(data), len(axes)):
        axes[j].axis("off")
    fig.suptitle("v4 WRSI vs documented drought events — per-year basin-mean "
                 "WRSI (bars) + ΣAET mm/yr (blue line). Event years marked "
                 "with thick red edge. Ordered by verdict (Strong → Poor).",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(OUT / "grid_wrsi_events.png", dpi=140,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # -- drought-response summary (horizontal bar) ---------------------------
    metrics.sort(key=lambda m: m["drop"])
    fig, ax = plt.subplots(figsize=(9, 6.5))
    isos = [m["iso"].upper() for m in metrics]
    drops = [m["drop"] for m in metrics]
    colors = [VERDICT_COLORS.get(m["verdict"], "#888") for m in metrics]
    bars = ax.barh(isos, drops, color=colors, edgecolor="#222",
                   linewidth=0.5)
    for b, m in zip(bars, metrics):
        ax.text(b.get_width() + (0.3 if b.get_width() > 0 else -0.3),
                b.get_y() + b.get_height() / 2,
                f" {m['drop']:+.1f}  ({m['verdict']})",
                va="center", ha="left" if b.get_width() > 0 else "right",
                fontsize=8)
    ax.axvline(0, color="#222", linewidth=0.7)
    ax.set_xlabel("event-year WRSI drop (non-event mean − event mean,  "
                  "or within-event range when window=event)  →  more "
                  "positive = stronger drought capture", fontsize=9)
    ax.set_title("v4 wflow→WRSI per-case drought response", fontsize=12,
                 fontweight="bold")
    handles = [mpatches.Patch(color=c, label=v)
               for v, c in VERDICT_COLORS.items()]
    ax.legend(handles=handles, title="verdict", loc="lower right",
              fontsize=8, title_fontsize=9)
    ax.grid(axis="x", linestyle=":", linewidth=0.4, color="#aaa")
    fig.tight_layout()
    fig.savefig(OUT / "drought_response_summary.png", dpi=150,
                bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"\n{len(list(OUT.glob('*.png')))} PNGs written to {OUT}")


if __name__ == "__main__":
    main()
