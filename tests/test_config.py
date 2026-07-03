"""Tests for configuration management."""

import logging
import sys
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from netbox_mcp_server.config import Settings, configure_logging
from netbox_mcp_server.server import parse_cli_args

ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - test value, not an actual bind


def test_settings_requires_netbox_url():
    """Test that Settings requires NETBOX_URL."""
    # Isolate from .env file by patching model_config
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ValidationError, match="netbox_url"),
    ):
        Settings(netbox_token="test-token", _env_file=None)


def test_settings_requires_netbox_token():
    """Test that Settings requires NETBOX_TOKEN."""
    # Isolate from .env file by patching model_config
    with (
        patch.dict("os.environ", {}, clear=True),
        pytest.raises(ValidationError, match="netbox_token"),
    ):
        Settings(netbox_url="https://netbox.example.com/", _env_file=None)


def test_settings_validates_url_format():
    """Test that invalid URLs are rejected."""

    with pytest.raises(ValidationError, match="Input should be a valid URL"):
        Settings(netbox_url="not-a-valid-url", netbox_token="test-token")


def test_settings_validates_port_range():
    """Test that port must be in valid range."""

    with pytest.raises(ValidationError, match="port"):
        Settings(
            netbox_url="https://netbox.example.com/",
            netbox_token="test-token",
            port=99999,
        )


def test_settings_masks_secrets_in_summary():
    """Test that get_effective_config_summary masks secrets."""

    settings = Settings(netbox_url="https://netbox.example.com/", netbox_token="super-secret-token")

    summary = settings.get_effective_config_summary()

    assert summary["netbox_token"] == "***REDACTED***"
    assert "super-secret-token" not in str(summary)


def test_cors_origins_rejects_wildcard():
    """Test that the CORS wildcard '*' is rejected in favor of an allowlist."""

    with pytest.raises(ValidationError, match="must not contain"):
        Settings(
            netbox_url="https://netbox.example.com/",
            netbox_token="test-token",
            cors_origins=["*"],
        )


def test_cors_origins_accepts_explicit_allowlist():
    """Test that explicit origins are accepted."""

    settings = Settings(
        netbox_url="https://netbox.example.com/",
        netbox_token="test-token",
        cors_origins=["https://app.example.com"],
    )
    assert settings.cors_origins == ["https://app.example.com"]


def test_cors_origins_rejects_malformed_origin():
    """Test that origins without scheme/host are rejected."""

    with pytest.raises(ValidationError, match="Invalid CORS_ORIGIN"):
        Settings(
            netbox_url="https://netbox.example.com/",
            netbox_token="test-token",
            cors_origins=["not-a-url"],
        )


# ===== HTTP Exposure Guard Tests =====


def _settings(**kwargs) -> Settings:
    base = {
        "netbox_url": "https://netbox.example.com/",
        "netbox_token": "test-token",
    }
    base.update(kwargs)
    return Settings(**base)


def test_http_exposure_false_for_stdio():
    """stdio transport is never a network exposure."""
    s = _settings(transport="stdio", host=ALL_INTERFACES)
    assert s.http_exposes_unauthenticated_writes() is False


def test_http_exposure_false_for_loopback_http():
    """HTTP bound to loopback is allowed without opt-in."""
    s = _settings(transport="http", host="127.0.0.1")
    assert s.http_exposes_unauthenticated_writes() is False


def test_http_exposure_true_for_nonloopback_without_optin():
    """HTTP bound to a non-loopback host without opt-in fails closed."""
    s = _settings(transport="http", host=ALL_INTERFACES)
    assert s.http_exposes_unauthenticated_writes() is True


def test_http_exposure_false_when_optin_set():
    """Explicit opt-in permits non-loopback HTTP exposure."""
    s = _settings(transport="http", host=ALL_INTERFACES, allow_unauthenticated_http=True)
    assert s.http_exposes_unauthenticated_writes() is False


# ===== CLI Argument Parsing Tests =====


def test_parse_cli_args_multiple():
    """Test that multiple arguments are captured."""

    original_argv = sys.argv
    try:
        sys.argv = [
            "server.py",
            "--netbox-url",
            "https://test.example.com/",
            "--transport",
            "http",
            "--port",
            "9000",
            "--log-level",
            "DEBUG",
            "--no-verify-ssl",
        ]
        result = parse_cli_args()
        assert result["netbox_url"] == "https://test.example.com/"
        assert result["transport"] == "http"
        assert result["port"] == 9000
        assert result["log_level"] == "DEBUG"
        assert result["verify_ssl"] is False
    finally:
        sys.argv = original_argv


# ===== Logging Configuration Tests =====


def test_configure_logging_suppresses_http_clients():
    """Test that HTTP client loggers are suppressed at INFO level."""

    configure_logging("INFO")

    urllib3_logger = logging.getLogger("urllib3")
    httpx_logger = logging.getLogger("httpx")

    assert urllib3_logger.level == logging.WARNING
    assert httpx_logger.level == logging.WARNING


def test_configure_logging_shows_http_clients_at_debug():
    """Test that HTTP client loggers are shown at DEBUG level."""
    configure_logging("DEBUG")

    root_logger = logging.getLogger()
    urllib3_logger = logging.getLogger("urllib3")
    httpx_logger = logging.getLogger("httpx")

    assert root_logger.level == logging.DEBUG
    assert urllib3_logger.level == logging.DEBUG
    assert httpx_logger.level == logging.DEBUG
