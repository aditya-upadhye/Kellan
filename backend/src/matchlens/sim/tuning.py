from dataclasses import dataclass

MsRange = tuple[int, int]


@dataclass(frozen=True, slots=True)
class EngineTuning:
    pressure_base: float = 0.05
    pressure_style_weight: float = 0.35
    build_up_press_floor: float = 0.6
    build_up_press_style_weight: float = 0.8
    build_up_zone_end_m: float = 60.0
    pressured_threshold: float = 0.5
    final_third_pressure_factor: float = 1.3

    shot_min_progress_m: float = 70.0
    shot_weight_scale: float = 2.5
    shot_xg_exponent: float = 1.0
    pass_weight: float = 0.7
    pass_possession_style_weight: float = 0.5
    carry_weight: float = 0.24
    carry_pressure_damping: float = 0.5
    transition_carry_boost: float = 0.6
    dribble_weight: float = 0.06
    final_third_dribble_boost: float = 1.5
    transition_length_actions: int = 3

    pass_distance_scale_m: float = 16.0
    pass_min_length_m: float = 4.0
    pass_max_length_m: float = 65.0
    forward_pass_directness_weight: float = 1.0
    backward_pass_directness_damping: float = 0.6
    goalkeeper_pass_weight_own_third: float = 0.15
    goalkeeper_pass_weight_elsewhere: float = 0.01
    pass_target_noise_m: float = 1.5

    pass_base_success: float = 0.95
    pass_free_length_m: float = 12.0
    pass_length_penalty: float = 0.006
    pass_pressure_penalty: float = 0.15
    low_pass_penalty: float = 0.04
    high_pass_penalty: float = 0.14
    pass_skill_weight: float = 0.004
    final_third_pass_penalty: float = 0.05
    box_pass_penalty: float = 0.12
    min_pass_success: float = 0.2
    max_pass_success: float = 0.98

    offside_share: float = 0.12
    out_of_play_share: float = 0.25
    interception_share: float = 0.55
    loose_ball_defender_share: float = 0.6

    carry_min_m: float = 3.0
    carry_max_m: float = 12.0
    carry_heading_sd_rad: float = 0.6
    final_third_carry_factor: float = 0.6
    second_half_pace_factor: float = 0.95
    carry_challenge_base: float = 0.14
    carry_challenge_pressure_weight: float = 0.15
    penalty_area_challenge_factor: float = 1.5
    foul_share_of_challenges: float = 0.26
    pressure_foul_share: float = 0.015
    penalty_area_foul_factor: float = 0.1
    booked_player_foul_factor: float = 0.5
    tackle_base_win: float = 0.55
    tackle_skill_weight: float = 0.006
    dribble_base_win: float = 0.5
    dribble_skill_weight: float = 0.006
    dribble_gain_m: tuple[float, float] = (3.0, 7.0)

    finishing_weight: float = 0.5
    keeper_weight: float = 0.4
    pressured_shot_penalty: float = 0.4
    header_after_cross_share: float = 0.6
    non_goal_outcome_weights: tuple[float, float, float, float] = (0.27, 0.38, 0.32, 0.03)
    penalty_miss_weights: tuple[float, float, float, float] = (0.0, 0.6, 0.35, 0.05)
    save_to_corner_share: float = 0.3
    block_to_corner_share: float = 0.35
    rebound_attacker_share: float = 0.3

    yellow_share: float = 0.15
    straight_red_share: float = 0.004
    direct_free_kick_share: float = 0.35
    direct_free_kick_max_distance_m: float = 30.0
    free_kick_cross_share: float = 0.5
    corner_header_share: float = 0.5

    substitutions_per_team: tuple[int, int] = (3, 5)
    substitution_window_ms: MsRange = (600_000, 2_100_000)

    pass_duration_ms: MsRange = (1_500, 2_500)
    pass_duration_per_m_ms: int = 30
    max_pass_duration_ms: int = 4_000
    carry_duration_base_ms: int = 1_000
    carry_duration_per_m_ms: int = 330
    duel_duration_ms: MsRange = (1_000, 2_000)
    shot_duration_ms: MsRange = (1_000, 2_000)
    ball_out_stoppage_ms: MsRange = (8_000, 20_000)
    foul_stoppage_ms: MsRange = (20_000, 40_000)
    goal_stoppage_ms: MsRange = (45_000, 75_000)
    added_time_ms: MsRange = (60_000, 300_000)


DEFAULT_TUNING = EngineTuning()
