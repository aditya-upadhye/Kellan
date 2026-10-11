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
export interface MatchClock {
  period: 1 | 2
  ms: number
}
