"""The PowerPool mining pool integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import CONF_API_KEY, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PowerPoolClient
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, PLATFORMS
from .coordinator import PowerPoolConfigEntry, PowerPoolCoordinator


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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload (rebuilding the coordinator on the new interval) when options change.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PowerPoolConfigEntry) -> bool:
    """Unload a config entry (tear down its platforms and coordinator)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: PowerPoolConfigEntry) -> None:
    """Reload the entry when its options change (e.g. a new poll interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
