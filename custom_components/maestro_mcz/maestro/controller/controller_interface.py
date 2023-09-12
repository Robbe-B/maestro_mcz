class MaestroControllerInterface:
    
    @property
    def Username(self) -> str:
        pass

    @property
    def Password(self) -> str:
        pass

    @property
    def Token(self) -> str:
        pass

    @property
    def Connected(self) -> bool:
        pass

    @property
    def Stoves(self):
        pass
    
    async def MakeRequest(self, method:str, url:str, headers={}, body=None):
        pass

    async def Login(self):
        pass

    async def StoveInfo(self):
        pass