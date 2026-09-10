"""GitHub Releases HTTP client with ETag-backed on-disk cache."""

from __future__ import annotations

import json
import logging
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import config
from .models import Release, ReleaseAsset
from .version import is_prerelease_tag, parse_version

logger = logging.getLogger(__name__)

try:
    import certifi

    def _ssl_context() -> ssl.SSLContext:
        return ssl.create_default_context(cafile=certifi.where())

except ImportError:

    def _ssl_context() -> ssl.SSLContext:
        return ssl.create_default_context()


class GitHubError(Exception):
    """Raised when GitHub cannot be reached or returned an unexpected payload."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


HttpRequestFn = Callable[[str, dict[str, str], float], HttpResponse]


def _default_request(url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            header_map = {key.lower(): value for key, value in response.headers.items()}
            return HttpResponse(status=int(response.status), headers=header_map, body=response.read())
    except HTTPError as exc:
        header_map = {key.lower(): value for key, value in (exc.headers.items() if exc.headers else [])}
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            body = b""
        if exc.code == 304:
            return HttpResponse(status=304, headers=header_map, body=body)
        raise GitHubError(_http_error_message(exc.code, header_map, body)) from exc


def _http_error_message(status: int, headers: dict[str, str], body: bytes) -> str:
    remaining = headers.get("x-ratelimit-remaining")
    if status in {403, 429} or remaining == "0":
        return "GitHub rate limit reached. Try again later."
    if status >= 500:
        return "GitHub is temporarily unavailable."
    snippet = body.decode("utf-8", errors="replace")[:160].strip()
    if snippet:
        return f"GitHub returned HTTP {status}: {snippet}"
    return f"GitHub returned HTTP {status}."


@dataclass
class FetchResult:
    releases: tuple[Release, ...]
    from_cache: bool
    etag_hit: bool
    error: str | None
    fetched_at: datetime | None
    etag: str = ""


class GitHubReleasesClient:
    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        request: HttpRequestFn | None = None,
        timeout: float = config.REQUEST_TIMEOUT_S,
        user_agent: str = config.USER_AGENT,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._request = request or _default_request
        self.timeout = timeout
        self.user_agent = user_agent

    def fetch_releases(self, url: str, cache_name: str, *, max_age_s: float | None = None) -> FetchResult:
        cached = self._read_cache(cache_name)
        if max_age_s is not None:
            fresh = _fresh_cache_result(cached, max_age_s)
            if fresh is not None:
                return fresh
        headers = {
            "Accept": config.ACCEPT_HEADER,
            "X-GitHub-Api-Version": config.API_VERSION,
            "User-Agent": self.user_agent,
        }
        if cached and cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])

        try:
            response = self._request(f"{url}?per_page={config.RELEASES_PER_PAGE}", headers, self.timeout)
        except GitHubError as exc:
            return self._stale_or_error(cached, str(exc))
        except (URLError, TimeoutError, OSError):
            return self._stale_or_error(cached, "Couldn't reach GitHub. Check your internet connection.")
        except Exception as exc:
            logger.exception("Unexpected GitHub request failure")
            return self._stale_or_error(cached, str(exc) or "Couldn't reach GitHub.")

        if response.status == 304 and cached:
            fetched_at = datetime.now(timezone.utc)
            etag = str(cached.get("etag") or response.headers.get("etag") or "")
            self._write_cache(
                cache_name,
                {
                    "etag": etag,
                    "fetched_at": fetched_at.isoformat(),
                    "releases": cached.get("releases") or [],
                },
            )
            return FetchResult(
                releases=_payload_to_releases(cached.get("releases") or []),
                from_cache=False,
                etag_hit=True,
                error=None,
                fetched_at=fetched_at,
                etag=etag,
            )

        if response.status != 200:
            return self._stale_or_error(cached, _http_error_message(response.status, response.headers, response.body))

        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._stale_or_error(cached, "GitHub returned an invalid response.")
        if not isinstance(payload, list):
            return self._stale_or_error(cached, "GitHub returned an invalid response.")

        etag = response.headers.get("etag", "")
        fetched_at = datetime.now(timezone.utc)
        self._write_cache(cache_name, {"etag": etag, "fetched_at": fetched_at.isoformat(), "releases": payload})
        return FetchResult(
            releases=_payload_to_releases(payload),
            from_cache=False,
            etag_hit=False,
            error=None,
            fetched_at=fetched_at,
            etag=etag,
        )

    def _stale_or_error(self, cached: dict[str, Any] | None, message: str) -> FetchResult:
        if cached and cached.get("releases") is not None:
            return FetchResult(
                releases=_payload_to_releases(cached.get("releases") or []),
                from_cache=True,
                etag_hit=False,
                error=message,
                fetched_at=_parse_cached_time(cached.get("fetched_at")),
                etag=str(cached.get("etag") or ""),
            )
        return FetchResult(releases=(), from_cache=False, etag_hit=False, error=message, fetched_at=None)

    def _cache_path(self, cache_name: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / cache_name

    def _read_cache(self, cache_name: str) -> dict[str, Any] | None:
        path = self._cache_path(cache_name)
        if path is None or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable update cache at %s", path)
            return None
        return payload if isinstance(payload, dict) else None

    def _write_cache(self, cache_name: str, payload: dict[str, Any]) -> None:
        path = self._cache_path(cache_name)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            logger.warning("Could not write update cache to %s", path, exc_info=True)


def parse_release(payload: dict[str, Any]) -> Release | None:
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        return None
    assets = tuple(
        ReleaseAsset(
            name=str(asset.get("name") or ""),
            size=int(asset.get("size") or 0),
            browser_download_url=str(asset.get("browser_download_url") or ""),
            digest=str(asset.get("digest") or ""),
            content_type=str(asset.get("content_type") or ""),
        )
        for asset in (payload.get("assets") or [])
        if isinstance(asset, dict) and asset.get("name")
    )
    return Release(
        tag_name=tag,
        name=str(payload.get("name") or tag),
        html_url=str(payload.get("html_url") or ""),
        body=str(payload.get("body") or ""),
        published_at=str(payload.get("published_at") or ""),
        prerelease=bool(payload.get("prerelease")),
        draft=bool(payload.get("draft")),
        assets=assets,
    )


def filter_releases(
    releases: tuple[Release, ...] | list[Release],
    *,
    include_prereleases: bool,
) -> tuple[Release, ...]:
    kept: list[Release] = []
    for release in releases:
        tag = (release.tag_name or "").strip()
        if release.draft:
            continue
        if tag.lower() in config.SKIP_TAGS:
            continue
        if parse_version(tag) is None:
            continue
        if not include_prereleases and is_prerelease_tag(tag, github_prerelease=release.prerelease):
            continue
        kept.append(release)
    return tuple(kept)


def pick_latest(releases: tuple[Release, ...] | list[Release]) -> Release | None:
    ranked = [release for release in releases if release.version is not None]
    if not ranked:
        return None
    ranked.sort(key=lambda release: (release.version, release.published_at or ""))
    return ranked[-1]


def _payload_to_releases(payload: list[Any]) -> tuple[Release, ...]:
    releases: list[Release] = []
    for item in payload:
        parsed = parse_release(item) if isinstance(item, dict) else None
        if parsed is not None:
            releases.append(parsed)
    return tuple(releases)


def _fresh_cache_result(cached: dict[str, Any] | None, max_age_s: float) -> FetchResult | None:
    if not cached or cached.get("releases") is None:
        return None
    fetched_at = _parse_cached_time(cached.get("fetched_at"))
    if fetched_at is None:
        return None
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    if age < 0 or age >= max_age_s:
        return None
    return FetchResult(
        releases=_payload_to_releases(cached.get("releases") or []),
        from_cache=True,
        etag_hit=False,
        error=None,
        fetched_at=fetched_at,
        etag=str(cached.get("etag") or ""),
    )


def _parse_cached_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
