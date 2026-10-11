export interface Recap {
  recap_id: string
  match_id: string
  profile_id: string
  kind: 'half' | 'full'
  title: string
  paragraphs: string[]
  key_moment_ids: string[]
  claims: Claim[]
  status: 'verified' | 'fallback'
}
export interface Claim {
  claim_id: string
  text_span: string
  metric_id: string
  value: number
  as_of_seq: number
}
