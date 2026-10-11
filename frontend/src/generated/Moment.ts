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
