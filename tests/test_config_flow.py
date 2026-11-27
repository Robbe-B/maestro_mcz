"""Exercise real HA flow management without contacting the MCZ cloud."""

from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.maestro_mcz.config_flow import MCZConfigFlow
from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.maestro.cloud.controller.controller import (
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
        assert result["result"].unique_id == "new-user"
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
        assert result["result"].unique_id == "MockedHost"
        # 3. Importing the same account again should be rejected.
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
        )
        assert duplicate["reason"] == "already_configured"


async def test_reauth_preserves_account_devices_and_options(hass, entry, controller):
    """Replace a changed password without losing the user's stove or saved account details."""
    # 1. Load a working account with a custom name and an old refresh setting.
    hass.config_entries.async_update_entry(
        entry, title="My stove account", options={"polling_interval": 60}
    )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ) as setup_controller,
        patch(
            "custom_components.maestro_mcz.config_flow.MaestroController",
            return_value=controller,
        ) as login_controller,
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        devices = dr.async_get(hass)
        entities = er.async_get(hass)
        original_device_ids = {
            device.id
            for device in dr.async_entries_for_config_entry(devices, entry.entry_id)
        }
        original_entity_ids = {
            entity.id
            for entity in er.async_entries_for_config_entry(entities, entry.entry_id)
        }
        original_entry_id = entry.entry_id
        setup_controller.reset_mock()

        # 2. Recover this account using only its new password, not another username.
        form = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        assert form["step_id"] == "reauth_confirm"
        assert form["description_placeholders"] == {
            "username": "test-user",
            "name": "My stove account",
        }
        with pytest.raises(vol.Invalid):
            form["data_schema"](
                {"username": "another-user", "password": "new-password"}
            )
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"password": "new-password"}
        )
        await hass.async_block_till_done(wait_background_tasks=True)

    # 3. HA reloads the same entry once and keeps its identity and stored account details.
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.entry_id == original_entry_id
    assert entry.unique_id == "test-user"
    assert entry.title == "My stove account"
    assert entry.data == {"username": "test-user", "password": "new-password"}
    assert entry.options == {"polling_interval": 60}
    assert original_device_ids
    assert original_entity_ids
    recovered_device_ids = {
        device.id
        for device in dr.async_entries_for_config_entry(devices, entry.entry_id)
    }
    recovered_entity_ids = {
        entity.id
        for entity in er.async_entries_for_config_entry(entities, entry.entry_id)
    }
    assert recovered_device_ids == original_device_ids
    assert recovered_entity_ids == original_entity_ids
    assert login_controller.call_args.args[1:] == ("test-user", "new-password")
    setup_controller.assert_called_once()
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (MaestroAuthenticationException("bad password"), "invalid_auth"),
        (MaestroConnectionException("offline"), "cannot_connect"),
    ],
)
async def test_reauth_error_and_retry(hass, entry, controller, exception, error):
    """Keep the saved password unchanged after a failed attempt and allow another try."""
    # 1. The existing account needs a password update, but validation initially fails.
    controller.retrieve_linked_stove_infos.side_effect = exception
    with (
        patch(
            "custom_components.maestro_mcz.config_flow.MaestroController",
            return_value=controller,
        ),
        patch.object(
            hass.config_entries, "async_reload", new_callable=AsyncMock
        ) as reload_entry,
    ):
        form = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )

        # 2. Submit the password and explain the failure without changing the account.
        failed = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"password": "new-password"}
        )
        assert failed["type"] is FlowResultType.FORM
        assert failed["step_id"] == "reauth_confirm"
        assert failed["errors"] == {"base": error}
        assert entry.data["password"] == "test-password"
        reload_entry.assert_not_awaited()

        # 3. Correct the problem and finish recovery using the same form.
        controller.retrieve_linked_stove_infos.side_effect = None
        recovered = await hass.config_entries.flow.async_configure(
            failed["flow_id"], {"password": "corrected-password"}
        )
        await hass.async_block_till_done()
    assert recovered["reason"] == "reauth_successful"
    assert entry.data["password"] == "corrected-password"
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_reauth_rejects_mismatched_account_identity(hass, entry, controller):
    """Refuse inconsistent account details rather than replacing another account's data."""
    # 1. The saved username no longer matches the account's registered identity.
    hass.config_entries.async_update_entry(entry, unique_id="another-user")
    with (
        patch(
            "custom_components.maestro_mcz.config_flow.MaestroController",
            return_value=controller,
        ),
        patch.object(
            hass.config_entries, "async_reload", new_callable=AsyncMock
        ) as reload_entry,
    ):
        form = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
        # 2. Even a valid password must not override that identity mismatch.
        result = await hass.config_entries.flow.async_configure(
            form["flow_id"], {"password": "new-password"}
        )
        await hass.async_block_till_done()
    # 3. Explain why recovery stopped and leave the existing credentials untouched.
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data["password"] == "test-password"
    reload_entry.assert_not_awaited()


@pytest.mark.parametrize(
    ("source", "extra_data"),
    [
        (config_entries.SOURCE_IMPORT, {}),
        (config_entries.SOURCE_USER, {"MOCKED_FOLDER": "/synthetic"}),
    ],
)
async def test_reauth_skips_saved_diagnostic_accounts(hass, source, extra_data):
    """Do not ask for a cloud password when an account only replays saved reports."""
    # 1. Register an imported or replay-backed account with dummy credentials.
    entry = MockConfigEntry(
        domain=DOMAIN,
        source=source,
        unique_id="MockedHost",
        data={"username": "dummy", "password": "dummy"} | extra_data,
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.maestro_mcz.config_flow.MaestroController"
    ) as cloud_controller:
        # 2. Try to start cloud sign-in recovery for the saved reports.
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
            },
            data=entry.data,
        )
    # 3. Stop with an explanation instead of showing a dummy-account password form.
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_not_supported"
    cloud_controller.assert_not_called()


@pytest.mark.parametrize("polling_interval", [None, 60])
async def test_polling_options_not_offered(hass, entry, polling_interval):
    """Hide refresh settings for new and existing accounts so polling stays consistent."""
    # 1. Keep a new account's defaults or an interval saved by an older installation.
    if polling_interval is not None:
        hass.config_entries.async_update_entry(
            entry, options={"polling_interval": polling_interval}
        )

    # 2. Ask whether Home Assistant should offer an integration options form.
    supports_options = MCZConfigFlow.async_supports_options_flow(entry)

    # 3. Neither account should offer the removed polling setting.
    assert supports_options is False
