"""Configuration management for NetBox MCP Server."""

import logging
import logging.config
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import AnyUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized configuration for NetBox MCP Server.

    Configuration precedence: CLI > Environment > .env file > Defaults

    Environment variables should match field names (e.g., NETBOX_URL, TRANSPORT).
    """

    # ===== Core NetBox Settings =====
    netbox_url: AnyUrl
    """Base URL of the NetBox instance (e.g., https://netbox.example.com/)"""

    netbox_token: SecretStr
    """API token for NetBox authentication (treated as secret)"""

    # ===== Transport Settings =====
    transport: Literal["stdio", "http"] = "stdio"
    """MCP transport protocol to use (stdio for Claude Desktop, http for web clients)"""

    host: str = "127.0.0.1"
    """Host address to bind HTTP server (only used when transport='http')"""

    port: int = 8000
    """Port to bind HTTP server (only used when transport='http')"""

    cors_origins: list[str] = Field(
        default_factory=list,
        description="Explicit allowlist of browser origins for HTTP CORS "
        "(e.g. https://app.example.com). The wildcard '*' is not permitted.",
    )

    # ===== Plugin Discovery Settings =====
    enable_plugin_discovery: bool = False
    """Whether to auto-discover plugin object types from NetBox at startup"""

    # ===== Security Settings =====
    verify_ssl: bool = True
    """Whether to verify SSL certificates when connecting to NetBox"""

    allow_unauthenticated_http: bool = False
    """Acknowledge exposing HTTP transport on a non-loopback address without
    built-in authentication. The server ships no auth and registers write tools
    backed by a privileged NetBox token, so network-exposed HTTP is refused
    unless this is explicitly set (e.g. when an authenticating reverse proxy is
    in front)."""

    # ===== Observability Settings =====
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    """Logging verbosity level"""

    # ===== Pydantic Configuration =====
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",  # No prefix, use field names directly
        extra="ignore",  # Ignore unknown environment variables
        case_sensitive=False,  # Environment variables are case-insensitive
    )

    # ===== Validators =====

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Ensure port is in valid range."""
        if not (0 < v < 65536):
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator("netbox_url")
    @classmethod
    def validate_netbox_url(cls, v: AnyUrl) -> AnyUrl:
        """Ensure NetBox URL has a scheme and host."""
        if not v.scheme or not v.host:
            raise ValueError(
                "NETBOX_URL must include scheme and host (e.g., https://netbox.example.com/)"
            )
        return v

    @model_validator(mode="after")
    def validate_http_transport_requirements(self) -> "Settings":
        """No additional validation needed for HTTP transport; defaults are appropriate."""
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def validate_cors_origins(cls, v: object) -> list[str]:
        """Ensure each CORS origin is an explicit, valid URL.

        The wildcard ``*`` is rejected: HTTP transport can expose write tools,
        so an allowlist of trusted origins is required rather than any origin.
        """
        for origin in v:
            if origin == "*":
                raise ValueError(
                    "CORS_ORIGINS must not contain '*'. Specify an explicit "
                    "allowlist of trusted origins (e.g. https://app.example.com)."
                )
            parsed = urlparse(origin)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError(
                    f"Invalid CORS_ORIGIN: {origin!r} (expected format: http://host:port)"
                )
        return v

    def http_exposes_unauthenticated_writes(self) -> bool:
        """Whether HTTP transport would serve write tools without authentication.

        True when transport is HTTP, the bind host is not loopback, and the
        operator has not opted in via ``allow_unauthenticated_http``. Used to
        fail closed before starting a network-exposed, unauthenticated server.
        """
        if self.transport != "http":
            return False
        if self.host in {"127.0.0.1", "localhost", "::1"}:
            return False
        return not self.allow_unauthenticated_http

    def get_effective_config_summary(self) -> dict:
        """
        Return a non-secret summary of effective configuration for logging.

        Returns:
            Dictionary with configuration values (secrets masked)
        """
        summary: dict[str, Any] = {
            "netbox_url": str(self.netbox_url),
            "netbox_token": "***REDACTED***",
            "transport": self.transport,
            "verify_ssl": self.verify_ssl,
            "enable_plugin_discovery": self.enable_plugin_discovery,
            "log_level": self.log_level,
        }
        if self.transport == "http":
            summary.update(
                {
                    "host": self.host,
                    "port": self.port,
                    "cors_origins": self.cors_origins,
                }
            )
        return summary


def configure_logging(
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
) -> None:
    """
    Configure structured logging using dictConfig.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "stream": "ext://sys.stderr",
            },
        },
        "loggers": {
            # Suppress noisy HTTP client logs unless DEBUG
            "urllib3": {
                "level": "WARNING" if log_level != "DEBUG" else "DEBUG",
            },
            "httpx": {
                "level": "WARNING" if log_level != "DEBUG" else "DEBUG",
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console"],
        },
    }

    logging.config.dictConfig(config)
