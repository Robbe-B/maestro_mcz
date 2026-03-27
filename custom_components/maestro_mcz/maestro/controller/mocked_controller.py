"""Representation of a MockedController."""

import asyncio
import json
import logging
import os
from pathlib import Path

from .controller_interface import MaestroControllerInterface
from .requests.activate_program import ProgramCommand
from .responses.model import Model
from .responses.state import State
from .responses.status import Status
from .responses.stove_info import AccessControl, Node, StoveInfo

_LOGGER = logging.getLogger(__name__)


class MockedController(MaestroControllerInterface):
    """Class of a MockedController."""

    _mocked_stoves: dict[str, MockedStove] = {}

    def __init__(self, folder_path: str | None) -> None:
        """Initialize the MockedController."""
        self._folder_path = folder_path
        self._username = "username"
        self._password = "password"
        self._is_authenticated = True
        self._token = "token"

    @property
    def is_authenticated(self) -> bool:
        """Returns the current authentication state."""
        return self._is_authenticated

    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        body=None,
        avoid_retries: bool = False,
    ):
        """Simulates making a request to the API (not in mocked implementation)."""
        pass  # noqa: PIE790

    async def retrieve_linked_stove_infos(self) -> list[StoveInfo]:
        """Simulates getting information about the stoves linked to the user account. (from json mock files)."""
        # fill the mocked controller with stove models from the json file(s)
        stoves = []
        file_paths = await self.get_mocked_files()
        if file_paths is not None:
            for _file_path in file_paths:
                try:
                    loop = asyncio.get_running_loop()
                    f = await loop.run_in_executor(None, open, _file_path)
                    data = json.load(f)
                    devices = data["data"]["devices"]
                    for stove in list(devices.values()):
                        stove_data = stove["coordinator.stove_data"]
                        node = Node(None, True)
                        node.id = stove_data["Id"]
                        node.name = stove_data["Name"]
                        node.model_id = stove_data["ModelId"]
                        node.sensor_set_type_id = stove_data["SensorSetTypeId"]
                        node.unique_code = (
                            stove_data["Name"]
                            + "_"
                            + stove_data["Id"]
                            + "_"
                            + stove_data["ModelId"]
                        )
                        maestro_stove_data = StoveInfo(None, True)
                        maestro_stove_data.node = node
                        maestro_stove_data.access_control = AccessControl(None, True)

                        model = Model(stove_data["Model"], True)
                        state = State(stove_data["State"], True)
                        status = Status(stove_data["Status"], True)
                        status.sm_sn = maestro_stove_data.node.unique_code
                        self._mocked_stoves[maestro_stove_data.node.id] = MockedStove(
                            maestro_stove_data, model, state, status
                        )
                        stoves.append(maestro_stove_data)
                except Exception as error:  # noqa: BLE001
                    _LOGGER.error(
                        "Mocked controller failed for (%s) due to a unexpected error: %s",
                        _file_path,
                        error,
                    )
        return stoves

    async def get_mocked_files(self) -> list[str] | None:
        """Check if there are mocked files, if so returns it."""
        try:
            loop = asyncio.get_running_loop()
            folder_path = self._folder_path
            files_in_dir = await loop.run_in_executor(None, os.listdir, folder_path)
            if files_in_dir is not None:
                # Only return regular files, ignore directories
                result: list[str] = []
                for file in files_in_dir:
                    full_path = Path(folder_path) / file
                    if full_path.is_file():
                        result.append(str(full_path))
                return result
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Failed to check mocked files: %s", e)
            return None
        return None

    async def do_ping_for_stove(self, device_id: str, device_name: str) -> None:
        """Pings the stove to check connectivity."""
        pass  # noqa: PIE790

    async def get_stove_model_for_stove(self, model_id: str) -> Model:
        """Gets the stove model for a given model ID."""
        stove = next(
            (
                stove
                for stove in self._mocked_stoves.values()
                if stove.stove_info.node.model_id == model_id
            ),
            None,
        )
        if stove:
            return stove.model
        return None

    async def get_stove_status_for_stove(self, device_id: str) -> Status:
        """Gets the stove status for a given device ID."""
        stove = self._mocked_stoves.get(device_id)
        if stove:
            return stove.status
        return None

    async def get_stove_state_for_stove(self, device_id: str) -> State:
        """Gets the stove state for a given device ID."""
        stove = self._mocked_stoves.get(device_id)
        if stove:
            return stove.state
        return None

    async def activate_program_with_commands_for_stove(
        self,
        device_id: str,
        model_id: str,
        configuration_id: str,
        sensor_set_type_id: str,
        commands: list[ProgramCommand],
        callback_on_success=None,
    ) -> None:
        """Activate a program on the stove with multiple commands for a given device ID."""
        if callback_on_success is not None:
            callback_on_success()


class MockedStove:
    """Class of a MockedStove."""

    stove_info: StoveInfo = None
    model: Model = None
    state: State = None
    status: Status = None

    def __init__(
        self, stove_info: StoveInfo, model: Model, state: State, status: Status
    ) -> None:
        """Initialize the MockedStove."""
        self.stove_info = stove_info
        self.model = model
        self.state = state
        self.status = status
