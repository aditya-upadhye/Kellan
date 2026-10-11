import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders the live match kickoff screen', () => {
    render(<App />)

    expect(screen.getByRole('link', { name: 'MatchLens home' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'See the game take shape.' })).toBeInTheDocument()
  })
})
