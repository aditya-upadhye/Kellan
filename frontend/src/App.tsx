import { useEffect, useMemo, useState } from 'react'
import type { MatchEvent } from './generated/MatchEvent'
import type { MatchMetadata } from './generated/MatchMetadata'
import type { MetricSnapshot } from './generated/MetricSnapshot'
import type { StreamEnvelope } from './generated/StreamEnvelope'
import type { TrackingFrame } from './generated/TrackingFrame'

type PlaybackSpeed = 1 | 10 | 30 | 60 | 'max'
type MatchStatus = 'starting' | 'running' | 'paused' | 'complete' | 'error'

interface Scenario {
  name: string
  description: string
}

interface MatchResponse {
  metadata: MatchMetadata
  status: MatchStatus
  clock: { period: 1 | 2; ms: number }
  score: { home: number; away: number }
  speed: PlaybackSpeed
  error: string | null
}

interface MatchStateResponse {
  status: MatchStatus
  metrics: MetricSnapshot[]
}

interface MatchEventData {
  type: MatchEvent['type']
  team_id: 'home' | 'away' | null
  player_id: string | null
  clock: MatchEvent['clock']
  seq: number
}

const speeds: PlaybackSpeed[] = [1, 10, 30, 60, 'max']

function formatClock(period: 1 | 2, ms: number): string {
  const endMinute = period * 45
  const minute = (period - 1) * 45 + Math.floor(ms / 60_000) + 1
  return minute <= endMinute ? `${minute}'` : `${endMinute}+${minute - endMinute}'`
}

function formatMetric(metric: MetricSnapshot | undefined, digits = 1): string {
  if (!metric) return '—'
  const unit = metric.unit === '%' || metric.unit === 'km/h' || metric.unit === 'm' ? metric.unit : ''
  return `${metric.value.toFixed(digits)}${unit}`
}

function getMetric(
  metrics: Map<string, MetricSnapshot>,
  metricId: string,
  window = 'match',
): MetricSnapshot | undefined {
  return metrics.get(`${metricId}:${window}`)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [scenario, setScenario] = useState('balanced')
  const [seed, setSeed] = useState(42)
  const [speed, setSpeed] = useState<PlaybackSpeed>(10)
  const [matchId, setMatchId] = useState<string | null>(null)
  const [match, setMatch] = useState<MatchResponse | null>(null)
  const [frame, setFrame] = useState<TrackingFrame | null>(null)
  const [metrics, setMetrics] = useState<Map<string, MetricSnapshot>>(new Map())
  const [events, setEvents] = useState<MatchEventData[]>([])
  const [socketState, setSocketState] = useState<'connecting' | 'live' | 'offline'>('offline')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    fetch('/api/scenarios')
      .then(async (response) => {
        if (!response.ok) throw new Error('Could not load match scenarios')
        return (await response.json()) as Scenario[]
      })
      .then((available) => {
        if (!active) return
        setScenarios(available)
        if (available.length) setScenario((current) => available.some((item) => item.name === current) ? current : available[0].name)
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'API is unavailable')
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    if (!matchId) return
    const socketUrl = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/matches/${matchId}`
    const socket = new WebSocket(socketUrl)
    socket.onopen = () => setSocketState('live')
    socket.onclose = () => setSocketState('offline')
    socket.onerror = () => setSocketState('offline')
    socket.onmessage = (message: MessageEvent<string>) => {
      const envelope = JSON.parse(message.data) as StreamEnvelope
      const data = envelope.data
      if (envelope.kind === 'status') {
        setMatch((current) => {
          if (!current || !isRecord(data)) return current
          const nextStatus = data.state
          const nextSpeed = data.speed
          const period = data.period
          const clockMs = data.clock_ms
          return {
            ...current,
            status:
              nextStatus === 'starting' ||
              nextStatus === 'running' ||
              nextStatus === 'paused' ||
              nextStatus === 'complete' ||
              nextStatus === 'error'
                ? nextStatus
                : current.status,
            speed:
              nextSpeed === 'max' || nextSpeed === '1' || nextSpeed === '10' || nextSpeed === '30' || nextSpeed === '60'
                ? nextSpeed === 'max'
                  ? 'max'
                  : (Number(nextSpeed) as Exclude<PlaybackSpeed, 'max'>)
                : current.speed,
            clock:
              (period === 1 || period === 2) && typeof clockMs === 'number'
                ? { period, ms: clockMs }
                : current.clock,
          }
        })
        return
      }
      if (envelope.kind === 'frame' && isRecord(data)) {
        const nextFrame = data as unknown as TrackingFrame
        setFrame(nextFrame)
        setMatch((current) =>
          current ? { ...current, clock: nextFrame.clock } : current,
        )
        return
      }
      if (envelope.kind === 'event' && isRecord(data)) {
        const event = data as unknown as MatchEventData
        setEvents((current) => [...current.slice(-7), event])
        setMatch((current) => {
          if (!current) return current
          const score = { ...current.score }
          if (event.type === 'goal' && event.team_id) score[event.team_id] += 1
          return { ...current, clock: event.clock, score }
        })
        return
      }
      if (envelope.kind === 'metrics' && isRecord(data) && Array.isArray(data.snapshots)) {
        setMetrics((current) => {
          const next = new Map(current)
          for (const snapshot of data.snapshots as MetricSnapshot[]) {
            next.set(`${snapshot.metric_id}:${snapshot.window}`, snapshot)
          }
          return next
        })
      }
    }
    return () => socket.close()
  }, [matchId])

  const selectedScenario = scenarios.find((item) => item.name === scenario)
  const homeXg = getMetric(metrics, 'team.home.xg')
  const awayXg = getMetric(metrics, 'team.away.xg')
  const homePossession = getMetric(metrics, 'team.home.possession_pct')
  const awayPossession = getMetric(metrics, 'team.away.possession_pct')
  const momentum = getMetric(metrics, 'match.momentum')
  const timeline = useMemo(() => events.slice(-5).reverse(), [events])

  async function startMatch() {
    setBusy(true)
    setError(null)
    setSocketState('connecting')
    setMatchId(null)
    setMatch(null)
    setFrame(null)
    setEvents([])
    setMetrics(new Map())
    try {
      const response = await fetch('/api/matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario, seed, speed }),
      })
      const result = (await response.json()) as { match_id?: string; detail?: string }
      if (!response.ok || !result.match_id) throw new Error(result.detail ?? 'Could not start match')
      setMatchId(result.match_id)
      const [matchResponse, stateResponse] = await Promise.all([
        fetch(`/api/matches/${result.match_id}`),
        fetch(`/api/matches/${result.match_id}/state`),
      ])
      if (!matchResponse.ok || !stateResponse.ok) throw new Error('Could not load match state')
      const matchResult = (await matchResponse.json()) as MatchResponse
      const stateResult = (await stateResponse.json()) as MatchStateResponse
      setMatch(matchResult)
      setSpeed(matchResult.speed)
      setMetrics(
        new Map(stateResult.metrics.map((item) => [`${item.metric_id}:${item.window}`, item])),
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'API is unavailable')
      setMatchId(null)
      setSocketState('offline')
    } finally {
      setBusy(false)
    }
  }

  async function control(action: 'pause' | 'resume' | 'speed', value?: PlaybackSpeed) {
    if (!matchId) return
    setError(null)
    try {
      const response = await fetch(`/api/matches/${matchId}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ...(value === undefined ? {} : { value }) }),
      })
      const result = (await response.json()) as {
        status?: MatchStatus
        speed?: PlaybackSpeed
        detail?: string
      }
      if (!response.ok) throw new Error(result.detail ?? 'Could not update match controls')
      setMatch((current) =>
        current
          ? {
              ...current,
              status: result.status ?? current.status,
              speed: result.speed ?? current.speed,
            }
          : current,
      )
      if (result.speed) setSpeed(result.speed)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Control request failed')
    }
  }

  const isLive = match?.status === 'running' || match?.status === 'paused'

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="MatchLens home">
          <span className="brand-mark">M</span>
          <span>match<span className="brand-accent">lens</span></span>
        </a>
        <div className="topbar-meta">
          <span className="season-label">MERIDIAN LEAGUE · LIVE SIMULATION</span>
          <span className={`connection-state ${socketState}`}>
            <span className="connection-dot" />
            {socketState === 'live' ? 'CONNECTED' : socketState === 'connecting' ? 'CONNECTING' : 'LOCAL MODE'}
          </span>
        </div>
      </header>

      <section className="page-heading" id="top">
        <div>
          <p className="eyebrow">MATCH CENTRE <span> / </span> LIVE VIEW</p>
          <h1>{match ? 'The match, as it happens.' : 'See the game take shape.'}</h1>
          <p className="page-subtitle">
            Follow every move, metric and moment in a fully simulated fixture.
          </p>
        </div>
        <div className="privacy-chip"><span /> FICTIONAL MATCH DATA</div>
      </section>

      {!match && (
        <section className="kickoff-card" aria-labelledby="kickoff-title">
          <div className="kickoff-copy">
            <span className="step-number">01 <i> / SET UP</i></span>
            <h2 id="kickoff-title">Choose your fixture</h2>
            <p>Pick a match scenario, set the seed, and watch the simulation unfold.</p>
            <div className="fixture-preview">
              <div className="fixture-team"><span className="team-crest crest-home">{selectedScenario?.name === 'red_card_press' ? 'PHF' : selectedScenario?.name === 'late_comeback' ? 'VEL' : 'KBA'}</span><span>{selectedScenario?.name === 'red_card_press' ? 'Port Halden FC' : selectedScenario?.name === 'late_comeback' ? 'Vellmont City' : 'Kestrel Bay Athletic'}</span></div>
              <span className="fixture-vs">VS</span>
              <div className="fixture-team away"><span className="team-crest crest-away">{selectedScenario?.name === 'late_comeback' ? 'KBA' : 'ASR'}</span><span>{selectedScenario?.name === 'late_comeback' ? 'Kestrel Bay Athletic' : 'Ashmoor Rovers'}</span></div>
            </div>
          </div>
          <div className="kickoff-form">
            <label htmlFor="scenario">SCENARIO</label>
            <select id="scenario" value={scenario} onChange={(event) => setScenario(event.target.value)}>
              {scenarios.map((item) => <option key={item.name} value={item.name}>{item.name.replaceAll('_', ' ')}</option>)}
            </select>
            <p className="field-hint">{selectedScenario?.description ?? 'Loading available scenarios…'}</p>
            <div className="form-row">
              <div className="seed-field">
                <label htmlFor="seed">RANDOM SEED</label>
                <input id="seed" type="number" min="0" value={seed} onChange={(event) => setSeed(Math.max(0, Number(event.target.value)))} />
              </div>
              <div className="speed-field">
                <label htmlFor="kickoff-speed">PLAYBACK SPEED</label>
                <select id="kickoff-speed" value={speed} onChange={(event) => setSpeed(event.target.value === 'max' ? 'max' : Number(event.target.value) as Exclude<PlaybackSpeed, 'max'>)}>
                  {speeds.map((item) => <option key={item} value={item}>{item === 'max' ? 'MAX' : `${item}×`}</option>)}
                </select>
              </div>
            </div>
            <button className="kickoff-button" onClick={() => void startMatch()} disabled={busy || scenarios.length === 0}>
              <span>{busy ? 'PREPARING FIXTURE…' : 'KICK OFF MATCH'}</span>
              <span className="button-arrow">↗</span>
            </button>
            <p className="offline-note"><span>●</span> Runs locally · No cloud account required</p>
          </div>
        </section>
      )}

      {match && (
        <>
          <section className="scoreboard" aria-label="Match scoreboard">
            <div className="score-team home-score-team">
              <span className="team-crest crest-home" style={{ background: match.metadata.home.colors.primary, color: match.metadata.home.colors.secondary }}>{match.metadata.home.short_name}</span>
              <span>{match.metadata.home.name}</span>
            </div>
            <div className="score-center">
              <div className="score-numbers"><span>{match.score.home}</span><i>:</i><span>{match.score.away}</span></div>
              <div className="score-meta"><span className={isLive ? 'live-pill' : 'state-pill'}>{match.status === 'complete' ? 'FULL TIME' : match.status === 'paused' ? 'PAUSED' : match.status === 'starting' ? 'WARMING UP' : 'LIVE'}</span><span>{formatClock(match.clock.period, match.clock.ms)}</span></div>
            </div>
            <div className="score-team away-score-team">
              <span>{match.metadata.away.name}</span>
              <span className="team-crest crest-away" style={{ background: match.metadata.away.colors.primary, color: match.metadata.away.colors.secondary }}>{match.metadata.away.short_name}</span>
            </div>
            <div className="score-xg"><span>xG</span><strong>{formatMetric(homeXg, 2)}</strong><i>—</i><strong>{formatMetric(awayXg, 2)}</strong></div>
          </section>

          <section className="live-layout">
            <div className="live-main">
              <div className="pitch-panel">
                <div className="panel-heading">
                  <div><span className="live-indicator" /> LIVE PITCH <span className="panel-divider">·</span> PERIOD {match.clock.period}</div>
                  <span className="frame-label">{frame ? `FRAME ${frame.frame_seq.toString().padStart(4, '0')}` : 'AWAITING TRACKING'}</span>
                </div>
                <div className="pitch-wrap">
                  <svg className="pitch" viewBox="0 0 105 68" role="img" aria-label="Live top-down view of the football pitch">
                    <defs><pattern id="mowing" width="15" height="68" patternUnits="userSpaceOnUse"><rect width="7.5" height="68" fill="#ffffff" opacity=".035" /></pattern></defs>
                    <rect x="0" y="0" width="105" height="68" rx="1.5" className="pitch-grass" />
                    <rect x="0" y="0" width="105" height="68" rx="1.5" fill="url(#mowing)" />
                    <g className="pitch-markings">
                      <rect x="1.5" y="1.5" width="102" height="65" rx=".7" />
                      <line x1="52.5" y1="1.5" x2="52.5" y2="66.5" />
                      <circle cx="52.5" cy="34" r="9.15" />
                      <circle cx="52.5" cy="34" r=".5" className="pitch-spot" />
                      <rect x="1.5" y="13.84" width="16.5" height="40.32" />
                      <rect x="1.5" y="24.84" width="5.5" height="18.32" />
                      <rect x="87" y="13.84" width="16.5" height="40.32" />
                      <rect x="98" y="24.84" width="5.5" height="18.32" />
                      <circle cx="12" cy="34" r=".45" className="pitch-spot" />
                      <circle cx="93" cy="34" r=".45" className="pitch-spot" />
                      <path d="M18 25.5 A9 9 0 0 1 18 42.5" />
                      <path d="M87 25.5 A9 9 0 0 0 87 42.5" />
                    </g>
                    {frame?.players.map((player) => {
                      const home = player.player_id.startsWith('h')
                      const team = home ? match.metadata.home : match.metadata.away
                      return <g key={player.player_id} className="player-marker" transform={`translate(${player.x} ${player.y})`}>
                        <circle r="1.6" fill={team.colors.primary} stroke={team.colors.secondary} strokeWidth=".45" />
                        <text y=".55" textAnchor="middle">{player.player_id.slice(1)}</text>
                      </g>
                    })}
                    {frame && <g className="ball-marker" transform={`translate(${frame.ball.x} ${frame.ball.y})`}><circle r="1.25" /><circle r="2.4" className="ball-pulse" /></g>}
                  </svg>
                  {!frame && <div className="pitch-loading"><span className="loading-ring" />{match.status === 'starting' ? 'Generating match data' : 'Waiting for first tracking frame'}</div>}
                </div>
                <div className="pitch-legend"><span><i className="legend-home" />{match.metadata.home.short_name}</span><span><i className="legend-away" />{match.metadata.away.short_name}</span><span><i className="legend-ball" />BALL</span><span className="ball-speed">BALL SPEED <b>{frame ? `${frame.ball_speed_kmh.toFixed(1)} km/h` : '—'}</b></span></div>
              </div>

              <div className="metrics-panel">
                <div className="panel-heading"><span>LIVE MATCH DATA</span><span className="metrics-updated">UPDATES WITH EVERY PLAY</span></div>
                <div className="metric-grid">
                  <div className="metric-card"><span className="metric-label">POSSESSION</span><div className="possession-values"><b>{formatMetric(homePossession, 0)}</b><span className="possession-track"><i style={{ width: `${Math.max(0, Math.min(100, homePossession?.value ?? 50))}%` }} /></span><b>{formatMetric(awayPossession, 0)}</b></div><div className="metric-subline"><span>{match.metadata.home.short_name}</span><span>{match.metadata.away.short_name}</span></div></div>
                  <MetricCard label="EXPECTED GOALS" home={formatMetric(homeXg, 2)} away={formatMetric(awayXg, 2)} homeName={match.metadata.home.short_name} awayName={match.metadata.away.short_name} />
                  <MetricCard label="PASSES COMPLETED" home={formatMetric(getMetric(metrics, 'team.home.passes'))} away={formatMetric(getMetric(metrics, 'team.away.passes'))} homeName={match.metadata.home.short_name} awayName={match.metadata.away.short_name} />
                  <div className="metric-card momentum-card"><span className="metric-label">MATCH MOMENTUM</span><div className="momentum-gauge"><span>{match.metadata.home.short_name}</span><div className="momentum-track"><i style={{ left: `${50 + Math.max(-50, Math.min(50, momentum?.value ?? 0))}%` }} /></div><span>{match.metadata.away.short_name}</span></div><div className="momentum-reading">{momentum ? momentum.value > 0 ? `${match.metadata.home.short_name} pressure` : momentum.value < 0 ? `${match.metadata.away.short_name} pressure` : 'Evenly balanced' : 'Calculating'}</div></div>
                </div>
              </div>
            </div>

            <aside className="match-sidebar">
              <div className="control-panel">
                <div className="panel-heading"><span>MATCH CONTROLS</span><span className="control-live">● {match.status.toUpperCase()}</span></div>
                <div className="control-buttons">
                  <button className="play-control" onClick={() => void control(match.status === 'paused' ? 'resume' : 'pause')} disabled={match.status === 'complete' || match.status === 'starting'} aria-label={match.status === 'paused' ? 'Resume match' : 'Pause match'}>
                    {match.status === 'paused' ? <span className="play-icon">▶</span> : <span className="pause-icon"><i /><i /></span>}
                    {match.status === 'paused' ? 'RESUME' : 'PAUSE'}
                  </button>
                  <label className="speed-control">SPEED<select value={speed} onChange={(event) => { const value = event.target.value === 'max' ? 'max' : Number(event.target.value) as Exclude<PlaybackSpeed, 'max'>; void control('speed', value) }}>{speeds.map((item) => <option value={item} key={item}>{item === 'max' ? 'MAX' : `${item}×`}</option>)}</select></label>
                </div>
                <button className="new-match-button" onClick={() => { setMatch(null); setMatchId(null); setSocketState('offline') }}>＋ NEW MATCH</button>
              </div>

              <div className="timeline-panel">
                <div className="panel-heading"><span>MATCH FEED</span><span className="feed-count">{events.length.toString().padStart(2, '0')}</span></div>
                {timeline.length ? <div className="event-list">{timeline.map((event) => <EventRow key={event.seq} event={event} homeName={match.metadata.home.short_name} awayName={match.metadata.away.short_name} />)}</div> : <div className="feed-empty"><span className="feed-empty-mark">⌁</span><p>Match events will appear here as the game unfolds.</p></div>}
              </div>
              <div className="sidebar-footnote"><span>ⓘ</span> Every event and metric is generated from the match simulation.</div>
            </aside>
          </section>
        </>
      )}

      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>}
      <footer className="app-footer"><span>MATCHLENS <i>·</i> MERIDIAN LEAGUE SIMULATION</span><span>LOCAL FIRST <i>·</i> BUILT FOR THE GAME</span></footer>
    </main>
  )
}

function MetricCard({ label, home, away, homeName, awayName }: { label: string; home: string; away: string; homeName: string; awayName: string }) {
  return <div className="metric-card"><span className="metric-label">{label}</span><div className="metric-pair"><b>{home}</b><i>—</i><b>{away}</b></div><div className="metric-subline"><span>{homeName}</span><span>{awayName}</span></div></div>
}

function EventRow({ event, homeName, awayName }: { event: MatchEventData; homeName: string; awayName: string }) {
  const isGoal = event.type === 'goal'
  const label = event.type.replaceAll('_', ' ').toUpperCase()
  return <article className={`event-row${isGoal ? ' goal-event' : ''}`}>
    <span className="event-time">{formatClock(event.clock.period, event.clock.ms)}</span>
    <span className="event-symbol">{isGoal ? '⚽' : event.type === 'card' ? '▰' : event.type === 'shot' ? '↗' : '·'}</span>
    <div className="event-copy"><strong>{isGoal ? 'GOAL' : label}</strong><span>{event.team_id === 'home' ? homeName : event.team_id === 'away' ? awayName : 'MATCH'}{event.player_id ? ` · ${event.player_id.toUpperCase()}` : ''}</span></div>
  </article>
}

export default App
