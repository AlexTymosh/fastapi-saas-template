from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class ServiceStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


class HealthLiveResponse(BaseModel):
    status: Literal["ok"]


class HealthReadyResponse(BaseModel):
    status: ServiceStatus
    services: dict[str, ServiceStatus]
