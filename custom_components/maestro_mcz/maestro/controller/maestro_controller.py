import json
import aiohttp
import async_timeout

from .. import MaestroStove
from ..const import LOGIN_URL
from ..controller.controller_interface import MaestroControllerInterface

class MaestroController(MaestroControllerInterface):
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

    async def MakeRequest(self, method:str, url:str, headers={}, body=None, recursive_try_on_error:bool = True, is_first_try:bool = True):
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
                    elif(is_first_try or recursive_try_on_error):  #we always try once more in case there was an unsuccessful attempt for the first try or if we need to retry recursively
                        await self.Login()
                        return await self.MakeRequest(
                            method=method, url=url, headers=headers, body=body, recursive_try_on_error=recursive_try_on_error, is_first_try = False
                        )
            except Exception as err:
                print(f"Error making request. Attempting to relogin. Error: {err}")

                #we always try once more in case there was an error for the first try or if we need to retry recursively
                if(is_first_try or recursive_try_on_error):
                    await self.Login()
                    return await self.MakeRequest(
                        method=method, url=url, headers=headers, body=body, recursive_try_on_error=recursive_try_on_error, is_first_try = False
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
            "POST", "https://s.maestro.mcz.it/hlapi/v1.0/Nav/FirstVisibleObjectsPaginated", {}, {}
        )

        for stove in res:
            maesto_stove = MaestroStove(self, stove)
            await maesto_stove.AsyncInit()
            self._stoves.append(maesto_stove)