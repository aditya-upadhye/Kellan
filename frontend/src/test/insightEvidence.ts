import type { InsightEvidence, EvidenceVersion } from '../generated/InsightEvidence'

export function insightFixture(id = 'insight-1'): InsightEvidence {
  const eventId = 'match-1-000002'
  const claim = { claim_id: 'claim-1', text_span: '36 km/h', metric_id: `event.${eventId}.ball_speed_kmh`, value: 36, as_of_seq: 2 }
  const version = (profile_id: string, language: 'en' | 'es'): EvidenceVersion => ({
    cue: { cue_id: `cue-${profile_id}`, match_id: 'match-1', profile_id, insight_id: id, trigger_seq: 2, clock: { period: 1, ms: 1000 }, template: 'speed_badge', slot: 'lower_third', priority: 80, start_delay_ms: 0, duration_ms: 5000, expires_at: { period: 1, ms: 61000 }, headline: 'A measured pass', body: language === 'es' ? 'El pase viajó a 36 km/h.' : 'The pass travelled at 36 km/h.', language, data: { claims: [claim], moment_type: 'player_spotlight' }, provenance: { metric_ids: [claim.metric_id], checker: { passed: true, attempts: 2, version: 'deterministic-v1' }, model_ids: ['mock'] } },
    claims: [{ claim, snapshot: { metric_id: claim.metric_id, scope: 'event', subject_id: eventId, label: 'Ball speed', value: 36, unit: 'km/h', window: 'match', as_of_seq: 2, clock: { period: 1, ms: 1000 } }, recomputed_value: 36, recomputation: 'matched', method: 'Read the synthetic ball-speed attribute from the cited pass.', scope_note: 'Full match, through 0:01. The replay is context.', source_event_ids: [eventId] }], numeric_check_passed: true, errors: [],
  })
  return {
    evidence_id: `evidence-${id}`, insight_id: id, match_id: 'match-1',
    moment: { moment_id: 'moment-1', match_id: 'match-1', type: 'player_spotlight', seq_start: 2, seq_end: 2, clock: { period: 1, ms: 1000 }, rule_score: .8, significance: .8, evidence_metric_ids: [claim.metric_id], subject_ids: ['h09'], source: 'rule' },
    versions: [version('analyst_en', 'en'), version('casual_es', 'es')],
    replay: { start: { period: 1, ms: 0 }, end: { period: 1, ms: 1000 }, frames: [0, 1000].map((ms, index) => ({ match_id: 'match-1', frame_seq: index + 1, clock: { period: 1 as const, ms }, ball: { x: 52.5 + index, y: 34 }, ball_speed_kmh: 36, players: [], ball_trajectory: [] })), events: [{ event_id: eventId, match_id: 'match-1', seq: 2, clock: { period: 1, ms: 1000 }, type: 'pass', team_id: 'home', player_id: 'h09', location: { x: 52.5, y: 34 }, end_location: { x: 60.5, y: 34 }, outcome: 'complete', attrs: { receiver_id: 'h06', length_m: 8, height: 'ground', under_pressure: false, ball_speed_kmh: 36 } }], note: 'Historical context ending at the evidence cutoff.' },
    traces: [{ trace_id: 'trace-1', match_id: 'match-1', moment_id: 'moment-1', agent: 'fact_checker', action: 'verify', status: 'rejected', latency_ms: 1, tokens_in: 0, tokens_out: 0, detail: 'value_mismatch', draft_text: 'The pass travelled at 99 km/h.', ts: '2026-10-20T00:00:00Z' }],
    interpretation_note: 'Numbers are checked. Tactical explanations are interpretations; this check does not establish causation.', replay_duration_ms: 1000,
  }
}
