"""Thin HTTP client for TheStatsAPI (https://api.thestatsapi.com/api).

Every call that can fail (404 / 429 / timeout / network error) returns
``None`` instead of raising, so callers can apply their own fallback logic
without wrapping every call in try/except.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / "STATSAPI_KEY.env")

logger = logging.getLogger("statsapi.client")

BASE_URL = "https://api.thestatsapi.com/api"
# On Vercel (and most serverless runtimes) only /tmp is writable at runtime.
DEFAULT_CACHE_DIR = (
    Path(tempfile.gettempdir()) / "statsapi_cache"
    if os.environ.get("VERCEL")
    else Path(__file__).resolve().parent / "cache"
)
DEFAULT_CACHE_TTL_HOURS = 6
DEFAULT_TIMEOUT = 10
MAX_RETRIES_429 = 3


class StatsAPIError(Exception):
    """Raised for setup/programmer errors only (e.g. missing API key)."""


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if not params:
        return {}
    return {k: v for k, v in params.items() if v is not None}


class StatsAPIClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.api_key = api_key or os.environ.get("STATSAPI_KEY")
        if not self.api_key:
            raise StatsAPIError(
                "STATSAPI_KEY environment variable is not set. "
                "Set it to your TheStatsAPI bearer token before running this script."
            )
        self.base_url = base_url.rstrip("/")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_seconds = cache_ttl_hours * 3600
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    # ------------------------------------------------------------------ #
    # Disk cache
    # ------------------------------------------------------------------ #
    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        raw = json.dumps({"path": path, "params": params}, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> Any:
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - payload.get("cached_at", 0) > self.cache_ttl_seconds:
            return None
        return payload.get("data")

    def _write_cache(self, key: str, data: Any) -> None:
        p = self._cache_path(key)
        try:
            p.write_text(
                json.dumps({"cached_at": time.time(), "data": data}),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not write cache file %s: %s", p, exc)

    # ------------------------------------------------------------------ #
    # Core request
    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: dict[str, Any] | None = None, use_cache: bool = True) -> Any:
        """Return the `data` payload for a GET request, or None on any failure."""
        clean = _clean_params(params)
        key = self._cache_key(path, clean)
        if use_cache:
            cached = self._read_cache(key)
            if cached is not None:
                return cached

        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.get(url, params=clean, timeout=self.timeout)
            except requests.exceptions.Timeout:
                logger.warning("Timeout calling %s (params=%s)", path, clean)
                return None
            except requests.exceptions.RequestException as exc:
                logger.warning("Request error calling %s: %s", path, exc)
                return None

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError:
                    logger.warning("Invalid JSON from %s", path)
                    return None
                data = body.get("data", body) if isinstance(body, dict) else body
                if use_cache:
                    self._write_cache(key, data)
                return data

            if resp.status_code == 404:
                logger.info("404 not_found for %s (params=%s)", path, clean)
                return None

            if resp.status_code == 429:
                if attempt > MAX_RETRIES_429:
                    logger.warning("Giving up on %s after %d retries (429)", path, attempt - 1)
                    return None
                retry_after = resp.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                logger.info("429 rate limited on %s, waiting %.1fs (attempt %d)", path, wait, attempt)
                time.sleep(wait)
                continue

            logger.warning(
                "Unexpected status %s for %s (params=%s): %s",
                resp.status_code,
                path,
                clean,
                resp.text[:300],
            )
            return None

    # ------------------------------------------------------------------ #
    # Teams
    # ------------------------------------------------------------------ #
    def search_teams(self, query: str, per_page: int = 20) -> list[dict]:
        data = self._get("/football/teams", {"search": query, "per_page": per_page})
        return data or []

    def get_team(self, team_id: str) -> dict | None:
        return self._get(f"/football/teams/{team_id}")

    def get_team_stats(self, team_id: str, season_id: str) -> dict | None:
        return self._get(f"/football/teams/{team_id}/stats", {"season_id": season_id})

    # ------------------------------------------------------------------ #
    # Matches
    # ------------------------------------------------------------------ #
    def list_matches(
        self,
        team_id: str | None = None,
        competition_id: str | None = None,
        season_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        status: str | None = None,
        per_page: int = 100,
        page: int = 1,
    ) -> list[dict]:
        params = {
            "team_id": team_id,
            "competition_id": competition_id,
            "season_id": season_id,
            "date_from": date_from,
            "date_to": date_to,
            "status": status,
            "per_page": per_page,
            "page": page,
        }
        data = self._get("/football/matches", params)
        return data or []

    def get_match(self, match_id: str) -> dict | None:
        return self._get(f"/football/matches/{match_id}")

    def get_match_stats(self, match_id: str) -> dict | None:
        return self._get(f"/football/matches/{match_id}/stats")

    def get_match_odds(self, match_id: str, bookmaker: str | None = None) -> dict | None:
        params = {"bookmaker": bookmaker} if bookmaker else None
        return self._get(f"/football/matches/{match_id}/odds", params)

    # ------------------------------------------------------------------ #
    # Coverage
    # ------------------------------------------------------------------ #
    def get_league_coverage(self, competition_id: str) -> dict | None:
        return self._get(f"/coverage/leagues/{competition_id}")
