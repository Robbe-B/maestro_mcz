"""Verify real HA registration and service calls, not just entity methods."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.maestro_mcz.const import DOMAIN


async def test_real_platform_setup_services_and_unload(hass, entry, controller):
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        registered = er.async_entries_for_config_entry(registry, entry.entry_id)
        assert {item.domain for item in registered} == {
            "binary_sensor",
            "button",
            "climate",
            "datetime",
            "fan",
            "number",
            "select",
            "sensor",
            "switch",
        }
        climate_id = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
        alarm_id = registry.async_get_entity_id(
            "sensor", DOMAIN, "SERIAL-001-last_alarm"
        )
        assert hass.states.get(climate_id).state == "heat"
        assert hass.states.get(alarm_id).state == "A00"

        with patch.object(
            entry.runtime_data, "update_data_after_set", new_callable=AsyncMock
        ) as refresh:
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": climate_id, "temperature": 23.5},
                blocking=True,
            )
            command = (
                controller.activate_program_with_commands_for_stove.await_args.args[4][
                    0
                ]
            )
            assert (command.SensorId, command.Value) == ("id-set_amb1", 23.5)
            refresh.assert_awaited_once()

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
        assert hass.states.get(climate_id).state == "unavailable"
