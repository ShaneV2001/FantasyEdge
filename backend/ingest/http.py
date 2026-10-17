"""Central HTTP client: retry with backoff, polite rate limiting and an on-disk response cache.

Every external call in FantasyEdge goes through `CachedHttp`. If a source fails and a stale cached
copy exists, the stale copy is served (and logged) so the app degrades instead of breaking.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger("fantasyedge.http")

USER_AGENT = "FantasyEdge/0.1 (+https://github.com/ShaneV2001/FantasyEdge; non-commercial)"


class SourceUnavailable(RuntimeError):
    """An upstream data source failed and no cached copy could be used."""

    def __init__(self, source: str, detail: str, status: int | None = None):
        super().__init__(f"{source}: {detail}")
        self.source = source
        self.detail = detail
        self.status = status  # HTTP status when the source answered with an error


class AuthRejected(RuntimeError):
    """The source refused our credentials (HTTP 401/403). Never answered from cache: a stale copy
    would hide an expired login."""

    def __init__(self, source: str, status: int):
        super().__init__(f"{source}: HTTP {status}")
        self.source = source
        self.status = status


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


@dataclass
class CachedResponse:
    body: bytes
    fetched_at: datetime
    stale: bool = False

    def json(self) -> Any:
        return json.loads(self.body) if self.body.strip() else None

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")


class CachedHttp:
    def __init__(
        self,
        cache_dir: Path,
        client: httpx.Client | None = None,
        min_interval_s: float = 0.1,
        timeout_s: float = 30.0,
    ):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.Client(
            timeout=timeout_s, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
        self.min_interval_s = min_interval_s
        self._last_call = 0.0
        self._lock = threading.Lock()

    # ---- cache helpers -------------------------------------------------
    def _key(self, url: str, params: dict | list | None, headers: dict | None = None) -> Path:
        raw = url + "?" + json.dumps(params or {}, sort_keys=True)
        if headers:  # e.g. ESPN's X-Fantasy-Filter selects different data at the same URL
            raw += "#" + json.dumps(headers, sort_keys=True)
        digest = hashlib.sha1(raw.encode()).hexdigest()[:20]
        return self.cache_dir / f"{digest}.bin"

    def _read_cache(self, path: Path) -> CachedResponse | None:
        meta = path.with_suffix(".meta")
        if not path.exists() or not meta.exists():
            return None
        fetched = datetime.fromisoformat(meta.read_text().strip())
        return CachedResponse(body=path.read_bytes(), fetched_at=fetched)

    def _write_cache(self, path: Path, body: bytes, fetched: datetime) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        path.with_suffix(".meta").write_text(fetched.isoformat())

    # ---- network -------------------------------------------------------
    def _throttle(self) -> None:
        with self._lock:
            wait = self.min_interval_s - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=0.5, max=8),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _fetch(
        self,
        url: str,
        params: dict | list | None,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        self._throttle()
        # Cookies ride on this request only: never on the shared client, the cache key or a log.
        if cookies:
            headers = {
                **(headers or {}),
                "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
            }
        resp = self.client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.content

    def get(
        self,
        url: str,
        *,
        source: str,
        params: dict | list | None = None,
        ttl: timedelta = timedelta(minutes=10),
        force: bool = False,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> CachedResponse:
        path = self._key(url, params, headers)
        cached = self._read_cache(path)
        now = datetime.now(UTC)
        if cached and not force and now - cached.fetched_at < ttl:
            return cached
        try:
            body = self._fetch(url, params, cookies, headers)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise AuthRejected(source, exc.response.status_code) from None
            return self._fallback(source, cached, exc)
        except (httpx.HTTPError, OSError) as exc:
            return self._fallback(source, cached, exc)
        self._write_cache(path, body, now)
        return CachedResponse(body=body, fetched_at=now)

    def _fallback(
        self, source: str, cached: CachedResponse | None, exc: BaseException
    ) -> CachedResponse:
        if cached:
            log.warning(
                "%s unavailable (%s); serving cache from %s", source, exc, cached.fetched_at
            )
            cached.stale = True
            return cached
        log.error("%s unavailable and no cache: %s", source, exc)
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        raise SourceUnavailable(source, str(exc), status) from exc

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()
