from typing import Any

import pytest
from pydantic import ValidationError

from matchlens.models.events import MATCH_EVENT_ADAPTER, EventType, format_event_id

ORIGIN = {"x": 52.5, "y": 34.0}
TARGET = {"x": 70.0, "y": 30.0}
ON_BALL: dict[str, Any] = {"team_id": "home", "player_id": "h08", "location": ORIGIN}


def event_payload(event_type: EventType, seq: int = 7, **fields: Any) -> dict[str, Any]:
    return {
        "event_id": format_event_id("m1", seq),
        "match_id": "m1",
        "seq": seq,
        "clock": {"period": 1, "ms": 60_000},
        "type": event_type.value,
        **fields,
    }


PASS_ATTRS: dict[str, Any] = {
    "receiver_id": "h10",
    "length_m": 18.1,
    "height": "ground",
    "under_pressure": False,
    "ball_speed_kmh": 52.0,
}
PASS_ATTRS_WITHOUT_RECEIVER = {
    key: value for key, value in PASS_ATTRS.items() if key != "receiver_id"
}

VALID_EVENTS: dict[EventType, dict[str, Any]] = {
    EventType.KICKOFF: event_payload(EventType.KICKOFF, **ON_BALL),
    EventType.PASS: event_payload(
        EventType.PASS, **ON_BALL, end_location=TARGET, outcome="complete", attrs=PASS_ATTRS
    ),
    EventType.CARRY: event_payload(
        EventType.CARRY, **ON_BALL, end_location=TARGET, attrs={"distance_m": 18.1}
    ),
    EventType.SHOT: event_payload(
        EventType.SHOT,
        **ON_BALL,
        outcome="saved",
        attrs={
            "body_part": "foot",
            "shot_speed_kmh": 104.0,
            "situation": "open_play",
            "assist_event_id": None,
        },
    ),
    EventType.TACKLE: event_payload(
        EventType.TACKLE, **ON_BALL, outcome="won", attrs={"opponent_id": "a07"}
    ),
    EventType.INTERCEPTION: event_payload(EventType.INTERCEPTION, **ON_BALL),
    EventType.PRESSURE: event_payload(
        EventType.PRESSURE, **ON_BALL, attrs={"target_player_id": "a10"}
    ),
    EventType.DUEL: event_payload(
        EventType.DUEL, **ON_BALL, outcome="lost", attrs={"opponent_id": "a04"}
    ),
    EventType.FOUL: event_payload(EventType.FOUL, **ON_BALL, attrs={"fouled_player_id": "a09"}),
    EventType.CARD: event_payload(
        EventType.CARD, team_id="away", player_id="a05", outcome="yellow", attrs={"reason": "foul"}
    ),
    EventType.SUBSTITUTION: event_payload(
        EventType.SUBSTITUTION,
        team_id="home",
        attrs={"player_in_id": "h14", "player_out_id": "h07"},
    ),
    EventType.GOAL: event_payload(
        EventType.GOAL,
        team_id="home",
        player_id="h10",
        attrs={"scorer_id": "h10", "assist_id": "h08", "shot_event_id": format_event_id("m1", 6)},
    ),
    EventType.POSSESSION_CHANGE: event_payload(EventType.POSSESSION_CHANGE, team_id="away"),
    EventType.BALL_OUT: event_payload(EventType.BALL_OUT, location={"x": 105.0, "y": 20.0}),
    EventType.PERIOD_END: event_payload(EventType.PERIOD_END),
    EventType.MATCH_END: event_payload(EventType.MATCH_END),
}


def test_every_event_type_has_a_valid_example() -> None:
    assert set(VALID_EVENTS) == set(EventType)


@pytest.mark.parametrize("event_type", list(EventType))
def test_event_round_trips_through_json(event_type: EventType) -> None:
    event = MATCH_EVENT_ADAPTER.validate_python(VALID_EVENTS[event_type])

    restored = MATCH_EVENT_ADAPTER.validate_json(MATCH_EVENT_ADAPTER.dump_json(event))

    assert restored == event
    assert restored.type == event_type


def test_serialized_event_always_carries_every_envelope_field() -> None:
    event = MATCH_EVENT_ADAPTER.validate_python(VALID_EVENTS[EventType.PERIOD_END])

    assert MATCH_EVENT_ADAPTER.dump_python(event, mode="json") == VALID_EVENTS[
        EventType.PERIOD_END
    ] | {
        "team_id": None,
        "player_id": None,
        "location": None,
        "end_location": None,
        "outcome": None,
        "attrs": {},
    }


def with_changes(event_type: EventType, **changes: Any) -> dict[str, Any]:
    return VALID_EVENTS[event_type] | changes


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (with_changes(EventType.PASS, outcome="won"), "outcome"),
        (with_changes(EventType.TACKLE, outcome="complete"), "outcome"),
        (with_changes(EventType.CARRY, outcome="complete"), "outcome"),
        (with_changes(EventType.PASS, attrs=PASS_ATTRS | {"height": "medium"}), "height"),
        (with_changes(EventType.PASS, attrs=PASS_ATTRS | {"spin": 3}), "spin"),
        (with_changes(EventType.PASS, attrs=PASS_ATTRS_WITHOUT_RECEIVER), "receiver_id"),
        (with_changes(EventType.PASS, attrs=PASS_ATTRS | {"receiver_id": "h08"}), "themselves"),
        (with_changes(EventType.PASS, end_location=None), "end_location"),
        (with_changes(EventType.SHOT, location={"x": 106.0, "y": 34.0}), "location"),
        (with_changes(EventType.PERIOD_END, team_id="home"), "team_id"),
        (with_changes(EventType.INTERCEPTION, attrs={"opponent_id": "a07"}), "opponent_id"),
        (with_changes(EventType.KICKOFF, event_id="m1-7"), "event_id must be m1-000007"),
        (with_changes(EventType.KICKOFF, type="corner"), "corner"),
        (
            with_changes(
                EventType.SUBSTITUTION, attrs={"player_in_id": "a14", "player_out_id": "h07"}
            ),
            "must belong to home",
        ),
        (
            with_changes(EventType.GOAL, player_id="h09"),
            "scorer_id must equal player_id",
        ),
    ],
)
def test_rejects_events_that_break_their_type_contract(
    payload: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        MATCH_EVENT_ADAPTER.validate_python(payload)
