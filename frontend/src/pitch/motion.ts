import type { BallSample, TrackingFrame } from '../generated/TrackingFrame'

export interface Position { x: number; y: number }

// Monotone cubic interpolation preserves sample endpoints without spline
// overshoot. The ball takes a straight segment: cosmetic curves would alter
// the evidence feed's pass direction.
function axis(a: number, b: number, incoming: number, outgoing: number, t: number): number {
  const d = b - a
  if (Math.abs(d) < 0.0001) return a
  const m0 = Math.sign(incoming) === Math.sign(d) ? Math.min(Math.abs(incoming), 2 * Math.abs(d)) * Math.sign(d) : 0
  const m1 = Math.sign(outgoing) === Math.sign(d) ? Math.min(Math.abs(outgoing), Math.abs(d)) * Math.sign(d) : 0
  const t2 = t * t, t3 = t2 * t
  return (2 * t3 - 3 * t2 + 1) * a + (t3 - 2 * t2 + t) * m0 + (-2 * t3 + 3 * t2) * b + (t3 - t2) * m1
}

export function interpolate(a: Position, b: Position, incoming: Position, outgoing: Position, t: number): Position {
  return { x: axis(a.x, b.x, incoming.x, outgoing.x, t), y: axis(a.y, b.y, incoming.y, outgoing.y, t) }
}

export function isDiscontinuity(previous: TrackingFrame | null, next: TrackingFrame, replayChanged: boolean): boolean {
  return !previous || replayChanged || previous.match_id !== next.match_id || previous.clock.period !== next.clock.period ||
    next.frame_seq <= previous.frame_seq || next.clock.ms - previous.clock.ms > 5000
}

export const zero: Position = { x: 0, y: 0 }

export function sampleBallPath(path: BallSample[], t: number): BallSample | null {
  if (!path.length) return null
  const time = Math.max(0, Math.min(1, t)) * 1000
  let index = 0
  while (index + 1 < path.length && path[index + 1].offset_ms <= time) index++
  const before = path[index], after = path[index + 1]
  if (!after) return before
  const span = after.offset_ms - before.offset_ms
  // A restart is an explicit placement, never a pass across the field.
  if (span <= 1) return before
  const blend = Math.max(0, Math.min(1, (time - before.offset_ms) / span))
  return {
    ...before,
    offset_ms: time,
    x: before.x + (after.x - before.x) * blend,
    y: before.y + (after.y - before.y) * blend,
    height_m: before.height_m + (after.height_m - before.height_m) * blend,
    progress: before.event_id === after.event_id ? before.progress + (after.progress - before.progress) * blend : before.progress,
  }
}
