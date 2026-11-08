"MaestroStove class."

import asyncio
import logging

from homeassistant.helpers.entity import DeviceInfo

from ..const import DOMAIN, MANUFACTURER
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
from .models.models import MczConfigItem


_LOGGER = logging.getLogger(__name__)


class MaestroStove:
    """Class to represent a Maestro Stove. (One instance per device)."""

    def __init__(
        self, controller: MaestroControllerInterface, stove: StoveInfo
    ) -> None:
        """Initialize the MaestroStove."""
        self._node = stove.node
        self._controller: MaestroControllerInterface = controller
        self._model = None
        self._state = None
        self._status = None
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
        return self._node.id

    @property
    def ModelId(self) -> str:
        """Return the model ID."""
        return self._node.model_id

    @property
    def SensorSetTypeId(self) -> str:
        """Return the sensor set type ID."""
        return self._node.sensor_set_type_id

    @property
    def Name(self) -> str:
        """Return the stove name."""
        return self._node.name

    @property
    def UniqueCode(self) -> str:
        """Return the stove unique code."""
        return self._node.unique_code

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

            await self.activateProgram(
                configuration.sensor_id,
                ping.configuration_id,
                mappings["Ping"],
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
            await self.activateProgram(
                configuration.sensor_id,
                ping.configuration_id,
                mappings[command],
            )
            await asyncio.sleep(1)

    async def _ping(self) -> None:
        m1_ping = (
            self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                "PING STOVE", "m1_cod_for_spe_mqtt"
            )
        )
        if m1_ping is not None:
            await self._do_ping_m1_configuration(m1_ping)
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

    async def _getStoveState(self) -> None:
        self._state = await self._controller.get_stove_state_for_stove(
            self.Id, self.Name
        )

    async def refresh(self):
        """Refresh the stove information, status and state."""
        try:
            await self._ping()
            self._is_integration_connected_to_cloud = self._controller.is_authenticated

            calls = {self._getStoveStatus(), self._getStoveState()}
            await asyncio.gather(*calls, return_exceptions=False)

            if self.Status is not None and self.Status.is_connected is not None:
                self._is_stove_connected_to_cloud = self.Status.is_connected
        except MaestroAuthenticationException, MaestroConnectionException:
            self._is_integration_connected_to_cloud = False
            raise

    async def activateProgram(
        self,
        sensor_id: str,
        configuration_id: str,
        value: object,
        callback_on_success=None,
    ):
        """Activate a program on the stove with a single command."""
        await self.activateProgramMultipleCommands(
            configuration_id, [ProgramCommand(sensor_id, value)], callback_on_success
        )

    async def activateProgramMultipleCommands(
        self,
        configuration_id: str,
        commands: list[ProgramCommand],
        callback_on_success=None,
    ):
        """Activate a program on the stove with multiple commands."""
        await self._controller.activate_program_with_commands_for_stove(
            self.Id,
            self.ModelId,
            configuration_id,
            self.SensorSetTypeId,
            commands,
            callback_on_success,
        )

    def get_device_info(self) -> DeviceInfo:
        """Return device info."""
        sw_version = ""

        if self.is_connected:
            sw_version = (
                f"{self.Status.sm_nome_app}.{self.Status.sm_vs_app}"
                f", Panel:{self.Status.mc_vs_app}"
                f", DB:{self.Status.nome_banca_dati_sel}"
            )
        else:
            sw_version = "Device Disconnected"

        return DeviceInfo(
            identifiers={(DOMAIN, self.UniqueCode)},
            name=self.Name,
            manufacturer=MANUFACTURER,
            model=self.Model.model_name,
            sw_version=sw_version,
        )

    def get_model_configuration_by_model_configuration_name(
        self, model_configuration_name: str
    ) -> ModelConfiguration | None:
        """Get the model configuration by the name of the model configuration."""
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
        self, model_configuration_name: str, sensor_name: str
    ) -> SensorConfiguration | None:
        """Get the sensor configuration by the name of the model configuration and sensor name."""
        model_configuration = self.get_model_configuration_by_model_configuration_name(
            model_configuration_name
        )
        if model_configuration is None:
            return None

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

    def get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
        self, mcz_config_items_list_to_match: list[MczConfigItem]
    ) -> tuple[MczConfigItem, SensorConfiguration] | None:
        """Get the first sensor configuration matching by the name of the model configuration and sensor name."""
        for x in mcz_config_items_list_to_match:
            if x.sensor_set_config_name is not None:
                matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    x.sensor_set_config_name, x.sensor_set_name
                )
                if matching_configuration is not None:
                    return (x, matching_configuration)
        return None

    def get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        self, mcz_config_items_list_to_match: list[MczConfigItem]
    ) -> list[tuple[MczConfigItem, SensorConfiguration]] | None:
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

    def get_all_matching_sensor_for_all_configurations_by_model_mode_and_sensor_name(
        self, mcz_config_items_list_to_match: list[MczConfigItem]
    ) -> list[tuple[MczConfigItem, SensorConfigurationMultipleModes]] | None:
        """Get the all sensor configurations matching for the matching mode by the name of the model configuration and sensor name."""
        temp_list = []
        for x in mcz_config_items_list_to_match:
            if x.mode_to_configuration_name_mapping is not None:
                temp_mode_configurations: dict[str, SensorConfiguration] = {}
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
