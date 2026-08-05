"""Parsing of raw PowerPool payloads into typed, unit-stable structures.

Everything the sensors read comes out of here, so the defensive handling lives
in one place: a partial or reshaped payload yields None fields rather than
raising, and hashrates are normalised to base units on ingest (see const.py for
why a per-poll unit would break long-term statistics).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    ALGORITHM_NAMES,
    ALGORITHM_UNITS,
    DEFAULT_HASHRATE_UNIT,
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
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(unit, str):
        return None
    split = _split_unit(unit)
    if split is None:
        return None
    return number * split[0]


def from_base_rate(base_value: float | None, unit: str) -> float | None:
    """Render a base-unit rate in `unit`, rounded for display."""
    if base_value is None:
        return None
    split = _split_unit(unit)
    if split is None:
        return None
    return round(base_value / split[0], 4)


def _num(value: Any) -> float | None:
    """Coerce to float, or None if absent/unparsable."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            return None
        blocks = _num(raw.get("blocks"))
        return cls(
            name=name.strip(),
            hashrate=to_base_rate(raw.get("hashrate"), raw.get("hashrate_units")),
            hashrate_avg=to_base_rate(
                raw.get("hashrate_avg"), raw.get("hashrate_avg_units")
            ),
            valid_shares=_num(raw.get("valid_shares")),
            invalid_shares=_num(raw.get("invalid_shares")),
            # Undocumented, but present on every worker the API returns.
            stale_shares=_num(raw.get("stale_shares")),
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
        value = _num(raw.get("value"))
        ticker = raw.get("ticker")
        if value is None or not isinstance(ticker, str) or not ticker:
            return None
        # The published docs say "txID"; the API actually sends "txid". Accept
        # both so this keeps working whichever way PowerPool settles.
        txid = raw.get("txid") or raw.get("txID")
        return cls(
            ticker=ticker.upper(),
            value=value,
            txid=txid if isinstance(txid, str) and txid else None,
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

    def total_paid(self, ticker: str) -> float:
        """Lifetime payout total for one coin, as far back as the API reports."""
        return sum(p.value for p in self.payments if p.ticker == ticker)

    @property
    def is_mining(self) -> bool:
        """True when any rig on any algorithm is currently hashing."""
        return any(algo.workers_online for algo in self.algorithms.values())

    @property
    def active_algorithms(self) -> dict[str, Algorithm]:
        """Only the algorithms this account actually mines."""
        return {k: v for k, v in self.algorithms.items() if v.is_active}

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
    """Sum an iterable, returning None when it holds no numbers at all."""
    present = [v for v in values if v is not None]
    return sum(present) if present else None


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
    if total <= 0:
        return None
    return round(valid / total * 100, 2)


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

    algorithms: dict[str, Algorithm] = {}
    raw_hashrates = body.get("hashrate")
    if isinstance(raw_hashrates, dict):
        for raw_key, raw_value in raw_hashrates.items():
            if not isinstance(raw_value, dict):
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
    raw_workers = body.get("workers")
    if isinstance(raw_workers, dict):
        for raw_key, entries in raw_workers.items():
            if not isinstance(entries, list):
                continue
            key = normalise_algorithm(str(raw_key))
            algorithm = algorithms.get(key)
            if algorithm is None:
                algorithm = Algorithm(
                    key=key, hashrate=None, hashrate_avg=None, revenue_24h_usd=None
                )
                algorithms[key] = algorithm
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if (worker := Worker.parse(entry)) is not None:
                    algorithm.workers[worker.name] = worker

    balances: dict[str, float] = {}
    raw_balances = body.get("balances")
    if isinstance(raw_balances, list):
        for entry in raw_balances:
            if not isinstance(entry, dict):
                continue
            ticker = entry.get("coinTicker")
            amount = _num(entry.get("balance"))
            if isinstance(ticker, str) and ticker and amount is not None:
                balances[ticker.upper()] = amount

    payments: list[Payment] = []
    raw_payments = body.get("payments")
    if isinstance(raw_payments, list):
        for entry in raw_payments:
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
    """
    return sorted(k for k, v in payload.items() if isinstance(v, dict))
