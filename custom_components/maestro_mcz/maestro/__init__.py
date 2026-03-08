import dataclasses

from .const import ACTIVATE_PROGRAM_URL, APPLIANCE_URL, PING_URL, STOVE_MODEL_URL
from .controller.controller_interface import MaestroControllerInterface
from .http.request import MczProgramCommand, RequestBuilder
from .responses.model import Model
from .responses.state import State
from .responses.status import Status
from .responses.stove_info import StoveInfo


class MaestroStove:
    """Class to represent a Maestro Stove. (One instance per device)."""

    def __init__(self, controller: MaestroControllerInterface, stove: StoveInfo):
        self._node = stove.node
        self._controller: MaestroControllerInterface = controller
        self._usemockeddata = False
        self._model = None
        self._state = None
        self._status = None

    async def AsyncInit(self):
        self._model = await self.StoveModel()

    @property
    def Id(self) -> str:
        return self._node.id

    @property
    def ModelId(self) -> str:
        return self._node.model_id

    @property
    def SensorSetTypeId(self) -> str:
        return self._node.sensor_set_type_id

    @property
    def Name(self) -> str:
        return self._node.name

    @property
    def UniqueCode(self) -> str:
        return self._node.unique_code

    @property
    def State(self) -> State:
        return self._state

    @property
    def Status(self) -> Status:
        return self._status

    @property
    def Model(self) -> Model:
        return self._model

    async def Ping(self):
        url = f"{PING_URL}/{self.Id}"
        await self._controller.MakeRequest("POST", url=url)

    async def StoveModel(self) -> Model:
        return Model(
            await self._controller.MakeRequest(
                "GET", f"{STOVE_MODEL_URL}/{self.ModelId}"
            )
        )

    async def StoveStatus(self) -> Status:
        return Status(
            await self._controller.MakeRequest(
                "GET", f"{APPLIANCE_URL}/{self.Id}/Status"
            )
        )

    async def StoveState(self) -> State:
        return State(
            await self._controller.MakeRequest(
                "GET", f"{APPLIANCE_URL}/{self.Id}/State"
            )
        )

    async def Refresh(self, include_ping: bool = True):
        if (
            not self._usemockeddata
        ):  # make sure not to execute this code with a mocked controller
            if include_ping:
                await self.Ping()
            self._state = await self.StoveState()
            self._status = await self.StoveStatus()

    def SetMockedData(
        self, model: Model, state: State, status: Status
    ):  # for mocked controller only
        self._model = model
        self._state = state
        self._status = status
        self._usemockeddata = True

    async def ActivateProgram(
        self,
        sensor_id: str,
        configuration_id: str,
        value: object,
        callback_on_success=None,
    ):
        command: list[MczProgramCommand] = [MczProgramCommand(sensor_id, value)]
        await self.ActivateProgramMultipleCommands(
            configuration_id, command, callback_on_success
        )

    async def ActivateProgramMultipleCommands(
        self,
        configuration_id: str,
        commands: list[MczProgramCommand],
        callback_on_success=None,
    ):
        url = f"{ACTIVATE_PROGRAM_URL}/{self.Id}"
        body = RequestBuilder(
            self,
            ConfigurationId=configuration_id,
            Commands=[dataclasses.asdict(ob) for ob in commands],
        )
        success = await self._controller.MakeRequest("POST", url=url, body=body)
        if callback_on_success is not None and success is not None:
            callback_on_success()
