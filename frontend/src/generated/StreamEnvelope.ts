export type JsonValue = unknown

export interface StreamEnvelope {
  kind: 'event' | 'frame' | 'metrics' | 'cue' | 'trace' | 'recap' | 'status'
  match_id: string
  data: {
    [k: string]: JsonValue
  }
}
