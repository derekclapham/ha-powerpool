"""Config and options flow for the PowerPool integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import PowerPoolApiError, PowerPoolAuthError, PowerPoolClient
from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .models import usernames_in

# The credential is a password-style field so the UI masks it and browsers
# don't offer to remember it.
_API_KEY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


def _interval_selector() -> NumberSelector:
    """Box for the poll interval (seconds)."""
    return NumberSelector(
        NumberSelectorConfig(
            min=MIN_SCAN_INTERVAL,
            max=MAX_SCAN_INTERVAL,
            step=30,
            unit_of_measurement="s",
            mode=NumberSelectorMode.BOX,
        )
    )


async def _discover_usernames(hass: HomeAssistant, api_key: str) -> list[str]:
    """Return the account usernames an API key unlocks.

    The `/api/user` response is keyed by username and the key alone selects the
    account, so setup reads the username off the response instead of asking for
    it — which removes the most likely setup typo.
    """
    client = PowerPoolClient(async_get_clientsession(hass), api_key)
    return usernames_in(await client.user())


class PowerPoolConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup flow.

    Each config entry is one PowerPool account. Adding the integration again
    with a different API key gives a second, independent entry — that is how
    multiple accounts are supported.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Carry state between the API key step and the account-picker step."""
        self._api_key: str = ""
        self._usernames: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect an API key and validate it against the API."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._api_key = user_input[CONF_API_KEY].strip()
            try:
                self._usernames = await _discover_usernames(self.hass, self._api_key)
            except PowerPoolAuthError:
                errors["base"] = "invalid_auth"
            except PowerPoolApiError:
                errors["base"] = "cannot_connect"
            else:
                if not self._usernames:
                    errors["base"] = "no_accounts"
                elif len(self._usernames) == 1:
                    return await self._create(self._usernames[0])
                else:
                    # One key covering several accounts: let the user pick, and
                    # they can run setup again to add the others.
                    return await self.async_step_account()

        return self.async_show_form(
            step_id="user", data_schema=_API_KEY_SCHEMA, errors=errors
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which account to track when the key unlocks more than one."""
        if user_input is not None:
            return await self._create(user_input[CONF_USERNAME])

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): SelectSelector(
                    SelectSelectorConfig(
                        options=self._usernames, mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(step_id="account", data_schema=schema)

    async def _create(self, username: str) -> ConfigFlowResult:
        """Create the entry, keyed on the username so it can't be added twice."""
        await self.async_set_unique_id(username.lower())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"PowerPool ({username})",
            data={CONF_API_KEY: self._api_key, CONF_USERNAME: username},
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauth — PowerPool resets the API key on a password change."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect a replacement API key for an existing account."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            try:
                usernames = await _discover_usernames(self.hass, api_key)
            except PowerPoolAuthError:
                errors["base"] = "invalid_auth"
            except PowerPoolApiError:
                errors["base"] = "cannot_connect"
            else:
                # Guard against pasting a *different* account's key, which
                # would silently repoint the entry and orphan its history.
                if entry.data[CONF_USERNAME] not in usernames:
                    errors["base"] = "account_mismatch"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_API_KEY: api_key}
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_API_KEY_SCHEMA,
            errors=errors,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> PowerPoolOptionsFlow:
        """Return the options flow handler."""
        return PowerPoolOptionsFlow()


class PowerPoolOptionsFlow(OptionsFlow):
    """Change the poll interval after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        schema = vol.Schema(
            {vol.Required(CONF_SCAN_INTERVAL, default=current): _interval_selector()}
        )
        return self.async_show_form(step_id="init", data_schema=schema)
