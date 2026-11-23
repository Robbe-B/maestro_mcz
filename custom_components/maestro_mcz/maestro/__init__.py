"MaestroStove class."

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import DOMAIN, M1_BOARD_TYPES, MANUFACTURER
from .controller.controller_interface import MaestroControllerInterface
from .controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)
from .controller.requests.activate_program import ProgramCommand
from .controller.responses.model import (
    Model,
    ModelConfiguration,
    SensorConfiguration,
    SensorConfigurationMultipleModes,
)
from .controller.responses.state import State
from .controller.responses.status import Status
from .controller.responses.stove_info import StoveInfo
from .models.models_types import (
    MczConfigItem,
    MczStoveModelGeneration,
)

_LOGGER = logging.getLogger(__name__)


def get_control_names(definition: MczConfigItem) -> tuple[str, ...]:
    """Try declared names against the model, independently of the detected generation."""
    if (
        definition.sensor_set_name_m1 is not None
        or definition.sensor_set_name_m2 is not None
    ):
        # Keep the original M2-before-M1 priority without changing the shared definition.
        names: tuple[str | None, ...] = (
            definition.sensor_set_name_m2,
            definition.sensor_set_name_m1,
        )
    else:
        names = (definition.sensor_set_name,)
    return tuple(name for name in names if name is not None)


@dataclass
class MaestroStoveDeviceMetadata:
    """Prepare device details and read-only system diagnostics for one stove."""

    _DATABASE_NAMES: ClassVar[dict[int, str]] = dict(
        enumerate(
            (
                "TA08",
                "TC08",
                "SA10",
                "SC10",
                "SC12",
                "SC14",
                "SL08",
                "SA08",
                "TA08-BRI",
                "SC08",
                "IK70-BRI",
                "IK80-BRI",
                "SC12-BRI",
                "LU10-BRI",
                "SL07",
                "LO08",
                " BT60",
                "BT70",
                "PH14",
                "IS07-BRI",
                "CO09",
                "ST12",
                "SC14-BRI",
                "TE06",
                "CUTHDE08",
                "SC14-MAT",
                "SC24-HYD",
                "SC16-HYD",
                "SC12-HYD",
                "IPV60",
                "IPV70",
                "JZ30-HYD",
                "VI09",
                "VI11",
                "FPC09",
                "FPC11",
                "FLOW10",
                "AKI16-HY",
                "AKI24-HY",
                "GR14",
                "VI90-H24",
                "AV12-BRI",
                "VI90-H16",
                "SL07-C",
                "IS07-B-C",
                "SA08-C",
                "SA08-C",
                "PH14-C",
                "VALMO-BR",
            ),
            start=1,
        )
    )

    serial_number: str | None = None
    board_type: str | None = None
    firmware_version: str | None = None
    active_database: str | None = None
    panel_firmware: str | None = None

    @property
    def software_version(self) -> str | None:
        """Combine known board type and firmware without inventing a version."""
        if self.firmware_version is None:
            return None
        if self.board_type is not None:
            return f"{self.board_type}.{self.firmware_version}"
        return self.firmware_version

    def update_from_status(
        self,
        status: Status | None,
        sensor_set_type_id: str,
        model_generation: MczStoveModelGeneration,
    ) -> None:
        """Retain motherboard identity and refresh the currently reported diagnostics."""
        self.active_database = None
        self.panel_firmware = None
        if status is None:
            return
        serial_number = status.sm_sn
        if isinstance(serial_number, str) and serial_number.strip():
            self.serial_number = serial_number
        board_type = M1_BOARD_TYPES.get(sensor_set_type_id)
        if board_type is None and model_generation is not MczStoveModelGeneration.M1:
            board_type = status.sm_nome_app
        if isinstance(board_type, str) and board_type.strip():
            self.board_type = board_type
        firmware = status.sm_vs_app
        if isinstance(firmware, str) and firmware.strip():
            self.firmware_version = firmware
        is_m1 = (
            model_generation is MczStoveModelGeneration.M1
            or sensor_set_type_id in M1_BOARD_TYPES
        )
        self.active_database = self._get_database_name(
            status.nome_banca_dati_sel, is_m1
        )
        if not is_m1 and isinstance(status.mc_vs_app, str) and status.mc_vs_app.strip():
            self.panel_firmware = status.mc_vs_app

    def _get_database_name(self, value: str | int | None, is_m1: bool) -> str | None:
        """Resolve supported numeric identifiers or preserve a reported database name."""
        if type(value) is int and is_m1:
            return self._DATABASE_NAMES.get(value)
        if isinstance(value, str) and value.strip() and not value.strip().isdecimal():
            return value
        return None

    def get_device_info(
        self, *, unique_code: str, name: str, model_name: str | None
    ) -> DeviceInfo:
        """Map stove identity and retained motherboard details to Home Assistant."""
        device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_code)},
            name=name,
            manufacturer=MANUFACTURER,
            model=model_name,
        )
        if self.serial_number is not None:
            device_info.serial_number = self.serial_number
        if self.software_version is not None:
            device_info.sw_version = self.software_version
        return device_info

    def get_sensor_value(self, name: str) -> str | None:
        """Return a prepared diagnostic without exposing response or model handling."""
        match name:
            case "sm_vs_app":
                return self.software_version
            case "nome_banca_dati_sel":
                return self.active_database
            case "mc_vs_app":
                return self.panel_firmware
            case _:
                raise ValueError(f"Unknown system information sensor: {name}")


class MaestroStove:
    """Class to represent a Maestro Stove. (One instance per device)."""

    def __init__(
        self,
        controller: MaestroControllerInterface,
        stove: StoveInfo,
        on_authentication_failed: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the MaestroStove."""
        self._node = stove.node
        self._controller: MaestroControllerInterface = controller
        self._on_authentication_failed = on_authentication_failed
        self._model: Model | None = None
        self._state: State | None = None
        self._status: Status | None = None
        self._device_metadata = MaestroStoveDeviceMetadata()
        self._is_integration_connected_to_cloud = False
        self._is_stove_connected_to_cloud = False

    async def async_init(self) -> None:
        """Async initialization to retrieve the stove model."""
        await self._getStoveModel()

    @property
    def is_connected(self) -> bool:
        """Return the connection status of the stove (end to end)."""
        return (
            self.is_integration_connected_to_cloud and self.is_stove_connected_to_cloud
        )

    @property
    def is_stove_connected_to_cloud(self) -> bool:
        """Return the connection status of the stove to the cloud."""
        return self._is_stove_connected_to_cloud

    @property
    def is_integration_connected_to_cloud(self) -> bool:
        """Return the connection status of the integration to the cloud."""
        return self._is_integration_connected_to_cloud

    @property
    def Id(self) -> str:
        """Return the stove ID."""
        assert self._node is not None and self._node.id is not None
        return self._node.id

    @property
    def ModelId(self) -> str:
        """Return the model ID."""
        assert self._node is not None and self._node.model_id is not None
        return self._node.model_id

    @property
    def SensorSetTypeId(self) -> str:
        """Return the sensor set type ID."""
        assert self._node is not None and self._node.sensor_set_type_id is not None
        return self._node.sensor_set_type_id

    @property
    def Name(self) -> str:
        """Return the stove name."""
        assert self._node is not None and self._node.name is not None
        return self._node.name

    @property
    def UniqueCode(self) -> str:
        """Return the stove unique code."""
        assert self._node is not None and self._node.unique_code is not None
        return self._node.unique_code

    @property
    def time_zone_iana(self) -> str | None:
        """Return the cloud's timezone for calendar-based history."""
        assert self._node is not None
        return self._node.time_zone_iana

    @property
    def State(self) -> State | None:
        """Return the stove state."""
        return self._state

    @property
    def Status(self) -> Status | None:
        """Return the stove status."""
        return self._status

    @property
    def Model(self) -> Model | None:
        """Return the stove model."""
        return self._model

    @property
    def model_generation(self) -> MczStoveModelGeneration:
        """Recognize M1's ping command, otherwise use M2+."""
        # Catalogue generation labels describe feature definitions, not stove identity.
        # Detect the stove through ping only; matching a feature must not reclassify it.
        if self.Model is None:
            return MczStoveModelGeneration.M2_PLUS

        find_ping = (
            self.get_sensor_configuration_by_model_configuration_name_and_sensor_name
        )
        if find_ping("PING STOVE", "m1_cod_for_spe_mqtt") is not None:
            return MczStoveModelGeneration.M1

        return MczStoveModelGeneration.M2_PLUS

    async def _do_ping_configuration(self, ping: SensorConfiguration) -> None:
        try:
            configuration = ping.configuration
            mappings = configuration.mappings
            if (
                not ping.configuration_id
                or not configuration.sensor_id
                or not configuration.enabled
                or configuration.type != "int"
                or not isinstance(mappings, dict)
                or type(mappings.get("Ping")) is not int
            ):
                raise MaestroConnectionException(
                    f"Invalid M2+ ping configuration for device '{self.Name}'"
                )

            await self._activate_program(
                ping.configuration_id,
                [ProgramCommand(configuration.sensor_id, mappings["Ping"])],
            )
        except MaestroConnectionException as err:
            _LOGGER.warning(
                "M2+ configuration ping failed for '%s'; continuing with cloud refresh: %s",
                self.Name,
                err,
            )

    async def _do_ping_m1_configuration(self, ping: SensorConfiguration) -> None:
        configuration = ping.configuration
        mappings = configuration.mappings
        if (
            not ping.configuration_id
            or not configuration.sensor_id
            or not configuration.enabled
            or configuration.type != "int"
            or not isinstance(mappings, dict)
            or type(mappings.get("C|RecuperoParametri")) is not int
            or mappings.get("C|RecuperoParametri") != 0
            or type(mappings.get("C|RecuperoInfo")) is not int
            or mappings.get("C|RecuperoInfo") != 1
        ):
            raise MaestroConnectionException(
                f"Invalid M1 PING STOVE configuration for device '{self.Name}'"
            )

        for command in ("C|RecuperoParametri", "C|RecuperoInfo"):
            await self._activate_program(
                ping.configuration_id,
                [ProgramCommand(configuration.sensor_id, mappings[command])],
            )
            await asyncio.sleep(1)

    async def _ping(self) -> None:
        m1_ping = (
            self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                "PING STOVE", "m1_cod_for_spe_mqtt"
            )
        )
        if m1_ping is not None:
            try:
                await self._do_ping_m1_configuration(m1_ping)
            except MaestroConnectionException as err:
                raise type(err)(
                    f"Ping for '{self.Name}': {err}", retry_after=err.retry_after
                ) from err
            return

        if False:  # For now, we don't want to ping M2+ stoves, as it can cause issues with some models. This can be re-enabled in the future if needed.
            m2_plus_ping = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                "cod_for_spe_mqtt", "cod_for_spe_mqtt"
            )

            if m2_plus_ping is not None:
                await self._do_ping_configuration(m2_plus_ping)

        await self._controller.do_ping_for_stove(self.Id, self.Name)

    async def _getStoveModel(self) -> None:
        self._model = await self._controller.get_stove_model_for_stove(
            self.ModelId, self.Name
        )

    async def _getStoveStatus(self) -> None:
        self._status = await self._controller.get_stove_status_for_stove(
            self.Id, self.Name
        )
        self._device_metadata.update_from_status(
            self._status, self.SensorSetTypeId, self.model_generation
        )

    async def _getStoveState(self) -> None:
        self._state = await self._controller.get_stove_state_for_stove(
            self.Id, self.Name
        )

    async def refresh(self) -> None:
        """Refresh the stove information, status and state."""
        try:
            await self._ping()
            self._is_integration_connected_to_cloud = self._controller.is_authenticated

            results = await asyncio.gather(
                self._getStoveStatus(), self._getStoveState(), return_exceptions=True
            )
            # Do not let a failed reading hide an account-wide rejection or backoff.
            for result in results:
                if isinstance(result, MaestroAuthenticationException):
                    raise result
            for result in results:
                if (
                    isinstance(result, MaestroConnectionException)
                    and result.retry_after is not None
                ):
                    raise result
            for result in results:
                if isinstance(result, BaseException):
                    raise result

            if self.Status is not None and self.Status.is_connected is not None:
                self._is_stove_connected_to_cloud = self.Status.is_connected
        except MaestroAuthenticationException, MaestroConnectionException:
            self._is_integration_connected_to_cloud = False
            raise

    async def activateProgram(
        self,
        sensor_id: str | None,
        configuration_id: str | None,
        value: object,
        callback_on_success: Callable[[], None] | None = None,
    ) -> None:
        """Activate a program on the stove with a single command."""
        await self.activateProgramMultipleCommands(
            configuration_id, [ProgramCommand(sensor_id, value)], callback_on_success
        )

    async def activateProgramMultipleCommands(
        self,
        configuration_id: str | None,
        commands: list[ProgramCommand],
        callback_on_success: Callable[[], None] | None = None,
    ) -> None:
        """Activate user commands and report failures through Home Assistant."""
        try:
            await self._activate_program(
                configuration_id, commands, callback_on_success
            )
        except MaestroAuthenticationException as err:
            if self._on_authentication_failed is not None:
                self._on_authentication_failed()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_invalid_auth",
            ) from err
        except MaestroConnectionException as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _activate_program(
        self,
        configuration_id: str | None,
        commands: list[ProgramCommand],
        callback_on_success: Callable[[], None] | None = None,
    ) -> None:
        """Keep ping failures unmodified for HA's setup and polling recovery."""
        await self._controller.activate_program_with_commands_for_stove(
            self.Id,
            self.ModelId,
            configuration_id,
            self.SensorSetTypeId,
            commands,
            callback_on_success,
        )

    def get_device_info(self) -> DeviceInfo:
        """Return the stove's identity and retained motherboard details."""
        assert self.Model is not None
        return self._device_metadata.get_device_info(
            unique_code=self.UniqueCode,
            name=self.Name,
            model_name=self.Model.model_name,
        )

    @property
    def device_metadata(self) -> MaestroStoveDeviceMetadata:
        """Return the stove's prepared device details and diagnostic readings."""
        return self._device_metadata

    def get_model_configuration_by_model_configuration_name(
        self, model_configuration_name: str
    ) -> ModelConfiguration | None:
        """Get the model configuration by the name of the model configuration."""
        assert self.Model is not None
        assert self.Model.model_configurations is not None
        return next(
            (
                x
                for x in self.Model.model_configurations
                if x.configuration_name is not None
                and model_configuration_name is not None
                and x.configuration_name.lower().strip()
                == model_configuration_name.lower().strip()
            ),
            None,
        )

    def get_sensor_configuration_by_model_configuration_name_and_sensor_name(
        self, model_configuration_name: str, sensor_name: str | None
    ) -> SensorConfiguration | None:
        """Get the sensor configuration by the name of the model configuration and sensor name."""
        model_configuration = self.get_model_configuration_by_model_configuration_name(
            model_configuration_name
        )
        if model_configuration is None:
            return None

        assert model_configuration.configurations is not None
        sensor_configuration = next(
            (
                x
                for x in model_configuration.configurations
                if x.sensor_name is not None
                and sensor_name is not None
                and x.sensor_name.lower() == sensor_name.lower()
            ),
            None,
        )
        if sensor_configuration is not None:
            return SensorConfiguration(
                sensor_configuration, model_configuration.configuration_id
            )
        return None

    def get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name[
        T: MczConfigItem
    ](
        self, mcz_config_items_list_to_match: Sequence[T]
    ) -> tuple[T, SensorConfiguration] | None:
        """Get the first sensor configuration matching by the name of the model configuration and sensor name."""
        for x in mcz_config_items_list_to_match:
            if x.sensor_set_config_name is not None:
                matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    x.sensor_set_config_name, x.sensor_set_name
                )
                if matching_configuration is not None:
                    return (x, matching_configuration)
        return None

    def get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name[
        T: MczConfigItem
    ](
        self, mcz_config_items_list_to_match: Sequence[T]
    ) -> list[tuple[T, SensorConfiguration]] | None:
        """Get the all sensor configurations matching by the name of the model configuration and sensor name."""
        temp_list = []
        for x in mcz_config_items_list_to_match:
            if x.sensor_set_config_name is not None:
                matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    x.sensor_set_config_name, x.sensor_set_name
                )
                if matching_configuration is not None:
                    temp_list.append((x, matching_configuration))
        if temp_list:
            return temp_list
        return None

    def get_all_matching_sensor_for_all_configurations_by_model_mode_and_sensor_name[
        T: MczConfigItem
    ](
        self, mcz_config_items_list_to_match: Sequence[T]
    ) -> list[tuple[T, SensorConfigurationMultipleModes]] | None:
        """Get the all sensor configurations matching for the matching mode by the name of the model configuration and sensor name."""
        temp_list = []
        for x in mcz_config_items_list_to_match:
            temp_mode_configurations: dict[str, SensorConfiguration] = {}
            if x.mode_to_configuration_name_mapping is not None:
                for mode in x.mode_to_configuration_name_mapping:
                    matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                        x.mode_to_configuration_name_mapping[mode], x.sensor_set_name
                    )
                    if matching_configuration is not None:
                        temp_mode_configurations[mode] = matching_configuration
            if (
                temp_mode_configurations is not None
                and len(temp_mode_configurations) > 0
            ):
                temp_list.append(
                    (x, SensorConfigurationMultipleModes(temp_mode_configurations))
                )
        if temp_list:
            return temp_list
        return None

    def get_supported_sensor_configurations[T: MczConfigItem](
        self, definitions: Sequence[T]
    ) -> list[tuple[T, SensorConfiguration]] | None:
        """Select declared generation-specific commands, then match their advertised names."""
        matches = []
        for definition in definitions:
            if definition.sensor_set_config_name is None:
                continue
            for sensor_name in get_control_names(definition):
                configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    definition.sensor_set_config_name, sensor_name
                )
                if configuration is not None:
                    matches.append((definition, configuration))
        return matches or None

    def get_first_supported_sensor_configuration[T: MczConfigItem](
        self, definitions: Sequence[T]
    ) -> tuple[T, SensorConfiguration] | None:
        """Find the first supported generation-specific command in catalogue order."""
        for definition in definitions:
            matches = self.get_supported_sensor_configurations([definition])
            if matches:
                return matches[0]
        return None
