export interface TrackingFrame {
  match_id: string
  frame_seq: number
  clock: MatchClock
  ball: Point
  ball_speed_kmh: number
  players: PlayerPos[]
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
