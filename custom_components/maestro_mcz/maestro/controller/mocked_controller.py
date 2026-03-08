"""Representation of a MockedController."""

import asyncio
import json
import logging
import os
from pathlib import Path

from .. import MaestroStove
from ..controller.controller_interface import MaestroControllerInterface
from ..responses.model import Model
from ..responses.state import State
from ..responses.status import Status
from ..responses.stove_info import AccessControl, Node, StoveInfo

_LOGGER = logging.getLogger(__name__)


class MockedController(MaestroControllerInterface):
    """Class of a MockedController."""

    def __init__(self, folder_path: str | None):
        self._folder_path = folder_path
        self._username = "username"
        self._password = "password"
        self._connected = True
        self._token = "token"
        self._stoves = []

    @property
    def Connected(self) -> bool:
        """Returns the current connection state."""
        return self._connected

    @property
    def Stoves(self):
        """Returns a list of mocked stoves."""
        return self._stoves

    async def MakeRequest(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        body=None,
    ):
        """Simulates making a request to the API (not in mocked implementation)."""
        return None

    async def StoveInfo(self):
        """Simulates getting information about the stoves linked to the user account. (from json mock files)."""
        # fill the mocked controller with stove models from the json file(s)
        self._stoves = []
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
                        maesto_stove = MaestroStove(self, maestro_stove_data)

                        model = Model(stove_data["Model"], True)
                        state = State(stove_data["State"], True)
                        status = Status(stove_data["Status"], True)
                        status.sm_sn = maestro_stove_data.node.unique_code
                        maesto_stove.SetMockedData(model, state, status)
                        self._stoves.append(maesto_stove)
                except Exception as error:  # noqa: BLE001
                    _LOGGER.error(
                        "Mocked controller failed for (%s) due to a unexpected error: %s",
                        _file_path,
                        error,
                    )

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
