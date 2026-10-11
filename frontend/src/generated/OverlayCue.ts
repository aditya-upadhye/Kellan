export type JsonValue = unknown

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
export interface MatchClock {
  period: 1 | 2
  ms: number
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
