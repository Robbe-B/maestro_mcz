"""Verify real HA registration and service calls, not just entity methods."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from custom_components.maestro_mcz.const import DOMAIN


async def test_real_platform_setup_services_and_unload(hass, entry, controller):
    """Check a complete HA session so working controls are not just a unit-test illusion."""
    # 1. Load the real integration, replacing only its connection to the cloud.
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        assert setup_succeeded
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        registered = er.async_entries_for_config_entry(registry, entry.entry_id)
        registered_platforms = {registered_entity.domain for registered_entity in registered}
        assert registered_platforms == {
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
        climate_entity_id = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
        alarm_entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, "SERIAL-001-last_alarm"
        )
        # 2. The heating control and alarm reading appear in Home Assistant.
        assert hass.states.get(climate_entity_id).state == "heat"
        assert hass.states.get(alarm_entity_id).state == "A00"

        # 3. Change the target temperature through HA, as a user would.
        with patch.object(
            entry.runtime_data, "update_data_after_set", new_callable=AsyncMock
        ) as refresh:
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": climate_entity_id, "temperature": 23.5},
                blocking=True,
            )
            activation = controller.activate_program_with_commands_for_stove.await_args
            sent_commands = activation.args[4]
            temperature_command = sent_commands[0]
            assert temperature_command.SensorId == "id-set_amb1"
            assert temperature_command.Value == 23.5
            refresh.assert_awaited_once()

        # 4. Unloading removes the active integration and marks its control unavailable.
        unload_succeeded = await hass.config_entries.async_unload(entry.entry_id)
        assert unload_succeeded
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
        assert hass.states.get(climate_entity_id).state == "unavailable"
