"""The PowerPool mining pool integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import CONF_API_KEY, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PowerPoolClient
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
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

    _register_devices(hass, entry, coordinator.data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Reload (rebuilding the coordinator on the new interval) when options change.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


def _live_identifiers(account: Account) -> set[tuple[str, str]]:
    """Device identifiers the account's current payload still describes."""
    username = account.username
    identifiers = {(DOMAIN, username)}
    for algorithm_key, algorithm in account.active_algorithms.items():
        identifiers.add((DOMAIN, f"{username}:{algorithm_key}"))
        identifiers.update(
            (DOMAIN, f"{username}:{algorithm_key}:{worker_name}")
            for worker_name in algorithm.workers
        )
    return identifiers


@callback
def _register_devices(
    hass: HomeAssistant, entry: PowerPoolConfigEntry, account: Account
) -> None:
    """Create the account/algorithm/worker devices, parents first.

    The platforms would otherwise each create their own devices in whatever
    order they happen to load, and a worker referencing its algorithm through
    `via_device` before that algorithm device exists is an error Home Assistant
    now warns about and intends to stop accepting. Registering the tree here,
    top down, means every parent is present before anything points at it.
    """
    registry = dr.async_get(hass)
    username = account.username
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


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: PowerPoolConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a device the account no longer reports.

    Rigs get sold, renamed or retired, and entities are only ever marked
    unavailable rather than removed so their history survives. Without this
    hook the delete button on a stale worker's device page stays greyed out and
    the device lingers for good. Anything the current payload still describes
    is refused, so a rig that is merely powered off cannot be deleted by
    accident.
    """
    # runtime_data is only set once the first refresh succeeds, and is cleared
    # on unload. Home Assistant offers the delete button without checking that
    # the entry is loaded, so a disabled entry — or one stuck retrying setup
    # because the pool is unreachable — would otherwise raise here and leave
    # the device permanently undeletable.
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None or coordinator.data is None:
        return True
    return not device.identifiers & _live_identifiers(coordinator.data)


async def async_unload_entry(hass: HomeAssistant, entry: PowerPoolConfigEntry) -> bool:
    """Unload a config entry (tear down its platforms and coordinator)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: PowerPoolConfigEntry) -> None:
    """Reload the entry when its options change (e.g. a new poll interval)."""
    await hass.config_entries.async_reload(entry.entry_id)
