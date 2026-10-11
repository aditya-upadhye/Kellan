export interface Insight {
  insight_id: string
  moment_id: string
  headline: string
  body: string
  claims: Claim[]
  tags: string[]
  status: 'draft' | 'verified' | 'rejected' | 'fallback'
  attempts: number
  errors: CheckError[]
}
export interface Claim {
  claim_id: string
  text_span: string
  metric_id: string
  value: number
  as_of_seq: number
}
export interface CheckError {
  code: 'unknown_metric' | 'value_mismatch' | 'uncited_number' | 'span_not_found' | 'unsupported_claim' | 'too_long'
  detail: string
}
