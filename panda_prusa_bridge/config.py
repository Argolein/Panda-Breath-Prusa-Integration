from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BridgeConfig:
    listen_host: str
    listen_port: int
    prusa_host: str
    prusa_status_path: str
    prusa_auth_type: str
    prusa_username: str
    prusa_password: str
    prusa_api_key: str
    request_timeout_seconds: float
    cache_ttl_seconds: float
    fallback_bed_target: float
    fallback_bed_current: float
    log_level: str

    @classmethod
    def load(cls, path: str | Path) -> "BridgeConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        return cls(
            listen_host=str(raw.get("listen_host", "0.0.0.0")),
            listen_port=int(raw.get("listen_port", 7126)),
            prusa_host=str(raw["prusa_host"]),
            prusa_status_path=str(raw.get("prusa_status_path", "/api/v1/status")),
            prusa_auth_type=str(raw.get("prusa_auth_type", "digest")).lower(),
            prusa_username=str(raw.get("prusa_username", "")),
            prusa_password=str(raw.get("prusa_password", "")),
            prusa_api_key=str(raw.get("prusa_api_key", "")),
            request_timeout_seconds=float(raw.get("request_timeout_seconds", 3.0)),
            cache_ttl_seconds=float(raw.get("cache_ttl_seconds", 2.0)),
            fallback_bed_target=float(raw.get("fallback_bed_target", 0.0)),
            fallback_bed_current=float(raw.get("fallback_bed_current", 0.0)),
            log_level=str(raw.get("log_level", "INFO")).upper(),
        )
