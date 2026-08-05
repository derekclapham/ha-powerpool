"""Constants for the PowerPool integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform

DOMAIN = "powerpool"
LOGGER = logging.getLogger(__package__)
PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

# Poll interval, stored in ConfigEntry.options once the user edits it via the
# Configure dialog. The account's API key and username use Home Assistant's own
# CONF_API_KEY / CONF_USERNAME in ConfigEntry.data.
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 300  # seconds — pool-side stats are averaged, not live
MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 3600

# API. PowerPool publishes two read-only endpoints; this integration uses only
# the private one. (The public /api/pool endpoint carries pool-wide stats that
# are identical for every account, so it belongs on a shared device rather than
# duplicated per entry — left for a later version.)
#
# The user payload is keyed by the account's username, so a response looks like
#   {"<username>": {"hashrate": {...}, "balances": [...], "workers": {...},
#                   "payments": [...], "earnings": {...}}}
# The API key alone selects the account, so the username is *derived from the
# response* rather than asked for during setup.
API_BASE_URL = "https://api.powerpool.io"
API_USER = "/api/user"

# Query-string parameter carrying the credential. Note this is the *API's*
# spelling; the key under which it is stored in ConfigEntry.data is Home
# Assistant's CONF_API_KEY ("api_key"), which is what diagnostics redacts on.
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

# --- limits on untrusted payload data ------------------------------------------
# Everything below `/api/user` is attacker-controlled if the pool is compromised
# or intercepted. Each worker becomes a Home Assistant device carrying eight
# entities, and the device and entity registries are held in memory and rewritten
# to .storage on every change — so an unbounded worker list is a durable,
# restart-surviving denial of service, not just a slow poll. These caps are far
# above any real mining operation.
MAX_WORKERS_PER_ALGORITHM = 250
# Also capped across the whole entry: the per-algorithm limit alone would still
# allow MAX_ALGORITHMS by MAX_WORKERS_PER_ALGORITHM devices, and Home Assistant
# enforces no device limit of its own — only a 10,000 cap on *entities*, which
# devices created during setup bypass entirely.
MAX_WORKERS_PER_ENTRY = 500
MAX_ALGORITHMS = 32
MAX_PAYMENTS = 500
# Distinct payout coins. Each becomes four sensors on the account device, and
# the set is drawn from payment tickers as well as balances.
MAX_COINS = 32
# Names reach device names, entity ids and log lines.
MAX_NAME_LENGTH = 64

# Ceiling on any counter or amount taken from the API. Real accounts report
# share counts in the millions, so this leaves ample headroom while guaranteeing
# two things: summing the per-entry maximum of them cannot overflow to infinity
# (a non-finite sensor state is rejected by Home Assistant, which leaves the
# entity frozen at its last value rather than unavailable — a sensor that lies
# quietly), and a pool alternating an enormous value with zero cannot be read as
# a meter reset, which would inflate long-term statistics irreversibly.
MAX_COUNTER_VALUE = 1e15

# Ceiling on a single API response. A real payload is a few KB; without a cap a
# compressed reply can inflate to hundreds of MB in memory before it is parsed
# (aiohttp decompresses transparently and applies no ratio limit), which will
# OOM a small Home Assistant host.
MAX_RESPONSE_BYTES = 2_000_000

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
