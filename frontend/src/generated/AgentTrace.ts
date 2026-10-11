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
  ts: string
}
