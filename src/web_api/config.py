from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WebApiConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    agent_socket: Path = Path("/tmp/fpga-agent.sock")
    user_cookie: str = "fpga_user"
    cookie_max_age_seconds: int = 60 * 60 * 12
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    ws_protocol: str = "fpga-demo.v1"

    @classmethod
    def from_env(cls) -> "WebApiConfig":
        return cls(
            host=os.environ.get("WEB_API_HOST", cls.host),
            port=_env_int("WEB_API_PORT", cls.port),
            agent_socket=Path(os.environ.get("WEB_API_AGENT_SOCKET", str(cls.agent_socket))),
            user_cookie=os.environ.get("WEB_API_USER_COOKIE", cls.user_cookie),
            cookie_max_age_seconds=_env_int("WEB_API_COOKIE_MAX_AGE_SECONDS", cls.cookie_max_age_seconds),
            cookie_secure=_env_bool("WEB_API_COOKIE_SECURE", cls.cookie_secure),
            cookie_samesite=os.environ.get("WEB_API_COOKIE_SAMESITE", cls.cookie_samesite),
            ws_protocol=os.environ.get("WEB_API_WS_PROTOCOL", cls.ws_protocol),
        )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")
