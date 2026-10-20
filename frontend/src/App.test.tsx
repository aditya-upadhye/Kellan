import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MatchMetadata } from './generated/MatchMetadata'
import type { ViewerProfile } from './generated/ViewerProfile'
import App from './App'

const profiles: ViewerProfile[] = [
  {
    profile_id: 'analyst_en',
    label: 'Analyst',
    mode: 'analyst',
    language: 'en',
    favorite_team_id: null,
    favorite_player_id: null,
    focus_metric: null,
    verbosity: 'detailed',
  },
  {
    profile_id: 'casual_en',
    label: 'Casual',
    mode: 'casual',
    language: 'en',
    favorite_team_id: null,
    favorite_player_id: null,
    focus_metric: null,
    verbosity: 'short',
  },
  {
    profile_id: 'casual_es',
    label: 'Casual (es)',
    mode: 'casual',
    language: 'es',
    favorite_team_id: null,
    favorite_player_id: null,
    focus_metric: null,
    verbosity: 'short',
  },
]

const metadata = {
  match_id: 'match-1',
  competition: 'Meridian League',
  venue: 'Harbor Ground',
  scenario: 'balanced',
  seed: 1,
  home: {
    team_id: 'home',
    name: 'Kestrel Bay Athletic',
    short_name: 'KBA',
    colors: { primary: '#0e5e6f', secondary: '#f4d35e' },
  },
  away: {
    team_id: 'away',
    name: 'Ashmoor Rovers',
    short_name: 'ASR',
    colors: { primary: '#8c1c13', secondary: '#f2e8cf' },
  },
} as MatchMetadata

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    json: async () => body,
  } as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('renders the live match kickoff screen', () => {
    render(<App />)

    expect(screen.getByRole('link', { name: 'Kellan home' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'See the game take shape.' })).toBeInTheDocument()
  })

  it('loads profile choices and allows comparison before kickoff', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) =>
        String(input) === '/api/profiles' ? jsonResponse(profiles) : jsonResponse([]),
      ),
    )
    render(<App />)

    const profileSelect = await screen.findByRole('combobox', { name: 'Primary viewer profile' })
    expect(within(profileSelect).getByRole('option', { name: 'Analyst' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'COMPARE PROFILES' }))
    const comparison = screen.getByRole('combobox', { name: 'Comparison viewer profile' })
    fireEvent.change(comparison, { target: { value: 'casual_es' } })

    expect(comparison).toHaveValue('casual_es')
    expect(screen.getByRole('button', { name: 'HIDE COMPARISON' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('starts the fixed Judge preset when the deployment enables Judge mode', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/config') return jsonResponse({ judge_mode: true })
      if (path === '/api/profiles') return jsonResponse(profiles)
      if (path === '/api/scenarios') {
        return jsonResponse([{ name: 'late_comeback', description: 'A late comeback.' }])
      }
      if (path === '/api/matches' && init?.method === 'POST') {
        return {
          ok: false,
          json: async () => ({ detail: 'test complete' }),
        } as Response
      }
      return jsonResponse({})
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Judge mode' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'START JUDGE MODE' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /KICK OFF MATCH/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'START JUDGE MODE' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/matches',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            scenario: 'late_comeback',
            seed: 1,
            speed: 10,
            profiles: profiles.map((profile) => profile.profile_id),
          }),
        }),
      ),
    )
  })

  it('keeps two selected profile views synchronized to the same live match', async () => {
    const sockets: Array<{
      onmessage: ((message: MessageEvent<string>) => void) | null
      close: ReturnType<typeof vi.fn>
    }> = []

    class TestWebSocket {
      onopen: ((event: Event) => void) | null = null
      onclose: ((event: CloseEvent) => void) | null = null
      onerror: ((event: Event) => void) | null = null
      onmessage: ((message: MessageEvent<string>) => void) | null = null
      close = vi.fn()

      constructor() {
        sockets.push(this)
      }
    }

    vi.stubGlobal('WebSocket', TestWebSocket)
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input)
        if (path === '/api/profiles') return jsonResponse(profiles)
        if (path === '/api/scenarios') {
          return jsonResponse([{ name: 'balanced', description: 'Evenly matched fixture.' }])
        }
        if (path === '/api/matches' && init?.method === 'POST') {
          return jsonResponse({ match_id: 'match-1' })
        }
        if (path === '/api/matches/match-1') {
          return jsonResponse({
            metadata,
            status: 'running',
            clock: { period: 1, ms: 60_000 },
            score: { home: 0, away: 0 },
            speed: 10,
            error: null,
            fault_inject_next: false,
          })
        }
        if (path === '/api/matches/match-1/state') {
          return jsonResponse({ status: 'running', metrics: [] })
        }
        if (path === '/api/matches/match-1/control' && init?.method === 'POST') {
          return jsonResponse({ status: 'running', speed: 10, fault_inject_next: true })
        }
        return jsonResponse({})
      })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'COMPARE PROFILES' }))
    fireEvent.change(screen.getByRole('combobox', { name: 'Comparison viewer profile' }), {
      target: { value: 'casual_es' },
    })
    const kickoff = await screen.findByRole('button', { name: /KICK OFF MATCH/ })
    await waitFor(() => expect(kickoff).toBeEnabled())
    fireEvent.click(kickoff)

    const comparison = await screen.findByRole('region', { name: 'Live profile comparison' })
    expect(within(comparison).getByText('Analyst')).toBeInTheDocument()
    expect(within(comparison).getByText('Casual (es)')).toBeInTheDocument()
    expect(within(comparison).getAllByText('0 : 0')).toHaveLength(2)

    await waitFor(() => expect(sockets).toHaveLength(1))
    act(() => {
      sockets[0]?.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            kind: 'event',
            match_id: 'match-1',
            data: {
              type: 'goal',
              team_id: 'home',
              player_id: 'h09',
              seq: 1,
              clock: { period: 1, ms: 70_000 },
            },
          }),
        }),
      )
    })

    expect(within(comparison).getAllByText('1 : 0')).toHaveLength(2)
    expect(within(comparison).getByText('Gol de KBA; cambia el marcador.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'ARM' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'CANCEL' })).toHaveAttribute('aria-pressed', 'true'))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/matches/match-1/control',
      expect.objectContaining({
        body: JSON.stringify({ action: 'inject_fault', enabled: true }),
      }),
    )

    act(() => {
      sockets[0]?.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            kind: 'trace',
            match_id: 'match-1',
            data: {
              trace_id: 'trace-1',
              match_id: 'match-1',
              moment_id: 'moment-1',
              agent: 'fact_checker',
              action: 'verify',
              status: 'rejected',
              latency_ms: 3,
              tokens_in: 0,
              tokens_out: 0,
              detail: 'attempt=1; value_mismatch',
              draft_text: 'A generated number was wrong.',
              ts: '2026-10-12T12:00:00Z',
            },
          }),
        }),
      )
    })

    const activity = screen.getByRole('region', { name: 'Agent activity' })
    expect(within(activity).getByText('attempt=1; value_mismatch')).toBeInTheDocument()
    expect(within(activity).getByText('A generated number was wrong.')).toBeInTheDocument()
    expect(within(activity).getByText('rejected').closest('.trace-row')).toHaveClass('rejected')

    act(() => {
      sockets[0]?.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            kind: 'cue',
            match_id: 'match-1',
            data: {
              action: 'show',
              cue_id: 'cue-1',
              match_id: 'match-1',
              profile_id: 'analyst_en',
              insight_id: 'insight-1',
              trigger_seq: 2,
              clock: { period: 1, ms: 90_000 },
              template: 'stat_bar',
              slot: 'side_panel',
              priority: 50,
              start_delay_ms: 0,
              duration_ms: 5_000,
              expires_at: { period: 1, ms: 150_000 },
              headline: 'Control is shifting',
              body: 'Kestrel Bay is building pressure.',
              language: 'en',
              data: { status: 'verified', claims: [] },
              provenance: {
                metric_ids: ['match.momentum'],
                checker: { passed: true, attempts: 1, version: 'deterministic-v1' },
                model_ids: ['mock-fast'],
              },
            },
          }),
        }),
      )
      sockets[0]?.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            kind: 'recap',
            match_id: 'match-1',
            data: {
              recap_id: 'recap-1',
              match_id: 'match-1',
              profile_id: 'analyst_en',
              kind: 'half',
              title: 'Half-time recap',
              paragraphs: ['Kestrel Bay controlled the first half.'],
              key_moment_ids: ['moment-1'],
              claims: [
                {
                  claim_id: 'claim-1',
                  text_span: '62% possession',
                  metric_id: 'team.home.possession_pct',
                  value: 62,
                  as_of_seq: 20,
                },
              ],
              status: 'verified',
            },
          }),
        }),
      )
    })

    expect(await screen.findByText('Control is shifting')).toBeInTheDocument()
    expect(screen.getByText('VERIFIED FROM match.momentum')).toBeInTheDocument()
    const recap = screen.getByRole('region', { name: 'Analyst match recap' })
    expect(within(recap).getByText('Half-time recap')).toBeInTheDocument()
    expect(within(recap).getByText('Kestrel Bay controlled the first half.')).toBeInTheDocument()
    fireEvent.click(within(recap).getByText('1 verified claims'))
    expect(within(recap).getByText('team.home.possession_pct')).toBeInTheDocument()

    fireEvent.change(screen.getByRole('combobox', { name: 'Primary viewer profile' }), {
      target: { value: 'casual_es' },
    })
    expect(screen.queryByText('Control is shifting')).not.toBeInTheDocument()
    expect(screen.queryByText('Half-time recap')).not.toBeInTheDocument()
    fireEvent.change(screen.getByRole('combobox', { name: 'Primary viewer profile' }), {
      target: { value: 'analyst_en' },
    })
    expect(await screen.findByText('Control is shifting')).toBeInTheDocument()

    act(() => {
      sockets[0]?.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            kind: 'cue',
            match_id: 'match-1',
            data: { action: 'remove', cue_id: 'cue-1', profile_id: 'analyst_en', reason: 'preempted' },
          }),
        }),
      )
    })
    await waitFor(() => expect(screen.queryByText('Control is shifting')).not.toBeInTheDocument())
  })
})
