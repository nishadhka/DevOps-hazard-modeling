#!/usr/bin/env python3
"""Upload the 11 FastFlood case packages to HuggingFace.

Mirrors the RIM2D dataset layout: each <case>/ folder (input/ output/ frames/,
preview.gif, run_command.txt, METHOD.md) plus a top-level README.md, published to
the dataset repo E4DRR/fastflood-ea-casestudy.

Reads HF_TOKEN from fastflood/.env (or any parent .env). The heavy artifacts live
only on the compute server + HuggingFace; only the pipeline code stays in git.

Usage:
    micromamba run -n aifs-etl python upload_fastflood_hf.py            # upload all
    micromamba run -n aifs-etl python upload_fastflood_hf.py --dry-run  # list only
    micromamba run -n aifs-etl python upload_fastflood_hf.py --case nairobi_2026-03-06
"""
from __future__ import annotations
import argparse, os, sys, time
from pathlib import Path
from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError

REPO = "E4DRR/fastflood-ea-casestudy"
REPO_TYPE = "dataset"                       # data, like E4DRR/rim2d-simulations
LOCAL = Path("/mnt/wflow-secondary/fastflood-data/hf_fastflood")

def load_token() -> str:
    # minimal .env reader (no python-dotenv dependency)
    for base in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
        env = base / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith("HF_TOKEN="):
                    return line.split("=", 1)[1].strip()
    tok = os.environ.get("HF_TOKEN")
    if tok:
        return tok
    raise SystemExit("HF_TOKEN not set. Add `HF_TOKEN=hf_…` to fastflood/.env or export it.")

def upload_with_retry(api, *, folder, path_in_repo, msg, allow=None, attempts=5, backoff=120):
    for i in range(1, attempts + 1):
        try:
            api.upload_folder(repo_id=REPO, repo_type=REPO_TYPE, folder_path=str(folder),
                              path_in_repo=path_in_repo, commit_message=msg,
                              allow_patterns=allow)
            return
        except HfHubHTTPError as e:
            if i == attempts or "429" not in str(e):
                raise
            wait = backoff * i
            print(f"  rate-limited, retry {i}/{attempts} in {wait}s"); time.sleep(wait)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--case", help="upload only this case slug")
    args = ap.parse_args()

    cases = sorted(d for d in LOCAL.iterdir() if d.is_dir())
    if args.case:
        cases = [c for c in cases if c.name == args.case]
        if not cases:
            raise SystemExit(f"case {args.case} not found under {LOCAL}")

    total = sum(sum(f.stat().st_size for f in c.rglob("*") if f.is_file()) for c in cases)
    print(f"repo: {REPO} ({REPO_TYPE})")
    print(f"cases: {len(cases)}   total: {total/1e9:.2f} GB")
    for c in cases:
        n = sum(1 for f in c.rglob("*") if f.is_file())
        print(f"  {c.name:22} {n:4} files")
    if args.dry_run:
        print("dry-run: nothing uploaded"); return

    token = load_token()
    api = HfApi(token=token)
    api.create_repo(REPO, repo_type=REPO_TYPE, exist_ok=True)
    print(f"repo ready: https://huggingface.co/datasets/{REPO}")

    # top-level README first
    readme = LOCAL / "README.md"
    if readme.exists() and not args.case:
        api.upload_file(path_or_fileobj=str(readme), path_in_repo="README.md",
                        repo_id=REPO, repo_type=REPO_TYPE,
                        commit_message="dataset card")
        print("  uploaded README.md")

    for c in cases:
        print(f"uploading {c.name} ...")
        upload_with_retry(api, folder=c, path_in_repo=c.name,
                          msg=f"add FastFlood case {c.name}")
        print(f"  done {c.name}")
    print(f"\n✓ all uploaded → https://huggingface.co/datasets/{REPO}")

if __name__ == "__main__":
    main()
