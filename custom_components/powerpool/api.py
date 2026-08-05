"""Thin async client for the PowerPool read-only REST API."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, quote_plus

import aiohttp

from .const import API_BASE_URL, API_USER, MAX_RESPONSE_BYTES, PARAM_API_KEY

# A generous single timeout covers connect + read. A slow or unreachable API
# surfaces as PowerPoolApiError, which the coordinator turns into UpdateFailed.
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class PowerPoolApiError(Exception):
    """Raised when the PowerPool API cannot be reached or returns junk."""


class PowerPoolAuthError(PowerPoolApiError):
    """Raised when the API key is rejected or yields no account."""


def scrub(text: str, api_key: str) -> str:
    """Replace an API key with a placeholder anywhere it appears in `text`.

    The credential travels in the query string, so anything that echoes a
    request URL would otherwise carry it into the Home Assistant log — and
    those logs get pasted into public issues. The percent-encoded forms are
    replaced too: a key containing `+`, `/` or `=` appears in a URL as
    `%2B`, `%2F`, `%3D`, which a plain substring match would sail straight
    past while the reader can simply URL-decode it.
    """
    if not api_key:
        return text
    for form in (
        api_key,
        quote(api_key, safe=""),
        quote_plus(api_key),
        quote(api_key),
    ):
        text = text.replace(form, "***")
    return text


def _reject_constant(name: str) -> float:
    """Reject the non-standard JSON constants Infinity/-Infinity/NaN."""
    raise ValueError(f"non-finite JSON constant {name!r}")


async def _read_capped(resp: aiohttp.ClientResponse, path: str) -> str:
    """Read a response body, refusing anything implausibly large.

    aiohttp decompresses `Content-Encoding: gzip` transparently and applies no
    ratio limit, so a kilobyte on the wire can become hundreds of megabytes in
    memory — enough to OOM a small Home Assistant host. Reading in chunks and
    stopping at the cap means the decision doesn't depend on a Content-Length
    the server is free to lie about. A real payload is a few KB.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.content.iter_chunked(65536):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise PowerPoolApiError(
                f"Response from {path} exceeded {MAX_RESPONSE_BYTES} bytes; "
                "refusing to buffer it"
            )
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace").strip()


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
            async with self._session.get(
                url,
                params=params,
                timeout=_TIMEOUT,
                # The API never legitimately redirects, and following one would
                # re-issue this request against a host the response chose.
                allow_redirects=False,
            ) as resp:
                if resp.status in (401, 403):
                    raise PowerPoolAuthError("API key rejected by PowerPool")
                if resp.status >= 300:
                    # Deliberately built from the status alone: an aiohttp error
                    # stringifies to include the full request URL, and the
                    # credential travels in that URL's query string.
                    raise PowerPoolApiError(
                        f"Unexpected HTTP {resp.status} from {path}"
                    )
                text = await _read_capped(resp, path)
        except PowerPoolAuthError:
            raise
        except PowerPoolApiError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            # `from None`, not `from err`: the cause's message embeds the
            # request URL — and therefore the API key — so chaining it would
            # put the credential back within reach of any handler that logs
            # with exc_info, however carefully this message is scrubbed.
            raise PowerPoolApiError(
                scrub(f"Error fetching {path}: {type(err).__name__}", self._api_key)
            ) from None

        try:
            # json.loads accepts the bare literals Infinity, -Infinity and NaN
            # by default. They are not valid JSON, nothing legitimate sends
            # them, and letting them through would put a non-finite float into
            # a sensor state and its long-term statistics.
            return json.loads(text, parse_constant=_reject_constant)
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
