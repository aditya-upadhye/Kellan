import type { ClaimEvidence } from './generated/InsightEvidence'

export function evidenceKey(item: ClaimEvidence): string {
  return `${item.claim.metric_id}@${item.claim.as_of_seq}`
}

export function evidenceClock(period: number, ms: number): string {
  const seconds = Math.floor(ms / 1000)
  return `${(period - 1) * 45 + Math.floor(seconds / 60)}:${(seconds % 60).toString().padStart(2, '0')}`
}
