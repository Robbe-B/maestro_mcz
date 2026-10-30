"""Exercise real HA flow management without contacting the MCZ cloud."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)


async def test_user_form(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] is None


async def test_user_success_and_duplicate(hass, controller):
    with (
        patch(
            "custom_components.maestro_mcz.config_flow.MaestroController",
            return_value=controller,
        ),
        patch("custom_components.maestro_mcz.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "new-user", "password": "test-password"}
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "new-user"
        assert result["data"] == {"username": "new-user", "password": "test-password"}
        assert result["result"].unique_id == "new-user"
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={"username": "new-user", "password": "test-password"},
        )
        assert duplicate["type"] is FlowResultType.ABORT
        assert duplicate["reason"] == "already_configured"


@pytest.mark.parametrize(
    "exception,error",
    [
        (MaestroAuthenticationException("bad credentials"), "invalid_auth"),
        (MaestroConnectionException("offline"), "cannot_connect"),
        (RuntimeError("unexpected"), "unknown"),
    ],
)
async def test_user_error_and_recovery(hass, controller, exception, error):
    controller.retrieve_linked_stove_infos.side_effect = exception
    with (
        patch(
            "custom_components.maestro_mcz.config_flow.MaestroController",
            return_value=controller,
        ),
        patch("custom_components.maestro_mcz.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={"username": "new-user", "password": "test-password"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}
        controller.retrieve_linked_stove_infos.side_effect = None
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "new-user", "password": "corrected-password"},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()


async def test_mock_import_and_duplicate(hass):
    data = {
        "host": "MockedHost",
        "MOCKED_FOLDER": "/synthetic",
        "username": "dummy",
        "password": "dummy",
    }
    with patch("custom_components.maestro_mcz.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Hub (MockedHost)"
        assert result["data"] == data
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )
        assert duplicate["reason"] == "already_configured"


async def test_options_defaults_and_save(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({}) == {"polling_interval": 30}
    for raw, expected in ((1, 30), (45, 45), (999, 300), ("60", 60)):
        assert result["data_schema"]({"polling_interval": raw}) == {
            "polling_interval": expected
        }
    saved = await hass.config_entries.options.async_configure(
        result["flow_id"], {"polling_interval": 60}
    )
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"polling_interval": 60}


async def test_options_existing_value(hass):
    entry = MockConfigEntry(domain=DOMAIN, options={"polling_interval": 120})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({}) == {"polling_interval": 120}
