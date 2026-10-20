import { describe, expect, it } from 'vitest'
import { evidenceZone, highlightedPlayers, visibleEvidenceEvents } from './evidence'
import type { PitchEvidence } from './evidence'
import { insightFixture } from '../test/insightEvidence'

const evidence: PitchEvidence = { evidenceId: 'e1', events: insightFixture().replay.events, sourceEventIds: ['match-1-000002'], playerIds: [], focusEventId: null, metricId: null, period: 1 }

describe('spatial evidence', () => {
  it('shows an event only at its historical time and highlights its real participants', () => {
    expect(visibleEvidenceEvents(evidence, 0)).toEqual([])
    expect(visibleEvidenceEvents(evidence, 1000)).toHaveLength(1)
    expect([...highlightedPlayers(evidence, 1000)].sort()).toEqual(['h06', 'h09'])
    expect(visibleEvidenceEvents(evidence, 6000)).toEqual([])
    expect(visibleEvidenceEvents({ ...evidence, focusEventId: 'unknown' }, 1000)).toEqual([])
  })

  it('mirrors the attacking-third calculation when teams change ends', () => {
    expect(evidenceZone({ ...evidence, metricId: 'team.home.field_tilt_pct' })).toEqual({ x: 70, width: 35 })
    expect(evidenceZone({ ...evidence, metricId: 'team.home.field_tilt_pct', period: 2 })).toEqual({ x: 0, width: 35 })
    expect(evidenceZone({ ...evidence, metricId: 'team.away.field_tilt_pct' })).toEqual({ x: 0, width: 35 })
    expect(evidenceZone({ ...evidence, metricId: 'team.home.goals' })).toBeNull()
  })
})
