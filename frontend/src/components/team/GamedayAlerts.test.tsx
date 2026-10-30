import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { GamedayOut } from '@/api'
import { renderPage } from '@/test/render'

import { GamedayAlerts } from './GamedayAlerts'

const TEAM = { teamId: 'me', leagueId: 'l', teamName: 'Mine', leagueName: 'L', platform: 'espn' } as const

const ref = (id: string, name: string, position = 'RB') => ({ player_id: id, name, position, nfl_team: 'KC' })

function serve(data: GamedayOut) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })),
  )
}

describe('GamedayAlerts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lists starters who might not play with who to start instead', async () => {
    serve({
      team_id: 'me',
      week: 9,
      generated_at: '2026-11-01T12:00:00Z',
      checked: 9,
      notes: [],
      alerts: [
        {
          player: ref('q', 'Questionable Guy'),
          slot: 'FLEX',
          severity: 'medium',
          status: 'Questionable',
          points: 11.2,
          kickoff: '2026-11-02T01:20:00Z',
          reasons: ['Questionable Guy is listed Questionable.', 'Latest practice report: Limited.'],
          pivot: { player: ref('e', 'Early Bench'), points: 9.1, kickoff: '2026-11-01T18:00:00Z' },
          late_pivot: { player: ref('l', 'Late Bench', 'WR'), points: 7.4, kickoff: '2026-11-02T01:20:00Z' },
          free_agent: null,
        },
      ],
    })
    renderPage(<GamedayAlerts team={TEAM} />)
    expect(await screen.findByText('1 starter might not play in week 9')).toBeInTheDocument()
    expect(screen.getByText('Questionable')).toBeInTheDocument()
    expect(screen.getByText('Latest practice report: Limited.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Early Bench' })).toBeInTheDocument()
    expect(screen.getByText(/Or wait for inactives with/)).toBeInTheDocument()
  })

  it('stays hidden when nobody is flagged', async () => {
    serve({ team_id: 'me', week: 9, generated_at: '2026-11-01T12:00:00Z', checked: 9, notes: [], alerts: [] })
    const { container } = renderPage(<GamedayAlerts team={TEAM} />)
    await new Promise((r) => setTimeout(r, 50))
    expect(container.querySelector('[data-testid="gameday-alerts"]')).toBeNull()
  })
})
