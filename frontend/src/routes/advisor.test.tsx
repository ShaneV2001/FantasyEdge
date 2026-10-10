import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AdviceOut } from '@/api'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useTeamStore } from '@/stores/team'
import { AdvisorPage } from './advisor'

const grade = (position: string, grade: 'A' | 'B' | 'C' | 'D' | 'F', delta: number) => ({
  position,
  points: 20,
  league_avg: 18,
  rank: 2,
  teams: 12,
  grade,
  delta_pct: delta,
})

const player = { player_id: 'p1', name: 'Chuba Hubbard', position: 'RB', nfl_team: 'CAR' }

const ADVICE: AdviceOut = {
  team_id: 'sl-1-1',
  season: 2026,
  week: 5,
  generated_at: '2026-10-10T12:00:00',
  grades: { QB: grade('QB', 'A', 0.2), RB: grade('RB', 'B', 0.08), WR: grade('WR', 'F', -0.3), TE: grade('TE', 'C', 0) },
  needs: ['WR'],
  deadline_passed: false,
  market: { source: 'fantasycalc', format: 'redraft_1qb_12_ppr0.5', stale: false },
  notes: [],
  actions: [
    {
      type: 'Sell',
      headline: 'Sell high on Chuba Hubbard',
      reasons: ['5 TDs on 11 red-zone touches (72 total opportunities); expected ~2.2. Likely to slow down.'],
      urgency: 'before_deadline',
      confidence: 'medium',
      priority: 4.35,
      players: [player],
    },
    {
      type: 'Trade',
      headline: 'Trade idea with Team Bravo: Give Chuba Hubbard for Tee Higgins',
      reasons: ['Your starting lineup gains 12.0 projected points rest of season; theirs gains 6.0.'],
      urgency: 'before_deadline',
      confidence: 'high',
      priority: 3.0,
      players: [player],
      counterparty_team_id: 'sl-1-2',
      counterparty_team_name: 'Team Bravo',
      trade: {
        verdict: 'accept',
        headline: 'Give Chuba Hubbard for Tee Higgins',
        reasons: ['Model value (points above replacement): you give 40, get 52.'],
        me: {
          team_id: 'sl-1-1',
          team_name: 'Team Alpha',
          gives: [player],
          receives: [{ player_id: 'p2', name: 'Tee Higgins', position: 'WR', nfl_team: 'CIN' }],
          lineup_before: 1400,
          lineup_after: 1412,
          lineup_delta: 12,
          model_value_out: 40,
          model_value_in: 52,
          market_value_out: 3000,
          market_value_in: 3100,
        },
        partner: {
          team_id: 'sl-1-2',
          team_name: 'Team Bravo',
          gives: [{ player_id: 'p2', name: 'Tee Higgins', position: 'WR', nfl_team: 'CIN' }],
          receives: [player],
          lineup_before: 1300,
          lineup_after: 1306,
          lineup_delta: 6,
          model_value_out: 52,
          model_value_in: 40,
          market_value_out: 3100,
          market_value_in: 3000,
        },
        tags: ['1-for-1'],
      },
    },
  ],
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <AdvisorPage />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('AdvisorPage', () => {
  beforeEach(() => {
    useTeamStore.getState().setTeam({
      teamId: 'sl-1-1',
      leagueId: 'sl-1',
      teamName: 'Team Alpha',
      leagueName: 'Fixture League',
      platform: 'sleeper',
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('renders grades and the ranked action feed with reasons', async () => {
    const fetchMock = vi.fn(async (_req: Request) => new Response(JSON.stringify(ADVICE), { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    renderPage()

    expect(await screen.findByText('Sell high on Chuba Hubbard')).toBeInTheDocument()
    expect(screen.getByText(/expected ~2.2/)).toBeInTheDocument()
    expect(screen.getByText('F')).toBeInTheDocument() // WR grade
    expect(screen.getByText('#1')).toBeInTheDocument()
    const req = fetchMock.mock.calls[0][0] as Request
    expect(req.url).toContain('/team/sl-1-1/advice')

    // trade breakdown is collapsible
    await userEvent.click(screen.getByRole('button', { name: /show trade breakdown/i }))
    expect(screen.getByText('+12.0 pts')).toBeInTheDocument()
  })

  it('shows an actionable error when the API is down', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))))
    renderPage()
    expect(await screen.findByText('Could not reach the ff-edge API.')).toBeInTheDocument()
    expect(screen.getByText(/python tasks.py api/)).toBeInTheDocument()
  })
})
