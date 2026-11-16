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
    MczCountersCoordinator,
)
from .maestro import MaestroStove
from .maestro.model_value_reader import get_counter_value, get_response_value
from .maestro.models import model_definitions, models_types

PARALLEL_UPDATES = 0


class MczCounterSensor(CoordinatorEntity[MczCountersCoordinator], SensorEntity):
    """Expose lifetime statistics while the cloud, but not necessarily the stove, is online."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MczCountersCoordinator,
        supported_counter: models_types.CounterMczConfigItem,
        account_coordinator: MczAccountCoordinator,
    ) -> None:
        """Associate each supported counter with its existing stove device."""
        super().__init__(coordinator)
        self._account_coordinator = account_coordinator
        self._supported_counter = supported_counter
        self._attr_translation_key = supported_counter.translation_key
        if supported_counter.translation_key is None:
            self._attr_name = supported_counter.user_friendly_name
        self._attr_native_unit_of_measurement = supported_counter.unit
        self._attr_suggested_display_precision = supported_counter.display_precision
        self._attr_device_class = supported_counter.device_class
        self._attr_state_class = supported_counter.state_class
        self._attr_entity_category = supported_counter.category
        self._attr_entity_registry_enabled_default = (
            supported_counter.enabled_by_default
        )
        self._attr_unique_id = (
            f"{coordinator.stove.UniqueCode}-{supported_counter.sensor_get_name}"
        )
        self._attr_device_info = coordinator.stove.get_device_info()

    async def async_added_to_hass(self) -> None:
        """Track cloud availability without requesting the hourly counters again."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._account_coordinator.async_add_listener(
                self._handle_coordinator_update
            )
        )

    @property
    def native_value(self) -> int | float | None:
        """Read the counter using its definition, just like live model readings."""
        data = self.coordinator.data
        if data is None:
            return None
        return get_counter_value(
            self._supported_counter,
            data.values,
            self.coordinator.stove.model_generation,
        )

    @property
    def available(self) -> bool:
        """Require cloud access and a successful, nonmissing counter reading."""
        return (
            self._account_coordinator.last_update_success
            and super().available
            and self.native_value is not None
        )


class MczYesterdayConsumptionSensor(
    CoordinatorEntity[MczConsumptionCoordinator], SensorEntity
):
    """Show a dated cloud estimate, not an accumulating energy meter."""

    _attr_has_entity_name = True
    _attr_translation_key = "consumption_yesterday"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: MczConsumptionCoordinator,
        account_coordinator: MczAccountCoordinator,
    ) -> None:
        """Associate history with the same stove as its live controls."""
        super().__init__(coordinator)
        self._account_coordinator = account_coordinator
        self._attr_unique_id = f"{coordinator.stove.UniqueCode}-consumption_yesterday"
        self._attr_device_info = coordinator.stove.get_device_info()

    async def async_added_to_hass(self) -> None:
        """Track cloud availability without requesting dated history again."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._account_coordinator.async_add_listener(
                self._handle_coordinator_update
            )
        )

    @property
    def available(self) -> bool:
        """Require yesterday's history, but not a stove currently online."""
        data = self.coordinator.data
        return (
            self._account_coordinator.last_update_success
            and super().available
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


class MczSensorEntity(CoordinatorEntity[MczAccountCoordinator], SensorEntity):
    """Sensor entity for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_native_value: bool | int | float | str | None = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_sensor: models_types.SensorMczConfigItem,
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
        self._attr_translation_key = supported_sensor.translation_key
        self._attr_device_info = self._stove.get_device_info()
        self._prop = supported_sensor.sensor_get_name
        self._supported_sensor = supported_sensor
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
    def native_value(self) -> bool | int | float | str | None:
        return self._attr_native_value

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        value = get_response_value(
            self._supported_sensor,
            self._stove.State,
            self._stove.Status,
            self._stove.model_generation,
        )

        if (
            self._api_value_renames is not None
            and isinstance(value, str)
            and value in self._api_value_renames
        ):
            self._attr_native_value = self._api_value_renames[value]
        else:
            self._attr_native_value = value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MczConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinator: MczAccountCoordinator = entry.runtime_data.coordinator
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
                new_entities.append(MczYesterdayConsumptionSensor(history, coordinator))
        if new_entities:
            async_add_entities(new_entities)

    for history in coordinator.consumption_coordinators.values():
        entry.async_on_unload(history.async_add_listener(async_discover_consumption))
        entry.async_create_background_task(
            hass,
            history.async_refresh(),
            name=f"{history.name} initial refresh",
        )

    discovered_counters: set[tuple[str, str]] = set()

    @callback
    def async_discover_counters() -> None:
        """Discover individual counters when they first provide a usable value."""
        new_entities = []
        for unique_code, counters in coordinator.counters_coordinators.items():
            if not counters.last_update_success or counters.data is None:
                continue
            for definition in model_definitions.supported_counters:
                assert definition.sensor_get_name is not None
                identity = (unique_code, definition.sensor_get_name)
                if identity in discovered_counters:
                    continue
                if (
                    get_counter_value(
                        definition,
                        counters.data.values,
                        counters.stove.model_generation,
                    )
                    is not None
                ):
                    discovered_counters.add(identity)
                    new_entities.append(
                        MczCounterSensor(counters, definition, coordinator)
                    )
        if new_entities:
            async_add_entities(new_entities)

    for counters in coordinator.counters_coordinators.values():
        entry.async_on_unload(counters.async_add_listener(async_discover_counters))
        entry.async_create_background_task(
            hass,
            counters.async_refresh(),
            name=f"{counters.name} initial refresh",
        )


def _getStoveSensorEntities(
    coordinator: MczAccountCoordinator,
    stove: MaestroStove,
) -> list[CoordinatorEntity[MczAccountCoordinator]]:
    """Get the sensor entities to create for this stove."""
    entities: list[CoordinatorEntity[MczAccountCoordinator]] = []
    supported_sensors = filter(
        lambda supported_sensor: (
            get_response_value(
                supported_sensor, stove.State, stove.Status, stove.model_generation
            )
            is not None
        ),
        iter(model_definitions.supported_sensors),
    )

    entities.extend(
        MczSensorEntity(coordinator, stove.UniqueCode, supported_sensor)
        for supported_sensor in supported_sensors
        if supported_sensor is not None
    )
    return entities
