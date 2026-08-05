"""Diagnostics for the PowerPool integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .coordinator import PowerPoolConfigEntry

# The API key is the credential. Usernames, payout addresses and transaction
# ids identify the account on-chain, so they are redacted too — a diagnostics
# download is routinely pasted into a public issue.
# Worker names are user-chosen and often name a site or room.
TO_REDACT = {CONF_API_KEY, "username", "txid", "address", "name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PowerPoolConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    account = coordinator.data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
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
