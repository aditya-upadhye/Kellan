from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
PlayerId = Annotated[str, StringConstraints(pattern=r"^[ha]\d{2}$")]
TeamSide = Literal["home", "away"]
Language = Literal["en", "es"]


class Contract(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        json_schema_serialization_defaults_required=True,
    )
