"""Tests for REPRO-1's snapshot scripts (scripts/make_snapshot.py, scripts/fetch_snapshot.py)."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make = _load("make_snapshot")
fetch = _load("fetch_snapshot")
DAY = "2026-10-14"
EIONET = "owq_eionet/batch_id=owq_eionet_aaaaaaaaaaaa"
NE = "natural_earth/batch_id=natural_earth_bbbbbbbbbbbb"


def _batch(raw: Path, rel: str, files: dict[str, bytes], status: str = "success") -> None:
    d = raw / rel
    entries = []
    for name, content in files.items():
        (d / name).parent.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(content)
        entries.append({"name": name, "sha256": hashlib.sha256(content).hexdigest()})
    (d / "manifest.json").write_text(json.dumps({"status": status, "files": entries}))


@pytest.fixture
def raw(tmp_path):
    r = tmp_path / "raw"
    _batch(r, EIONET, {"a.csv": b"x,y\n1,2\n"})
    _batch(r, NE, {"z.zip": b"zip", "extracted/z.shp": b"shp"})
    _batch(r, "open_meteo/batch_id=open_meteo_cccccccccccc", {"grid_cells.csv": b"c"}, status="partial")
    (r / "open_meteo/batch_id=open_meteo_dddddddddddd").mkdir(parents=True)   # a --plan folder
    return r


def test_archive_is_reproducible_and_skips_incomplete_batches(raw, tmp_path):
    a1, d1, skipped = make.make_snapshot(raw, tmp_path / "out1", DAY)
    a2, d2, _ = make.make_snapshot(raw, tmp_path / "out2", DAY)
    assert d1 == d2 and a1.read_bytes() == a2.read_bytes()
    assert len(skipped) == 2
    assert (a1.parent / f"{a1.name}.sha256").read_text().split()[0] == d1


def test_fetch_restores_identical_files(raw, tmp_path):
    archive, digest, _ = make.make_snapshot(raw, tmp_path / "out", DAY)
    target = tmp_path / "fresh_raw"
    assert fetch.extract(archive, digest, target) == [NE, EIONET]
    for rel in (f"{EIONET}/a.csv", f"{EIONET}/manifest.json", f"{NE}/extracted/z.shp"):
        assert (target / rel).read_bytes() == (raw / rel).read_bytes()


def test_wrong_checksum_extracts_nothing(raw, tmp_path):
    archive, _, _ = make.make_snapshot(raw, tmp_path / "out", DAY)
    target = tmp_path / "fresh_raw"
    with pytest.raises(SystemExit, match="Checksum mismatch"):
        fetch.extract(archive, "0" * 64, target)
    assert not target.exists()


def test_existing_batches_need_force(raw, tmp_path):
    archive, digest, _ = make.make_snapshot(raw, tmp_path / "out", DAY)
    target = tmp_path / "fresh_raw"
    fetch.extract(archive, digest, target)
    with pytest.raises(SystemExit, match="already exist"):
        fetch.extract(archive, digest, target)
    assert fetch.extract(archive, digest, target, force=True) == [NE, EIONET]


def test_changed_file_blocks_the_snapshot(raw, tmp_path):
    (raw / EIONET / "a.csv").write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="no longer match"):
        make.make_snapshot(raw, tmp_path / "out", DAY)


def test_config_reader_ignores_comments(tmp_path):
    path = tmp_path / "snapshot.yaml"
    path.write_text('# header\nurl: "https://example.org/a.tar.gz"   # note\nsha256: ""\n')
    assert fetch.read_config(path) == {"url": "https://example.org/a.tar.gz", "sha256": ""}