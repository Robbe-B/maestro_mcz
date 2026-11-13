"""Platform for Sensor integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    MczAccountCoordinator,
    MczConfigEntry,
    MczConsumptionCoordinator,
)
from .maestro import MaestroStove
from .maestro.models import models

PARALLEL_UPDATES = 0


class MczYesterdayConsumptionSensor(
    CoordinatorEntity[MczConsumptionCoordinator], SensorEntity
):
    """Show a dated cloud estimate, not an accumulating energy meter."""

    _attr_has_entity_name = True
    _attr_translation_key = "consumption_yesterday"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: MczConsumptionCoordinator) -> None:
        """Associate history with the same stove as its live controls."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.stove.UniqueCode}-consumption_yesterday"
        self._attr_device_info = coordinator.stove.get_device_info()

    @property
    def available(self) -> bool:
        """Require yesterday's history, but not a stove currently online."""
        data = self.coordinator.data
        return (
            super().available
            and data is not None
            and data.date == self.coordinator.yesterday
            and data.value is not None
        )

    @property
    def native_value(self) -> float | None:
        """Never relabel an older day's estimate as yesterday."""
        data = self.coordinator.data
        if data is None or data.date != self.coordinator.yesterday:
            return None
        return data.value

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Keep the original period and successful retrieval time explicit."""
        data = self.coordinator.data
        if data is None:
            return None
        return {
            "consumption_date": data.date.isoformat(),
            "last_successful_update": data.last_updated.isoformat(),
        }


class MczSensorEntity(CoordinatorEntity, SensorEntity):
    """Sensor entity for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_native_value = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_sensor: models.SensorMczConfigItem,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._attr_name = supported_sensor.user_friendly_name
        self._attr_native_unit_of_measurement = supported_sensor.unit
        self._attr_suggested_display_precision = supported_sensor.display_precision
        self._attr_device_class = supported_sensor.device_class
        self._attr_state_class = supported_sensor.state_class
        self._attr_unique_id = f"{stove_unique_code}-{supported_sensor.sensor_get_name}"
        self._attr_icon = supported_sensor.icon
        self._attr_device_info = self._stove.get_device_info()
        self._prop = supported_sensor.sensor_get_name
        self.entity_registry_enabled_default = supported_sensor.enabled_by_default
        self.entity_category = supported_sensor.category
        self._api_value_renames = supported_sensor.api_value_renames
        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def available(self) -> bool:
        """Check availability based on coordinator and stove connection."""
        # Check 1: coordinator is available
        if not super().available:
            return False
        # Check 2: is the stove connected
        return self._stove.is_connected

    @property
    def native_value(self):
        return self._attr_native_value

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        value = getattr(self._stove.Status, self._prop, None)
        if value is None:
            value = getattr(self._stove.State, self._prop, None)

        if self._api_value_renames is not None and value in self._api_value_renames:
            self._attr_native_value = self._api_value_renames[value]
        else:
            self._attr_native_value = value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MczConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: MczAccountCoordinator = entry.runtime_data
    entities = []
    for stove in coordinator.stoves.values():
        entities.extend(_getStoveSensorEntities(coordinator, stove))
    async_add_entities(entities)

    discovered: set[str] = set()

    @callback
    def async_discover_consumption() -> None:
        """Add a sensor when a stove first provides a valid yesterday reading."""
        new_entities = []
        for unique_code, history in coordinator.consumption_coordinators.items():
            if (
                unique_code not in discovered
                and history.last_update_success
                and history.data is not None
                and history.data.date == history.yesterday
                and history.data.value is not None
            ):
                discovered.add(unique_code)
                new_entities.append(MczYesterdayConsumptionSensor(history))
        if new_entities:
            async_add_entities(new_entities)

    for history in coordinator.consumption_coordinators.values():
        entry.async_on_unload(history.async_add_listener(async_discover_consumption))
        entry.async_create_background_task(
            hass,
            history.async_refresh(),
            name=f"{history.name} initial refresh",
        )


def _getStoveSensorEntities(
    coordinator: MczAccountCoordinator,
    stove: MaestroStove,
) -> list[CoordinatorEntity]:
    """Get the sensor entities to create for this stove."""
    entities = []
    supported_sensors = filter(
        lambda supported_sensor: (
            any(
                (
                    supported_sensor.sensor_get_name == sensor_name_status
                    and getattr(stove.Status, sensor_name_status) is not None
                )
                for sensor_name_status in dir(stove.Status)
            )
            or any(
                (
                    supported_sensor.sensor_get_name == sensor_name_state
                    and getattr(stove.State, sensor_name_state) is not None
                )
                for sensor_name_state in dir(stove.State)
            )
        ),
        iter(models.supported_sensors),
    )

    entities.extend(
        MczSensorEntity(coordinator, stove.UniqueCode, supported_sensor)
        for supported_sensor in supported_sensors
        if supported_sensor is not None
    )
    return entities
