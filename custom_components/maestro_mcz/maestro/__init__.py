import asyncio

from .controller.controller_interface import MaestroControllerInterface

from .responses.model import Model
from .responses.status import Status
from .responses.state import State

from .http.request import RequestBuilder


class MaestroStove:
    def __init__(self, controller: MaestroControllerInterface, stove):
        self._stove = stove
        self._controller: MaestroControllerInterface = controller
        self._id = stove["Node"]["Id"]
        self._name = stove["Node"]["Name"]
        self._modelid = stove["Node"]["ModelId"]
        self._sensorsettypeid = stove["Node"]["SensorSetTypeId"]
        self._uniquecode = stove["Node"]["UniqueCode"]
        self._usemockeddata = False
        self._model = None
        self._state = None
        self._status = None

    async def AsyncInit(self):
        self._model = await self.StoveModel()

    @property
    def Id(self) -> str:
        return self._id

    @property
    def ModelId(self) -> str:
        return self._modelid

    @property
    def SensorSetTypeId(self) -> str:
        return self._sensorsettypeid

    @property
    def Name(self) -> str:
        return self._name

    @property
    def UniqueCode(self) -> str:
        return self._uniquecode

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
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/Ping/{self.Id}"
        await self._controller.MakeRequest("POST", url=url)

    async def StoveModel(self) -> Model:
        return Model(
            await self._controller.MakeRequest(
                "GET", f"https://s.maestro.mcz.it/hlapi/v1.0/Model/{self.ModelId}"
            )
        )

    async def StoveStatus(self) -> Status:
        return Status(
            await self._controller.MakeRequest(
                "GET", f"https://s.maestro.mcz.it/mcz/v1.0/Appliance/{self.Id}/Status"
            )
        )

    async def StoveState(self) -> State:
        return State(
            await self._controller.MakeRequest(
                "GET", f"https://s.maestro.mcz.it/mcz/v1.0/Appliance/{self.Id}/State"
            )
        )

    async def Refresh(self):
        if(not self._usemockeddata): #make sure not to execute this code with a mocked controller
            await self.Ping()
            await asyncio.sleep(3.5) #we need to wait here because there is an actual delay between sending a SET and receiving the updated value from the polled MCZ database
            self._state = await self.StoveState()
            self._status = await self.StoveStatus()
    
    async def SetMockedData(self, model: Model, state: State, status: Status): # for mocked controller only
        self._model = model
        self._state = state
        self._status = status
        self._usemockeddata = True

    async def ActivateProgram(self, sensor_id: str, configuration_id: str, value: object):
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/ActivateProgram/{self.Id}"
        command = [{"SensorId": sensor_id, "Value": value}]
        body = RequestBuilder(self, ConfigurationId=configuration_id, Commands=command)
        await self._controller.MakeRequest("POST", url=url, body=body, recursive_try_on_error = False)