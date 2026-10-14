"""Tests for REPRO-1 snapshot mode: pipeline_mode() and the network block in http.request()."""
import pytest

from src.utils import config as cfg
from src.utils import http
from src.utils.exceptions import ConfigError, NetworkDisabledError
from src.extract import boundaries, owq, wqp_sites
from src.utils import manifest, paths


class ExplodingSession:
    """A fake session that fails the test if anything actually tries to use the network."""
    def request(self, *args, **kwargs):
        raise AssertionError("a network call was made")


class OkSession:
    class Response:
        ok, content, text, headers = True, b"data", "data", {}

    def request(self, *args, **kwargs):
        return self.Response()


@pytest.fixture
def no_env_file(monkeypatch):
    monkeypatch.setattr(cfg, "load_env", lambda: None)  # ignore any local .env


def test_mode_defaults_to_snapshot(monkeypatch, no_env_file):
    monkeypatch.delenv("PIPELINE_MODE", raising=False)
    assert cfg.pipeline_mode() == "snapshot"
    assert cfg.is_snapshot_mode()


@pytest.mark.parametrize("value, expected", [("live", "live"), ("snapshot", "snapshot"), (" Live ", "live")])
def test_valid_modes(monkeypatch, no_env_file, value, expected):
    monkeypatch.setenv("PIPELINE_MODE", value)
    assert cfg.pipeline_mode() == expected


def test_invalid_mode_is_a_config_error(monkeypatch, no_env_file):
    monkeypatch.setenv("PIPELINE_MODE", "offline")
    with pytest.raises(ConfigError, match="PIPELINE_MODE"):
        cfg.pipeline_mode()


def test_snapshot_mode_blocks_requests_and_names_the_url(monkeypatch):
    monkeypatch.setenv("PIPELINE_MODE", "snapshot")
    with pytest.raises(NetworkDisabledError, match="https://example.org/data"):
        http.request(ExplodingSession(), "GET", "https://example.org/data")


def test_live_mode_allows_requests(monkeypatch):
    monkeypatch.setenv("PIPELINE_MODE", "live")
    assert http.request(OkSession(), "GET", "https://example.org/data").ok


# ---------------------------------------------------------------- extractors (step 3 and 4)

@pytest.mark.parametrize("extractor", [boundaries, owq, wqp_sites], ids=lambda m: m.__name__)
def test_missing_batch_in_snapshot_mode_fails_with_a_clear_message(monkeypatch, extractor):
    """Also proves wqp_sites no longer calls the API (state list) before the batch check."""
    monkeypatch.setenv("PIPELINE_MODE", "snapshot")
    with pytest.raises(ConfigError, match="Snapshot missing batch .*fetch_snapshot.py"):
        extractor.run()


def test_complete_batch_is_reused_offline(monkeypatch):
    monkeypatch.setenv("PIPELINE_MODE", "snapshot")
    batch_id = manifest.make_batch_id(boundaries.SOURCE_CODE, {"download_url": boundaries._download_url()})
    batch_dir = paths.raw_batch_dir(boundaries.SOURCE_CODE, batch_id)
    names = [boundaries.ZIP_NAME, "ne_admin1.shp"]
    for name in names:
        (batch_dir / name).write_bytes(b"frozen")
    manifest.write_manifest(batch_dir, source_code=boundaries.SOURCE_CODE, batch_id=batch_id, params={},
                            requests_log=[], files=[manifest.file_entry(batch_dir / n, "bin", None) for n in names],
                            status="success")
    assert boundaries.run() == batch_dir / "manifest.json"   # no network call, no error


def test_batch_is_complete_needs_success_and_matching_files(tmp_path):
    (tmp_path / "a.csv").write_text("x")
    entry = manifest.file_entry(tmp_path / "a.csv", "csv", 0)
    manifest.write_manifest(tmp_path, source_code="s", batch_id="b", params={}, requests_log=[],
                            files=[entry], status="partial")
    assert not manifest.batch_is_complete(tmp_path)          # not success yet
    manifest.write_manifest(tmp_path, source_code="s", batch_id="b", params={}, requests_log=[],
                            files=[entry], status="success")
    assert manifest.batch_is_complete(tmp_path)
    (tmp_path / "a.csv").write_text("changed")
    assert not manifest.batch_is_complete(tmp_path)          # checksum no longer matches