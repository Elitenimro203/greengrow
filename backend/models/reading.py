from pydantic import BaseModel, Field
from typing import Optional

class SensorReading(BaseModel):
    bac_id: str
    timestamp: float
    moisture_percent: float = Field(ge=0.0, le=100.0)
    temperature_celsius: float = Field(ge=-10.0, le=60.0)
    humidity_air_percent: float = Field(ge=0.0, le=100.0)
    pump_active: bool
    source: Optional[str] = "hardware"