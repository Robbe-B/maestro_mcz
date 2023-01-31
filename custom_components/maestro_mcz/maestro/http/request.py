def RequestBuilder(self, ConfigurationId: str, Commands: str):
    return  {
                "ModelId": self.ModelId,
                "ConfigurationId":ConfigurationId,
                "SensorSetTypeId":self.SensorSetTypeId,
                "Commands":Commands
            }