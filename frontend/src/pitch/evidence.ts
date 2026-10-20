import type { InsightEvidence } from '../generated/InsightEvidence'

export type ReplayEvent = InsightEvidence['replay']['events'][number]

export interface PitchEvidence {
  evidenceId: string
  events: ReplayEvent[]
  sourceEventIds: string[]
  playerIds: string[]
  focusEventId: string | null
  metricId: string | null
  period: number
}

export function visibleEvidenceEvents(evidence: PitchEvidence, clockMs: number): ReplayEvent[] {
  if (evidence.focusEventId) return evidence.events.filter(event => event.event_id === evidence.focusEventId)
  return evidence.events.filter(event => event.clock.ms <= clockMs && event.clock.ms >= clockMs - 4000)
}

export function evidenceZone(evidence: PitchEvidence): { x: number; width: number } | null {
  if (!evidence.metricId?.endsWith('.field_tilt_pct')) return null
  const home = evidence.metricId.startsWith('team.home.')
  const right = home === (evidence.period === 1)
  return { x: right ? 70 : 0, width: 35 }
}

export function highlightedPlayers(evidence: PitchEvidence, clockMs: number): Set<string> {
  const players = new Set(evidence.playerIds)
  const sourceIds = new Set(evidence.sourceEventIds)
  if (evidence.metricId?.startsWith('player.')) players.add(evidence.metricId.split('.')[1])
  for (const event of visibleEvidenceEvents(evidence, clockMs)) if (sourceIds.has(event.event_id)) {
    if (event.player_id) players.add(event.player_id)
    if (event.type === 'pass') players.add(event.attrs.receiver_id)
  }
  return players
}
