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

    expect(screen.getByRole('link', { name: 'MatchLens home' })).toBeInTheDocument()
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
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
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
          })
        }
        if (path === '/api/matches/match-1/state') {
          return jsonResponse({ status: 'running', metrics: [] })
        }
        return jsonResponse({})
      }),
    )
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
  })
})
