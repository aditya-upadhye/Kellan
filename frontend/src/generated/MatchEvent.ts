export type MatchEvent =
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
export interface MatchClock {
  period: 1 | 2
  ms: number
}
export interface Point {
  x: number
  y: number
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
