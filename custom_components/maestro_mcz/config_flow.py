"""Config flow for maestro_mcz integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import probatio as vol
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, MOCKED_FOLDER
from .maestro.controller.controller_interface import MaestroControllerInterface
from .maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
    MaestroController,
)

_LOGGER = logging.getLogger(__name__)
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
    session = async_get_clientsession(hass)
    controller: MaestroControllerInterface = MaestroController(
        session, data[CONF_USERNAME], data[CONF_PASSWORD]
    )
    try:
        await controller.retrieve_linked_stove_infos()

    except MaestroAuthenticationException as exc:
        raise InvalidAuth from exc
    except MaestroConnectionException as exc:
        raise CannotConnect from exc

    # Return info that you want to store in the config entry.
    return {"title": data[CONF_USERNAME]}


class MCZConfigFlow(ConfigFlow, domain=DOMAIN):
    """Own account setup/import forms, entry identity and reauthentication.

    Validate credentials through a temporary controller; integration setup
    creates the long-lived account and polling coordinators.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Recover the existing cloud account without changing its identity."""
        entry = self._get_reauth_entry()
        if entry.source == SOURCE_IMPORT or MOCKED_FOLDER in entry.data:
            return self.async_abort(reason="reauth_not_supported")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate a replacement password for the saved Maestro username."""
        entry = self._get_reauth_entry()
        username = entry.data[CONF_USERNAME]
        errors: dict[str, str] = {}

        if user_input is not None:
            credentials = {
                CONF_USERNAME: username,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await validate_input(self.hass, credentials)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            else:
                await self.async_set_unique_id(username)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={CONF_USERNAME: username},
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a flow initiated by the async_setup code."""

        # 1. Set a unique ID based on something static (IP, MAC, or a fixed string)
        await self.async_set_unique_id(import_data[CONF_HOST])

        # 2. This helper immediately stops the flow if the ID is already in HA
        self._abort_if_unique_id_configured()

        # 3. If not already there, create the entry
        return self.async_create_entry(
            title=f"Hub ({import_data[CONF_HOST]})", data=import_data
        )


class CannotConnect(HomeAssistantError):
    """Represent a service connection failure as a config-flow form error."""


class InvalidAuth(HomeAssistantError):
    """Represent rejected credentials as a config-flow form error."""
