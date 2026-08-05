"""Data update coordinator for the PowerPool integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PowerPoolApiError, PowerPoolAuthError, PowerPoolClient
from .const import DOMAIN, LOGGER
from .models import Account, parse_account


# How many consecutive empty responses to accept, once the account has polled
# successfully at least once, before concluding the API key is dead. PowerPool
# answers `200 {}` both for a rejected key and (in principle) for a blip on its
# side, and nothing in the response tells them apart. Reauth is disruptive — it
# flags the entry as broken and raises a notification — so a working account
# that goes empty is given a couple of polls to recover first.
#
# This does not apply to the very first refresh: there, an empty response is
# taken at face value, because a coordinator is rebuilt on every setup retry
# and a counter that resets each time would leave a genuinely dead key retrying
# setup forever instead of asking the user for a new one.
_AUTH_FAILURES_BEFORE_REAUTH = 3


class PowerPoolCoordinator(DataUpdateCoordinator[Account]):
    """Polls one PowerPool account and exposes it as a parsed Account.

    One coordinator per config entry, so several accounts each poll on their
    own timer without sharing state. A single endpoint backs every sensor, so
    unlike a multi-endpoint integration there is nothing to split by cadence.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: PowerPoolClient,
        username: str,
        interval: timedelta,
    ) -> None:
        """Initialise the coordinator for one account."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {username}",
            update_interval=interval,
        )
        self.client = client
        self.username = username
        self._auth_failures = 0

    async def _async_update_data(self) -> Account:
        """Poll the account endpoint and parse it."""
        try:
            payload = await self.client.user()
        except PowerPoolAuthError as err:
            self._auth_failures += 1
            # `self.data` is only set once a poll has succeeded, so None here
            # means this is the first refresh — fail straight to reauth.
            if (
                self.data is None
                or self._auth_failures >= _AUTH_FAILURES_BEFORE_REAUTH
            ):
                # Starts the reauth flow so the user can paste a new key — the
                # one on file is reset whenever they change their password.
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(
                f"{err} (attempt {self._auth_failures} of "
                f"{_AUTH_FAILURES_BEFORE_REAUTH} before reauthenticating)"
            ) from err
        except PowerPoolApiError as err:
            # UpdateFailed flips the entities to unavailable and schedules a
            # retry, rather than logging a traceback.
            raise UpdateFailed(str(err)) from err

        self._auth_failures = 0
        return parse_account(payload, self.username)


# Typed config entry alias — lets `entry.runtime_data` be known as the coordinator.
type PowerPoolConfigEntry = ConfigEntry[PowerPoolCoordinator]
