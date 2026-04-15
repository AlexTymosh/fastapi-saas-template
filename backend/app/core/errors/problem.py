from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InvalidParam(BaseModel):
    name: str
    reason: str
    pointer: str | None = None
    code: str | None = None


class ProblemDetails(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None

    error_code: str | None = None
    request_id: str | None = None
    errors: list[InvalidParam] | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
