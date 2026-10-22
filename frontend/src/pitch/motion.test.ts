import { describe, expect, it } from 'vitest'
import type { BallSample, TrackingFrame } from '../generated/TrackingFrame'
import { interpolate, isDiscontinuity, sampleBallPath, zero } from './motion'

function frame(seq: number, ms = seq * 1000): TrackingFrame {
  return { match_id: 'fixture', frame_seq: seq, clock: { period: 1, ms }, ball: { x: 52.5, y: 34 }, interval_ms: 1000, ball_speed_kmh: 0, players: [], ball_trajectory: [], player_trajectories: {} }
}

describe('tracking playback', () => {
  it('hits the measured positions and never overshoots, even after an abrupt reversal', () => {
    const start = { x: 45, y: 37 }, end = { x: 42, y: 39 }
    const incoming = { x: 30, y: -20 }, outgoing = { x: -20, y: 50 }
    expect(interpolate(start, end, incoming, outgoing, 0)).toEqual(start)
    expect(interpolate(start, end, incoming, outgoing, 1)).toEqual(end)
    let last = start
    for (let step = 1; step <= 100; step++) {
      const position = interpolate(start, end, incoming, outgoing, step / 100)
      expect(position.x).toBeGreaterThanOrEqual(end.x)
      expect(position.x).toBeLessThanOrEqual(last.x)
      expect(position.y).toBeGreaterThanOrEqual(last.y)
      expect(position.y).toBeLessThanOrEqual(end.y)
      last = position
    }
  })

  it('holds stationary players still despite a stale movement tangent', () => {
    expect(interpolate({ x: 5, y: 9 }, { x: 5, y: 9 }, { x: 8, y: -2 }, zero, .5)).toEqual({ x: 5, y: 9 })
  })

  it('resets across halftime, match changes, replay seeks and missing tracking', () => {
    expect(isDiscontinuity(frame(1), frame(2), false)).toBe(false)
    expect(isDiscontinuity(null, frame(1), false)).toBe(true)
    expect(isDiscontinuity(frame(5), frame(2), false)).toBe(true)
    expect(isDiscontinuity(frame(1), frame(2), true)).toBe(true)
    expect(isDiscontinuity(frame(1), { ...frame(2), match_id: 'another' }, false)).toBe(true)
    expect(isDiscontinuity(frame(1), { ...frame(2), clock: { period: 2, ms: 0 } }, false)).toBe(true)
    expect(isDiscontinuity(frame(1), frame(20), false)).toBe(true)
  })

  it('plays a short pass within its actual flight window instead of stretching it to a second', () => {
    const sample = (offset_ms: number, x: number, height_m = 0): BallSample => ({ offset_ms, x, y: 34, height_m, action: 'pass', preparing: false, actor_id: 'h06', event_id: 'pass-1', progress: offset_ms / 500 })
    const path = [sample(0, 40), sample(250, 45, 1.5), sample(500, 50), sample(1000, 50)]
    expect(sampleBallPath(path, .25)?.x).toBe(45)
    expect(sampleBallPath(path, .25)?.height_m).toBe(1.5)
    expect(sampleBallPath(path, .5)?.x).toBe(50)
    expect(sampleBallPath(path, .9)?.x).toBe(50)
    expect(sampleBallPath([], .5)).toBeNull()
  })

  it('places a restart without animating a cross-field ball flight', () => {
    const sample = (offset_ms: number, x: number): BallSample => ({ offset_ms, x, y: 34, height_m: 0, action: 'hold', preparing: false, actor_id: null, event_id: null, progress: 0 })
    const path = [sample(0, 105), sample(999, 105), sample(1000, 52.5)]
    expect(sampleBallPath(path, .9995)?.x).toBe(105)
    expect(sampleBallPath(path, 1)?.x).toBe(52.5)
  })
})
