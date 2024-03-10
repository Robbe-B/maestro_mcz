from dataclasses import dataclass

def RequestBuilder(self, ConfigurationId: str, Commands: str):
    return  {
                "ModelId": self.ModelId,
                "ConfigurationId":ConfigurationId,
                "SensorSetTypeId":self.SensorSetTypeId,
                "Commands":Commands
            }

@dataclass
class MczProgramCommand:
    SensorId: str | None = None
    Value: object | None = None

    def __init__(self, sensor_id: str | None, value: object | None ) -> None:
        self.SensorId = sensor_id
        self.Value = value