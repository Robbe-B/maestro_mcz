import dataclasses
import json

from ..responses.state import State
from ..responses.status import Status
from ..responses.model import Model
from .. import MaestroStove
from ..controller.controller_interface import MaestroControllerInterface

class MockedController(MaestroControllerInterface):
    def __init__(self, file_paths: list[str]| None):
        self._file_paths = file_paths
        self._username = "username"
        self._password = "password"
        self._connected = True
        self._id = None
        self._token = "token"
        self._stoves = []
        self._stove_models = {}
        self._stove_states = {}
        self._stove_status = {}

    @property
    def Username(self) -> str:
        return self._username

    @property
    def Password(self) -> str:
        return self._password

    @property
    def Token(self) -> str:
        return self._token

    @property
    def Connected(self) -> bool:
        return self._connected

    @property
    def Stoves(self):
        return self._stoves

    async def MakeRequest(self, method: str, url: str, headers={}, body=None):
        return None

    async def Login(self):
        await self.StoveInfo()

    async def StoveInfo(self):
        # fill the mocked controller with stove models from the json file(s)
        if(self._file_paths is not None):
            for _file_path in self._file_paths:
                try:
                    f = open(_file_path)
                    data = json.load(f)
                    devices = data["data"]["devices"]
                    for stove in list(devices.values()):
                        stove_data = stove["coordinator.stove_data"]
                        maestro_stove_data = {
                            "Node": {
                                "Id": stove_data["Id"],
                                "Name": stove_data["Name"],
                                "ModelId": stove_data["ModelId"],
                                "SensorSetTypeId": stove_data["SensorSetTypeId"],
                                "UniqueCode": stove_data["Name"] + "_" + stove_data["Id"] + stove_data["ModelId"],
                            }
                        }

                        self._stove_models[stove_data["ModelId"]] = stove_data["Model"]
                        self._stove_states[stove_data["Id"]] = stove_data["State"]
                        self._stove_status[stove_data["Id"]] = stove_data["Status"]
                        maesto_stove = MaestroStove(self, maestro_stove_data)

                        model = Model(stove_data["Model"], True)
                        state  = State(stove_data["State"], True)
                        status = Status(stove_data["Status"], True)
                        status.sm_sn = maestro_stove_data["Node"]["UniqueCode"]
                        await maesto_stove.SetMockedData(model, state, status)
                        self._stoves.append(maesto_stove)
                except Exception as error:
                    pass