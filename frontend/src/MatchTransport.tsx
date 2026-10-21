import { useMemo } from 'react'
import type { TrackingFrame } from './generated/TrackingFrame'

export function MatchTransport({ frames, current, replaying, paused, evidence, onSeek, onToggle, onLive }: {
  frames: TrackingFrame[]
  current: TrackingFrame | null
  replaying: boolean
  paused: boolean
  evidence: boolean
  onSeek: (index: number) => void
  onToggle: () => void
  onLive: () => void
}) {
  const times = useMemo(() => {
    const result: number[] = []
    for (const frame of frames) result.push(result.length ? result[result.length - 1] + (frame.interval_ms ?? 1000) : 0)
    return result
  }, [frames])
  const index = replaying ? Math.max(0, frames.findIndex(frame => frame.frame_seq === current?.frame_seq)) : frames.length - 1
  const position = times[index] ?? 0
  const end = times.at(-1) ?? 0
  const disabled = frames.length < 2
  const clock = current ? `Period ${current.clock.period} · ${Math.floor(current.clock.ms / 60000)}:${String(Math.floor(current.clock.ms / 1000) % 60).padStart(2, '0')}` : 'Waiting for tracking'
  function seek(ms: number) {
    const found = times.findIndex(time => time >= Math.max(0, Math.min(end, ms)))
    onSeek(found < 0 ? frames.length - 1 : found)
  }
  return <div className="match-transport" aria-label={evidence ? 'Insight replay playback' : 'Match playback'}>
    <div className="match-transport-buttons">
      <button type="button" disabled={disabled} onClick={() => seek(position - 10000)} aria-label="Rewind match view 10 seconds">−10s</button>
      <button type="button" disabled={disabled} onClick={onToggle}>{replaying && paused ? 'PLAY VIEW' : 'PAUSE VIEW'}</button>
      <button type="button" disabled={disabled || position >= end} onClick={() => seek(position + 10000)} aria-label="Forward match view 10 seconds">+10s</button>
      <span className="match-transport-clock">{clock}</span>
      <button type="button" className={!replaying ? 'at-live' : ''} disabled={!replaying} onClick={onLive}>{replaying ? 'RETURN LIVE' : 'LIVE'}</button>
    </div>
    <input type="range" min={0} max={Math.max(1, end)} step={50} value={position} disabled={disabled} aria-label={evidence ? 'Seek insight replay' : 'Seek match replay'} aria-valuetext={clock} onChange={event => seek(Number(event.target.value))} onKeyDown={event => {
      const offset = event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? -1000 : event.key === 'ArrowRight' || event.key === 'ArrowUp' ? 1000 : event.key === 'PageDown' ? -10000 : event.key === 'PageUp' ? 10000 : null
      if (offset !== null) { event.preventDefault(); seek(position + offset) }
      else if (event.key === 'Home' || event.key === 'End') { event.preventDefault(); seek(event.key === 'Home' ? 0 : end) }
    }} />
    <p>{evidence ? 'Pinned insight footage' : replaying ? 'Watching recorded tracking. Score, statistics and commentary remain live.' : 'Rewind or drag to review received match footage.'} Seeking pauses the view; Play resumes at 1×.</p>
  </div>
}
