export interface TrackingFrame {
  match_id: string
  frame_seq: number
  clock: MatchClock
  ball: Point
  ball_speed_kmh: number
  players: PlayerPos[]
  ball_trajectory: BallSample[]
}
export interface MatchClock {
  period: 1 | 2
  ms: number
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
