from __future__ import annotations

import pytest

from matchlens.agents.facts import join_body

SHIFT = "Momentum shifts by"
SURGE = "as the away side surges"


@pytest.mark.parametrize(
    ("pieces", "body"),
    [
        ([(SHIFT, "-39.2 index")], f"{SHIFT} -39.2 index"),
        ([(f"{SHIFT} ", "-39.2 index")], f"{SHIFT} -39.2 index"),
        ([("", "-39.2 index")], "-39.2 index"),
        ([("Momentum (", "-39.2 index"), (")", None)], "Momentum (-39.2 index)"),
        ([("by", "-39.2 index"), (SURGE, None)], f"by -39.2 index {SURGE}"),
        ([("by", "-39.2 index"), (".", None)], "by -39.2 index."),
        ([("by", "-39.2 index"), (", then", None)], "by -39.2 index, then"),
        ([("by", "-39.2 index"), (" as", None)], "by -39.2 index as"),
        ([("from", "-72.0 index"), ("to", "-39.2 index")], "from -72.0 index to -39.2 index"),
        ([("Home has", "2"), ("goals", None)], "Home has 2 goals"),
        ([("Held at", "46.1%"), ("possession", None)], "Held at 46.1% possession"),
    ],
)
def test_rendered_value_gets_grammatical_spacing(
    pieces: list[tuple[str, str | None]], body: str
) -> None:
    assert join_body(pieces) == body


def test_value_text_is_never_changed_by_spacing() -> None:
    body = join_body([("by", "-39.2 index"), ("as", None)])

    assert body.count("-39.2 index") == 1
