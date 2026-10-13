from typing import Literal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from matchlens.agents.producer import ProducerScheduler, priority_for
from matchlens.models.clock import MatchClock
from matchlens.models.cues import CheckerResult, CueProvenance, CueSlot, OverlayCue
from matchlens.models.insights import MomentType


def clock(ms: int, period: Literal[1, 2] = 1) -> MatchClock:
    return MatchClock(period=period, ms=ms)


def elapsed(match_clock: MatchClock) -> int:
    return (match_clock.period - 1) * 45 * 60_000 + match_clock.ms


def cue(
    cue_id: str,
    *,
    profile_id: str = "profile-a",
    slot: CueSlot = "lower_third",
    seq: int = 1,
    ms: int = 0,
    priority: int = 50,
    duration_ms: int = 5_000,
    expiry_ms: int = 60_000,
    start_delay_ms: int = 0,
) -> OverlayCue:
    return OverlayCue(
        cue_id=cue_id,
        match_id="match-a",
        profile_id=profile_id,
        insight_id=f"insight-{cue_id}",
        trigger_seq=seq,
        clock=clock(ms),
        template="moment_card",
        slot=slot,
        priority=priority,
        start_delay_ms=start_delay_ms,
        duration_ms=duration_ms,
        expires_at=clock(expiry_ms),
        headline="A moment",
        body="Match update",
        language="en",
        data={},
        provenance=CueProvenance(
            metric_ids=[],
            checker=CheckerResult(passed=True, attempts=1, version="test"),
            model_ids=[],
        ),
    )


def test_schedules_only_one_cue_per_profile_slot_and_applies_noncritical_gap() -> None:
    scheduler = ProducerScheduler()

    first = scheduler.offer(cue("one"), "milestone", clock(0), wall_ms=0)
    second = scheduler.offer(cue("two", seq=2, ms=1_000), "milestone", clock(1_000), wall_ms=1_000)
    assert [item.cue_id for item in first.delivered] == ["one"]
    assert second.delivered == ()

    after_duration = scheduler.advance(clock(5_000), wall_ms=5_000)
    assert after_duration.delivered == ()
    paced = scheduler.advance(clock(20_000), wall_ms=20_000)
    assert [item.cue_id for item in paced.delivered] == ["two"]
    assert paced.delivered[0].start_delay_ms == 0


def test_goal_preempts_lower_priority_cue_and_bypasses_pacing() -> None:
    scheduler = ProducerScheduler()
    scheduler.offer(cue("ordinary", priority=40), "milestone", clock(0), wall_ms=0)

    result = scheduler.offer(
        cue("goal", seq=2, ms=1_000, priority=100), "goal", clock(1_000), wall_ms=1_000
    )

    assert [item.cue_id for item in result.preempted] == ["ordinary"]
    assert [item.cue_id for item in result.delivered] == ["goal"]


def test_card_preempts_lower_priority_pending_cue() -> None:
    scheduler = ProducerScheduler()
    scheduler.offer(cue("active", slot="side_panel"), "milestone", clock(0), wall_ms=0)
    scheduler.offer(
        cue("waiting", seq=2, ms=1_000, priority=30), "milestone", clock(1_000), wall_ms=1_000
    )

    result = scheduler.offer(
        cue("card", seq=3, ms=2_000, priority=90), "card", clock(2_000), wall_ms=2_000
    )

    assert [item.cue_id for item in result.preempted] == ["active", "waiting"]
    assert [item.cue_id for item in result.delivered] == ["card"]


def test_delivery_preserves_trigger_order_when_critical_cue_arrives() -> None:
    scheduler = ProducerScheduler()
    scheduler.offer(cue("active", duration_ms=30_000), "milestone", clock(0), wall_ms=0)
    scheduler.offer(
        cue("earlier", seq=2, ms=500, slot="side_panel", priority=100, start_delay_ms=2_000),
        "milestone",
        clock(500),
        wall_ms=500,
    )

    critical = scheduler.offer(
        cue("goal", seq=3, ms=600, priority=100), "goal", clock(600), wall_ms=600
    )
    assert [item.cue_id for item in critical.preempted] == ["active"]
    assert critical.delivered == ()

    delivered = scheduler.advance(clock(20_000), wall_ms=20_000)
    assert [item.cue_id for item in delivered.delivered] == ["earlier", "goal"]


def test_cues_in_different_profiles_and_slots_do_not_block_each_other() -> None:
    scheduler = ProducerScheduler()
    scheduler.offer(cue("first"), "milestone", clock(0), wall_ms=0)

    result = scheduler.offer(
        cue("other-slot", profile_id="profile-b", slot="side_panel", seq=2),
        "milestone",
        clock(1_000),
        wall_ms=1_000,
    )

    assert [item.cue_id for item in result.delivered] == ["other-slot"]


def test_pending_cue_expires_without_delivery() -> None:
    scheduler = ProducerScheduler()
    scheduler.offer(cue("active"), "milestone", clock(0), wall_ms=0)
    scheduler.offer(
        cue("stale", seq=2, ms=1_000, expiry_ms=10_000),
        "milestone",
        clock(1_000),
        wall_ms=1_000,
    )

    result = scheduler.advance(clock(10_000), wall_ms=10_000)

    assert [item.cue_id for item in result.expired] == ["stale"]
    assert result.delivered == ()


def test_slot_duration_uses_wall_time_while_expiry_uses_match_time() -> None:
    scheduler = ProducerScheduler()
    scheduler.offer(cue("goal", duration_ms=5_000), "goal", clock(0), wall_ms=0)
    scheduler.offer(cue("card", seq=2, ms=1_000, priority=50), "card", clock(1_000), wall_ms=100)

    still_occupied = scheduler.advance(clock(50_000), wall_ms=4_999)
    assert still_occupied.delivered == ()

    available = scheduler.advance(clock(50_000), wall_ms=5_000)
    assert [item.cue_id for item in available.delivered] == ["card"]


def test_clock_advances_across_halftime_and_rejects_reversal() -> None:
    scheduler = ProducerScheduler()
    scheduler.offer(
        cue("first", ms=1_000, duration_ms=1_000), "milestone", clock(1_000), wall_ms=1_000
    )

    result = scheduler.advance(clock(0, period=2), wall_ms=2_000)

    assert result.expired == ()
    with pytest.raises(ValueError, match="cannot move backwards"):
        scheduler.advance(clock(44 * 60_000, period=1), wall_ms=3_000)


@pytest.mark.parametrize(
    ("significance", "favorite", "expected"),
    [(0.0, False, 0), (0.42, False, 42), (0.42, True, 62), (1.0, True, 100)],
)
def test_priority_for(significance: float, favorite: bool, expected: int) -> None:
    assert priority_for(significance, favorite) == expected


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=15_000),
            st.sampled_from(["lower_third", "side_panel"]),
            st.integers(min_value=0, max_value=100),
            st.sampled_from(["milestone", "goal", "card"]),
            st.integers(min_value=1, max_value=10_000),
        ),
        min_size=1,
        max_size=30,
    )
)
def test_property_no_profile_has_two_active_cues_in_one_slot(
    offers: list[tuple[int, CueSlot, int, MomentType, int]],
) -> None:
    scheduler = ProducerScheduler()
    active: dict[tuple[str, str], tuple[OverlayCue, int]] = {}
    now_ms = 0

    for index, (delta, slot, priority, moment_type, duration) in enumerate(offers, 1):
        now_ms += delta
        now = clock(now_ms)
        active = {
            key: (active_cue, ends_at)
            for key, (active_cue, ends_at) in active.items()
            if ends_at > now_ms
        }
        offered = cue(
            f"cue-{index}",
            slot=slot,
            seq=index,
            ms=now_ms,
            priority=priority,
            duration_ms=duration,
            expiry_ms=now_ms + 60_000,
        )
        result = scheduler.offer(offered, moment_type, now, wall_ms=now_ms)
        for removed in (*result.preempted, *result.expired):
            active.pop((removed.profile_id, removed.slot), None)
        for delivered in result.delivered:
            key = (delivered.profile_id, delivered.slot)
            assert key not in active
            active[key] = (delivered, now_ms + delivered.duration_ms)

        assert len(active) == len(set(active))
