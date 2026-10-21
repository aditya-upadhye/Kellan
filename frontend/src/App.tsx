import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { InsightInspector, InsightShelf } from './InsightInspector'
import { evidenceKey } from './evidenceFormatting'
import { useInsightEvidence } from './useInsightEvidence'
import { EvidenceMarks2D } from './pitch/EvidenceMarks2D'
import { MatchTransport } from './MatchTransport'
import type { CameraView } from './pitch/PitchScene'
import type { PitchEvidence } from './pitch/evidence'
import type { MatchEvent } from './generated/MatchEvent'
import type { MatchMetadata } from './generated/MatchMetadata'
import type { MetricSnapshot } from './generated/MetricSnapshot'
import type { StreamEnvelope } from './generated/StreamEnvelope'
import type { TrackingFrame } from './generated/TrackingFrame'
import type { ViewerProfile } from './generated/ViewerProfile'
import type { AgentTrace } from './generated/AgentTrace'
import type { OverlayCue } from './generated/OverlayCue'
import type { Recap } from './generated/Recap'

type PlaybackSpeed = 1 | 10 | 30 | 60 | 'max'
type MatchStatus = 'starting' | 'running' | 'paused' | 'complete' | 'error' | 'stopped'
type LiveCue = OverlayCue & { removing?: boolean }

const Pitch3D = lazy(() => import('./Pitch3D').then(module => ({ default: module.Pitch3D })))

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
  fault_inject_next?: boolean
  insight_waiting?: boolean
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
const spanishEventLabels: Partial<Record<MatchEvent['type'], string>> = {
  kickoff: 'Inicio',
  pass: 'Pase',
  carry: 'Conducción',
  tackle: 'Entrada',
  interception: 'Intercepción',
  pressure: 'Presión',
  duel: 'Duelo',
  foul: 'Falta',
  substitution: 'Cambio',
  possession_change: 'Cambio de posesión',
  ball_out: 'Balón fuera',
  period_end: 'Fin del periodo',
  match_end: 'Fin del partido',
}

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
  const [judgeMode, setJudgeMode] = useState(false)
  const [profiles, setProfiles] = useState<ViewerProfile[]>([])
  const [primaryProfileId, setPrimaryProfileId] = useState('analyst_en')
  const [secondaryProfileId, setSecondaryProfileId] = useState('casual_en')
  const [compareProfiles, setCompareProfiles] = useState(false)
  const [matchId, setMatchId] = useState<string | null>(null)
  const [match, setMatch] = useState<MatchResponse | null>(null)
  const [frame, setFrame] = useState<TrackingFrame | null>(null)
  const [frameHistory, setFrameHistory] = useState<TrackingFrame[]>([])
  const [pitchView, setPitchView] = useState<'2d' | '3d'>('3d')
  const [camera, setCamera] = useState<CameraView>('broadcast')
  const [replayFrames, setReplayFrames] = useState<TrackingFrame[] | null>(null)
  const [replayIndex, setReplayIndex] = useState(0)
  const [replayPaused, setReplayPaused] = useState(false)
  const [replaySeekToken, setReplaySeekToken] = useState(0)
  const [storyCues, setStoryCues] = useState<OverlayCue[]>([])
  const [selectedClaimKey, setSelectedClaimKey] = useState<string | null>(null)
  const [focusedEventId, setFocusedEventId] = useState<string | null>(null)
  const pitchStage = useRef<HTMLDivElement>(null)
  const inspection = useInsightEvidence(matchId)
  const [metrics, setMetrics] = useState<Map<string, MetricSnapshot>>(new Map())
  const [events, setEvents] = useState<MatchEventData[]>([])
  const [traces, setTraces] = useState<AgentTrace[]>([])
  const [cues, setCues] = useState<LiveCue[]>([])
  const [recaps, setRecaps] = useState<Recap[]>([])
  const [faultArmed, setFaultArmed] = useState(false)
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
    let active = true
    fetch('/api/profiles')
      .then(async (response) => {
        if (!response.ok) throw new Error('Could not load viewer profiles')
        return (await response.json()) as ViewerProfile[]
      })
      .then((available) => {
        if (!active) return
        setProfiles(available)
        setPrimaryProfileId((current) =>
          available.some((profile) => profile.profile_id === current)
            ? current
            : (available[0]?.profile_id ?? ''),
        )
        setSecondaryProfileId((current) =>
          available.some((profile) => profile.profile_id === current)
            ? current
            : (available.find((profile) => profile.profile_id !== 'analyst_en')?.profile_id ?? ''),
        )
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : 'Could not load profiles')
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    let active = true
    fetch('/api/config')
      .then(async (response) => {
        if (!response.ok) throw new Error('Could not load deployment settings')
        return (await response.json()) as { judge_mode?: boolean }
      })
      .then((config) => {
        if (active) {
          setJudgeMode(config.judge_mode === true)
          if (config.judge_mode === true) {
            setScenario('late_comeback')
            setSeed(1)
            setSpeed(10)
          }
        }
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
            insight_waiting: data.insight_waiting === true,
            status:
              nextStatus === 'starting' ||
              nextStatus === 'running' ||
              nextStatus === 'paused' ||
              nextStatus === 'complete' ||
              nextStatus === 'error' ||
              nextStatus === 'stopped'
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
        setFrameHistory((current) => current.at(-1)?.frame_seq === nextFrame.frame_seq ? current : [...current, nextFrame])
        setFrame(nextFrame)
        setMatch((current) =>
          current ? { ...current, clock: nextFrame.clock } : current,
        )
        return
      }
      if (envelope.kind === 'trace' && isRecord(data)) {
        const trace = data as unknown as AgentTrace
        setTraces((current) => [...current.slice(-79), trace])
        if (trace.action === 'fault_injection') setFaultArmed(false)
        return
      }
      if (envelope.kind === 'cue' && isRecord(data)) {
        const cueId = typeof data.cue_id === 'string' ? data.cue_id : null
        if (!cueId) return
        if (data.action === 'remove') {
          setCues((current) => current.map((cue) => cue.cue_id === cueId ? { ...cue, removing: true } : cue))
        } else if (data.action === 'show') {
          const cue = data as unknown as LiveCue
          setStoryCues((current) => [...current.filter(item => item.cue_id !== cue.cue_id), cue])
          setCues((current) => [...current.filter((item) => item.cue_id !== cueId), { ...cue, removing: false }])
        }
        return
      }
      if (envelope.kind === 'recap' && isRecord(data)) {
        const recap = data as unknown as Recap
        setRecaps((current) => [
          ...current.filter((item) => item.profile_id !== recap.profile_id || item.kind !== recap.kind),
          recap,
        ])
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

  useEffect(() => {
    if (!replayFrames || replayPaused) return
    const timer = window.setTimeout(() => {
      if (replayIndex + 1 >= replayFrames.length) {
        if (inspection.data) setReplayPaused(true)
        else setReplayFrames(null)
      }
      else setReplayIndex(replayIndex + 1)
    }, replayFrames[replayIndex + 1]?.interval_ms ?? 1000)
    return () => window.clearTimeout(timer)
  }, [replayFrames, replayIndex, replayPaused, inspection.data])

  const selectedScenario = scenarios.find((item) => item.name === scenario)
  const homeXg = getMetric(metrics, 'team.home.xg')
  const awayXg = getMetric(metrics, 'team.away.xg')
  const homePossession = getMetric(metrics, 'team.home.possession_pct')
  const awayPossession = getMetric(metrics, 'team.away.possession_pct')
  const momentum = getMetric(metrics, 'match.momentum')
  const timeline = useMemo(() => events.slice(-5).reverse(), [events])
  const primaryProfile = profiles.find((profile) => profile.profile_id === primaryProfileId)
  const secondaryProfile = profiles.find((profile) => profile.profile_id === secondaryProfileId)
  const pitchCues = cues.filter((cue) => cue.slot !== 'side_panel')
  const sidePanelCues = cues.filter((cue) => cue.slot === 'side_panel')
  const visibleRecaps = recaps.filter((recap) => recap.profile_id === primaryProfileId)
  const displayedFrame = replayFrames?.[replayIndex] ?? frame
  const players = useMemo(() => [...(match?.metadata.home.players ?? []), ...(match?.metadata.away.players ?? [])], [match?.metadata.home.players, match?.metadata.away.players])
  const playerById = useMemo(() => new Map(players.map(player => [player.player_id, player])), [players])
  const transportFrames = inspection.data && replayFrames ? replayFrames : frameHistory
  const frameDuration = displayedFrame?.interval_ms || 1000
  const displayedTrail = replayFrames
    ? replayFrames.slice(Math.max(0, replayIndex - 13), replayIndex + 1)
    : frameHistory.slice(-14)
  const evidenceVersion = inspection.data?.versions.find(version => version.cue.profile_id === primaryProfileId)
  const evidenceClaim = evidenceVersion?.claims.find(item => evidenceKey(item) === selectedClaimKey) ?? evidenceVersion?.claims[0]
  const pitchEvidence = useMemo<PitchEvidence | null>(() => {
    if (!inspection.data || !replayFrames) return null
    return {
      evidenceId: inspection.data.evidence_id,
      events: inspection.data.replay.events,
      sourceEventIds: evidenceClaim?.source_event_ids ?? [],
      playerIds: inspection.data.moment.subject_ids.filter(id => /^[ha]\d{2}$/.test(id)),
      focusEventId: focusedEventId,
      metricId: evidenceClaim?.claim.metric_id ?? null,
      period: inspection.data.moment.clock.period,
    }
  }, [inspection.data, replayFrames, evidenceClaim, focusedEventId])

  function closeInspection() {
    inspection.close()
    setReplayFrames(null); setReplayPaused(false); setFocusedEventId(null); setSelectedClaimKey(null)
  }

  async function showWhy(cue: OverlayCue) {
    setReplayFrames(null); setReplayPaused(true); setSelectedClaimKey(null); setFocusedEventId(null)
    const data = await inspection.open(cue.insight_id)
    if (!data) return
    setReplayFrames(data.replay.frames.length ? data.replay.frames : null)
    setReplayIndex(0); setReplayPaused(data.replay.frames.length < 2)
    setReplaySeekToken(value => value + 1)
    setPitchView('3d'); setCamera('broadcast')
    pitchStage.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  }

  function seekEvidenceEvent(eventId: string) {
    const event = inspection.data?.replay.events.find(item => item.event_id === eventId)
    if (!event || !replayFrames?.length) return
    const index = replayFrames.findIndex(item => item.clock.ms >= event.clock.ms)
    setReplayIndex(index < 0 ? replayFrames.length - 1 : index)
    setFocusedEventId(eventId); setReplayPaused(true)
    setReplaySeekToken(value => value + 1)
  }

  function seekMatch(index: number) {
    if (!transportFrames.length) return
    setReplayFrames(transportFrames)
    setReplayIndex(Math.max(0, Math.min(transportFrames.length - 1, index)))
    setReplayPaused(true); setFocusedEventId(null)
    setReplaySeekToken(value => value + 1)
  }

  function toggleViewPlayback() {
    if (!replayFrames) seekMatch(frameHistory.length - 1)
    else setReplayPaused(!replayPaused)
  }

  const removeCue = useCallback((cueId: string) => {
    setCues((current) => current.filter((cue) => cue.cue_id !== cueId))
  }, [])
  const beginCueRemoval = useCallback((cueId: string) => {
    setCues((current) => current.map((cue) => cue.cue_id === cueId ? { ...cue, removing: true } : cue))
  }, [])

  function changePrimaryProfile(profileId: string) {
    setPrimaryProfileId(profileId)
    if (secondaryProfileId === profileId) {
      setSecondaryProfileId(
        profiles.find((profile) => profile.profile_id !== profileId)?.profile_id ?? '',
      )
    }
  }

  async function startMatch(useJudgePreset = false) {
    closeInspection()
    setStoryCues([])
    setBusy(true)
    setError(null)
    setSocketState('connecting')
    setMatchId(null)
    setMatch(null)
    setFrame(null)
    setFrameHistory([])
    setReplayFrames(null)
    setReplayIndex(0)
    setEvents([])
    setTraces([])
    setCues([])
    setRecaps([])
    setFaultArmed(false)
    setMetrics(new Map())
    try {
      const response = await fetch('/api/matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          useJudgePreset || judgeMode
            ? {
                scenario: 'late_comeback',
                seed: 1,
                speed: 10,
                profiles: profiles.map((profile) => profile.profile_id),
              }
            : { scenario, seed, speed },
        ),
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
      setFaultArmed(matchResult.fault_inject_next ?? false)
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

  async function control(
    action: 'pause' | 'resume' | 'speed' | 'inject_fault',
    value?: PlaybackSpeed | boolean,
  ) {
    if (!matchId) return
    setError(null)
    try {
      const response = await fetch(`/api/matches/${matchId}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          action === 'inject_fault' ? { action, enabled: value } : { action, ...(value === undefined ? {} : { value }) },
        ),
      })
      const result = (await response.json()) as {
        status?: MatchStatus
        speed?: PlaybackSpeed
        fault_inject_next?: boolean
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
      if (typeof result.fault_inject_next === 'boolean') {
        setFaultArmed(result.fault_inject_next)
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Control request failed')
    }
  }

  const isLive = match?.status === 'running' || match?.status === 'paused'

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Kellan home">
          <span className="brand-mark">K</span>
          <span>kellan</span>
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

      <section className="profile-switcher" aria-label="Viewer profile controls">
        <label>
          <span>VIEWER PROFILE</span>
          <select
            aria-label="Primary viewer profile"
            value={primaryProfileId}
            onChange={(event) => changePrimaryProfile(event.target.value)}
            disabled={profiles.length === 0}
          >
            {profiles.map((profile) => (
              <option key={profile.profile_id} value={profile.profile_id}>
                {profile.label}
              </option>
            ))}
          </select>
        </label>
        <button
          className={compareProfiles ? 'compare-toggle active' : 'compare-toggle'}
          type="button"
          aria-pressed={compareProfiles}
          onClick={() => setCompareProfiles((current) => !current)}
          disabled={profiles.length < 2}
        >
          {compareProfiles ? 'HIDE COMPARISON' : 'COMPARE PROFILES'}
        </button>
        {compareProfiles && (
          <label>
            <span>COMPARE WITH</span>
            <select
              aria-label="Comparison viewer profile"
              value={secondaryProfileId}
              onChange={(event) => setSecondaryProfileId(event.target.value)}
            >
              {profiles
                .filter((profile) => profile.profile_id !== primaryProfileId)
                .map((profile) => (
                  <option key={profile.profile_id} value={profile.profile_id}>
                    {profile.label}
                  </option>
                ))}
            </select>
          </label>
        )}
        <p>Choose how the same live match is presented.</p>
      </section>

      {!match && (
        <section className="kickoff-card" aria-labelledby="kickoff-title">
          <div className="kickoff-copy">
            <span className="step-number">01 <i> / SET UP</i></span>
            <h2 id="kickoff-title">{judgeMode ? 'Judge mode' : 'Choose your fixture'}</h2>
            <p>{judgeMode ? 'The judge preset runs the late comeback at 10x with every viewer profile.' : 'Pick a match scenario, set the seed, and watch the simulation unfold.'}</p>
            <div className="fixture-preview">
              <div className="fixture-team"><span className="team-crest crest-home">{selectedScenario?.name === 'red_card_press' ? 'PHF' : selectedScenario?.name === 'late_comeback' ? 'VEL' : 'KBA'}</span><span>{selectedScenario?.name === 'red_card_press' ? 'Port Halden FC' : selectedScenario?.name === 'late_comeback' ? 'Vellmont City' : 'Kestrel Bay Athletic'}</span></div>
              <span className="fixture-vs">VS</span>
              <div className="fixture-team away"><span className="team-crest crest-away">{selectedScenario?.name === 'late_comeback' ? 'KBA' : 'ASR'}</span><span>{selectedScenario?.name === 'late_comeback' ? 'Kestrel Bay Athletic' : 'Ashmoor Rovers'}</span></div>
            </div>
          </div>
          <div className="kickoff-form">
            <label htmlFor="scenario">SCENARIO</label>
            <select id="scenario" value={scenario} onChange={(event) => setScenario(event.target.value)} disabled={judgeMode}>
              {scenarios.map((item) => <option key={item.name} value={item.name}>{item.name.replaceAll('_', ' ')}</option>)}
            </select>
            <p className="field-hint">{selectedScenario?.description ?? 'Loading available scenarios…'}</p>
            <div className="form-row">
              <div className="seed-field">
                <label htmlFor="seed">RANDOM SEED</label>
                <input id="seed" type="number" min="0" value={seed} onChange={(event) => setSeed(Math.max(0, Number(event.target.value)))} disabled={judgeMode} />
              </div>
              <div className="speed-field">
                <label htmlFor="kickoff-speed">PLAYBACK SPEED</label>
                <select id="kickoff-speed" value={speed} onChange={(event) => setSpeed(event.target.value === 'max' ? 'max' : Number(event.target.value) as Exclude<PlaybackSpeed, 'max'>)} disabled={judgeMode}>
                  {speeds.map((item) => <option key={item} value={item}>{item === 'max' ? 'MAX' : `${item}×`}</option>)}
                </select>
              </div>
            </div>
            {judgeMode && <button className="kickoff-button" onClick={() => void startMatch(true)} disabled={busy || profiles.length === 0}>START JUDGE MODE</button>}
            {!judgeMode && <button className="kickoff-button" onClick={() => void startMatch()} disabled={busy || scenarios.length === 0}>
              <span>{busy ? 'PREPARING FIXTURE…' : 'KICK OFF MATCH'}</span>
              <span className="button-arrow">↗</span>
            </button>}
            {!judgeMode && <button className="judge-preset-button" onClick={() => void startMatch(true)} disabled={busy || profiles.length === 0}>START JUDGE MODE PRESET</button>}
            <p className="offline-note">
              <span>●</span>
              {judgeMode ? 'No account required · Live synthetic fixture' : 'Runs locally · No cloud account required'}
            </p>
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
              <div className="score-meta"><span className={isLive ? 'live-pill' : 'state-pill'}>{match.status === 'complete' ? 'FULL TIME' : match.status === 'stopped' ? 'SESSION ENDED' : match.status === 'error' ? 'ERROR' : match.status === 'paused' ? 'PAUSED' : match.status === 'starting' ? 'WARMING UP' : 'LIVE'}</span><span>{formatClock(match.clock.period, match.clock.ms)}</span></div>
            </div>
            <div className="score-team away-score-team">
              <span>{match.metadata.away.name}</span>
              <span className="team-crest crest-away" style={{ background: match.metadata.away.colors.primary, color: match.metadata.away.colors.secondary }}>{match.metadata.away.short_name}</span>
            </div>
            <div className="score-xg"><span>xG</span><strong>{formatMetric(homeXg, 2)}</strong><i>—</i><strong>{formatMetric(awayXg, 2)}</strong></div>
          </section>

          <section
            className={compareProfiles ? 'profile-views split' : 'profile-views'}
            aria-label={compareProfiles ? 'Live profile comparison' : 'Live profile view'}
          >
            {primaryProfile && (
              <ProfileView
                profile={primaryProfile}
                match={match}
                metrics={metrics}
                events={events}
              />
            )}
            {compareProfiles && secondaryProfile && (
              <ProfileView
                profile={secondaryProfile}
                match={match}
                metrics={metrics}
                events={events}
              />
            )}
          </section>

          <InsightShelf cues={storyCues} profileId={primaryProfileId} selectedId={inspection.requestedId} onInspect={cue => void showWhy(cue)} />

          <section className={`live-layout${inspection.requestedId ? ' inspecting' : ''}`}>
            <div className="live-main">
              <div className="pitch-panel" ref={pitchStage}>
                <div className="pitch-view-controls" aria-label="Pitch view controls">
                  <div className="pitch-view-toggle">
                    <button type="button" className={pitchView === '3d' ? 'active' : ''} aria-pressed={pitchView === '3d'} onClick={() => setPitchView('3d')}>3D VIEW</button>
                    <button type="button" className={pitchView === '2d' ? 'active' : ''} aria-pressed={pitchView === '2d'} onClick={() => setPitchView('2d')}>2D VIEW</button>
                  </div>
                  {pitchView === '3d' && <label>CAMERA <select aria-label="3D camera angle" value={camera} onChange={(event) => setCamera(event.target.value as typeof camera)}><option value="broadcast">Broadcast</option><option value="sideline">Close sideline</option><option value="goal">Goal end</option><option value="wide">Full pitch</option></select></label>}
                </div>
                <div className="panel-heading">
                  <div><span className="live-indicator" /> {inspection.data && replayFrames ? 'INSIGHT REPLAY' : replayFrames ? 'TRACKING REPLAY' : 'LIVE PITCH'} <span className="panel-divider">·</span> PERIOD {displayedFrame?.clock.period ?? match.clock.period}</div>
                  <span className="frame-label">{replayFrames ? `REPLAY ${formatClock(displayedFrame?.clock.period ?? 1, displayedFrame?.clock.ms ?? 0)}` : frame ? `FRAME ${frame.frame_seq.toString().padStart(4, '0')}` : 'AWAITING TRACKING'}</span>
                </div>
                <div className="pitch-wrap">
                  {pitchView === '3d' ? <Suspense fallback={<div className="pitch pitch-3d pitch-scene-loading" role="status">Loading 3D stadium...</div>}><Pitch3D frame={displayedFrame} trail={displayedTrail} camera={camera} homeColor={match.metadata.home.colors.primary} awayColor={match.metadata.away.colors.primary} players={players} frameDurationMs={replayPaused && replayFrames ? 0 : replayFrames ? frameDuration : speed === 'max' ? 16 : frameDuration / speed} replaying={replayFrames !== null} evidence={pitchEvidence} seekToken={replaySeekToken} /></Suspense> : <svg className="pitch" viewBox="0 0 105 68" role="img" aria-label="Live top-down view of the football pitch">
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
                    {displayedFrame?.players.map((player) => {
                      const home = player.player_id.startsWith('h')
                      const team = home ? match.metadata.home : match.metadata.away
                      return <g key={player.player_id} className="player-marker" transform={`translate(${player.x} ${player.y})`}>
                        <title>{team.short_name} #{playerById.get(player.player_id)?.number ?? '?'} {playerById.get(player.player_id)?.name ?? 'Unknown player'}</title>
                        <circle r="1.6" fill={team.colors.primary} stroke={team.colors.secondary} strokeWidth=".45" />
                        <text y=".55" textAnchor="middle">{playerById.get(player.player_id)?.number ?? '?'}</text>
                      </g>
                    })}
                    {pitchEvidence && displayedFrame && <EvidenceMarks2D evidence={pitchEvidence} clockMs={displayedFrame.clock.ms} />}
                    {displayedFrame && <g className="ball-marker" transform={`translate(${displayedFrame.ball.x} ${displayedFrame.ball.y})`}><circle r="1.25" /><circle r="2.4" className="ball-pulse" /></g>}
                  </svg>}
                  {!frame && <div className="pitch-loading"><span className="loading-ring" />{match.status === 'starting' ? 'Generating match data' : 'Waiting for first tracking frame'}</div>}
                  {replayFrames && <div className="pitch-replay-badge">TRACKING REPLAY · LIVE MATCH CONTINUES</div>}
                  <div className="broadcast-overlay-layer" aria-live="polite">
                    {!replayFrames && pitchCues.map((cue) => (
                      <CueOverlay key={cue.cue_id} cue={cue} active={cue.profile_id === primaryProfileId} onExpire={beginCueRemoval} onExitComplete={removeCue} onInspect={() => void showWhy(cue)} />
                    ))}
                  </div>
                </div>
                <MatchTransport frames={transportFrames} current={displayedFrame} replaying={replayFrames !== null} paused={replayPaused} evidence={Boolean(inspection.data && replayFrames)} onSeek={seekMatch} onToggle={toggleViewPlayback} onLive={closeInspection} />
                <div className="pitch-legend"><span><i className="legend-home" />{match.metadata.home.short_name}</span><span><i className="legend-away" />{match.metadata.away.short_name}</span><span><i className="legend-ball" />BALL</span>{pitchEvidence && <span className="evidence-legend">GOLD: SOURCE / TEAL: CONTEXT</span>}<span className="ball-speed">{replayFrames ? 'REPLAY' : ''} BALL SPEED <b>{displayedFrame ? `${displayedFrame.ball_speed_kmh.toFixed(1)} km/h` : '—'}</b></span></div>
                <details className="match-squads"><summary>PLAYERS ON THE PITCH · SHIRT NUMBERS &amp; NAMES</summary><div className="match-squad-columns">{[match.metadata.home, match.metadata.away].map(team => <section key={team.team_id}><h3><i style={{ background: team.colors.primary }} />{team.name}</h3><ul>{team.players.filter(player => displayedFrame ? displayedFrame.players.some(point => point.player_id === player.player_id) : player.starter).map(player => <li key={player.player_id}><b>{player.number}</b><span>{player.name}</span><small>{player.role}</small></li>)}</ul></section>)}</div><p>Fictional players. Lineups follow the displayed footage.</p></details>
              </div>

              <div className="metrics-panel">
                <div className="panel-heading"><span>LIVE MATCH DATA</span><span className="metrics-updated">UPDATES WITH EVERY PLAY</span></div>
                <div className="metric-grid">
                  <div className="metric-card"><span className="metric-label">POSSESSION</span><div className="possession-values"><b>{formatMetric(homePossession, 0)}</b><span className="possession-track"><i style={{ width: `${Math.max(0, Math.min(100, homePossession?.value ?? 50))}%` }} /></span><b>{formatMetric(awayPossession, 0)}</b></div><div className="metric-subline"><span>{match.metadata.home.short_name}</span><span>{match.metadata.away.short_name}</span></div></div>
                  <MetricCard label="EXPECTED GOALS" home={formatMetric(homeXg, 2)} away={formatMetric(awayXg, 2)} homeName={match.metadata.home.short_name} awayName={match.metadata.away.short_name} />
                  <MetricCard label="PASSES ATTEMPTED" home={formatMetric(getMetric(metrics, 'team.home.passes'), 0)} away={formatMetric(getMetric(metrics, 'team.away.passes'), 0)} homeName={match.metadata.home.short_name} awayName={match.metadata.away.short_name} />
                  <div className="metric-card momentum-card"><span className="metric-label">MATCH MOMENTUM</span><div className="momentum-gauge"><span>{match.metadata.home.short_name}</span><div className="momentum-track"><i style={{ left: `${50 + Math.max(-50, Math.min(50, momentum?.value ?? 0))}%` }} /></div><span>{match.metadata.away.short_name}</span></div><div className="momentum-reading">{momentum ? momentum.value > 0 ? `${match.metadata.home.short_name} pressure` : momentum.value < 0 ? `${match.metadata.away.short_name} pressure` : 'Evenly balanced' : 'Calculating'}</div></div>
                </div>
              </div>
            </div>

            <aside className="match-sidebar">
              {inspection.requestedId && <InsightInspector
                data={inspection.data} loading={inspection.loading} error={inspection.error}
                profileId={primaryProfileId} profiles={profiles} selectedClaim={selectedClaimKey}
                onSelectClaim={key => { setSelectedClaimKey(key); setFocusedEventId(null) }}
                onProfile={changePrimaryProfile} onClose={closeInspection}
                onRetry={() => { const cue = storyCues.find(item => item.insight_id === inspection.requestedId); if (cue) void showWhy(cue) }}
                replayIndex={replayIndex} replayPaused={replayPaused}
                onReplayPause={() => { setFocusedEventId(null); setReplayPaused(!replayPaused) }}
                onSeek={index => { setReplayIndex(index); setReplayPaused(true); setFocusedEventId(null); setReplaySeekToken(value => value + 1) }}
                onRestart={() => { if (inspection.data?.replay.frames.length) { setReplayFrames(inspection.data.replay.frames); setReplayIndex(0); setReplayPaused(false); setFocusedEventId(null); setReplaySeekToken(value => value + 1) } }}
                activeEventId={focusedEventId} onEvent={seekEvidenceEvent}
              />}
              <div className="control-panel">
                <div className="panel-heading"><span>MATCH CONTROLS</span><span className="control-live">● {match.status.toUpperCase()}</span></div>
                {match.insight_waiting && <p className="insight-waiting" role="status">Preparing the next insight. Match playback will resume automatically.</p>}
                <div className="control-buttons">
                  <button className="play-control" onClick={() => void control(match.status === 'paused' ? 'resume' : 'pause')} disabled={match.status === 'complete' || match.status === 'starting'} aria-label={match.status === 'paused' ? 'Resume match' : 'Pause match'}>
                    {match.status === 'paused' ? <span className="play-icon">▶</span> : <span className="pause-icon"><i /><i /></span>}
                    {match.status === 'paused' ? 'RESUME' : 'PAUSE'}
                  </button>
                  <label className="speed-control">SPEED<select value={speed} onChange={(event) => { const value = event.target.value === 'max' ? 'max' : Number(event.target.value) as Exclude<PlaybackSpeed, 'max'>; void control('speed', value) }}>{speeds.map((item) => <option value={item} key={item}>{item === 'max' ? 'MAX' : `${item}×`}</option>)}</select></label>
                </div>
                <button className="new-match-button" onClick={() => { closeInspection(); setMatch(null); setMatchId(null); setSocketState('offline') }}>＋ NEW MATCH</button>
              </div>

              {!inspection.requestedId && sidePanelCues.map((cue) => (
                <CueOverlay key={cue.cue_id} cue={cue} active={cue.profile_id === primaryProfileId} onExpire={beginCueRemoval} onExitComplete={removeCue} onInspect={() => void showWhy(cue)} />
              ))}

              <div className="timeline-panel">
                <div className="panel-heading"><span>MATCH FEED</span><span className="feed-count">{events.length.toString().padStart(2, '0')}</span></div>
                {timeline.length ? <div className="event-list">{timeline.map((event) => <EventRow key={event.seq} event={event} homeName={match.metadata.home.short_name} awayName={match.metadata.away.short_name} playerLabel={event.player_id ? playerById.has(event.player_id) ? `#${playerById.get(event.player_id)!.number} ${playerById.get(event.player_id)!.name}` : 'Unknown player' : undefined} />)}</div> : <div className="feed-empty"><span className="feed-empty-mark">•</span><p>Match events will appear here as the game unfolds.</p></div>}
              </div>
              <section className="agent-panel" aria-label="Agent activity">
                <div className="panel-heading">
                  <span>AGENT ACTIVITY</span>
                  <span className="feed-count">{traces.length.toString().padStart(2, '0')}</span>
                </div>
                <div className="fault-control">
                  <div>
                    <strong>Inject a wrong stat</strong>
                    <span>Arm fault injection for the next moment.</span>
                  </div>
                  <button
                    type="button"
                    className={faultArmed ? 'fault-toggle armed' : 'fault-toggle'}
                    aria-pressed={faultArmed}
                    disabled={!isLive}
                    onClick={() => void control('inject_fault', !faultArmed)}
                  >
                    {faultArmed ? 'CANCEL' : 'ARM'}
                  </button>
                </div>
                <div className="agent-trace-list" aria-live="polite">
                  {traces.length ? traces.slice(-10).reverse().map((trace, index) => (
                    <TraceRow key={`${trace.trace_id}-${index}`} trace={trace} />
                  )) : <p className="trace-empty">Agent decisions will appear here.</p>}
                </div>
              </section>
              <RecapPanel recaps={visibleRecaps} profileLabel={primaryProfile?.label ?? 'Viewer'} />
              <div className="sidebar-footnote"><span>ⓘ</span> Every event and metric is generated from the match simulation.</div>
            </aside>
          </section>
        </>
      )}

      {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError(null)} aria-label="Dismiss error">×</button></div>}
      <footer className="app-footer"><span>KELLAN <i>·</i> MERIDIAN LEAGUE SIMULATION</span><span>LOCAL FIRST <i>·</i> BUILT FOR THE GAME</span></footer>
    </main>
  )
}

function CueOverlay({ cue, active, onExpire, onExitComplete, onInspect }: { cue: LiveCue; active: boolean; onExpire: (cueId: string) => void; onExitComplete: (cueId: string) => void; onInspect: () => void }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    let expiry: ReturnType<typeof setTimeout>
    const show = setTimeout(() => {
      setVisible(true)
      expiry = setTimeout(() => onExpire(cue.cue_id), cue.duration_ms)
    }, cue.start_delay_ms)
    return () => {
      clearTimeout(show)
      clearTimeout(expiry)
    }
  }, [cue.cue_id, cue.duration_ms, cue.start_delay_ms, onExpire])

  useEffect(() => {
    if (!cue.removing) return
    const exit = setTimeout(() => onExitComplete(cue.cue_id), 180)
    return () => clearTimeout(exit)
  }, [cue.cue_id, cue.removing, onExitComplete])

  if (!active || (!visible && !cue.removing)) return null
  const fallback = cue.data.status === 'fallback'
  return (
    <article className={`broadcast-cue cue-${cue.template} slot-${cue.slot}${cue.removing ? ' exiting' : ''}`} aria-label={`${cue.template.replaceAll('_', ' ')} overlay`}>
      <div className="broadcast-cue-meta">
        <span>{cue.template.replaceAll('_', ' ')}</span>
        <span className={fallback ? 'cue-status fallback' : 'cue-status'}>{fallback ? 'FALLBACK' : 'VERIFIED'}</span>
      </div>
      <strong>{cue.headline}</strong>
      <p>{cue.body}</p>
      <button type="button" className="cue-inspect" onClick={onInspect}>SHOW ME WHY ↗</button>
      {cue.provenance.metric_ids.length > 0 && (
        <small>VERIFIED FROM {cue.provenance.metric_ids.join(' · ')}</small>
      )}
    </article>
  )
}

function RecapPanel({ recaps, profileLabel }: { recaps: Recap[]; profileLabel: string }) {
  return (
    <section className="recap-panel" aria-label={`${profileLabel} match recap`}>
      <div className="panel-heading">
        <span>MATCH RECAP</span>
        <span className="feed-count">{recaps.length.toString().padStart(2, '0')}</span>
      </div>
      {recaps.length === 0 ? (
        <p className="recap-empty">Half-time and full-time recaps will appear here.</p>
      ) : (
        <div className="recap-list">
          {(['half', 'full'] as const).map((kind) => {
            const recap = recaps.find((item) => item.kind === kind)
            if (!recap) return null
            return (
              <article className="recap-card" key={`${recap.profile_id}-${recap.kind}`}>
                <div className="recap-card-heading">
                  <h3>{recap.title}</h3>
                  <span className={recap.status === 'verified' ? 'recap-status' : 'recap-status fallback'}>
                    {recap.status.toUpperCase()}
                  </span>
                </div>
                {recap.paragraphs.map((paragraph, index) => <p key={`${index}-${paragraph}`}>{paragraph}</p>)}
                {recap.claims.length > 0 && (
                  <details className="recap-evidence">
                    <summary>{recap.claims.length} verified claims</summary>
                    <ul>
                      {recap.claims.map((claim) => (
                        <li key={claim.claim_id}>
                          <span>{claim.text_span}</span>
                          <code>{claim.metric_id}</code>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
                {recap.key_moment_ids.length > 0 && (
                  <small>{recap.key_moment_ids.length} key moments</small>
                )}
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function TraceRow({ trace }: { trace: AgentTrace }) {
  const rejected = trace.status === 'rejected'
  return (
    <article className={rejected ? 'trace-row rejected' : 'trace-row'}>
      <div className="trace-row-heading">
        <span>{trace.agent.replaceAll('_', ' ')}</span>
        <span>{trace.action.replaceAll('_', ' ')}</span>
        <strong>{trace.status}</strong>
      </div>
      {trace.moment_id && <p className="trace-moment">{trace.moment_id}</p>}
      <p className="trace-detail">{trace.detail}</p>
      {rejected && trace.draft_text && <blockquote>{trace.draft_text}</blockquote>}
    </article>
  )
}

function MetricCard({ label, home, away, homeName, awayName }: { label: string; home: string; away: string; homeName: string; awayName: string }) {
  return <div className="metric-card"><span className="metric-label">{label}</span><div className="metric-pair"><b>{home}</b><i>—</i><b>{away}</b></div><div className="metric-subline"><span>{homeName}</span><span>{awayName}</span></div></div>
}

function ProfileView({
  profile,
  match,
  metrics,
  events,
}: {
  profile: ViewerProfile
  match: MatchResponse
  metrics: Map<string, MetricSnapshot>
  events: MatchEventData[]
}) {
  const latestEvent = events.at(-1)
  const homeName = match.metadata.home.short_name
  const awayName = match.metadata.away.short_name
  const homePossession = getMetric(metrics, 'team.home.possession_pct')
  const awayPossession = getMetric(metrics, 'team.away.possession_pct')
  const homeXg = getMetric(metrics, 'team.home.xg')
  const awayXg = getMetric(metrics, 'team.away.xg')
  const spanish = profile.language === 'es'
  const status: Record<MatchStatus, string> = spanish
    ? {
        starting: 'PREPARANDO',
        running: 'EN DIRECTO',
        paused: 'PAUSADO',
        complete: 'FINALIZADO',
        error: 'ERROR',
        stopped: 'SESIÓN FINALIZADA',
      }
    : {
        starting: 'STARTING',
        running: 'LIVE',
        paused: 'PAUSED',
        complete: 'FULL TIME',
        error: 'ERROR',
        stopped: 'SESSION ENDED',
      }

  let summary: string
  if (profile.mode === 'analyst') {
    summary = `xG ${formatMetric(homeXg, 2)}–${formatMetric(awayXg, 2)} · ${homeName} ${formatMetric(homePossession, 0)} / ${awayName} ${formatMetric(awayPossession, 0)} ${spanish ? 'posesión' : 'possession'}`
  } else if (profile.mode === 'player_focus') {
    const favoritePlayer = [
      ...match.metadata.home.players,
      ...match.metadata.away.players,
    ].find((player) => player.player_id === profile.favorite_player_id)
    const favoriteEvent = [...events]
      .reverse()
      .find((event) => event.player_id === profile.favorite_player_id)
    const involved = latestEvent?.player_id === profile.favorite_player_id
    summary = involved
      ? spanish
        ? `${favoritePlayer?.name ?? profile.label} aparece en la acción más reciente.`
        : `${favoritePlayer?.name ?? profile.label} appears in the latest action.`
      : favoriteEvent
        ? spanish
          ? `${favoritePlayer?.name ?? profile.label} aparece en un evento reciente.`
          : `${favoritePlayer?.name ?? profile.label} appears in a recent event.`
        : spanish
          ? `No hay eventos recientes de ${favoritePlayer?.name ?? profile.label}.`
          : `No recent events for ${favoritePlayer?.name ?? profile.label}.`
  } else {
    summary = profile.language === 'es'
      ? spanishEventSummary(latestEvent, homeName, awayName)
      : englishEventSummary(latestEvent, homeName, awayName)
  }

  return (
    <article
      className={`profile-view profile-${profile.mode} profile-${profile.profile_id}`}
      data-profile-id={profile.profile_id}
    >
      <div className="profile-view-heading">
        <div>
          <span className="profile-view-kicker">{spanish ? 'VISTA DE PERFIL' : 'PROFILE VIEW'}</span>
          <h2>{profile.label}</h2>
        </div>
        <span className="profile-status">{status[match.status]}</span>
      </div>
      <div className="profile-view-score">
        <span>{homeName}</span>
        <strong>{match.score.home} : {match.score.away}</strong>
        <span>{awayName}</span>
      </div>
      <div className="profile-view-footer">
        <span>{formatClock(match.clock.period, match.clock.ms)}</span>
        <p>{summary}</p>
      </div>
    </article>
  )
}

function englishEventSummary(
  event: MatchEventData | undefined,
  homeName: string,
  awayName: string,
): string {
  if (!event) return 'Waiting for the first match event.'
  const team = event.team_id === 'home' ? homeName : event.team_id === 'away' ? awayName : null
  if (event.type === 'goal') return `A goal for ${team ?? 'the match'} changes the score.`
  if (event.type === 'card') return `A card adds pressure${team ? ` for ${team}` : ''}.`
  if (event.type === 'shot') return `A shot tests the defence${team ? ` of ${team}` : ''}.`
  return `${event.type.replaceAll('_', ' ')}${team ? ` · ${team}` : ''}.`
}

function spanishEventSummary(
  event: MatchEventData | undefined,
  homeName: string,
  awayName: string,
): string {
  if (!event) return 'Esperando la primera acción del partido.'
  const team = event.team_id === 'home' ? homeName : event.team_id === 'away' ? awayName : null
  if (event.type === 'goal') return `Gol de ${team ?? 'el partido'}; cambia el marcador.`
  if (event.type === 'card') return `Una tarjeta añade presión${team ? ` a ${team}` : ''}.`
  if (event.type === 'shot') return `Un disparo pone a prueba la defensa${team ? ` de ${team}` : ''}.`
  return `${spanishEventLabels[event.type] ?? 'Acción'}${team ? ` · ${team}` : ''}.`
}

function EventRow({ event, homeName, awayName, playerLabel }: { event: MatchEventData; homeName: string; awayName: string; playerLabel?: string }) {
  const isGoal = event.type === 'goal'
  const label = event.type.replaceAll('_', ' ').toUpperCase()
  return <article className={`event-row${isGoal ? ' goal-event' : ''}`}>
    <span className="event-time">{formatClock(event.clock.period, event.clock.ms)}</span>
    <span className="event-symbol">{isGoal ? '⚽' : event.type === 'card' ? '▰' : event.type === 'shot' ? '↗' : '·'}</span>
    <div className="event-copy"><strong>{isGoal ? 'GOAL' : label}</strong><span>{event.team_id === 'home' ? homeName : event.team_id === 'away' ? awayName : 'MATCH'}{playerLabel ? ` · ${playerLabel}` : ''}</span></div>
  </article>
}

export default App
