"""Constants for the PowerPool integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform

DOMAIN = "powerpool"
LOGGER = logging.getLogger(__package__)
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

# Keys used in ConfigEntry.data / ConfigEntry.options. The API key is captured
# during the config flow and never changes shape; the scan interval starts at
# the default and is overridden from options once the user edits it.
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 300  # seconds — pool-side stats are averaged, not live
MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 3600

# API. Only two endpoints exist and both are read-only:
#   /api/user?apiKey=<key>  -> private, keyed by username (see below)
#   /api/pool               -> public pool-wide stats (unused in this version)
#
# The user payload is keyed by the account's username, so a response looks like
#   {"<username>": {"hashrate": {...}, "balances": [...], "workers": {...},
#                   "payments": [...], "earnings": {...}}}
# The API key alone selects the account, so the username is *derived from the
# response* rather than asked for during setup.
API_BASE_URL = "https://api.powerpool.io"
API_USER = "/api/user"
API_POOL = "/api/pool"

# Query-string parameter carrying the credential. Held here so redaction in
# diagnostics.py and the log-scrubbing in api.py stay in step.
PARAM_API_KEY = "apiKey"

# --- hashrate units -----------------------------------------------------------
# PowerPool reports a hashrate as a float plus a *separate* units string, and
# the units follow the magnitude ("66.3" + "TH/s" now, "980" + "GH/s" after the
# miner throttles). A sensor whose unit changes between polls breaks Home
# Assistant's long-term statistics, so every value is normalised to base units
# (hashes or solutions per second) on ingest and rendered in a unit fixed per
# algorithm — see ALGORITHM_UNITS.
SI_PREFIXES: dict[str, float] = {
    "": 1.0,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
    "P": 1e15,
    "E": 1e18,
    "Z": 1e21,
}

# Base quantity of the rate. Equihash counts solutions, everything else hashes.
# Ordered longest-first so "MSol/s" matches "Sol" before it can match "H".
RATE_BASES: tuple[str, ...] = ("SOL", "H")

# Display unit per algorithm, chosen so a single miner's hashrate lands on a
# readable number rather than 0.000012 of a pool-scale unit. The keys are the
# algorithm names PowerPool uses, normalised by normalise_algorithm().
ALGORITHM_UNITS: dict[str, str] = {
    "sha256": "TH/s",
    "scrypt": "GH/s",
    "eaglesong": "TH/s",
    "blake2s": "GH/s",
    "x11": "GH/s",
    "kheavyhash": "TH/s",
    "etchash": "MH/s",
    "equihash": "kSol/s",
}
DEFAULT_HASHRATE_UNIT = "GH/s"

# Display precision for coin balances and payouts. Most coins are quoted in
# eight decimals; stablecoins read better at two.
COIN_PRECISION: dict[str, int] = {"USDC": 2, "USDT": 2}
DEFAULT_COIN_PRECISION = 8

# Human labels for the algorithm devices. Anything not listed falls back to the
# raw key from the API, so a newly added algorithm still works.
ALGORITHM_NAMES: dict[str, str] = {
    "sha256": "SHA-256",
    "scrypt": "Scrypt",
    "eaglesong": "Eaglesong",
    "blake2s": "Blake2s",
    "x11": "X11",
    "kheavyhash": "kHeavyHash",
    "etchash": "Etchash",
    "equihash": "Equihash",
}
