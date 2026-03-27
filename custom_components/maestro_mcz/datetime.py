"""Platform for DateTime integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import homeassistant.util.dt as dt_util

from . import MczDeviceCoordinator
from .maestro.controller.requests.activate_program import ProgramCommand
from .maestro.controller.responses.model import SensorConfiguration
from .maestro.models import models
from .maestro.types.enums import SensorTypeEnum


class MczDateTimeEntity(CoordinatorEntity, DateTimeEntity):
    """Representation of a date/time entity."""

    _attr_has_entity_name = True
    _attr_native_value = None
    _attr_am_pm = None
    _attr_weekday = None

    _supported_date_time_sensor: models.DateTimeMczConfigItem | None = None
    _date_time_configuration: SensorConfiguration | None = None

    _sensor_configuration_weekday: SensorConfiguration | None = None
    _sensor_configuration_year: SensorConfiguration | None = None
    _sensor_configuration_month: SensorConfiguration | None = None
    _sensor_configuration_day: SensorConfiguration | None = None
    _sensor_configuration_hour: SensorConfiguration | None = None
    _sensor_configuration_minute: SensorConfiguration | None = None
    _sensor_configuration_second: SensorConfiguration | None = None
    _sensor_configuration_am_pm: SensorConfiguration | None = None

    def __init__(
        self,
        coordinator: MczDeviceCoordinator,
        supported_date_time: models.DateTimeMczConfigItem,
        matching_date_time_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the date/time entity."""
        super().__init__(coordinator)
        self.coordinator: MczDeviceCoordinator = coordinator
        self._attr_name = supported_date_time.user_friendly_name
        self._attr_unique_id = (
            f"{self.coordinator.stove.UniqueCode}-{supported_date_time.sensor_set_name}"
        )
        self._attr_icon = supported_date_time.icon
        self._prop = supported_date_time.sensor_set_name
        self._enabled_default = supported_date_time.enabled_by_default
        self._category = supported_date_time.category

        self._supported_date_time_sensor = supported_date_time
        self.set_date_time_configuration(matching_date_time_configuration)

        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    @property
    def native_value(self) -> datetime | None:
        return self._attr_native_value

    @property
    def am_pm(self) -> bool | None:
        return self._attr_am_pm

    @property
    def weekday(self) -> int | None:
        return self._attr_weekday

    def set_date_time_configuration(
        self, matching_date_time_configuration: SensorConfiguration
    ):
        self._date_time_configuration = matching_date_time_configuration

        if self._supported_date_time_sensor.sensor_set_config_name is not None:
            # set weekday config
            if self._supported_date_time_sensor.sensor_set_name is not None:
                supported_sensor_weekday = self.coordinator.stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    self._supported_date_time_sensor.sensor_set_config_name,
                    self._supported_date_time_sensor.sensor_set_name_weekday,
                )
                if (
                    supported_sensor_weekday is not None
                    and supported_sensor_weekday.configuration is not None
                    and supported_sensor_weekday.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    self._sensor_configuration_weekday = supported_sensor_weekday
            # set year config
            if self._supported_date_time_sensor.sensor_set_name_year is not None:
                supported_sensor_year = self.coordinator.stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    self._supported_date_time_sensor.sensor_set_config_name,
                    self._supported_date_time_sensor.sensor_set_name_year,
                )
                if (
                    supported_sensor_year is not None
                    and supported_sensor_year.configuration is not None
                    and supported_sensor_year.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    self._sensor_configuration_year = supported_sensor_year
            # set month config
            if self._supported_date_time_sensor.sensor_set_name_month is not None:
                supported_sensor_month = self.coordinator.stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    self._supported_date_time_sensor.sensor_set_config_name,
                    self._supported_date_time_sensor.sensor_set_name_month,
                )
                if (
                    supported_sensor_month is not None
                    and supported_sensor_month.configuration is not None
                    and supported_sensor_month.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    self._sensor_configuration_month = supported_sensor_month
            # set day config
            if self._supported_date_time_sensor.sensor_set_name_day is not None:
                supported_sensor_day = self.coordinator.stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    self._supported_date_time_sensor.sensor_set_config_name,
                    self._supported_date_time_sensor.sensor_set_name_day,
                )
                if (
                    supported_sensor_day is not None
                    and supported_sensor_day.configuration is not None
                    and supported_sensor_day.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    self._sensor_configuration_day = supported_sensor_day
            # set hour config
            if self._supported_date_time_sensor.sensor_set_name_hour is not None:
                supported_sensor_hour = self.coordinator.stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    self._supported_date_time_sensor.sensor_set_config_name,
                    self._supported_date_time_sensor.sensor_set_name_hour,
                )
                if (
                    supported_sensor_hour is not None
                    and supported_sensor_hour.configuration is not None
                    and supported_sensor_hour.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    self._sensor_configuration_hour = supported_sensor_hour
            # set minute config
            if self._supported_date_time_sensor.sensor_set_name_minute is not None:
                supported_sensor_minute = self.coordinator.stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    self._supported_date_time_sensor.sensor_set_config_name,
                    self._supported_date_time_sensor.sensor_set_name_minute,
                )
                if (
                    supported_sensor_minute is not None
                    and supported_sensor_minute.configuration is not None
                    and supported_sensor_minute.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    self._sensor_configuration_minute = supported_sensor_minute
            # set second config
            if self._supported_date_time_sensor.sensor_set_name_second is not None:
                supported_sensor_second = self.coordinator.stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    self._supported_date_time_sensor.sensor_set_config_name,
                    self._supported_date_time_sensor.sensor_set_name_second,
                )
                if (
                    supported_sensor_second is not None
                    and supported_sensor_second.configuration is not None
                    and supported_sensor_second.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    self._sensor_configuration_second = supported_sensor_second
            # set am pm config
            if self._supported_date_time_sensor.sensor_set_name_am_pm is not None:
                supported_sensor_am_pm = self.coordinator.stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    self._supported_date_time_sensor.sensor_set_config_name,
                    self._supported_date_time_sensor.sensor_set_name_am_pm,
                )
                if (
                    supported_sensor_am_pm is not None
                    and supported_sensor_am_pm.configuration is not None
                    and supported_sensor_am_pm.configuration.type
                    == SensorTypeEnum.BOOLEAN.value
                ):
                    self._sensor_configuration_am_pm = supported_sensor_am_pm

    async def async_set_value(self, value: datetime) -> None:
        """Update the date/time."""
        list_of_commands: list[ProgramCommand] = []
        converted_to_timezone = value.astimezone(dt_util.DEFAULT_TIME_ZONE)
        if converted_to_timezone is not None:
            if self._date_time_configuration is not None:
                if (
                    self._sensor_configuration_weekday is not None
                    and self._sensor_configuration_weekday.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    list_of_commands.append(
                        ProgramCommand(
                            self._sensor_configuration_weekday.configuration.sensor_id,
                            converted_to_timezone.weekday(),
                        )
                    )
                if (
                    self._sensor_configuration_year is not None
                    and self._sensor_configuration_year.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    list_of_commands.append(
                        ProgramCommand(
                            self._sensor_configuration_year.configuration.sensor_id,
                            converted_to_timezone.year,
                        )
                    )
                if (
                    self._sensor_configuration_month is not None
                    and self._sensor_configuration_month.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    list_of_commands.append(
                        ProgramCommand(
                            self._sensor_configuration_month.configuration.sensor_id,
                            converted_to_timezone.month,
                        )
                    )
                if (
                    self._sensor_configuration_day is not None
                    and self._sensor_configuration_day.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    list_of_commands.append(
                        ProgramCommand(
                            self._sensor_configuration_day.configuration.sensor_id,
                            converted_to_timezone.day,
                        )
                    )
                if (
                    self._sensor_configuration_hour is not None
                    and self._sensor_configuration_hour.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    list_of_commands.append(
                        ProgramCommand(
                            self._sensor_configuration_hour.configuration.sensor_id,
                            converted_to_timezone.hour,
                        )
                    )
                if (
                    self._sensor_configuration_minute is not None
                    and self._sensor_configuration_minute.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    list_of_commands.append(
                        ProgramCommand(
                            self._sensor_configuration_minute.configuration.sensor_id,
                            converted_to_timezone.minute,
                        )
                    )
                if (
                    self._sensor_configuration_second is not None
                    and self._sensor_configuration_second.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    list_of_commands.append(
                        ProgramCommand(
                            self._sensor_configuration_second.configuration.sensor_id,
                            converted_to_timezone.second,
                        )
                    )
                if (
                    self._sensor_configuration_am_pm is not None
                    and self._sensor_configuration_am_pm.configuration.type
                    == SensorTypeEnum.BOOLEAN.value
                ):
                    list_of_commands.append(
                        ProgramCommand(
                            self._sensor_configuration_am_pm.configuration.sensor_id,
                            self.am_pm,
                        )
                    )

                await self.coordinator.stove.activateProgramMultipleCommands(
                    self._date_time_configuration.configuration_id, list_of_commands
                )

                await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:

        weekday: int | None = None
        year: int | None = None
        month: int | None = None
        day: int | None = None
        hour: int | None = None
        minute: int | None = None
        second: int | None = None
        am_pm: bool | None = None

        if self._supported_date_time_sensor is not None:
            if self._sensor_configuration_weekday is not None and hasattr(
                self.coordinator.stove.Status,
                self._supported_date_time_sensor.sensor_get_name_weekday,
            ):
                weekday = getattr(
                    self.coordinator.stove.Status,
                    self._supported_date_time_sensor.sensor_get_name_weekday,
                )
            if self._sensor_configuration_year is not None and hasattr(
                self.coordinator.stove.Status,
                self._supported_date_time_sensor.sensor_get_name_year,
            ):
                year = getattr(
                    self.coordinator.stove.Status,
                    self._supported_date_time_sensor.sensor_get_name_year,
                )
            if self._sensor_configuration_month is not None and hasattr(
                self.coordinator.stove.Status,
                self._supported_date_time_sensor.sensor_get_name_month,
            ):
                month = getattr(
                    self.coordinator.stove.Status,
                    self._supported_date_time_sensor.sensor_get_name_month,
                )
            if self._sensor_configuration_day is not None and hasattr(
                self.coordinator.stove.Status,
                self._supported_date_time_sensor.sensor_get_name_day,
            ):
                day = getattr(
                    self.coordinator.stove.Status,
                    self._supported_date_time_sensor.sensor_get_name_day,
                )
            if self._sensor_configuration_hour is not None and hasattr(
                self.coordinator.stove.Status,
                self._supported_date_time_sensor.sensor_get_name_hour,
            ):
                hour = getattr(
                    self.coordinator.stove.Status,
                    self._supported_date_time_sensor.sensor_get_name_hour,
                )
            if self._sensor_configuration_minute is not None and hasattr(
                self.coordinator.stove.Status,
                self._supported_date_time_sensor.sensor_get_name_minute,
            ):
                minute = getattr(
                    self.coordinator.stove.Status,
                    self._supported_date_time_sensor.sensor_get_name_minute,
                )
            if self._sensor_configuration_second is not None and hasattr(
                self.coordinator.stove.Status,
                self._supported_date_time_sensor.sensor_get_name_second,
            ):
                second = getattr(
                    self.coordinator.stove.Status,
                    self._supported_date_time_sensor.sensor_get_name_second,
                )
            if self._sensor_configuration_am_pm is not None and hasattr(
                self.coordinator.stove.Status,
                self._supported_date_time_sensor.sensor_get_name_am_pm,
            ):
                am_pm = getattr(
                    self.coordinator.stove.Status,
                    self._supported_date_time_sensor.sensor_get_name_am_pm,
                )

        if weekday is not None:
            self._attr_weekday = weekday
        else:
            self._attr_weekday = None

        if (
            year is not None
            and year != 0
            and month is not None
            and month != 0
            and day is not None
            and day != 0
            and hour is not None
            and minute is not None
        ):
            if second is None:
                second = 0

            try:
                self._attr_native_value = datetime(
                    year=year,
                    month=month,
                    day=day,
                    hour=hour,
                    minute=minute,
                    second=second,
                    tzinfo=dt_util.DEFAULT_TIME_ZONE,
                )
            except Exception as e:  # noqa: BLE001
                self._attr_native_value = None
        else:
            self._attr_native_value = None

        if am_pm is not None:
            self._attr_am_pm = am_pm
        else:
            self._attr_am_pm = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up datetime entities from a config entry."""
    coordinators = entry.runtime_data
    entities = []
    for coordinator in coordinators.values():
        entities.extend(_getStoveDateTimeEntities(coordinator))
    async_add_entities(entities)


def _getStoveDateTimeEntities(
    coordinator: MczDeviceCoordinator,
) -> list[CoordinatorEntity]:
    """Get the date time entities to create for this stove."""
    entities = []
    supported_date_times = coordinator.stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_date_times
    )
    if supported_date_times is not None:
        entities.extend(
            MczDateTimeEntity(coordinator, dt[0], dt[1])
            for dt in supported_date_times
            if dt[0] is not None and dt[1] is not None
        )
    return entities
