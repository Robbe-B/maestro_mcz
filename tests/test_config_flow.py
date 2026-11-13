"""Exercise real HA flow management without contacting the MCZ cloud."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant.common import MockConfigEntry

from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)


async def test_user_form(hass):
    """Show the login form first, so a new user knows where to enter credentials."""
    # 1. Start adding the integration without entering account details yet.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    # 2. HA should ask for details, not create an incomplete account.
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] is None


async def test_user_success_and_duplicate(hass, controller):
    """Accept a valid account once, preventing duplicate controls for the same account."""
    account_details = {"username": "new-user", "password": "test-password"}
    # 1. Make the cloud accept the account, without loading real platforms.
    with (
        patch(
            "custom_components.maestro_mcz.config_flow.MaestroController",
            return_value=controller,
        ),
        patch("custom_components.maestro_mcz.async_setup_entry", return_value=True),
    ):
        login_form = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        # 2. Fill in the login form and finish creating the account.
        created_account = await hass.config_entries.flow.async_configure(
            login_form["flow_id"], account_details
        )
        await hass.async_block_till_done()
        assert created_account["type"] is FlowResultType.CREATE_ENTRY
        assert created_account["title"] == "new-user"
        assert created_account["data"] == account_details
        assert created_account["result"].unique_id == "new-user"

        # 3. Adding the same account again should stop with a clear reason.
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data=account_details,
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
    """Explain a failed login and let the user correct it without starting over."""
    # 1. Make the first login fail for the reason chosen by this test case.
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
        # 2. The user stays on the form and sees the appropriate error.
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}
        # 3. Remove the failure and submit corrected details on the same form.
        controller.retrieve_linked_stove_infos.side_effect = None
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "new-user", "password": "corrected-password"},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()


async def test_mock_import_and_duplicate(hass):
    """Allow a replay account once, so troubleshooting does not create duplicate devices."""
    # 1. Supply the account details used for an offline replay.
    data = {
        "host": "MockedHost",
        "MOCKED_FOLDER": "/synthetic",
        "username": "dummy",
        "password": "dummy",
    }
    with patch("custom_components.maestro_mcz.async_setup_entry", return_value=True):
        # 2. Import those details and check the resulting account.
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )
        await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "Hub (MockedHost)"
        assert result["data"] == data
        # 3. Importing the same account again should be rejected.
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )
        assert duplicate["reason"] == "already_configured"


async def test_options_defaults_and_save(hass, entry):
    """Keep refresh settings usable: sensible defaults, safe limits, and saved choices."""
    # 1. Open options for an account that has no saved refresh interval.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({}) == {"polling_interval": 10}
    # 2. Check the minimum, ordinary values, maximum, and numeric text.
    for entered_interval, expected_interval in (
        (1, 10),
        (10, 10),
        (30, 30),
        (45, 45),
        (999, 300),
        ("60", 60),
    ):
        validated_options = result["data_schema"](
            {"polling_interval": entered_interval}
        )
        assert validated_options == {"polling_interval": expected_interval}

    # 3. Choose one minute and verify that HA remembers it.
    saved = await hass.config_entries.options.async_configure(
        result["flow_id"], {"polling_interval": 60}
    )
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"polling_interval": 60}


@pytest.mark.parametrize("polling_interval", [10, 30, 120])
async def test_options_existing_value(hass, polling_interval):
    """Respect an existing refresh choice instead of silently replacing it with the default."""
    # 1. Give the account the saved interval chosen by this test case.
    entry = MockConfigEntry(
        domain=DOMAIN, options={"polling_interval": polling_interval}
    )
    entry.add_to_hass(hass)
    # 2. Reopening options should show that same saved value.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({}) == {"polling_interval": polling_interval}
