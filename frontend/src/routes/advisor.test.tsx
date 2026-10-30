import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AdviceOut, PendingTradesOut } from '@/api'
import { renderPage as renderWithRouter } from '@/test/render'
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
  return renderWithRouter(<AdvisorPage />)
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
    expect(await screen.findByText('Could not reach the FantasyEdge API.')).toBeInTheDocument()
    expect(screen.getByText(/python tasks.py api/)).toBeInTheDocument()
  })
})

describe('AdvisorPage with accepted trades waiting on ESPN', () => {
  const PENDING: PendingTradesOut = {
    team_id: 'es-1-2026-9',
    review_hours: 24,
    trades: [
      {
        id: 'p1',
        partner_team_id: 'es-1-2026-1',
        partner_name: 'Rival',
        give: [{ player_id: 'q', name: 'Jayden Daniels', position: 'QB' }],
        receive: [{ player_id: 'h', name: 'Tyler Huntley', position: 'QB' }],
        drops: [],
        accepted_at: '2026-10-30T02:42:32',
      },
    ],
    outlook: null,
  }
  const AFTER: AdviceOut = {
    ...ADVICE,
    team_id: 'es-1-2026-9',
    view: 'after',
    pending_trades: 1,
    // QB drops a rank; TE improves its letter at the same rank
    grades: { ...ADVICE.grades, QB: { ...grade('QB', 'C', 0), rank: 7 }, TE: grade('TE', 'B', 0.1) },
    actions: [{ ...ADVICE.actions[0], headline: 'Start Bryce Young over Tyler Huntley' }],
    notes: ['Advice and grades as if your accepted trade had gone through (still waiting on ESPN).'],
  }
  let urls: string[] = []

  beforeEach(() => {
    urls = []
    useTeamStore.getState().setTeam({ teamId: 'es-1-2026-9', leagueId: 'es-1-2026', teamName: 'Mine', leagueName: 'L', platform: 'espn' })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (req: Request) => {
        const url = new URL(req.url)
        urls.push(url.pathname + url.search)
        if (url.pathname.endsWith('/pending-trades')) return Response.json(PENDING)
        return Response.json(url.searchParams.get('roster') === 'after' ? AFTER : { ...ADVICE, team_id: 'es-1-2026-9' })
      }),
    )
  })

  it('switches the feed and grades to the roster after the trades, showing what changed', async () => {
    renderPage()
    expect(await screen.findByText('Sell high on Chuba Hubbard')).toBeInTheDocument()
    const banner = await screen.findByTestId('pending-trades')
    expect(screen.queryByTestId('grade-was')).not.toBeInTheDocument() // today's view: nothing to compare

    await userEvent.click(within(banner).getByRole('radio', { name: 'After accepted trades' }))
    expect(await screen.findByText('Start Bryce Young over Tyler Huntley')).toBeInTheDocument()
    expect(urls).toContain('/team/es-1-2026-9/advice?roster=after')
    expect(screen.getByText('Team grade after the accepted trades')).toBeInTheDocument()
    expect(screen.getByText(/as if your accepted trade had gone through/)).toBeInTheDocument()
    const was = screen.getAllByTestId('grade-was')
    expect(was.map((w) => w.textContent)).toEqual(['▼ was A · #2', '▲ was C · #2']) // QB and TE moved, RB/WR didn't

    await userEvent.click(within(banner).getByRole('radio', { name: 'Current roster' }))
    expect(await screen.findByText('Sell high on Chuba Hubbard')).toBeInTheDocument()
  })

  it('has no roster toggle without pending trades', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (req: Request) =>
        Response.json(new URL(req.url).pathname.endsWith('/pending-trades') ? { ...PENDING, trades: [] } : ADVICE),
      ),
    )
    renderPage()
    await screen.findByText('Sell high on Chuba Hubbard')
    expect(screen.queryByTestId('pending-trades')).not.toBeInTheDocument()
  })
})
