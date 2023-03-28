"""Config flow for maestro_mcz integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
)

from .const import DOMAIN, DEFAULT_POLLING_INTERVAL
from .maestro import MaestroController

_LOGGER = logging.getLogger(__name__)
CONF_POLLING_INTERVAL = "polling_interval"
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    controller = MaestroController(data[CONF_USERNAME], data[CONF_PASSWORD])
    await controller.Login()
    await controller.StoveInfo()

    # Return info that you want to store in the config entry.
    return {"title": data[CONF_USERNAME]}


class MCZConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for maestro_mcz."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(user_input["username"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
    
    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)
    
class OptionsFlowHandler(OptionsFlow):
    """Handle a option flow for nut."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle options flow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        polling_interval = self.config_entry.options.get(
            CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
        )

        base_schema = {
            vol.Optional(CONF_POLLING_INTERVAL, default=polling_interval): vol.All(
                vol.Coerce(int), vol.Clamp(min=DEFAULT_POLLING_INTERVAL, max=300)
            )
        }

        return self.async_show_form(step_id="init", data_schema=vol.Schema(base_schema))
    
class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
