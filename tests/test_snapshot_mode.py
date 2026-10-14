"""Tests for REPRO-1 snapshot mode: pipeline_mode() and the network block in http.request()."""
import pytest

from src.utils import config as cfg
from src.utils import http
from src.utils.exceptions import ConfigError, NetworkDisabledError


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