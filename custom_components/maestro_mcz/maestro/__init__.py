"MaestroStove class."

import asyncio

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
        self._is_connected = False

    async def AsyncInit(self) -> None:
        """Async initialization to retrieve the stove model."""
        await self._getStoveModel()

    @property
    def is_connected(self) -> bool:
        """Return the connection status of the stove."""
        return self._is_connected

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

    async def _ping(self) -> None:
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
            # if the ping is successful and we are authenticated, we can proceed to refresh the status and state
            self._is_connected = self._controller.is_authenticated
        except MaestroAuthenticationException, MaestroConnectionException:
            self._is_connected = False
            raise

        calls = {self._getStoveStatus(), self._getStoveState()}
        await asyncio.gather(*calls, return_exceptions=False)
        # return_exceptions = False to raise the first exception encountered
        # flagging the update as 'failed' and marking the stove as unavailable

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
