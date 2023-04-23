import json
from uuid import UUID
import aiohttp
import asyncio
import async_timeout

from .responses.model import Model
from .responses.status import Status
from .responses.state import State

from .http.request import RequestBuilder
from .const import LOGIN_URL


class MaestroController:
    def __init__(self, username, password):
        self._username = username
        self._password = password
        self._connected = False
        self._id = None
        self._token = None
        self._stoves = []

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

    async def MakeRequest(self, method, url, headers={}, body=None):
        async with async_timeout.timeout(15):
            headers["auth-token"] = self._token

            try:
                async with aiohttp.ClientSession() as session:
                    if method == "GET":
                        async with session.get(url, headers=headers) as resp:
                            response = await resp.json()
                    elif method == "POST":
                        headers["content-type"] = "application/json"
                        jbody = json.dumps(body, ensure_ascii=False)
                        async with session.post(url, headers=headers, data=jbody) as resp:
                            response = await resp.json()
                    if resp.status == 200:
                        return response
                    else:
                        await self.Login()
                        return await self.MakeRequest(
                            method=method, url=url, headers=headers, body=body
                        )
            except:
                print("Error making request. Attempting to relogin")
                await self.Login()
                return await self.MakeRequest(
                    method=method, url=url, headers=headers, body=body
                )

    async def Login(self):
        LOGIN_BODY = {"username": self.Username, "password": self.Password}

        headers = {}
        headers["content-type"] = "application/json"
        headers["tenantid"] = "7c201fd8-42bd-4333-914d-0f5822070757"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                LOGIN_URL, json=LOGIN_BODY, headers=headers
            ) as resp:
                response = await resp.json()
                self._token = response["Token"]
                self._connected = True

        await self.StoveInfo()

    async def StoveInfo(self):
        if self.Connected == False:
            await self.Login()
        res = await self.MakeRequest(
            "GET", "https://s.maestro.mcz.it/hlapi/v1.0/Nav/Auth/FirstVisibleObjects"
        )

        for stove in res:
            maesto_stove = MaestroStove(self, stove)
            await maesto_stove.AsyncInit()
            self._stoves.append(maesto_stove)


class MaestroStove:
    def __init__(self, controller: MaestroController, stove):
        self._stove = stove
        self._controller: MaestroController = controller
        self._id = stove["Node"]["Id"]
        self._name = stove["Node"]["SensorSetName"]
        self._modelid = stove["Node"]["ModelId"]
        self._sensorsettypeid = stove["Node"]["SensorSetTypeId"]
        self._uniquecode = stove["Node"]["UniqueCode"]

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
        await self.Ping()
        await asyncio.sleep(5)
        self._state = await self.StoveState()
        self._status = await self.StoveStatus()

    async def ActivateProgram(self, sensor_id: UUID, configuration_id: UUID, value: object):
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/ActivateProgram/{self.Id}"
        command = [{"SensorId": str(sensor_id), "Value": value}]
        body = RequestBuilder(self, ConfigurationId=str(configuration_id), Commands=command)
        await self._controller.MakeRequest("POST", url=url, body=body)