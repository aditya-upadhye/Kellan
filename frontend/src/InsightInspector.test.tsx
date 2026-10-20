import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { InsightInspector, InsightShelf } from './InsightInspector'
import { insightFixture } from './test/insightEvidence'

describe('insight inspection', () => {
  it('connects published numeric phrases to calculations, events and rejected drafts', () => {
    const onSelectClaim = vi.fn(), onEvent = vi.fn(), onProfile = vi.fn(), onSeek = vi.fn()
    render(<InsightInspector data={insightFixture()} loading={false} error={null} profileId="analyst_en" profiles={[]} selectedClaim={null} onSelectClaim={onSelectClaim} onProfile={onProfile} onClose={vi.fn()} onRetry={vi.fn()} replayIndex={0} replayPaused={true} onReplayPause={vi.fn()} onSeek={onSeek} onRestart={vi.fn()} activeEventId={null} onEvent={onEvent} />)
    fireEvent.click(screen.getByRole('button', { name: 'Inspect claim: 36 km/h' }))
    expect(onSelectClaim).toHaveBeenCalledWith('event.match-1-000002.ball_speed_kmh@2')
    expect(screen.getByText('REPRODUCED')).toBeInTheDocument()
    expect(screen.getByText('Saved at publication')).toBeInTheDocument()
    expect(screen.getByText('Recomputed from inputs')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Inspect event pass at 0:01' }))
    expect(onEvent).toHaveBeenCalledWith('match-1-000002')
    fireEvent.click(screen.getByRole('button', { name: 'casual_es' }))
    expect(onProfile).toHaveBeenCalledWith('casual_es')
    fireEvent.change(screen.getByRole('slider', { name: 'Evidence replay position' }), { target: { value: '1' } })
    expect(onSeek).toHaveBeenCalledWith(1)
    expect(screen.getByText('The pass travelled at 99 km/h.')).toBeInTheDocument()
    expect(screen.getByText(/does not establish causation/)).toBeInTheDocument()
  })

  it('keeps only the selected audience in the published insight shelf', () => {
    const data = insightFixture(), inspect = vi.fn()
    render(<InsightShelf cues={data.versions.map(version => version.cue)} profileId="casual_es" selectedId={null} onInspect={inspect} />)
    const shelf = screen.getByRole('region', { name: 'Published insights' })
    expect(within(shelf).getByText('El pase viajó a 36 km/h.')).toBeInTheDocument()
    expect(within(shelf).queryByText('The pass travelled at 36 km/h.')).not.toBeInTheDocument()
    fireEvent.click(within(shelf).getByRole('button', { name: 'Show me why: A measured pass' }))
    expect(inspect).toHaveBeenCalledWith(data.versions[1].cue)
  })
})
