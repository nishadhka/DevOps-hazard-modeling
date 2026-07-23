# Running the FastFlood CLI on Linux (via Wine)

The ICPAC FastFlood distribution (`fastflood_cli_icpac/`) ships **only Windows
binaries** — `fastflood.exe` is a `PE32+ executable (console) x86-64, for MS
Windows`. There is **no native Linux/ELF build** anywhere in the distribution or
in `fastflood_icpac_2024.zip`. The other extension-less files in `cli/`
(`proj.db`, `CH`, `GL27`, `ITRF2000/2008/2014`, `nad27`, `nad83`, `world`,
`other.extra`) are **PROJ** coordinate-reference-system data files that ship
alongside the binary — they are not programs.

To run it on this Linux VM (Debian 12 "bookworm", amd64) we run the Windows
`.exe` under **Wine**.

---

## 1. Layout & disk notes

The heavy binaries do **not** live on the small root disk. They were moved to
the 300 GB secondary disk and symlinked back so all paths still work:

```
fastflood/
├── .env                       # API key (gitignored)
├── .gitignore                 # ignores the items below
├── RUNNING_FASTFLOOD_CLI.md   # this file (git-tracked)
├── fastflood_cli_icpac   ->   /mnt/wflow-secondary/fastflood-data/fastflood_cli_icpac   (symlink, 1.5G)
└── fastflood_icpac_2024.zip -> /mnt/wflow-secondary/fastflood-data/fastflood_icpac_2024.zip (symlink, 1.4G)
```

`fastflood_cli_icpac/` contains:

- `cli/`     — `fastflood.exe` + PROJ data + an example DEM (`dem_example_nairobi.tif`)
- `desktop/` — Windows desktop installer (`FastFlood Setup.exe`, `fastflood-win32-x64.zip`)

The Wine prefix also lives on the big disk to keep the root disk free:
`/mnt/wflow-secondary/fastflood-data/.wineprefix`.

> The root disk (`/`) is only 30 GB. Keep large outputs / DEMs / the Wine prefix
> on `/mnt/wflow-secondary` (300 GB) or `/mnt/wflow-data` (100 GB).

---

## 2. One-time setup

### 2a. Install Wine (64-bit)

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y wine64
# verify
wine --version          # -> wine-8.0 (Debian 8.0~repack-4)
```

`fastflood.exe` is 64-bit only, so `wine64` is sufficient — the 32-bit
(`syswow64`) layer is **not** needed. The missing-`syswow64/rundll32.exe`
warning during prefix creation is harmless for this binary.

> If the install fills the root disk, clear the apt cache with
> `sudo apt-get clean`, and keep big files on the secondary disk.

### 2b. Initialise the Wine prefix (on the big disk)

```bash
export WINEPREFIX=/mnt/wflow-secondary/fastflood-data/.wineprefix
export WINEDEBUG=-all          # silence the noisy fixme/err logs
wineboot -i                    # creates the prefix
```

### 2c. API key in `.env`

`fastflood/.env` (gitignored) holds the authentication key:

```
FASTFLOOD_KEY=<your-fastflood-api-key>
```

---

## 3. Running it

Always run **from inside `cli/`** — `fastflood.exe` needs `proj.db` and the
other PROJ data files in its working directory.

```bash
# environment
export WINEPREFIX=/mnt/wflow-secondary/fastflood-data/.wineprefix
export WINEDEBUG=-all

# go to the cli dir (via the symlink) and load the key
cd ~/DevOps-hazard-modeling/fastflood/fastflood_cli_icpac/cli
set -a; . ~/DevOps-hazard-modeling/fastflood/.env; set +a

# sanity check (prints version banner, then asks for -key)
wine fastflood.exe
```

### Step 1 — Download a DEM (Copernicus 30 m) for part of Nairobi

```bash
wine fastflood.exe -key "$FASTFLOOD_KEY" \
  -d_dem cop30 20m 4079597.073636 -116642.905163 4103139.678348 -149205.079213 \
  -dout dem_nairobi.tif
```

Expected: downloads/patches tiles → writes `dem_nairobi.tif`
(~8.4 MB, 1232×1704, EPSG:3857 Web-Mercator), ~1 s. Coordinates are in
**EPSG:3857 metres**: `minX minY maxX maxY`.

### Step 2 — Run a flash-flood simulation

```bash
wine fastflood.exe -key "$FASTFLOOD_KEY" \
  -dem dem_example_nairobi.tif -sim -rain 30.0 -dur 3 \
  -whout flood.tif
```

- `-rain 30.0` — rainfall intensity (mm)
- `-dur 3`     — duration (hours)
- `-whout`     — output water-height (flood depth) GeoTIFF

Expected: diffusive-wave cascade runs → writes `flood.tif`
(~13.7 MB), ~20 s. Use your own `dem_nairobi.tif` from Step 1 in place of the
bundled `dem_example_nairobi.tif` to simulate on a freshly downloaded area.

For the full option list:

```bash
wine fastflood.exe -help
```

---

## 4. Verified result (2026-06-24)

| Step | Command | Output | Time |
|------|---------|--------|------|
| 1. DEM download | `-d_dem cop30 20m … -dout dem_nairobi.tif` | `dem_nairobi.tif` 8.4 MB, 1232×1704, EPSG:3857 | 1.2 s |
| 2. Flood sim | `-dem dem_example_nairobi.tif -sim -rain 30.0 -dur 3 -whout flood.tif` | `flood.tif` 13.7 MB | 19.7 s |

Both steps exited 0 under `wine-8.0`.

---

## 5. Security note

- `.env` is **gitignored** — the key is not committed.
- The repo is public; **rotate the key** if it has been shared in plaintext
  (chat logs, exported transcripts, etc.).
- `fastflood_cli_icpac/` and `fastflood_icpac_2024.zip` are gitignored (heavy
  binaries / vendor distribution).
