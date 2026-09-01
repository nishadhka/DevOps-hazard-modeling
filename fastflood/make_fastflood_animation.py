#!/usr/bin/env python3
"""Build a RIM2D-style water-depth animation from FastFlood.

FastFlood is a fast steady-state method: a single run yields the max-depth
envelope, not a time series. To animate the *build-up* of the flood we drive
FastFlood with the cumulative IMERG storm hyetograph — running it at a sequence
of elapsed times so the inundation grows exactly as the real event accumulates.

For moment k (elapsed t_k hours):
    cum_total_k(x)   = Σ_{frames up to t_k} rate * 0.5      [mm]
    mean_intensity_k = cum_total_k / t_k                    [mm/hr]
    FastFlood(-rain mean_intensity_k, -dur t_k) -> wh_k.tif
Each wh_k is the inundation the event has produced by time t_k. Rendered over a
dark DEM hillshade with a blue->cyan depth ramp, titled + time-stamped like the
RIM2D preview.gif.

Usage:
  make_fastflood_animation.py <run_dir> <rain_nc_dir> <out_dir> \
      <title> <start_iso> <event_hours> [n_moments=24]
  <run_dir>     holds dem.tif + man.tif (from run_all_cases.sh)
  <rain_nc_dir> holds imerg_t*.nc frames
"""
import sys, os, glob, subprocess, datetime as dt
from pathlib import Path
import numpy as np, xarray as xr, rasterio
from rasterio.transform import from_origin
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource, LinearSegmentedColormap
from PIL import Image

FF_ROOT = Path("/home/sa_112625140081245282401/DevOps-hazard-modeling/fastflood")
CLI = FF_ROOT / "fastflood_cli_icpac/cli"
WINEPREFIX = "/mnt/wflow-secondary/fastflood-data/.wineprefix"

def read_key():
    for line in (FF_ROOT / ".env").read_text().splitlines():
        if line.startswith("FASTFLOOD_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no key")

def grid_from_dem(dem_tif):
    with rasterio.open(dem_tif) as s:
        return s.profile, s.read(1), s.transform, s.crs

def write_like(path, arr, profile):
    p = profile.copy(); p.update(count=1, dtype="float32", compress="deflate")
    with rasterio.open(path, "w", **p) as d: d.write(arr.astype("float32"), 1)

def run_fastflood(dem, man, rain, dur, whout, key, tries=3):
    """Run FastFlood; retry on the occasional Wine thread crash. Returns True
    if an output raster was produced."""
    env = dict(os.environ, WINEPREFIX=WINEPREFIX, WINEDEBUG="-all")
    cmd = ["wine", "fastflood.exe", "-key", key, "-dem", dem, "-sim",
           "-man", man, "-rain", rain, "-dur", f"{dur:.4f}", "-whout", whout]
    if os.path.exists(whout):
        os.remove(whout)
    for _ in range(tries):
        subprocess.run(cmd, cwd=CLI, env=env, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=900)
        if os.path.exists(whout) and os.path.getsize(whout) > 0:
            return True
    return False

def main():
    run_dir = Path(sys.argv[1]); rain_dir = Path(sys.argv[2]); out = Path(sys.argv[3])
    title = sys.argv[4]; start = dt.datetime.fromisoformat(sys.argv[5])
    event_h = float(sys.argv[6]); n = int(sys.argv[7]) if len(sys.argv) > 7 else 24
    frame_ms = int(sys.argv[8]) if len(sys.argv) > 8 else 450   # per-frame GIF hold
    tz = sys.argv[9] if len(sys.argv) > 9 else "EAT"
    out.mkdir(parents=True, exist_ok=True); frames_dir = out / "frames"; frames_dir.mkdir(exist_ok=True)
    key = read_key()
    dem_tif = str(run_dir / "dem.tif"); man_tif = str(run_dir / "man.tif")
    profile, dem, transform, crs = grid_from_dem(dem_tif)

    # cumulative rainfall (mm) per IMERG frame, on the DEM grid
    files = sorted(glob.glob(str(rain_dir / "imerg_t*.nc")),
                   key=lambda p: int(p.split("_t")[-1].split(".")[0]))
    nf = len(files); dt_h = event_h / nf                      # hours per frame
    # We only need the cumulative total at the N sampled moments, not at every
    # frame — snapshot on the fly to keep memory at O(N) grids, not O(nframes)
    # (a 1000-frame event on a 2.4M-cell grid would otherwise need tens of GB).
    moment_fi = [max(1, int(round(k / n * nf))) - 1 for k in range(1, n + 1)]
    snap_at = {}                                              # frame index -> moment k
    for k, fi in enumerate(moment_fi, start=1):
        snap_at.setdefault(fi, k)
    cum = np.zeros(dem.shape, dtype="float64"); snaps = {}
    for i, f in enumerate(files):
        cum += np.nan_to_num(xr.open_dataset(f)["Band1"].values) * dt_h
        if i in snap_at:
            snaps[i] = cum.copy()

    # dark hillshade backdrop (computed once)
    ls = LightSource(azdeg=315, altdeg=45)
    demf = np.where(np.isfinite(dem), dem, np.nan)
    hs = ls.hillshade(np.nan_to_num(demf, nan=np.nanmin(demf)), vert_exag=3)
    water_cmap = LinearSegmentedColormap.from_list("w", ["#1f4e8c", "#3b8fd0", "#7fe0ff"])

    imgs = []; prev_wh = None
    for k in range(1, n + 1):
        t_h = event_h * k / n
        fi = moment_fi[k - 1]                                # last frame index for this moment
        cum_mm = snaps[fi]
        # Drive FastFlood with the cumulative storm TOTAL delivered over the full
        # event duration, so inundation grows monotonically as rain accumulates
        # and the final moment equals the full-event result.
        mean_int = cum_mm / event_h                          # mm/hr, fixed denominator
        rain_tif = str(out / f"_rain_{k:02d}.tif"); wh_tif = str(frames_dir / f"wh_{k:02d}.tif")
        write_like(rain_tif, mean_int, profile)
        ok = run_fastflood(dem_tif, man_tif, rain_tif, event_h, wh_tif, key)
        if ok:
            with rasterio.open(wh_tif) as s: wh = s.read(1).astype("float64")
            wh = np.where(np.isfinite(wh), wh, 0.0)
        else:
            # FastFlood crashed all retries for this moment — reuse the previous
            # frame's depth so the animation stays intact rather than aborting.
            print(f"  moment {k}/{n}  FastFlood failed, reusing previous frame")
            wh = prev_wh if prev_wh is not None else np.zeros_like(dem, dtype="float64")
        prev_wh = wh

        # ---- render frame, RIM2D-style ----
        h, w = dem.shape; dpi = 100
        fig = plt.figure(figsize=(w/dpi, h/dpi), dpi=dpi); ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
        ax.imshow(hs, cmap="gray", vmin=0, vmax=1)
        ax.imshow(np.dstack([np.zeros_like(hs)]*3 + [np.full_like(hs, 0.55)]))  # navy tint
        depth = np.ma.masked_less_equal(wh, 0.05)
        ax.imshow(depth, cmap=water_cmap, vmin=0.05, vmax=3.0, alpha=0.95)
        stamp = (start + dt.timedelta(hours=t_h)).strftime("%d %b %Y %H:%M")
        ax.text(0.012, 0.965, title, transform=ax.transAxes, color="white",
                fontsize=13, weight="bold", va="top", ha="left")
        ax.text(0.988, 0.965, f"{stamp} {tz}", transform=ax.transAxes, color="#ffb020",
                fontsize=13, weight="bold", va="top", ha="right")
        png = str(frames_dir / f"frame_{k:02d}.png"); fig.savefig(png, dpi=dpi); plt.close(fig)
        im = Image.open(png).convert("RGB")
        gw = 720; im = im.resize((gw, round(gw * h / w)), Image.LANCZOS)  # match RIM2D width
        imgs.append(im.convert("P", palette=Image.ADAPTIVE))
        os.remove(rain_tif)
        print(f"  moment {k}/{n}  t={t_h:4.1f}h  wet(>5cm)={100*(wh>0.05).mean():4.1f}%  maxdepth={wh.max():.2f}m")

    gif = out / "preview.gif"
    # slower playback; hold the first and last (peak) frames longer so the build-up reads
    durations = [frame_ms] * len(imgs)
    durations[0] = max(frame_ms, 900); durations[-1] = max(frame_ms * 4, 2500)
    imgs[0].save(gif, save_all=True, append_images=imgs[1:], duration=durations,
                 loop=0, optimize=True)
    print(f"wrote {gif}  ({len(imgs)} frames, {frame_ms}ms/frame, peak-hold)")

if __name__ == "__main__":
    main()
