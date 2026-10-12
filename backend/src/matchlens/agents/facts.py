from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from matchlens.models.metrics import MetricSnapshot

REFERENCE_PATTERN = re.compile(r"\{[^{}]*\}")
NO_EVIDENCE_CITED = "no evidence cited"

_PLACES = {"count": 0, "": 0, "%": 1, "km/h": 1, "m": 1, "xG": 2, "ratio": 1, "index": 1}
_ATTACHED_UNITS = {"%"}
_OPENERS = '([{"\u201c\u2018'


def join_body(pieces: Iterable[tuple[str, str | None]]) -> str:
    body: list[str] = []
    after_fact = False
    for text, fact in pieces:
        gap = " " if after_fact and text[:1].isalnum() else ""
        body.append(gap + text)
        after_fact = after_fact and not text
        if fact is None:
            continue
        tail = "".join(body)[-1:]
        if tail and not tail.isspace() and tail not in _OPENERS:
            body.append(" ")
        body.append(fact)
        after_fact = True
    return "".join(body)


def render_fact(snapshot: MetricSnapshot) -> str:
    places = _PLACES[snapshot.unit]
    shown = Decimal(str(snapshot.value)).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    if shown == 0:
        shown = shown.copy_abs()
    if snapshot.unit in {"", "count"}:
        return f"{shown:f}"
    separator = "" if snapshot.unit in _ATTACHED_UNITS else " "
    return f"{shown:f}{separator}{snapshot.unit}"
