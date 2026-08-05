"""Thin async client for the PowerPool read-only REST API."""

from __future__ import annotations

import json
from typing import Any

import aiohttp

from .const import API_BASE_URL, API_POOL, API_USER, PARAM_API_KEY

# A generous single timeout covers connect + read. A slow or unreachable API
# surfaces as PowerPoolApiError, which the coordinator turns into UpdateFailed.
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class PowerPoolApiError(Exception):
    """Raised when the PowerPool API cannot be reached or returns junk."""


class PowerPoolAuthError(PowerPoolApiError):
    """Raised when the API key is rejected or yields no account."""


def scrub(text: str, api_key: str) -> str:
    """Replace an API key with a placeholder anywhere it appears in `text`.

    The credential travels in the query string, so aiohttp errors — which
    embed the full request URL — would otherwise carry it into the Home
    Assistant log. Every message raised from this module is scrubbed.
    """
    if not api_key:
        return text
    return text.replace(api_key, "***")


class PowerPoolClient:
    """Minimal client over the two endpoints PowerPool publishes.

    Stateless apart from the API key; it borrows Home Assistant's shared
    aiohttp session rather than opening its own, so there is nothing to close.
    """

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        """Store the shared HA aiohttp session and the account's API key."""
        self._session = session
        self._api_key = api_key

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a path and parse JSON, normalising every failure to our error.

        Callers only have to catch PowerPoolApiError. A 401/403 is promoted to
        PowerPoolAuthError so the config flow can tell "wrong key" apart from
        "PowerPool is down" and the coordinator can trigger reauth.
        """
        url = f"{API_BASE_URL}{path}"
        try:
            async with self._session.get(url, params=params, timeout=_TIMEOUT) as resp:
                if resp.status in (401, 403):
                    raise PowerPoolAuthError("API key rejected by PowerPool")
                resp.raise_for_status()
                text = (await resp.text()).strip()
        except PowerPoolAuthError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PowerPoolApiError(
                scrub(f"Error fetching {path}: {err}", self._api_key)
            ) from err

        try:
            return json.loads(text)
        except ValueError as err:
            # e.g. an HTML error or maintenance page from the edge/CDN.
            raise PowerPoolApiError(
                scrub(f"Invalid JSON from {path}: {text[:80]!r}", self._api_key)
            ) from err

    async def user(self) -> dict[str, Any]:
        """Private account payload, keyed by username.

        PowerPool does not use HTTP status to signal a bad credential: a wrong
        key — or no key at all — answers `200 {}`. So an empty object is the
        only "rejected" signal there is, and it is raised as PowerPoolAuthError.
        Because the same response would also come back from a transient
        server-side blip, the coordinator requires several in a row before it
        treats the key as truly dead (see PowerPoolCoordinator).
        """
        data = await self._get(API_USER, {PARAM_API_KEY: self._api_key})
        if not isinstance(data, dict):
            raise PowerPoolApiError(
                f"Unexpected user payload type: {type(data).__name__}"
            )
        if not data:
            raise PowerPoolAuthError("API key returned no account data")
        return data

    async def pool(self) -> dict[str, Any]:
        """Public pool-wide stats (no credential required)."""
        data = await self._get(API_POOL)
        if not isinstance(data, dict):
            raise PowerPoolApiError(
                f"Unexpected pool payload type: {type(data).__name__}"
            )
        return data
