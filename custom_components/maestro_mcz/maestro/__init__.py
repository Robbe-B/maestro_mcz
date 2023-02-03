import json
import aiohttp
import asyncio
import async_timeout

from .responses.status import Status
from .responses.state import State
from .types.mode import ModeEnum
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
            self._stoves.append(MaestroStove(self, stove))

class MaestroStove:
    def __init__(self, controller: MaestroController, stove):
        self._stove = stove
        self._controller: MaestroController = controller
        self._id = stove["Node"]["Id"]
        self._name = stove["Node"]["SensorSetName"]
        self._modelid = stove["Node"]["ModelId"]
        self._sensorsettypeid = stove["Node"]["SensorSetTypeId"]
        self._uniquecode = stove["Node"]["UniqueCode"]

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

    async def Ping(self):
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/Ping/{self.Id}"
        await self._controller.MakeRequest("POST", url=url)

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

    async def Mode(self, Mode: ModeEnum):
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/ActivateProgram/{self.Id}"
        configurationid = "d85b93a4-4cae-4745-925d-ef53547c661e"
        command = [
            {
                "SensorId": "bd064ae8-9091-4696-b137-5a4e243ebb91",
                "Value": int(Mode.value[0]),
            }
        ]
        body = RequestBuilder(self, ConfigurationId=configurationid, Commands=command)
        await self._controller.MakeRequest("POST", url=url, body=body)

    async def Power(self):
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/ActivateProgram/{self.Id}"
        configurationid = "e373bb67-fe69-4d49-b2f2-4b636fa68e37"
        command = [{"SensorId": "9c7f0959-47a2-44ea-906d-f5d22218d00e", "Value": True}]
        body = RequestBuilder(self, ConfigurationId=configurationid, Commands=command)
        await self._controller.MakeRequest("POST", url=url, body=body)

    async def Temperature(self, temp: float):
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/ActivateProgram/{self.Id}"
        configurationid = "875fb696-4af1-42da-bb78-ebe57c90fe5c"
        command = [{"SensorId": "b866d2a9-d0ab-4558-8367-910c52261be1", "Value": temp}]
        body = RequestBuilder(self, ConfigurationId=configurationid, Commands=command)
        await self._controller.MakeRequest("POST", url=url, body=body)

    async def Fan(self, fan: int):
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/ActivateProgram/{self.Id}"
        configurationid = "bcb11620-e1f0-419f-ba03-db4651c34017"
        command = [{"SensorId": "72aac073-1815-4d52-bb2e-2ed7d1c78e1f", "Value": fan}]
        body = RequestBuilder(self, ConfigurationId=configurationid, Commands=command)
        await self._controller.MakeRequest("POST", url=url, body=body)

    async def Pot(self, pot: int):
        url = f"https://s.maestro.mcz.it/mcz/v1.0/Program/ActivateProgram/{self.Id}"
        configurationid = "fa2e1c9e-83e3-4435-825b-cdfb50da92a7"
        command = [{"SensorId": "f7750f3e-9ff2-4351-b53a-6d1a9d1f6bc6", "Value": pot}]
        body = RequestBuilder(self, ConfigurationId=configurationid, Commands=command)
        await self._controller.MakeRequest("POST", url=url, body=body)