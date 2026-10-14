#!/usr/bin/env python3
"""REPRO-1: package data/raw/ into a reproducible snapshot archive (standard library only).

Run on the host after a successful live run (no packages needed):
    python3 scripts/make_snapshot.py
Writes snapshot/wq_raw_snapshot_<date>.tar.gz plus a .sha256 file and prints size and checksum.

Only batches whose manifest says "success" are packaged; partial runs and --plan folders are
skipped and listed. A "success" batch whose files no longer match their manifest checksums
stops the script. data/landing/ is never included. Files go in sorted order with fixed
metadata (owner, time, permissions), so the same raw data always gives the same checksum.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import tarfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITHUB_ASSET_LIMIT = 2 * 1024 ** 3  # GitHub release assets must be under 2 GiB


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_batches(raw: Path) -> tuple[list[Path], list[str], list[str]]:
    """(files of every complete batch, sorted; skipped batches; batches whose files changed)."""
    files: list[Path] = []
    skipped: list[str] = []
    errors: list[str] = []
    for batch_dir in sorted(raw.glob("*/batch_id=*")):
        rel = batch_dir.relative_to(raw).as_posix()
        manifest_path = batch_dir / "manifest.json"
        if not manifest_path.exists():
            skipped.append(f"{rel}: no manifest.json")
            continue
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        if m.get("status") != "success":
            skipped.append(f"{rel}: status {m.get('status')!r}")
            continue
        bad = [f["name"] for f in m.get("files", [])
               if not (batch_dir / f["name"]).is_file()
               or sha256_of(batch_dir / f["name"]) != f.get("sha256")]
        if bad:
            errors.append(f"{rel}: {bad[:3]}")
            continue
        files.extend(p for p in batch_dir.rglob("*") if p.is_file() and not p.name.endswith(".tmp"))
    return sorted(files), skipped, errors


def write_archive(files: list[Path], raw: Path, archive: Path) -> None:
    """Deterministic .tar.gz: sorted members, fixed owner/time/mode, gzip time 0."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = archive.with_name(archive.name + ".tmp")
    with open(tmp, "wb") as out, \
            gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in files:
            info = tar.gettarinfo(str(path), arcname=path.relative_to(raw).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.mode = 0o644
            with open(path, "rb") as f:
                tar.addfile(info, f)
    tmp.replace(archive)


def make_snapshot(raw: Path, out_dir: Path, day: str) -> tuple[Path, str, list[str]]:
    """Build the archive and its .sha256 file. Returns (archive, sha256, skipped batches)."""
    files, skipped, errors = collect_batches(raw)
    if errors:
        raise SystemExit("Refusing to snapshot: these batches no longer match their manifests:\n  "
                         + "\n  ".join(errors))
    if not files:
        raise SystemExit(f"No complete batches under {raw}: run the pipeline in live mode first")
    archive = out_dir / f"wq_raw_snapshot_{day}.tar.gz"
    write_archive(files, raw, archive)
    digest = sha256_of(archive)
    (out_dir / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return archive, digest, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="REPRO-1: package data/raw/ into a snapshot archive")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "snapshot")
    parser.add_argument("--date", default=date.today().isoformat(), help="date in the file name")
    args = parser.parse_args(argv)

    archive, digest, skipped = make_snapshot(args.raw_dir, args.out_dir, args.date)
    for reason in skipped:
        print(f"skipped {reason}")
    size = archive.stat().st_size
    print(f"archive: {archive}\nsize:    {size:,} bytes ({size / 1024 ** 2:.1f} MiB)\nsha256:  {digest}")
    if size >= GITHUB_ASSET_LIMIT:
        print("TOO LARGE for a GitHub release asset (2 GiB limit): report the size to the PM; do not upload.")
        return 1
    print(f"Next: attach it to a GitHub release named snapshot-{args.date}, "
          "then put its download URL and the sha256 in config/snapshot.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())