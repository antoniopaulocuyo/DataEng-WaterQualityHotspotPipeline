#!/usr/bin/env python3
"""REPRO-1: put the frozen raw data in place for PIPELINE_MODE=snapshot (standard library only).

    python3 scripts/fetch_snapshot.py                    # download the URL in config/snapshot.yaml
    python3 scripts/fetch_snapshot.py --file <archive>   # use a local archive instead
    python3 scripts/fetch_snapshot.py --force            # replace batches that already exist

The archive's SHA-256 must match config/snapshot.yaml (or --sha256, or the archive's .sha256
file) before anything is extracted. Existing batches are never overwritten without --force.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "snapshot.yaml"


def read_config(path: Path) -> dict[str, str]:
    """config/snapshot.yaml holds flat `key: value` lines, read without PyYAML so this runs anywhere."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.split(" #", 1)[0].strip().strip('"').strip("'")
    return values


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    print(f"downloading {url}")
    with urllib.request.urlopen(url) as response, open(part, "wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    part.replace(dest)
    return dest


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = tar.getmembers()
    for m in members:
        p = PurePosixPath(m.name)
        if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
            raise SystemExit(f"Refusing unsafe archive member: {m.name}")
    return members


def extract(archive: Path, expected_sha256: str, raw: Path, force: bool = False) -> list[str]:
    """Verify the checksum, then extract into raw/. Returns the 'source/batch_id=…' folders."""
    actual = sha256_of(archive)
    if actual != expected_sha256.strip().lower():
        raise SystemExit(f"Checksum mismatch for {archive.name}: expected {expected_sha256}, "
                         f"got {actual}. Nothing was extracted.")
    with tarfile.open(archive, "r:gz") as tar:
        members = _safe_members(tar)
        batches = sorted({"/".join(PurePosixPath(m.name).parts[:2])
                          for m in members if len(PurePosixPath(m.name).parts) >= 2})
        existing = [b for b in batches if (raw / b).exists()]
        if existing and not force:
            raise SystemExit("These batches already exist in data/raw/ (use --force to replace them):\n  "
                             + "\n  ".join(existing))
        for b in existing:
            shutil.rmtree(raw / b)
        raw.mkdir(parents=True, exist_ok=True)
        if hasattr(tarfile, "data_filter"):
            tar.extractall(raw, members=members, filter="data")
        else:
            tar.extractall(raw, members=members)
    return batches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REPRO-1: fetch, verify and extract the raw data snapshot")
    parser.add_argument("--file", type=Path, help="local archive instead of downloading")
    parser.add_argument("--sha256", help="expected checksum (default: config/snapshot.yaml or <archive>.sha256)")
    parser.add_argument("--force", action="store_true", help="replace batches that already exist")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    args = parser.parse_args(argv)

    cfg = read_config(CONFIG)
    if args.file:
        archive = args.file
    else:
        url = cfg.get("url", "")
        if not url:
            raise SystemExit("config/snapshot.yaml has no url yet: pass --file <archive>")
        archive = download(url, ROOT / "snapshot" / url.rsplit("/", 1)[-1])

    expected = args.sha256 or cfg.get("sha256", "")
    sidecar = archive.with_name(archive.name + ".sha256")
    if not expected and sidecar.exists():
        expected = sidecar.read_text(encoding="utf-8").split()[0]
    if not expected:
        raise SystemExit("No checksum to verify against: set sha256 in config/snapshot.yaml or pass --sha256")

    batches = extract(archive, expected, args.raw_dir, args.force)
    print(f"checksum OK; extracted {len(batches)} batches into {args.raw_dir}:")
    for b in batches:
        print(f"  {b}")
    print("Next: docker compose up -d, then trigger the DAG (PIPELINE_MODE=snapshot is the default)")
    return 0


if __name__ == "__main__":
    sys.exit(main())