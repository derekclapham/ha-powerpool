"""The PowerPool mining pool integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import CONF_API_KEY, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PowerPoolClient
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, PLATFORMS
from .coordinator import PowerPoolConfigEntry, PowerPoolCoordinator
from .entity import account_device_info, algorithm_device_info, worker_device_info
from .models import Account


async def async_setup_entry(hass: HomeAssistant, entry: PowerPoolConfigEntry) -> bool:
    """Set up one PowerPool account from a config entry."""
    interval = timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    )

    # Reuse HA's shared aiohttp session rather than owning a connection.
    client = PowerPoolClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])
    coordinator = PowerPoolCoordinator(
        hass, entry, client, entry.data[CONF_USERNAME], interval
    )

    # First refresh before creating entities so they start with real values; if
    # the API is unreachable this raises ConfigEntryNotReady and HA retries, and
    # a rejected key raises ConfigEntryAuthFailed to start the reauth flow.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _register_devices(hass, entry, coordinator.data, entry.data[CONF_USERNAME])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload (rebuilding the coordinator on the new interval) when options change.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


@callback
def _register_devices(
    hass: HomeAssistant,
    entry: PowerPoolConfigEntry,
    account: Account,
    username: str,
) -> None:
    """Create the account/algorithm/worker devices, parents first.

    The platforms would otherwise each create their own devices in whatever
    order they happen to load, and a worker referencing its algorithm through
    `via_device` before that algorithm device exists is an error Home Assistant
    now warns about and intends to stop accepting. Registering the tree here,
    top down, means every parent is present before anything points at it.
    """
    registry = dr.async_get(hass)
    registry.async_get_or_create(
        config_entry_id=entry.entry_id, **account_device_info(username)
    )
    for algorithm_key, algorithm in account.active_algorithms.items():
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **algorithm_device_info(username, algorithm_key),
        )
        for worker_name in algorithm.workers:
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                **worker_device_info(username, algorithm_key, worker_name),
            )


async def async_unload_entry(hass: HomeAssistant, entry: PowerPoolConfigEntry) -> bool:
    """Unload a config entry (tear down its platforms and coordinator)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: PowerPoolConfigEntry) -> None:
    """Reload the entry when its options change (e.g. a new poll interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
