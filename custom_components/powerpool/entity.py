"""Shared entity base classes and the device hierarchy.

Three device tiers per config entry, so entity names stay short and every
translation key can be static:

    PowerPool <username>                     account — balances, payouts
      └─ PowerPool <username> <algorithm>    per-algorithm totals
           └─ PowerPool <username> <worker>  one physical rig

The username appears at every tier because worker and algorithm names are only
unique *within* an account, and this integration is built to run several.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PowerPoolCoordinator
from .models import Account, Algorithm, Worker, algorithm_label

# The pool dashboard, linked from every device page.
CONFIGURATION_URL = "https://powerpool.io/dashboard"


def account_device_info(username: str) -> DeviceInfo:
    """Device describing the account itself — the root of the tree."""
    return DeviceInfo(
        identifiers={(DOMAIN, username)},
        manufacturer="PowerPool",
        model="Mining account",
        name=f"PowerPool {username}",
        configuration_url=CONFIGURATION_URL,
    )


def algorithm_device_info(username: str, algorithm: str) -> DeviceInfo:
    """Device for one algorithm, nested under the account."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{username}:{algorithm}")},
        manufacturer="PowerPool",
        model="Mining algorithm",
        name=f"PowerPool {username} {algorithm_label(algorithm)}",
        via_device=(DOMAIN, username),
        configuration_url=CONFIGURATION_URL,
    )


def worker_device_info(username: str, algorithm: str, worker: str) -> DeviceInfo:
    """Device for one rig, nested under its algorithm."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{username}:{algorithm}:{worker}")},
        manufacturer="PowerPool",
        model="Mining worker",
        name=f"PowerPool {username} {worker}",
        via_device=(DOMAIN, f"{username}:{algorithm}"),
        configuration_url=CONFIGURATION_URL,
    )


class PowerPoolEntity(CoordinatorEntity[PowerPoolCoordinator]):
    """Common plumbing for every PowerPool entity."""

    _attr_has_entity_name = True

    @property
    def account(self) -> Account:
        """The freshly parsed account payload."""
        return self.coordinator.data


class PowerPoolAccountEntity(PowerPoolEntity):
    """An entity describing the account as a whole."""

    def __init__(self, coordinator: PowerPoolCoordinator, key: str) -> None:
        """Attach to the account device."""
        super().__init__(coordinator)
        username = coordinator.username
        self._attr_unique_id = f"{username}:{key}"
        self._attr_device_info = account_device_info(username)


class PowerPoolAlgorithmEntity(PowerPoolEntity):
    """An entity describing the account's position on one algorithm."""

    def __init__(
        self, coordinator: PowerPoolCoordinator, algorithm: str, key: str
    ) -> None:
        """Attach to the algorithm device, nested under the account."""
        super().__init__(coordinator)
        username = coordinator.username
        self._algorithm = algorithm
        self._attr_unique_id = f"{username}:{algorithm}:{key}"
        self._attr_device_info = algorithm_device_info(username, algorithm)

    @property
    def algorithm(self) -> Algorithm | None:
        """This entity's algorithm, or None if it dropped out of the payload."""
        return self.account.algorithms.get(self._algorithm)

    @property
    def available(self) -> bool:
        """Unavailable when the algorithm stops being reported."""
        return super().available and self.algorithm is not None


class PowerPoolWorkerEntity(PowerPoolEntity):
    """An entity describing one physical rig."""

    def __init__(
        self,
        coordinator: PowerPoolCoordinator,
        algorithm: str,
        worker: str,
        key: str,
    ) -> None:
        """Attach to the worker device, nested under its algorithm."""
        super().__init__(coordinator)
        username = coordinator.username
        self._algorithm = algorithm
        self._worker = worker
        self._attr_unique_id = f"{username}:{algorithm}:{worker}:{key}"
        self._attr_device_info = worker_device_info(username, algorithm, worker)

    @property
    def worker(self) -> Worker | None:
        """This entity's rig, or None while the pool isn't reporting it."""
        algorithm = self.account.algorithms.get(self._algorithm)
        return algorithm.workers.get(self._worker) if algorithm else None

    @property
    def available(self) -> bool:
        """Unavailable — not removed — when the rig stops reporting.

        A rig that is unplugged or rebooting disappears from the payload
        entirely. Going unavailable keeps its history intact for when it
        comes back.
        """
        return super().available and self.worker is not None
