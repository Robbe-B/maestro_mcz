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
    with patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None):
        assert await async_setup(hass, {})


async def test_setup_starts_mock_import(hass):
    with (
        patch(
            "custom_components.maestro_mcz._has_mocked_folder",
            return_value="/synthetic",
        ),
        patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ) as flow,
    ):
        assert await async_setup(hass, {})
        await hass.async_block_till_done()
    assert flow.await_args.args == ("maestro_mcz",)
    assert flow.await_args.kwargs["context"] == {"source": "import"}
    assert flow.await_args.kwargs["data"]["MOCKED_FOLDER"] == "/synthetic"


@pytest.mark.parametrize("exists", [False, True])
async def test_mock_folder_detection(exists):
    with patch("custom_components.maestro_mcz.Path.is_dir", return_value=exists):
        assert await _has_mocked_folder() == (
            "config/custom_components/maestro_mcz/mocked" if exists else None
        )


@pytest.mark.parametrize("mocked", [False, True])
async def test_setup_entry_initializes_coordinator_and_platforms(
    hass, entry, controller, mocked
):
    if mocked:
        hass.config_entries.async_update_entry(
            entry, data=dict(entry.data) | {"MOCKED_FOLDER": "/synthetic"}
        )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ) as live,
        patch(
            "custom_components.maestro_mcz.MockedController", return_value=controller
        ) as mock,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ) as forward,
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert (mock if mocked else live).call_count == 1
    assert (live if mocked else mock).call_count == 0
    assert isinstance(entry.runtime_data, MczAccountCoordinator)
    assert list(entry.runtime_data.stoves) == ["SERIAL-001"]
    assert entry.runtime_data.update_interval == timedelta(seconds=30)
    forward.assert_awaited_once_with(entry, PLATFORMS)
    controller.get_stove_model_for_stove.assert_awaited_once_with(
        "model-1", "Living Room"
    )
    controller.do_ping_for_stove.assert_awaited_once_with("device-1", "Living Room")


@pytest.mark.parametrize(
    "error", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_setup_account_failure_returns_false(hass, entry, controller, error):
    controller.retrieve_linked_stove_infos.side_effect = error("unavailable")
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ) as forward,
    ):
        assert await async_setup_entry(hass, entry) is False
    forward.assert_not_awaited()


@pytest.mark.parametrize("result", [False, True])
async def test_unload_and_options_reload(hass, entry, result):
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new_callable=AsyncMock,
        return_value=result,
    ) as unload:
        assert await async_unload_entry(hass, entry) is result
    unload.assert_awaited_once_with(entry, PLATFORMS)
    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as reload:
        await _async_update_listener(hass, entry)
    reload.assert_awaited_once_with(entry.entry_id)


async def test_coordinator_empty_account(hass, entry):
    coordinator = MczAccountCoordinator(hass, entry, "empty", [])
    for method in (coordinator._async_setup, coordinator._async_update_data):
        with pytest.raises(UpdateFailed, match="No stoves"):
            await method()


async def test_coordinator_model_failure(coordinator, stove, controller):
    controller.get_stove_model_for_stove.side_effect = MaestroConnectionException(
        "offline"
    )
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
    controller.do_ping_for_stove.side_effect = error("offline")
    with pytest.raises(expected):
        await coordinator._async_update_data()


async def test_coordinator_delayed_refresh_contract(coordinator):
    with (
        patch(
            "custom_components.maestro_mcz.asyncio.sleep", new_callable=AsyncMock
        ) as sleep,
        patch.object(coordinator, "async_refresh", new_callable=AsyncMock) as refresh,
    ):
        await MczAccountCoordinator.update_data_after_set(coordinator)
    assert [args.args for args in sleep.await_args_list] == [(3,), (3,)]
    assert refresh.await_count == 2
