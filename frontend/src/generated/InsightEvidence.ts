export type JsonValue = unknown

export interface InsightEvidence {
  evidence_id: string
  insight_id: string
  match_id: string
  moment: Moment
  versions: EvidenceVersion[]
  replay: EvidenceReplay
  traces: AgentTrace[]
  interpretation_note: string
  replay_duration_ms: number
}
export interface Moment {
  moment_id: string
  match_id: string
  type:
    | 'goal'
    | 'big_chance'
    | 'card'
    | 'momentum_swing'
    | 'press_shift'
    | 'control_shift'
    | 'milestone'
    | 'speed_alert'
    | 'player_spotlight'
  seq_start: number
  seq_end: number
  clock: MatchClock
  rule_score: number
  significance: number
  evidence_metric_ids: string[]
  subject_ids: string[]
  source: 'rule' | 'agent' | 'fallback'
}
export interface MatchClock {
  period: 1 | 2
  ms: number
}
export interface EvidenceVersion {
  cue: OverlayCue
  claims: ClaimEvidence[]
  numeric_check_passed: boolean
  errors: CheckError[]
}
export interface OverlayCue {
  cue_id: string
  match_id: string
  profile_id: string
  insight_id: string
  trigger_seq: number
  clock: MatchClock
  template: 'stat_bar' | 'player_tag' | 'moment_card' | 'momentum_graph' | 'speed_badge' | 'recap_panel'
  slot: 'lower_third' | 'top_right' | 'side_panel' | 'full_screen'
  priority: number
  start_delay_ms: number
  duration_ms: number
  expires_at: MatchClock
  headline: string
  body: string
  language: 'en' | 'es'
  data: {
    [k: string]: JsonValue
  }
  provenance: CueProvenance
}
export interface CueProvenance {
  metric_ids: string[]
  checker: CheckerResult
  model_ids: string[]
}
export interface CheckerResult {
  passed: boolean
  attempts: number
  version: string
}
export interface ClaimEvidence {
  claim: Claim
  snapshot: MetricSnapshot | null
  recomputed_value: number | null
  recomputation: 'matched' | 'mismatch' | 'unavailable'
  method: string
  scope_note: string
  source_event_ids: string[]
}
export interface Claim {
  claim_id: string
  text_span: string
  metric_id: string
  value: number
  as_of_seq: number
}
export interface MetricSnapshot {
  metric_id: string
  scope: 'match' | 'team' | 'player' | 'event'
  subject_id: string | null
  label: string
  value: number
  unit: '' | 'count' | '%' | 'km/h' | 'm' | 'xG' | 'ratio' | 'index'
  window: 'match' | 'last_5m' | 'last_10m'
  as_of_seq: number
  clock: MatchClock
}
export interface CheckError {
  code: 'unknown_metric' | 'value_mismatch' | 'uncited_number' | 'span_not_found' | 'unsupported_claim' | 'too_long'
  detail: string
}
export interface EvidenceReplay {
  start: MatchClock
  end: MatchClock
  frames: TrackingFrame[]
  events: (
    | KickoffEvent
    | PassEvent
    | CarryEvent
    | ShotEvent
    | TackleEvent
    | InterceptionEvent
    | PressureEvent
    | DuelEvent
    | FoulEvent
    | CardEvent
    | SubstitutionEvent
    | GoalEvent
    | PossessionChangeEvent
    | BallOutEvent
    | PeriodEndEvent
    | MatchEndEvent
  )[]
  note: string
}
export interface TrackingFrame {
  match_id: string
  frame_seq: number
  clock: MatchClock
  ball: Point
  ball_speed_kmh: number
  players: PlayerPos[]
  ball_trajectory: BallSample[]
}
export interface Point {
  x: number
  y: number
}
export interface PlayerPos {
  player_id: string
  x: number
  y: number
  speed_kmh: number
}
/**
 * Authored synthetic ball movement within the preceding tracking second.
 */
export interface BallSample {
  offset_ms: number
  x: number
  y: number
  height_m: number
  action: 'pass' | 'carry' | 'shot' | 'hold'
  actor_id: string | null
  event_id: string | null
  progress: number
}
export interface KickoffEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'kickoff'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: null
  outcome: null
  attrs: NoAttrs
}
export interface NoAttrs {}
export interface PassEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'pass'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: Point
  outcome: 'complete' | 'incomplete' | 'out' | 'offside'
  attrs: PassAttrs
}
export interface PassAttrs {
  receiver_id: string
  length_m: number
  height: 'ground' | 'low' | 'high'
  under_pressure: boolean
  ball_speed_kmh: number
}
export interface CarryEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'carry'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: Point
  outcome: null
  attrs: CarryAttrs
}
export interface CarryAttrs {
  distance_m: number
}
export interface ShotEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'shot'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: Point | null
  outcome: 'goal' | 'saved' | 'blocked' | 'off_target' | 'woodwork'
  attrs: ShotAttrs
}
export interface ShotAttrs {
  body_part: 'foot' | 'head'
  shot_speed_kmh: number
  situation: 'open_play' | 'set_piece' | 'penalty'
  assist_event_id: string | null
}
export interface TackleEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'tackle'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: null
  outcome: 'won' | 'lost'
  attrs: DuelAttrs
}
export interface DuelAttrs {
  opponent_id: string
}
export interface InterceptionEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'interception'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: null
  outcome: null
  attrs: NoAttrs
}
export interface PressureEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'pressure'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: null
  outcome: null
  attrs: PressureAttrs
}
export interface PressureAttrs {
  target_player_id: string
}
export interface DuelEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'duel'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: null
  outcome: 'won' | 'lost'
  attrs: DuelAttrs
}
export interface FoulEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'foul'
  team_id: 'home' | 'away'
  player_id: string
  location: Point
  end_location: null
  outcome: null
  attrs: FoulAttrs
}
export interface FoulAttrs {
  fouled_player_id: string
}
export interface CardEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'card'
  team_id: 'home' | 'away'
  player_id: string
  location: null
  end_location: null
  outcome: 'yellow' | 'second_yellow' | 'red'
  attrs: CardAttrs
}
export interface CardAttrs {
  reason: string
}
export interface SubstitutionEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'substitution'
  team_id: 'home' | 'away'
  player_id: null
  location: null
  end_location: null
  outcome: null
  attrs: SubstitutionAttrs
}
export interface SubstitutionAttrs {
  player_in_id: string
  player_out_id: string
}
export interface GoalEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'goal'
  team_id: 'home' | 'away'
  player_id: string
  location: null
  end_location: null
  outcome: null
  attrs: GoalAttrs
}
export interface GoalAttrs {
  scorer_id: string
  assist_id: string | null
  shot_event_id: string
}
export interface PossessionChangeEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'possession_change'
  team_id: 'home' | 'away'
  player_id: null
  location: null
  end_location: null
  outcome: null
  attrs: NoAttrs
}
export interface BallOutEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'ball_out'
  team_id: ('home' | 'away') | null
  player_id: string | null
  location: Point
  end_location: null
  outcome: null
  attrs: NoAttrs
}
export interface PeriodEndEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'period_end'
  team_id: null
  player_id: null
  location: null
  end_location: null
  outcome: null
  attrs: NoAttrs
}
export interface MatchEndEvent {
  event_id: string
  match_id: string
  seq: number
  clock: MatchClock
  type: 'match_end'
  team_id: null
  player_id: null
  location: null
  end_location: null
  outcome: null
  attrs: NoAttrs
}
export interface AgentTrace {
  trace_id: string
  match_id: string
  moment_id: string | null
  agent: 'detector' | 'explainer' | 'fact_checker' | 'personalizer' | 'producer'
  action: string
  status: 'ok' | 'approved' | 'rejected' | 'retry' | 'fallback' | 'error'
  latency_ms: number
  tokens_in: number
  tokens_out: number
  detail: string
  draft_text: string | null
  ts: string
}
