from typing import Literal

from pydantic import JsonValue

from matchlens.models.base import Contract, Identifier

EnvelopeKind = Literal["event", "frame", "metrics", "cue", "trace", "recap", "status"]


class StreamEnvelope(Contract):
    kind: EnvelopeKind
    match_id: Identifier
    data: dict[str, JsonValue]
