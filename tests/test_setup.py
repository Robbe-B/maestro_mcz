"""Setup, coordinator lifecycle, and error propagation regression coverage."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.maestro_mcz import (
    PLATFORMS,
    MczAccountCoordinator,
    _async_update_listener,
    _has_mocked_folder,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)


async def test_setup_without_mocked_folder(hass):
    """Start normally without replay files, so ordinary installations need no extra folder."""
    # 1. Pretend there are no saved reports to replay.
    with patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None):
        # 2. Basic integration setup should still succeed.
        setup_succeeded = await async_setup(hass, {})
    assert setup_succeeded


async def test_setup_starts_mock_import(hass):
    """Discover replay files automatically, making reported stove problems reproducible."""
    # 1. Provide a replay folder and record the request to create a replay account.
    with (
        patch(
            "custom_components.maestro_mcz._has_mocked_folder",
            return_value="/synthetic",
        ),
        patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ) as flow,
    ):
        # 2. Run setup and let HA finish its background work.
        setup_succeeded = await async_setup(hass, {})
        assert setup_succeeded
        await hass.async_block_till_done()
    # 3. The new account should import reports from the folder we supplied.
    assert flow.await_args.args == ("maestro_mcz",)
    assert flow.await_args.kwargs["context"] == {"source": "import"}
    assert flow.await_args.kwargs["data"]["MOCKED_FOLDER"] == "/synthetic"


@pytest.mark.parametrize("exists", [False, True])
async def test_mock_folder_detection(exists):
    """Use the replay folder only when it exists, avoiding a nonexistent data source."""
    # 1. Choose whether the expected replay folder is present.
    expected_folder = (
        "config/custom_components/maestro_mcz/mocked" if exists else None
    )
    with patch("custom_components.maestro_mcz.Path.is_dir", return_value=exists):
        # 2. Ask setup which folder it should use.
        detected_folder = await _has_mocked_folder()
    assert detected_folder == expected_folder


@pytest.mark.parametrize("mocked", [False, True])
@pytest.mark.parametrize("polling_interval", [None, 10, 30, 120])
async def test_setup_entry_initializes_coordinator_and_platforms(
    hass, entry, controller, mocked, polling_interval
):
    """Load the right data source and refresh interval so the account's controls work."""
    # 1. Prepare the saved options and choose live cloud data or offline replay.
    if polling_interval is not None:
        hass.config_entries.async_update_entry(
            entry, options={"polling_interval": polling_interval}
        )
    if mocked:
        hass.config_entries.async_update_entry(
            entry, data=dict(entry.data) | {"MOCKED_FOLDER": "/synthetic"}
        )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ) as live_controller_factory,
        patch(
            "custom_components.maestro_mcz.MockedController", return_value=controller
        ) as replay_controller_factory,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ) as setup_platforms,
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Let HA set up the account and its controls.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        assert setup_succeeded
        await hass.async_block_till_done()
    # 3. Only the chosen data source should be used.
    if mocked:
        replay_controller_factory.assert_called_once()
        live_controller_factory.assert_not_called()
    else:
        live_controller_factory.assert_called_once()
        replay_controller_factory.assert_not_called()
    assert isinstance(entry.runtime_data, MczAccountCoordinator)
    assert list(entry.runtime_data.stoves) == ["SERIAL-001"]
    expected_interval = 10 if polling_interval is None else polling_interval
    assert entry.runtime_data.update_interval == timedelta(seconds=expected_interval)
    setup_platforms.assert_awaited_once_with(entry, PLATFORMS)
    controller.get_stove_model_for_stove.assert_awaited_once_with(
        "model-1", "Living Room"
    )
    controller.do_ping_for_stove.assert_awaited_once_with("device-1", "Living Room")


@pytest.mark.parametrize(
    "error", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_setup_account_failure_returns_false(hass, entry, controller, error):
    """Do not create controls when the account cannot be reached or authenticated."""
    # 1. Make account discovery fail before any controls are created.
    controller.retrieve_linked_stove_infos.side_effect = error("unavailable")
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ) as forward,
    ):
        # 2. Try setting up the account.
        setup_succeeded = await async_setup_entry(hass, entry)
    # 3. Setup must fail without loading empty or misleading controls.
    assert setup_succeeded is False
    forward.assert_not_awaited()


@pytest.mark.parametrize("result", [False, True])
async def test_unload_and_options_reload(hass, entry, result):
    """Unload controls and reload changed options so HA applies the user's new settings."""
    # 1. Unload the platforms, keeping HA's success or failure result.
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new_callable=AsyncMock,
        return_value=result,
    ) as unload:
        unload_result = await async_unload_entry(hass, entry)
    assert unload_result is result
    unload.assert_awaited_once_with(entry, PLATFORMS)
    # 2. Updating options should reload this account, not a different account.
    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload:
        await _async_update_listener(hass, entry)
    reload.assert_awaited_once_with(entry.entry_id)


async def test_coordinator_empty_account(hass, entry):
    """Report an account with no stoves instead of pretending a refresh succeeded."""
    # 1. Start with a refresh manager that has no stoves.
    coordinator = MczAccountCoordinator(hass, entry, "empty", [])
    # 2. Both its first setup and later refreshes must explain the missing stove.
    for method in (coordinator._async_setup, coordinator._async_update_data):
        with pytest.raises(UpdateFailed, match="No stoves"):
            await method()


async def test_coordinator_model_failure(coordinator, stove, controller):
    """Stop setup if the stove's supported controls cannot be loaded."""
    # 1. Pretend the cloud cannot return the stove model.
    controller.get_stove_model_for_stove.side_effect = MaestroConnectionException(
        "offline"
    )
    # 2. The refresh manager should tell HA that setup failed.
    with pytest.raises(UpdateFailed, match="offline"):
        await coordinator._async_setup()


@pytest.mark.parametrize(
    "error,expected",
    [
        (MaestroAuthenticationException, ConfigEntryAuthFailed),
        (MaestroConnectionException, UpdateFailed),
    ],
)
async def test_coordinator_maps_update_failures(
    coordinator, controller, error, expected
):
    """Distinguish expired login from connection trouble so HA can respond appropriately."""
    # 1. Make the stove's ping fail with this case's account or connection error.
    controller.do_ping_for_stove.side_effect = error("offline")
    # 2. HA receives the matching kind of failure, not a generic success.
    with pytest.raises(expected):
        await coordinator._async_update_data()


async def test_coordinator_delayed_refresh_contract(coordinator):
    """Wait for a changed setting to reach the cloud before reading it back twice."""
    # 1. Record waits and refreshes without actually delaying the test.
    with (
        patch(
            "custom_components.maestro_mcz.asyncio.sleep", new_callable=AsyncMock
        ) as sleep,
        patch.object(coordinator, "async_refresh", new_callable=AsyncMock) as refresh,
    ):
        # 2. Request the normal follow-up after changing a stove setting.
        await MczAccountCoordinator.update_data_after_set(coordinator)
    # 3. Both follow-up reads retain their three-second settling delay.
    assert [args.args for args in sleep.await_args_list] == [(3,), (3,)]
    assert refresh.await_count == 2
