from matchlens.models.pitch import PITCH_LENGTH_M, PITCH_WIDTH_M
from matchlens.sim.space import (
    CENTRE_LATERAL_M,
    HALFWAY_M,
    Spot,
    clamp_to_pitch,
    from_attacking_frame,
    to_attacking_frame,
)
from matchlens.sim.squad import PlayerState, TeamState

IN_POSSESSION_SHIFT = 0.6
OUT_OF_POSSESSION_SHIFT = 0.5
OUT_OF_POSSESSION_RETREAT_M = 9.0
OUT_OF_POSSESSION_COMPACTNESS = 0.8
IN_POSSESSION_LATERAL_PULL = 0.3
OUT_OF_POSSESSION_LATERAL_PULL = 0.45
DEFENSIVE_LINE_ANCHOR_M = 30.0
OFFSIDE_LINE_TOLERANCE_M = 0.5
GOALKEEPER_BASE_DEPTH_M = 4.0
GOALKEEPER_STEP_UP = 0.12
GOALKEEPER_MAX_DEPTH_M = 18.0
EDGE_MARGIN_M = 1.0


def team_shape(
    team: TeamState, ball: Spot, *, attacking_right: bool, in_possession: bool
) -> dict[str, Spot]:
    ball_in_frame = to_attacking_frame(ball, attacking_right=attacking_right)
    shape: dict[str, Spot] = {}
    for player in team.on_pitch():
        frame_spot = (
            _goalkeeper_spot(ball_in_frame)
            if player.is_goalkeeper
            else _outfield_spot(team, player, ball_in_frame, in_possession=in_possession)
        )
        shape[player.player_id] = clamp_to_pitch(
            from_attacking_frame(frame_spot, attacking_right=attacking_right)
        )
    return shape


def _goalkeeper_spot(ball_in_frame: Spot) -> Spot:
    depth = GOALKEEPER_BASE_DEPTH_M + max(0.0, ball_in_frame.x - 30.0) * GOALKEEPER_STEP_UP
    lateral = CENTRE_LATERAL_M + (ball_in_frame.y - CENTRE_LATERAL_M) * 0.1
    return Spot(min(depth, GOALKEEPER_MAX_DEPTH_M), lateral)


def _outfield_spot(
    team: TeamState, player: PlayerState, ball_in_frame: Spot, *, in_possession: bool
) -> Spot:
    anchor_depth, anchor_lateral = team.anchor_of(player)
    ball_offset = ball_in_frame.x - HALFWAY_M
    if in_possession:
        onside_limit = max(ball_in_frame.x, opponent_defensive_line(ball_in_frame.x))
        depth = min(anchor_depth + ball_offset * IN_POSSESSION_SHIFT, onside_limit)
        lateral_pull = IN_POSSESSION_LATERAL_PULL
    else:
        depth = _defending_depth(anchor_depth, ball_offset)
        lateral_pull = OUT_OF_POSSESSION_LATERAL_PULL
    lateral = anchor_lateral + (ball_in_frame.y - CENTRE_LATERAL_M) * lateral_pull
    return Spot(
        min(max(depth, EDGE_MARGIN_M), PITCH_LENGTH_M - EDGE_MARGIN_M),
        min(max(lateral, EDGE_MARGIN_M), PITCH_WIDTH_M - EDGE_MARGIN_M),
    )


def opponent_defensive_line(ball_depth: float) -> float:
    ball_offset_for_defenders = (PITCH_LENGTH_M - ball_depth) - HALFWAY_M
    line_depth = _defending_depth(DEFENSIVE_LINE_ANCHOR_M, ball_offset_for_defenders)
    return PITCH_LENGTH_M - line_depth + OFFSIDE_LINE_TOLERANCE_M


def _defending_depth(anchor_depth: float, ball_offset: float) -> float:
    shifted = anchor_depth + ball_offset * OUT_OF_POSSESSION_SHIFT - OUT_OF_POSSESSION_RETREAT_M
    return HALFWAY_M + (shifted - HALFWAY_M) * OUT_OF_POSSESSION_COMPACTNESS
