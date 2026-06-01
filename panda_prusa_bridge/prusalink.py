from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from threading import Lock

from panda_prusa_bridge.config import BridgeConfig


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BridgeStatus:
    bed_target: float
    bed_current: float
    source_ok: bool
    last_update_monotonic: float | None
    last_error: str | None


class PrusaLinkClient:
    def __init__(self, config: BridgeConfig):
        self._config = config
        self._lock = Lock()
        self._cached_status = BridgeStatus(
            bed_target=config.fallback_bed_target,
            bed_current=config.fallback_bed_current,
            source_ok=False,
            last_update_monotonic=None,
            last_error="not_fetched_yet",
        )
        self._cached_at = 0.0
        self._last_logged_error: str | None = None
        self._last_logged_success: tuple[float, float] | None = None

    def get_status(self) -> BridgeStatus:
        now = time.monotonic()
        with self._lock:
            if now - self._cached_at < self._config.cache_ttl_seconds:
                return self._cached_status

            self._cached_status = self._fetch_status(now)
            self._cached_at = now
            return self._cached_status

    def _fetch_status(self, now: float) -> BridgeStatus:
        request = urllib.request.Request(
            url=f"{self._config.prusa_host.rstrip('/')}{self._config.prusa_status_path}",
            headers=self._build_headers(),
            method="GET",
        )

        try:
            with self._build_opener().open(
                request,
                timeout=self._config.request_timeout_seconds,
            ) as response:
                payload = json.load(response)
        except (
            OSError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            error_message = str(exc)
            if error_message != self._last_logged_error:
                LOGGER.warning("PrusaLink status fetch failed: %s", exc)
                self._last_logged_error = error_message
            return BridgeStatus(
                bed_target=self._config.fallback_bed_target,
                bed_current=self._config.fallback_bed_current,
                source_ok=False,
                last_update_monotonic=self._cached_status.last_update_monotonic,
                last_error=error_message,
            )

        printer = payload["printer"]
        bed_target = self._coerce_number(
            printer.get("target_bed"),
            self._config.fallback_bed_target,
        )
        bed_current = self._coerce_number(
            printer.get("temp_bed"),
            self._config.fallback_bed_current,
        )

        success_signature = (bed_target, bed_current)
        if success_signature != self._last_logged_success or self._last_logged_error is not None:
            LOGGER.info(
                "PrusaLink update target=%.2f current=%.2f",
                bed_target,
                bed_current,
            )
            self._last_logged_success = success_signature
            self._last_logged_error = None
        return BridgeStatus(
            bed_target=bed_target,
            bed_current=bed_current,
            source_ok=True,
            last_update_monotonic=now,
            last_error=None,
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._config.prusa_auth_type == "api_key" and self._config.prusa_api_key:
            headers["X-Api-Key"] = self._config.prusa_api_key
        return headers

    def _build_opener(self) -> urllib.request.OpenerDirector:
        if self._config.prusa_auth_type != "digest":
            return urllib.request.build_opener()

        password_manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_manager.add_password(
            realm=None,
            uri=self._config.prusa_host,
            user=self._config.prusa_username,
            passwd=self._config.prusa_password,
        )
        digest_handler = urllib.request.HTTPDigestAuthHandler(password_manager)
        return urllib.request.build_opener(digest_handler)

    @staticmethod
    def _coerce_number(value: object, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback
