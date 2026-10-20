import type { ReactNode } from 'react'
import type { ClaimEvidence, EvidenceVersion, InsightEvidence } from './generated/InsightEvidence'
import type { OverlayCue } from './generated/OverlayCue'
import type { ViewerProfile } from './generated/ViewerProfile'
import { evidenceClock, evidenceKey } from './evidenceFormatting'

export function InsightShelf({ cues, profileId, selectedId, onInspect }: {
  cues: OverlayCue[]
  profileId: string
  selectedId: string | null
  onInspect: (cue: OverlayCue) => void
}) {
  const stories = cues.filter(cue => cue.profile_id === profileId).reverse()
  return <section className="insight-shelf" aria-label="Published insights">
    <div className="insight-shelf-heading"><div><span className="evidence-kicker">THE PLAY BEHIND THE WORDS</span><h2>Every insight has a way back to the pitch.</h2></div><span>{stories.length ? `${stories.length} TO INSPECT` : 'AWAITING FIRST INSIGHT'}</span></div>
    {stories.length ? <div className="insight-cards">{stories.map(cue => <button
      type="button" key={cue.cue_id}
      className={`insight-story${cue.insight_id === selectedId ? ' selected' : ''}`}
      data-insight-id={cue.insight_id}
      aria-label={`Show me why: ${cue.headline}`}
      aria-pressed={cue.insight_id === selectedId}
      onClick={() => onInspect(cue)}
    ><span className="story-meta">{evidenceClock(cue.clock.period, cue.clock.ms)} <i>{String(cue.data.moment_type ?? 'insight').replaceAll('_', ' ')}</i></span><strong>{cue.headline}</strong><span className="story-excerpt">{cue.body}</span><span className="story-inspect">SHOW ME WHY <b aria-hidden="true">↗</b></span></button>)}</div>
      : <p className="insight-empty">When an insight goes on screen, inspect its numbers, replay the supporting passage, and follow the agent decisions. Published stories stay here after their overlay expires.</p>}
  </section>
}

function ClaimText({ text, version, selected, onSelect }: { text: string; version: EvidenceVersion; selected: string | null; onSelect: (key: string) => void }) {
  const matches: { start: number; end: number; item: ClaimEvidence }[] = []
  for (const item of version.claims) {
    let cursor = 0
    while (cursor < text.length) {
      const start = text.indexOf(item.claim.text_span, cursor)
      if (start < 0) break
      matches.push({ start, end: start + item.claim.text_span.length, item })
      cursor = start + item.claim.text_span.length
    }
  }
  matches.sort((a, b) => a.start - b.start || b.end - a.end)
  const children: ReactNode[] = []
  let cursor = 0
  for (const match of matches) {
    if (match.start < cursor) continue
    children.push(text.slice(cursor, match.start))
    const key = evidenceKey(match.item)
    children.push(<button type="button" className={`claim-phrase${key === selected ? ' selected' : ''}`} key={`${match.start}:${key}`} onClick={() => onSelect(key)} aria-label={`Inspect claim: ${match.item.claim.text_span}`}>{text.slice(match.start, match.end)}</button>)
    cursor = match.end
  }
  children.push(text.slice(cursor))
  return <>{children}</>
}

function metricValue(value: number | null | undefined, unit: string): string {
  return value == null ? 'Unavailable' : `${Number(value.toFixed(4))}${unit === '%' ? '%' : unit && unit !== 'count' ? ` ${unit}` : ''}`
}

export function InsightInspector({ data, loading, error, profileId, profiles, selectedClaim, onSelectClaim, onProfile, onClose, onRetry, replayIndex, replayPaused, onReplayPause, onSeek, onRestart, activeEventId, onEvent }: {
  data: InsightEvidence | null
  loading: boolean
  error: string | null
  profileId: string
  profiles: ViewerProfile[]
  selectedClaim: string | null
  onSelectClaim: (key: string) => void
  onProfile: (profileId: string) => void
  onClose: () => void
  onRetry: () => void
  replayIndex: number
  replayPaused: boolean
  onReplayPause: () => void
  onSeek: (index: number) => void
  onRestart: () => void
  activeEventId: string | null
  onEvent: (eventId: string) => void
}) {
  const version = data?.versions.find(item => item.cue.profile_id === profileId)
  const claim = version?.claims.find(item => evidenceKey(item) === selectedClaim) ?? version?.claims[0]
  const claimKey = claim ? evidenceKey(claim) : null
  const frame = data?.replay.frames[replayIndex]
  const sourceIds = new Set(claim?.source_event_ids ?? [])
  return <section className="evidence-inspector" aria-label="Insight evidence inspector">
    <div className="inspector-heading"><div><span className="evidence-kicker">SHOW ME WHY</span><h2>The evidence behind this insight</h2></div><button type="button" onClick={onClose} aria-label="Close evidence inspector">×</button></div>
    {loading && <p className="inspector-message" role="status">Opening saved evidence and historical tracking…</p>}
    {error && <div className="inspector-message" role="alert"><p>{error}</p><button type="button" onClick={onRetry}>TRY AGAIN</button></div>}
    {data && <>
      <div className="evidence-version-tabs" aria-label="Evidence audience versions">{data.versions.map(item => <button type="button" key={item.cue.profile_id} aria-pressed={item.cue.profile_id === profileId} onClick={() => onProfile(item.cue.profile_id)}>{profiles.find(profile => profile.profile_id === item.cue.profile_id)?.label ?? item.cue.profile_id}</button>)}</div>
      {version ? <>
        <div className="inspected-story"><span className="evidence-kicker">PUBLISHED WORDING / {version.cue.language.toUpperCase()}</span><h3><ClaimText text={version.cue.headline} version={version} selected={claimKey} onSelect={onSelectClaim} /></h3><p><ClaimText text={version.cue.body} version={version} selected={claimKey} onSelect={onSelectClaim} /></p><small>Underlined numbers open their calculation.</small></div>
        <div className={`numeric-verdict${!version.numeric_check_passed ? ' failed' : ''}`}>{version.claims.length ? version.numeric_check_passed ? 'NUMERIC CLAIMS CHECKED' : 'NUMERIC CHECK NEEDS REVIEW' : 'NO NUMERIC CLAIMS IN THIS VERSION'}</div>
        {version.errors.length > 0 && <ul className="evidence-errors">{version.errors.map((item, i) => <li key={i}>{item.code}: {item.detail}</li>)}</ul>}
        {claim ? <div className="claim-calculation">
          <div className="calculation-heading"><span>THE CALCULATION</span><strong className={claim.recomputation === 'matched' ? 'calculation-match' : 'calculation-warning'}>{claim.recomputation === 'matched' ? 'REPRODUCED' : claim.recomputation.toUpperCase()}</strong></div>
          <div className="claim-choices">{version.claims.map(item => <button type="button" key={item.claim.claim_id} aria-pressed={evidenceKey(item) === claimKey} onClick={() => onSelectClaim(evidenceKey(item))}>{item.claim.text_span}</button>)}</div>
          <p>{claim.method}</p>
          <dl className="calculation-values"><div><dt>Saved at publication</dt><dd>{metricValue(claim.snapshot?.value, claim.snapshot?.unit ?? '')}</dd></div><div><dt>Recomputed from inputs</dt><dd>{metricValue(claim.recomputed_value, claim.snapshot?.unit ?? '')}</dd></div></dl>
          <p className="evidence-scope">{claim.scope_note}</p>
          <details><summary>Metric reference</summary><code>{claim.claim.metric_id}</code><small>Event sequence {claim.claim.as_of_seq} / {claim.source_event_ids.length} source events</small></details>
        </div> : <p className="inspector-message">This wording has no numeric spans to inspect. The replay shows the moment's context.</p>}
      </> : <p className="inspector-message">No published version is available for this audience. Choose one of the available versions above.</p>}
      <div className="evidence-replay-controls"><div className="calculation-heading"><span>HISTORICAL REPLAY / 1×</span><strong>{frame ? evidenceClock(frame.clock.period, frame.clock.ms) : 'NO TRACKING'}</strong></div>
        {data.replay.frames.length > 0 ? <><div className="evidence-playback"><button type="button" onClick={onReplayPause}>{replayPaused ? 'PLAY REPLAY' : 'PAUSE REPLAY'}</button><button type="button" onClick={onRestart}>RESTART</button><button type="button" onClick={onClose}>RETURN LIVE</button></div><input type="range" aria-label="Evidence replay position" min={0} max={Math.max(0, data.replay.frames.length - 1)} value={replayIndex} onChange={event => onSeek(Number(event.target.value))} /></> : <p>No tracking was available before this insight's cutoff.</p>}
        <p>{data.replay.note}</p>
      </div>
      <div className="evidence-event-list"><div className="calculation-heading"><span>EVENTS IN THIS PASSAGE</span><span><i className="evidence-source-dot" /> SOURCE / CONTEXT</span></div>{data.replay.events.length ? data.replay.events.map(event => <button type="button" key={event.event_id} title={event.event_id} aria-label={`Inspect event ${event.type.replaceAll('_', ' ')} at ${evidenceClock(event.clock.period, event.clock.ms)}`} aria-pressed={activeEventId === event.event_id} onClick={() => onEvent(event.event_id)} className={sourceIds.has(event.event_id) ? 'source-event' : ''}><time>{evidenceClock(event.clock.period, event.clock.ms)}</time><strong>{event.type.replaceAll('_', ' ')}</strong><span>{sourceIds.has(event.event_id) ? 'SOURCE' : 'CONTEXT'}</span></button>) : <p>No event markers fall inside this tracking clip.</p>}</div>
      <details className="evidence-agent-decisions" open={data.traces.some(trace => trace.status === 'rejected')}><summary>Agent decisions <span>{data.traces.length}</span></summary>{data.traces.length ? data.traces.map((trace, i) => <article key={`${trace.trace_id}:${i}`} className={trace.status === 'rejected' ? 'rejected' : ''}><div><strong>{trace.agent.replaceAll('_', ' ')}</strong><span>{trace.status}</span></div><p>{trace.action.replaceAll('_', ' ')} — {trace.detail}</p>{trace.status === 'rejected' && trace.draft_text && <blockquote>{trace.draft_text}</blockquote>}</article>) : <p>No agent trace was retained for this moment.</p>}</details>
      <p className="evidence-interpretation">{data.interpretation_note}</p>
      <div className="evidence-identity"><span>SAME EVIDENCE ACROSS AUDIENCES</span><code>{data.evidence_id}</code><span>Cutoff {evidenceClock(data.moment.clock.period, data.moment.clock.ms)}</span></div>
    </>}
  </section>
}
