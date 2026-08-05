"""Sensor platform for the PowerPool integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import COIN_PRECISION, DEFAULT_COIN_PRECISION
from .coordinator import PowerPoolConfigEntry, PowerPoolCoordinator
from .entity import (
    PowerPoolAccountEntity,
    PowerPoolAlgorithmEntity,
    PowerPoolWorkerEntity,
)
from .models import Account, Algorithm, Payment, Worker, from_base_rate, hashrate_unit

# Read-only sensors backed by one coordinator; nothing to serialise on update.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class CoinSensorDescription(SensorEntityDescription):
    """A sensor reading one coin's position on the account."""

    value_fn: Callable[[Account, str], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class AlgorithmSensorDescription(SensorEntityDescription):
    """A sensor reading the account's aggregate on one algorithm."""

    value_fn: Callable[[Algorithm], StateType]
    # Rate sensors carry a value in base units/s; the entity renders it in the
    # algorithm's fixed display unit (see const.ALGORITHM_UNITS).
    is_rate: bool = False


@dataclass(frozen=True, kw_only=True)
class WorkerSensorDescription(SensorEntityDescription):
    """A sensor reading one rig."""

    value_fn: Callable[[Worker], StateType]
    is_rate: bool = False


COIN_SENSORS: tuple[CoinSensorDescription, ...] = (
    CoinSensorDescription(
        key="balance",
        translation_key="coin_balance",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda account, ticker: account.balances.get(ticker),
    ),
    CoinSensorDescription(
        key="total_paid",
        translation_key="coin_total_paid",
        # TOTAL rather than TOTAL_INCREASING: the payments list the API returns
        # is finite, so the lifetime sum can step *down* as old payouts age out.
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda account, ticker: account.total_paid(ticker),
    ),
    CoinSensorDescription(
        key="last_payout",
        translation_key="coin_last_payout",
        value_fn=lambda account, ticker: _last_payout_value(account, ticker),
    ),
    CoinSensorDescription(
        key="last_payout_time",
        translation_key="coin_last_payout_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda account, ticker: _last_payout_time(account, ticker),
    ),
)


ALGORITHM_SENSORS: tuple[AlgorithmSensorDescription, ...] = (
    AlgorithmSensorDescription(
        key="hashrate",
        translation_key="hashrate",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        is_rate=True,
        value_fn=lambda algorithm: algorithm.hashrate,
    ),
    AlgorithmSensorDescription(
        key="hashrate_avg",
        translation_key="hashrate_avg",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        is_rate=True,
        value_fn=lambda algorithm: algorithm.hashrate_avg,
    ),
    AlgorithmSensorDescription(
        key="revenue_24h",
        translation_key="revenue_24h",
        # Deliberately not SensorDeviceClass.MONETARY: that device class only
        # accepts state_class TOTAL (an accumulating amount of money), and this
        # is a forward-looking *rate* that rises and falls. Plain USD keeps the
        # measurement semantics and still records statistics.
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda algorithm: algorithm.revenue_24h_usd,
    ),
    AlgorithmSensorDescription(
        key="workers_online",
        translation_key="workers_online",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="workers",
        value_fn=lambda algorithm: algorithm.workers_online,
    ),
    # Deliberately no state_class on the three account-wide share totals.
    # They are sums over the workers in the *current* payload, so they step
    # down whenever a rig drops out or the pool resets that rig's counter —
    # and unlike a worker sensor, this entity stays available while it happens
    # (its algorithm is still reported). A recorder reading a decrease on an
    # available TOTAL_INCREASING sensor treats it as a meter reset and adds the
    # new value on top of the running sum, so every rig reboot would inflate
    # long-term statistics permanently. The per-worker equivalents below keep
    # TOTAL_INCREASING, because there a reset is exactly what it describes and
    # a vanished rig goes unavailable rather than reading zero.
    AlgorithmSensorDescription(
        key="valid_shares",
        translation_key="valid_shares",
        native_unit_of_measurement="shares",
        value_fn=lambda algorithm: algorithm.valid_shares,
    ),
    AlgorithmSensorDescription(
        key="invalid_shares",
        translation_key="invalid_shares",
        native_unit_of_measurement="shares",
        value_fn=lambda algorithm: algorithm.invalid_shares,
    ),
    AlgorithmSensorDescription(
        key="stale_shares",
        translation_key="stale_shares",
        native_unit_of_measurement="shares",
        value_fn=lambda algorithm: algorithm.stale_shares,
    ),
    AlgorithmSensorDescription(
        key="share_efficiency",
        translation_key="share_efficiency",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2,
        value_fn=lambda algorithm: algorithm.share_efficiency,
    ),
)


WORKER_SENSORS: tuple[WorkerSensorDescription, ...] = (
    WorkerSensorDescription(
        key="hashrate",
        translation_key="hashrate",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        is_rate=True,
        value_fn=lambda worker: worker.hashrate,
    ),
    WorkerSensorDescription(
        key="hashrate_avg",
        translation_key="hashrate_avg",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        is_rate=True,
        value_fn=lambda worker: worker.hashrate_avg,
    ),
    WorkerSensorDescription(
        key="valid_shares",
        translation_key="valid_shares",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="shares",
        value_fn=lambda worker: worker.valid_shares,
    ),
    WorkerSensorDescription(
        key="invalid_shares",
        translation_key="invalid_shares",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="shares",
        value_fn=lambda worker: worker.invalid_shares,
    ),
    WorkerSensorDescription(
        key="stale_shares",
        translation_key="stale_shares",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="shares",
        value_fn=lambda worker: worker.stale_shares,
    ),
    WorkerSensorDescription(
        key="share_efficiency",
        translation_key="share_efficiency",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=2,
        value_fn=lambda worker: worker.share_efficiency,
    ),
    WorkerSensorDescription(
        key="blocks",
        translation_key="blocks",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement="blocks",
        value_fn=lambda worker: worker.blocks,
    ),
)


def _last_payout_value(account: Account, ticker: str) -> float | None:
    """Amount of the most recent payout in one coin."""
    payment = _last_payment(account, ticker)
    return payment.value if payment else None


def _last_payout_time(account: Account, ticker: str) -> datetime | None:
    """When the most recent payout in one coin landed."""
    payment = _last_payment(account, ticker)
    return payment.when if payment else None


def _last_payment(account: Account, ticker: str) -> Payment | None:
    """Most recent payment in one coin (payments are already newest-first)."""
    return next((p for p in account.payments if p.ticker == ticker), None)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PowerPoolConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors discovered on the first refresh.

    PowerPool reports every algorithm and payout coin it supports on every
    account, nearly all of them permanently zero, so the two are filtered
    differently:

    * Algorithms the account does not mine are skipped entirely — each one
      would otherwise create its own empty device.
    * Coins the account has never held live on the existing account device, so
      they are created but disabled, and can be switched on from the device
      page the moment a payout in one of them matters.

    Anything that appears later — a new rig, a first payout in a new coin —
    needs a reload of the entry to gain entities; anything that disappears goes
    unavailable rather than being removed, so history survives a reboot.
    """
    coordinator = entry.runtime_data
    account = coordinator.data
    entities: list[SensorEntity] = []

    active_coins = account.active_coins
    for ticker in account.known_coins:
        entities.extend(
            PowerPoolCoinSensor(
                coordinator, ticker, description, enabled=ticker in active_coins
            )
            for description in COIN_SENSORS
        )

    for algorithm_key, algorithm in account.active_algorithms.items():
        entities.extend(
            PowerPoolAlgorithmSensor(coordinator, algorithm_key, description)
            for description in ALGORITHM_SENSORS
        )
        entities.extend(
            PowerPoolWorkerSensor(coordinator, algorithm_key, worker_name, description)
            for worker_name in algorithm.workers
            for description in WORKER_SENSORS
        )

    async_add_entities(entities)


class PowerPoolCoinSensor(PowerPoolAccountEntity, SensorEntity):
    """A balance or payout figure for one coin."""

    entity_description: CoinSensorDescription

    def __init__(
        self,
        coordinator: PowerPoolCoordinator,
        ticker: str,
        description: CoinSensorDescription,
        *,
        enabled: bool,
    ) -> None:
        """Initialise with the coin as the entity's display unit."""
        super().__init__(coordinator, f"{ticker}:{description.key}")
        self.entity_description = description
        self._ticker = ticker
        # A coin the account has never held is registered but switched off.
        self._attr_entity_registry_enabled_default = enabled
        self._attr_translation_placeholders = {"coin": ticker}
        # Timestamps carry a device class instead of a unit.
        if description.device_class is not SensorDeviceClass.TIMESTAMP:
            self._attr_native_unit_of_measurement = ticker
            self._attr_suggested_display_precision = COIN_PRECISION.get(
                ticker, DEFAULT_COIN_PRECISION
            )

    @property
    def native_value(self) -> StateType | datetime:
        """Read the figure out of the parsed account."""
        return self.entity_description.value_fn(self.account, self._ticker)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the payout's transaction id for templating."""
        if self.entity_description.key != "last_payout":
            return None
        payment = _last_payment(self.account, self._ticker)
        return {"transaction_id": payment.txid} if payment else None


class PowerPoolAlgorithmSensor(PowerPoolAlgorithmEntity, SensorEntity):
    """An account-wide figure for one mining algorithm."""

    entity_description: AlgorithmSensorDescription

    def __init__(
        self,
        coordinator: PowerPoolCoordinator,
        algorithm: str,
        description: AlgorithmSensorDescription,
    ) -> None:
        """Initialise, fixing the display unit for rate sensors."""
        super().__init__(coordinator, algorithm, description.key)
        self.entity_description = description
        if description.is_rate:
            self._attr_native_unit_of_measurement = hashrate_unit(algorithm)

    @property
    def native_value(self) -> StateType:
        """Read the figure, converting rates into the fixed display unit."""
        algorithm = self.algorithm
        if algorithm is None:
            return None
        value = self.entity_description.value_fn(algorithm)
        if self.entity_description.is_rate:
            return from_base_rate(value, hashrate_unit(self._algorithm))
        return value


class PowerPoolWorkerSensor(PowerPoolWorkerEntity, SensorEntity):
    """A figure for one physical rig."""

    entity_description: WorkerSensorDescription

    def __init__(
        self,
        coordinator: PowerPoolCoordinator,
        algorithm: str,
        worker: str,
        description: WorkerSensorDescription,
    ) -> None:
        """Initialise, fixing the display unit for rate sensors."""
        super().__init__(coordinator, algorithm, worker, description.key)
        self.entity_description = description
        if description.is_rate:
            self._attr_native_unit_of_measurement = hashrate_unit(algorithm)

    @property
    def native_value(self) -> StateType:
        """Read the figure, converting rates into the fixed display unit."""
        worker = self.worker
        if worker is None:
            return None
        value = self.entity_description.value_fn(worker)
        if self.entity_description.is_rate:
            return from_base_rate(value, hashrate_unit(self._algorithm))
        return value
