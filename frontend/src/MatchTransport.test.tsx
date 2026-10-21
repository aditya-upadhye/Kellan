import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MatchTransport } from './MatchTransport'
import { insightFixture } from './test/insightEvidence'

describe('MatchTransport', () => {
  const frames = insightFixture().replay.frames
  it('seeks received footage and keeps Return Live explicit', () => {
    const onSeek = vi.fn(), onLive = vi.fn()
    render(<MatchTransport frames={frames} current={frames[1]} replaying paused evidence={false} onSeek={onSeek} onToggle={vi.fn()} onLive={onLive} />)
    fireEvent.change(screen.getByRole('slider', { name: 'Seek match replay' }), { target: { value: '0' } })
    expect(onSeek).toHaveBeenCalledWith(0)
    fireEvent.click(screen.getByRole('button', { name: 'RETURN LIVE' }))
    expect(onLive).toHaveBeenCalledOnce()
  })
  it('supports keyboard rewind and time intervals across period boundaries', () => {
    const onSeek = vi.fn()
    const periodFrames = [frames[0], { ...frames[1], clock: { period: 2 as const, ms: 0 }, interval_ms: 0 }, { ...frames[1], frame_seq: 3, clock: { period: 2 as const, ms: 1000 }, interval_ms: 1000 }]
    render(<MatchTransport frames={periodFrames} current={periodFrames[2]} replaying paused evidence={false} onSeek={onSeek} onToggle={vi.fn()} onLive={vi.fn()} />)
    fireEvent.keyDown(screen.getByRole('slider'), { key: 'ArrowLeft' })
    expect(onSeek).toHaveBeenCalledWith(0)
    fireEvent.keyDown(screen.getByRole('slider'), { key: 'End' })
    expect(onSeek).toHaveBeenLastCalledWith(2)
  })
})
