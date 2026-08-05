"""Binary sensor platform for the PowerPool integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import PowerPoolConfigEntry, PowerPoolCoordinator
from .entity import PowerPoolAccountEntity, PowerPoolWorkerEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the mining-state binary sensors."""
    coordinator = entry.runtime_data
    account = coordinator.data

    entities: list[BinarySensorEntity] = [PowerPoolMiningSensor(coordinator)]
    entities.extend(
        PowerPoolWorkerOnlineSensor(coordinator, algorithm_key, worker_name)
        for algorithm_key, algorithm in account.active_algorithms.items()
        for worker_name in algorithm.workers
    )
    async_add_entities(entities)


class PowerPoolMiningSensor(PowerPoolAccountEntity, BinarySensorEntity):
    """On while any rig on the account is hashing."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "mining"

    def __init__(self, coordinator: PowerPoolCoordinator) -> None:
        """Initialise against the account device."""
        super().__init__(coordinator, "mining")

    @property
    def is_on(self) -> bool:
        """True when at least one worker reports a hashrate."""
        return self.account.is_mining


class PowerPoolWorkerOnlineSensor(PowerPoolWorkerEntity, BinarySensorEntity):
    """On while this rig is submitting work.

    A rig the pool has stopped reporting goes *unavailable* rather than off —
    see PowerPoolWorkerEntity.available. Off means the rig is still known to
    the pool but its hashrate has fallen to zero.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "worker_online"

    def __init__(
        self, coordinator: PowerPoolCoordinator, algorithm: str, worker: str
    ) -> None:
        """Initialise against the worker device."""
        super().__init__(coordinator, algorithm, worker, "online")

    @property
    def is_on(self) -> bool:
        """True when the rig reports a non-zero hashrate."""
        worker = self.worker
        return bool(worker and worker.is_online)
