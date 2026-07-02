"""Tests for yt-dlp throttle configuration (Phase F)."""
from app.config.local_config import get_ytdlp_throttle_opts


class TestThrottleOpts:
    def test_defaults_present(self, monkeypatch):
        for k in ("YTDLP_SLEEP_INTERVAL", "YTDLP_MAX_SLEEP_INTERVAL",
                  "YTDLP_SLEEP_REQUESTS", "YTDLP_RATELIMIT", "YTDLP_RETRIES"):
            monkeypatch.delenv(k, raising=False)
        opts = get_ytdlp_throttle_opts()
        assert opts["sleep_interval"] == 1.0
        assert opts["max_sleep_interval"] == 5.0
        assert opts["sleep_interval_requests"] == 1
        assert opts["retries"] == 10
        assert "ratelimit" not in opts  # 0 => unlimited => omitted

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("YTDLP_SLEEP_INTERVAL", "3")
        monkeypatch.setenv("YTDLP_RATELIMIT", "500000")
        opts = get_ytdlp_throttle_opts()
        assert opts["sleep_interval"] == 3.0
        assert opts["ratelimit"] == 500000

    def test_invalid_values_fall_back_to_defaults(self, monkeypatch):
        monkeypatch.setenv("YTDLP_SLEEP_INTERVAL", "notanumber")
        assert get_ytdlp_throttle_opts()["sleep_interval"] == 1.0
