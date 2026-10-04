from pydantic import Field

from matchlens.models.base import Contract

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0


class Point(Contract):
    x: float = Field(ge=0.0, le=PITCH_LENGTH_M)
    y: float = Field(ge=0.0, le=PITCH_WIDTH_M)
