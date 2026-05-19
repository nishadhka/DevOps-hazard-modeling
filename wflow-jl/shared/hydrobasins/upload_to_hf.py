"""Upload HydroBASINS analysis outputs to HuggingFace.

Heavy / generated artifacts (PNGs, GeoJSON, downloaded shapefiles) live on
HuggingFace at the dataset E4DRR/wflow.jl-simulations; only the Python source
and Markdown notes stay in the git repository.

Inspired by:
    https://github.com/icpac-igad/grib-index-kerchunk/blob/main/gefs/upload_parquets_to_hf.py

Usage
-----
    uv run python -m shared.hydrobasins.upload_to_hf
    uv run python -m shared.hydrobasins.upload_to_hf --dest hydrobasins/v2
    uv run python -m shared.hydrobasins.upload_to_hf --folder shared/hydrobasins/outputs --dry-run

Reads HF_TOKEN from `.env` at the repo root (or any parent — `find_dotenv()`).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError

HF_REPO = "E4DRR/wflow.jl-simulations"
HF_REPO_TYPE = "dataset"

HERE = Path(__file__).resolve().parent
DEFAULT_LOCAL = HERE / "outputs"
DEFAULT_DEST = "hydrobasins/level08"


def _load_token() -> str:
    load_dotenv(find_dotenv(usecwd=True))
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit(
            "HF_TOKEN not set. Add `HF_TOKEN=hf_…` to .env or export it before running."
        )
    return token


def _summarise(folder: Path) -> tuple[int, int]:
    """Return (file_count, total_bytes) for a folder."""
    files = [p for p in folder.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def _upload_folder_with_retry(api: HfApi, *, folder: Path, dest: str,
                              commit_message: str, max_attempts: int = 5,
                              base_backoff_sec: int = 300) -> None:
    """upload_folder with exponential back-off on 429 (rate-limited)."""
    for attempt in range(1, max_attempts + 1):
        try:
            api.upload_folder(
                folder_path=str(folder),
                path_in_repo=dest,
                repo_id=HF_REPO,
                repo_type=HF_REPO_TYPE,
                commit_message=commit_message,
            )
            return
        except HfHubHTTPError as e:
            if getattr(e.response, "status_code", None) == 429 and attempt < max_attempts:
                backoff = base_backoff_sec * (2 ** (attempt - 1))
                print(f"  [429] rate-limited; sleeping {backoff}s before retry "
                      f"{attempt + 1}/{max_attempts}", file=sys.stderr)
                time.sleep(backoff)
                continue
            raise


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--folder", type=Path, default=DEFAULT_LOCAL,
                   help=f"Local folder to upload (default: {DEFAULT_LOCAL})")
    p.add_argument("--dest", default=DEFAULT_DEST,
                   help=f"Path inside the HF dataset (default: {DEFAULT_DEST})")
    p.add_argument("--message", default=None,
                   help="Commit message on the dataset (default auto-generated)")
    p.add_argument("--dry-run", action="store_true",
                   help="List what would be uploaded; do not push")
    args = p.parse_args()

    folder = args.folder.resolve()
    if not folder.is_dir():
        raise SystemExit(f"Folder not found: {folder}")

    n_files, total_bytes = _summarise(folder)
    print(f"Source folder : {folder}")
    print(f"Files         : {n_files} ({total_bytes / 1e6:,.2f} MB)")
    print(f"HF target     : {HF_REPO_TYPE} {HF_REPO} → {args.dest}")

    if args.dry_run:
        print("\nDRY RUN — file list:")
        for p_ in sorted(folder.rglob("*")):
            if p_.is_file():
                rel = p_.relative_to(folder)
                print(f"  {rel}  ({p_.stat().st_size:,} B)")
        return

    token = _load_token()
    api = HfApi(token=token)

    commit_message = args.message or (
        f"hydrobasins: upload {n_files} files ({total_bytes / 1e6:,.1f} MB) → {args.dest}"
    )
    print(f"Commit message: {commit_message}\n")

    _upload_folder_with_retry(
        api, folder=folder, dest=args.dest, commit_message=commit_message,
    )
    print(f"\n✓ Uploaded to https://huggingface.co/datasets/{HF_REPO}/tree/main/{args.dest}")


if __name__ == "__main__":
    main()
