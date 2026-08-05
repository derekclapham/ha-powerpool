"""Parsing of raw PowerPool payloads into typed, unit-stable structures.

Everything the sensors read comes out of here, so the defensive handling lives
in one place: a partial or reshaped payload yields None fields rather than
raising, and hashrates are normalised to base units on ingest (see const.py for
why a per-poll unit would break long-term statistics).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Any
import unicodedata

from homeassistant.util import dt as dt_util

from .const import (
    ALGORITHM_NAMES,
    ALGORITHM_UNITS,
    DEFAULT_HASHRATE_UNIT,
    MAX_ALGORITHMS,
    MAX_COINS,
    MAX_COUNTER_VALUE,
    MAX_NAME_LENGTH,
    MAX_PAYMENTS,
    MAX_WORKERS_PER_ALGORITHM,
    MAX_WORKERS_PER_ENTRY,
    RATE_BASES,
    SI_PREFIXES,
)

# A trailing coin qualifier, as in "Equihash (Zcash)". Stripped before
# normalising so the name still resolves to the "equihash" unit — folding it in
# would yield "equihashzcash", miss ALGORITHM_UNITS and fall back to a
# hashes-per-second unit for an algorithm measured in solutions per second.
_ALGORITHM_QUALIFIER = re.compile(r"\([^)]*\)")


def normalise_algorithm(key: str) -> str:
    """Reduce an algorithm name to a stable lookup key.

    The API is consistent today ("sha256", "kheavyhash"), but the same
    algorithms appear elsewhere as "SHA-256" and "Equihash (Zcash)", so
    qualifiers and punctuation are dropped rather than trusted.
    """
    return "".join(
        c for c in _ALGORITHM_QUALIFIER.sub("", key).lower() if c.isalnum()
    )


def algorithm_label(key: str) -> str:
    """Human name for an algorithm, falling back to the raw API key."""
    return ALGORITHM_NAMES.get(key, key.upper() if key.isalnum() else key)


def hashrate_unit(algorithm: str) -> str:
    """Fixed display unit for an algorithm's hashrate sensors."""
    return ALGORITHM_UNITS.get(algorithm, DEFAULT_HASHRATE_UNIT)


def _split_unit(unit: str) -> tuple[float, str] | None:
    """Split a rate unit like "MSol/s" into (multiplier, base).

    Returns None for anything unrecognised, which the callers turn into a None
    reading rather than a wrong number.
    """
    cleaned = unit.strip().removesuffix("/s").strip().upper()
    for base in RATE_BASES:
        if cleaned.endswith(base):
            prefix = cleaned[: len(cleaned) - len(base)]
            multiplier = SI_PREFIXES.get(prefix)
            if multiplier is not None:
                return multiplier, base
    return None


def to_base_rate(value: Any, unit: Any) -> float | None:
    """Convert a reported (value, unit) pair to base units per second.

    Base units are hashes/s, or solutions/s for Equihash. Both are kept in the
    same field because an account only ever mixes them across algorithms, never
    within one sensor.
    """
    number = _num(value)
    if number is None or not isinstance(unit, str):
        return None
    split = _split_unit(unit)
    if split is None:
        return None
    scaled = number * split[0]
    # The multiply itself can overflow to inf from a merely large input.
    return scaled if math.isfinite(scaled) else None


def from_base_rate(base_value: float | None, unit: str) -> float | None:
    """Render a base-unit rate in `unit`, rounded for display."""
    if base_value is None:
        return None
    split = _split_unit(unit)
    if split is None:
        return None
    return round(base_value / split[0], 4)


def _num(value: Any) -> float | None:
    """Coerce to a finite float, or None if that isn't possible.

    Two hostile inputs get past a naive `float()`: `json.loads` accepts the
    bare literals `Infinity` and `NaN`, and a long enough integer literal
    raises OverflowError rather than ValueError. Either would escape this
    module's defensive parsing and fail every poll with a traceback, so both
    are rejected here rather than at each call site. Non-finite values are
    dropped too — `inf` would otherwise reach a sensor state and poison
    long-term statistics.
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _counter(value: Any) -> float | None:
    """Read a counter or amount, clamped to a plausible ceiling.

    Clamping on the way in is what keeps every derived figure finite: these
    values are summed across an account's rigs and payouts, and a sum that
    reaches infinity is rejected by Home Assistant's sensor platform, which
    leaves the entity showing its last good reading instead of going
    unavailable. It also denies a lying pool the oscillation — an enormous
    value, then zero — that the recorder would read as a meter reset and add
    to the running total on every poll.
    """
    number = _num(value)
    if number is None:
        return None
    return max(-MAX_COUNTER_VALUE, min(number, MAX_COUNTER_VALUE))


def sanitise_name(value: Any) -> str | None:
    """Make an API-supplied name safe to use as an identifier and a label.

    A worker name becomes a Home Assistant device name, part of an entity's
    unique id, and text in log lines, so it is the main place hostile strings
    reach the rest of the system. Three things are removed:

    * Unicode control, format and surrogate characters — these carry ANSI
      escapes that rewrite an operator's terminal when a log line is tailed,
      newlines that forge extra log entries, and bidi overrides that make a
      name render as something other than what it is.
    * Colons, because unique ids and device identifiers are colon-delimited;
      a name may not introduce a delimiter and collide with another tier.
    * Excess length, which would otherwise bloat both registries.

    Returns None when nothing usable survives, which drops the entry.
    """
    if not isinstance(value, str):
        return None
    cleaned = "".join(
        c
        for c in value
        if c != ":" and unicodedata.category(c) not in {"Cc", "Cf", "Co", "Cs"}
    ).strip()
    return cleaned[:MAX_NAME_LENGTH] or None


def _timestamp(value: Any) -> datetime | None:
    """Convert an epoch value to a tz-aware datetime.

    PowerPool's payment timestamps are seconds, but the field is a float and
    other pools ship milliseconds, so anything implausibly large is rescaled
    rather than landing the sensor in the year 55000.
    """
    epoch = _num(value)
    if epoch is None or epoch <= 0:
        return None
    if epoch > 1e11:  # milliseconds
        epoch /= 1000
    # Anything still beyond the year 2100 is not a payout date; showing it
    # would just put a nonsense timestamp on a device-class TIMESTAMP sensor.
    if epoch > 4_102_444_800:
        return None
    try:
        return dt_util.utc_from_timestamp(epoch)
    except (OverflowError, OSError, ValueError):
        return None


@dataclass
class Worker:
    """One mining rig reporting to the account under a given algorithm."""

    name: str
    hashrate: float | None  # base units/s
    hashrate_avg: float | None  # base units/s
    valid_shares: float | None
    invalid_shares: float | None
    stale_shares: float | None
    blocks: int | None

    @property
    def is_online(self) -> bool:
        """True when the rig is currently submitting work."""
        return bool(self.hashrate)

    @property
    def share_efficiency(self) -> float | None:
        """Accepted shares as a percentage of all shares submitted."""
        return _efficiency(self.valid_shares, self.invalid_shares, self.stale_shares)

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Worker | None:
        """Build a Worker, or None when the entry carries no usable name."""
        name = sanitise_name(raw.get("name"))
        if name is None:
            return None
        blocks = _counter(raw.get("blocks"))
        return cls(
            name=name,
            hashrate=to_base_rate(raw.get("hashrate"), raw.get("hashrate_units")),
            hashrate_avg=to_base_rate(
                raw.get("hashrate_avg"), raw.get("hashrate_avg_units")
            ),
            valid_shares=_counter(raw.get("valid_shares")),
            invalid_shares=_counter(raw.get("invalid_shares")),
            # Undocumented, but present on every worker the API returns.
            stale_shares=_counter(raw.get("stale_shares")),
            blocks=int(blocks) if blocks is not None else None,
        )


@dataclass
class Algorithm:
    """The account's aggregate position on one mining algorithm."""

    key: str
    hashrate: float | None  # base units/s
    hashrate_avg: float | None  # base units/s
    revenue_24h_usd: float | None
    workers: dict[str, Worker] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Human name, e.g. "SHA-256"."""
        return algorithm_label(self.key)

    @property
    def unit(self) -> str:
        """Fixed display unit for this algorithm's hashrate sensors."""
        return hashrate_unit(self.key)

    @property
    def workers_online(self) -> int:
        """How many rigs are currently hashing."""
        return sum(1 for worker in self.workers.values() if worker.is_online)

    @property
    def valid_shares(self) -> float | None:
        """Accepted shares summed across the account's rigs."""
        return _sum_or_none(w.valid_shares for w in self.workers.values())

    @property
    def invalid_shares(self) -> float | None:
        """Rejected shares summed across the account's rigs."""
        return _sum_or_none(w.invalid_shares for w in self.workers.values())

    @property
    def stale_shares(self) -> float | None:
        """Stale shares summed across the account's rigs."""
        return _sum_or_none(w.stale_shares for w in self.workers.values())

    @property
    def share_efficiency(self) -> float | None:
        """Accepted shares as a percentage of all shares submitted."""
        return _efficiency(self.valid_shares, self.invalid_shares, self.stale_shares)

    @property
    def is_active(self) -> bool:
        """True when the account shows any sign of mining this algorithm.

        PowerPool returns every algorithm it supports on every account, almost
        all of them all-zero, so this is what keeps eight dead device trees out
        of Home Assistant. Having a worker counts even at zero hashrate: a rig
        that is powered off is still one the user owns.
        """
        return bool(
            self.workers
            or self.hashrate
            or self.hashrate_avg
            or self.revenue_24h_usd
        )


@dataclass
class Payment:
    """A single payout the pool has sent."""

    ticker: str
    value: float
    txid: str | None
    when: datetime | None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Payment | None:
        """Build a Payment, or None when the amount or coin is unusable."""
        value = _counter(raw.get("value"))
        # The ticker becomes part of an entity's unique id and its name, so it
        # goes through the same sanitiser as a worker name.
        ticker = sanitise_name(raw.get("ticker"))
        if value is None or ticker is None:
            return None
        # The published docs say "txID"; the API actually sends "txid". Accept
        # both so this keeps working whichever way PowerPool settles.
        txid = sanitise_name(raw.get("txid") or raw.get("txID"))
        return cls(
            ticker=ticker.upper(),
            value=value,
            txid=txid,
            when=_timestamp(raw.get("timestamp")),
        )


@dataclass
class Account:
    """One PowerPool account: the whole parsed payload for a config entry."""

    username: str
    algorithms: dict[str, Algorithm] = field(default_factory=dict)
    balances: dict[str, float] = field(default_factory=dict)
    payments: list[Payment] = field(default_factory=list)

    @property
    def last_payment(self) -> Payment | None:
        """Most recent payout, or None if the account has never been paid."""
        return self.payments[0] if self.payments else None

    def total_paid(self, ticker: str) -> float | None:
        """Lifetime payout total for one coin, as far back as the API reports."""
        return _sum_or_none(p.value for p in self.payments if p.ticker == ticker)

    @property
    def is_mining(self) -> bool:
        """True when any rig on any algorithm is currently hashing."""
        return any(algo.workers_online for algo in self.algorithms.values())

    @property
    def active_algorithms(self) -> dict[str, Algorithm]:
        """Only the algorithms this account actually mines."""
        return {k: v for k, v in self.algorithms.items() if v.is_active}

    @property
    def known_coins(self) -> list[str]:
        """Every payout coin worth an entity, bounded.

        Drawn from balances *and* payment tickers, because a coin can have been
        paid out and since fallen to a zero balance. Capped because payments are
        attacker-controlled and each distinct ticker costs four more sensors on
        the account device; active coins are kept in preference to dormant ones
        so a flood of invented tickers cannot crowd out a real balance.
        """
        active = self.active_coins
        dormant = sorted(set(self.balances) - active)
        return sorted(active)[:MAX_COINS] + dormant[: max(0, MAX_COINS - len(active))]

    @property
    def active_coins(self) -> set[str]:
        """Coins the account holds a balance in or has ever been paid in.

        PowerPool lists every payout coin it supports with a zero balance, so
        without this every account would get four sensors for each of ten coins.
        """
        return {ticker for ticker, amount in self.balances.items() if amount} | {
            payment.ticker for payment in self.payments
        }


def _sum_or_none(values: Any) -> float | None:
    """Sum an iterable, returning None when it holds no usable numbers.

    The finite check is not redundant with the clamp applied on ingest: it is
    the guarantee that holds even if a future caller feeds this unclamped
    values. A non-finite state is refused by Home Assistant's sensor platform,
    which leaves the entity frozen at its previous reading rather than
    unavailable — so it must never get that far.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None
    total = sum(present)
    return total if math.isfinite(total) else None


def _efficiency(
    valid: float | None, invalid: float | None, stale: float | None = None
) -> float | None:
    """Accepted shares as a percentage of every share submitted.

    Stale shares — submitted, but too late to count — sit in the denominator
    alongside rejects, so this reads as "how much of the work sent actually
    earned anything".
    """
    if valid is None:
        return None
    total = valid + (invalid or 0) + (stale or 0)
    if total <= 0 or not math.isfinite(total):
        return None
    result = valid / total * 100
    return round(result, 2) if math.isfinite(result) else None


def parse_account(payload: dict[str, Any], username: str) -> Account:
    """Turn the raw `/api/user` payload into an Account.

    `payload` is the whole response (keyed by username); `username` selects the
    account this config entry tracks. A username the response no longer carries
    yields an empty Account rather than an error, so a transient partial payload
    marks entities unavailable instead of failing the entry.
    """
    body = payload.get(username)
    if not isinstance(body, dict):
        return Account(username=username)

    # Every list and map below is attacker-controlled if the pool is
    # compromised, and each entry costs a Home Assistant device or entity that
    # persists in .storage across restarts. Truncating on ingest is what stops
    # one hostile response from permanently bloating the registries.
    raw_hashrates = body.get("hashrate")
    raw_hashrates = raw_hashrates if isinstance(raw_hashrates, dict) else {}
    raw_workers = body.get("workers")
    raw_workers = raw_workers if isinstance(raw_workers, dict) else {}

    # The cap is applied once to the union of both maps, not separately to each:
    # truncating them independently would let a payload naming different
    # algorithms in each map carry twice the intended number through. Worker
    # keys are ordered first so that an algorithm which appears only in the
    # workers map — a rig connected but not yet credited with hashrate — is
    # never starved of a slot by hashrate-only entries.
    allowed = set(
        list(dict.fromkeys([*raw_workers, *raw_hashrates]))[:MAX_ALGORITHMS]
    )

    algorithms: dict[str, Algorithm] = {}
    if raw_hashrates:
        for raw_key, raw_value in raw_hashrates.items():
            if raw_key not in allowed or not isinstance(raw_value, dict):
                continue
            key = normalise_algorithm(str(raw_key))
            algorithms[key] = Algorithm(
                key=key,
                hashrate=to_base_rate(
                    raw_value.get("hashrate"), raw_value.get("hashrate_units")
                ),
                hashrate_avg=to_base_rate(
                    raw_value.get("hashrate_avg"), raw_value.get("hashrate_avg_units")
                ),
                revenue_24h_usd=_num(raw_value.get("estimated_24h_usd_revenue")),
            )

    # Workers are reported in their own map, also keyed by algorithm. An
    # algorithm can appear here without appearing above (a rig connected but
    # not yet credited with hashrate), so missing entries are created.
    if raw_workers:
        budget = MAX_WORKERS_PER_ENTRY
        for raw_key, entries in raw_workers.items():
            if raw_key not in allowed or not isinstance(entries, list):
                continue
            key = normalise_algorithm(str(raw_key))
            algorithm = algorithms.get(key)
            if algorithm is None:
                algorithm = Algorithm(
                    key=key, hashrate=None, hashrate_avg=None, revenue_24h_usd=None
                )
                algorithms[key] = algorithm
            # Bounded per algorithm *and* across the entry, because the
            # per-algorithm limit alone still multiplies by the algorithm cap.
            for entry in entries[: min(MAX_WORKERS_PER_ALGORITHM, budget)]:
                if not isinstance(entry, dict):
                    continue
                if (worker := Worker.parse(entry)) is not None:
                    algorithm.workers[worker.name] = worker
            budget = MAX_WORKERS_PER_ENTRY - sum(
                len(a.workers) for a in algorithms.values()
            )
            if budget <= 0:
                break

    balances: dict[str, float] = {}
    raw_balances = body.get("balances")
    if isinstance(raw_balances, list):
        for entry in raw_balances[:MAX_COINS]:
            if not isinstance(entry, dict):
                continue
            ticker = sanitise_name(entry.get("coinTicker"))
            amount = _num(entry.get("balance"))
            if ticker and amount is not None:
                balances[ticker.upper()] = amount

    payments: list[Payment] = []
    raw_payments = body.get("payments")
    if isinstance(raw_payments, list):
        for entry in raw_payments[:MAX_PAYMENTS]:
            if isinstance(entry, dict) and (payment := Payment.parse(entry)):
                payments.append(payment)
    # Newest first, so `last_payment` is payments[0]. Undated payouts sort last
    # rather than poisoning the comparison.
    payments.sort(key=lambda p: p.when or dt_util.utc_from_timestamp(0), reverse=True)

    return Account(
        username=username,
        algorithms=algorithms,
        balances=balances,
        payments=payments,
    )


def usernames_in(payload: dict[str, Any]) -> list[str]:
    """Account usernames present in a `/api/user` response.

    The API key alone selects the account, so this is how setup discovers the
    username instead of asking the user to type it.

    Names that don't survive sanitising are dropped rather than offered. A
    username is the root of every device identifier and unique id in the entry,
    so one containing the `:` delimiter could be chosen to collide with another
    account's algorithm tier — `alice` plus `alice:sha256` would have the second
    account's device identifier equal the first account's SHA-256 device.
    """
    return sorted(
        k
        for k, v in payload.items()
        if isinstance(v, dict) and sanitise_name(k) == k
    )
