"""Diagnostics for the PowerPool integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import PowerPoolConfigEntry

# A diagnostics download is routinely pasted into a public issue, so this has to
# assume an untrusted reader.
#
# The API key is the credential. Usernames, payout addresses and transaction ids
# name the account on-chain directly. An exact payout *amount* does the same job
# indirectly: a public block explorer can be searched for a transaction of that
# value, which leads back to the wallet — so amounts are redacted alongside the
# identifiers they would otherwise reveal. Timestamps, tickers and counts stay,
# because they are what makes a diagnostics download useful for debugging and
# are far weaker on their own.
#
# Worker names are user-chosen and often name a site or a room.
# "txID" is redacted as well as "txid" because the API has been seen using both.
TO_REDACT = {
    CONF_API_KEY,
    "username",
    "txid",
    "txID",
    "address",
    "name",
    "value",
    "balances",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PowerPoolConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    account = coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            # Redacted too, so that adding an option later can't quietly start
            # publishing it.
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "account": async_redact_data(
            {
                "username": account.username,
                "algorithms": {
                    key: {
                        "hashrate": algorithm.hashrate,
                        "hashrate_avg": algorithm.hashrate_avg,
                        "revenue_24h_usd": algorithm.revenue_24h_usd,
                        "unit": algorithm.unit,
                        "workers_online": algorithm.workers_online,
                        "worker_count": len(algorithm.workers),
                        "workers": [
                            asdict(worker) for worker in algorithm.workers.values()
                        ],
                    }
                    for key, algorithm in account.algorithms.items()
                },
                "balances": account.balances,
                "payment_count": len(account.payments),
                "last_payment": (
                    asdict(account.last_payment) if account.last_payment else None
                ),
            },
            TO_REDACT,
        ),
    }
