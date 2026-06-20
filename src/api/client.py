"""alerts.in.ua API client with pagination and rate-limit backoff."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from .schemas import ActiveAlertRegion, RawAlert

log = logging.getLogger(__name__)

BASE_URL = "https://api.alerts.in.ua/v3"
_DEFAULT_TIMEOUT = 30.0
_RATE_LIMIT_DELAY = 1.0   # seconds between pages
_MAX_RETRIES = 5
_BACKOFF_BASE = 2.0


def _get_api_key() -> str:
    return os.environ.get("ALERTS_API_KEY", "")


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_get_api_key()}"}


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, **kwargs
) -> httpx.Response:
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(url, **kwargs)
            if resp.status_code == 429:
                wait = _BACKOFF_BASE ** attempt
                log.warning("Rate limited — waiting %.1fs", wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            if attempt == _MAX_RETRIES - 1:
                raise
            wait = _BACKOFF_BASE ** attempt
            log.warning("HTTP %s — retry %d in %.1fs", exc.response.status_code, attempt + 1, wait)
            await asyncio.sleep(wait)
    raise RuntimeError("Exhausted retries")


async def fetch_active_alerts() -> list[ActiveAlertRegion]:
    """Single call — returns currently active alert regions.

    Returns empty list (no crash) if ALERTS_API_KEY is not set.
    The live-status banner in app.py will simply show no active alerts.
    """
    if not _get_api_key():
        log.warning("ALERTS_API_KEY not set — live status check skipped")
        return []
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await _get_with_retry(
            client, f"{BASE_URL}/alerts/active.json", headers=_headers()
        )
        raw = resp.json()
        if isinstance(raw, list):
            return [ActiveAlertRegion(**r) for r in raw]
        return [ActiveAlertRegion(**r) for r in raw.get("alerts", [])]


async def fetch_history_paginated(
    since: datetime | None = None,
    per_page: int = 100,
) -> AsyncIterator[list[RawAlert]]:
    """
    Async generator — yields pages of RawAlert until exhausted.
    Uses delta load if `since` provided (ISO 8601, UTC).
    """
    params: dict[str, str | int] = {"per_page": per_page, "page": 1}
    if since:
        params["started_after"] = since.astimezone(timezone.utc).isoformat()

    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        while True:
            resp = await _get_with_retry(
                client,
                f"{BASE_URL}/alerts/history.json",
                headers=_headers(),
                params=params,
            )
            data = resp.json()

            alerts_raw = data if isinstance(data, list) else data.get("alerts", [])
            if not alerts_raw:
                break

            page_alerts = [RawAlert(**a) for a in alerts_raw]
            yield page_alerts

            total = data.get("total", 0) if isinstance(data, dict) else 0
            fetched = int(params["page"]) * per_page
            if total and fetched >= total:
                break

            params["page"] = int(params["page"]) + 1
            await asyncio.sleep(_RATE_LIMIT_DELAY)
