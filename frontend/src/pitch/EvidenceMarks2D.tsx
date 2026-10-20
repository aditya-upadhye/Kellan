import { evidenceZone, visibleEvidenceEvents } from './evidence'
import type { PitchEvidence } from './evidence'

export function EvidenceMarks2D({ evidence, clockMs }: { evidence: PitchEvidence; clockMs: number }) {
  const sourceIds = new Set(evidence.sourceEventIds)
  const zone = evidenceZone(evidence)
  return <g aria-label="Historical evidence markers">
    <defs><marker id="source-arrow" markerWidth="4" markerHeight="4" refX="3" refY="2" orient="auto"><path d="M0,0 L4,2 L0,4" fill="#ffd37c" /></marker><marker id="context-arrow" markerWidth="4" markerHeight="4" refX="3" refY="2" orient="auto"><path d="M0,0 L4,2 L0,4" fill="#73c8ce" /></marker></defs>
    {zone && <rect x={zone.x} y={0} width={zone.width} height={68} fill="#ffd37c" opacity=".12" />}
    {visibleEvidenceEvents(evidence, clockMs).map(event => {
      if (!event.location) return null
      const source = sourceIds.has(event.event_id)
      const color = source ? '#ffd37c' : '#73c8ce'
      return <g key={event.event_id} opacity={source ? 1 : .5}><circle cx={event.location.x} cy={event.location.y} r="1.6" fill="none" stroke={color} strokeWidth=".4" />{event.end_location && <line x1={event.location.x} y1={event.location.y} x2={event.end_location.x} y2={event.end_location.y} stroke={color} strokeWidth={source ? .55 : .3} markerEnd={`url(#${source ? 'source' : 'context'}-arrow)`} />}</g>
    })}
  </g>
}
