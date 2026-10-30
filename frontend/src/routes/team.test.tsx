import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PendingTradesOut, PositionGradeOut, RosterPlayer, TeamOut } from '@/api'
import { useTeamStore } from '@/stores/team'
import { renderPage } from '@/test/render'

import { TeamPage } from './team'

const grade = (position: string, g: PositionGradeOut['grade'], rank: number): PositionGradeOut => ({
  position,
  points: 20,
  league_avg: 18,
  rank,
  teams: 10,
  grade: g,
  delta_pct: 0,
})

const player = (id: string, name: string, position: string, over: Partial<RosterPlayer> = {}): RosterPlayer => ({
  player_id: id,
  name,
  position,
  nfl_team: 'DET',
  ppg: 15,
  proj_ros_points: 150,
  games_remaining: 10,
  ros_value_par: 40,
  next4_points: 60,
  slot: 'starter',
  optimal_starter: true,
  signal: 'hold',
  ...over,
})

const TEAM: TeamOut = {
  team_id: 'es-1-2026-9',
  team_name: 'Mine',
  owner_name: 'Me',
  record: '4-3',
  league: {
    league_id: 'es-1-2026',
    platform: 'espn',
    name: 'Office League',
    season: 2026,
    week: 7,
    num_teams: 10,
    roster_positions: ['QB', 'RB', 'WR'],
    scoring: 'PPR',
    trade_deadline_week: 12,
    deadline_passed: false,
    playoff_week_start: 15,
    uses_faab: false,
    faab_budget: null,
    last_synced_at: null,
  },
  roster: [player('qb', 'Jayden Daniels', 'QB'), player('rb', 'Jonah Coleman', 'RB')],
  grades: { QB: grade('QB', 'B', 3), RB: grade('RB', 'D', 8) },
  needs: ['RB'],
  surplus: [],
  starter_points: 120.3,
  league_teams: [],
  market: { source: 'fantasycalc', format: 'redraft', stale: false },
}

const AFTER: TeamOut = {
  ...TEAM,
  view: 'after',
  pending_trades: 1,
  roster: [player('hu', 'Tyler Huntley', 'QB', { slot: 'bench', arriving: true }), player('rb', 'Jonah Coleman', 'RB')],
  grades: { QB: grade('QB', 'B', 3), RB: grade('RB', 'C', 5) },
  needs: [],
  starter_points: 123.8,
}

const PENDING: PendingTradesOut = {
  team_id: 'es-1-2026-9',
  review_hours: 24,
  trades: [
    {
      id: 'p1',
      partner_team_id: 'es-1-2026-1',
      partner_name: 'Rival',
      give: [{ player_id: 'qb', name: 'Jayden Daniels', position: 'QB' }],
      receive: [{ player_id: 'hu', name: 'Tyler Huntley', position: 'QB' }],
      drops: [],
      accepted_at: '2026-10-30T02:42:32',
    },
  ],
  outlook: null,
}

const REGRESSION = { team_id: 'es-1-2026-9', roster: [], league: [], thresholds: { tdoe: 2, efficiency_z: 1.5 } }

function serve(pending: PendingTradesOut) {
  const urls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (req: Request) => {
      const url = new URL(req.url)
      urls.push(url.pathname + url.search)
      if (url.pathname.endsWith('/pending-trades')) return Response.json(pending)
      if (url.pathname.endsWith('/regression')) return Response.json(REGRESSION)
      return Response.json(url.searchParams.get('roster') === 'after' ? AFTER : TEAM)
    }),
  )
  return urls
}

describe('TeamPage with accepted trades waiting on ESPN', () => {
  beforeEach(() => {
    useTeamStore.getState().setTeam({ teamId: 'es-1-2026-9', leagueId: 'es-1-2026', teamName: 'Mine', leagueName: 'L', platform: 'espn' })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the roster, grades and points after the trades, marking what changed', async () => {
    const urls = serve(PENDING)
    renderPage(<TeamPage />)
    expect(await screen.findByText('Jayden Daniels')).toBeInTheDocument()
    const banner = await screen.findByTestId('pending-trades')

    await userEvent.click(within(banner).getByRole('radio', { name: 'After accepted trades' }))
    expect(await screen.findByText('Roster after the accepted trades')).toBeInTheDocument()
    expect(urls).toContain('/team/es-1-2026-9?roster=after')
    expect(urls).toContain('/team/es-1-2026-9/regression?roster=after')
    expect(screen.getByText('Tyler Huntley')).toBeInTheDocument()
    expect(screen.getByText('NEW')).toBeInTheDocument()
    expect(screen.queryByText('Jayden Daniels', { selector: 'a' })).not.toBeInTheDocument()
    expect(screen.getByText(/after 1 accepted trade · starting lineup projects 123\.8 ppg \(was 120\.3\)/)).toBeInTheDocument()
    expect(screen.getAllByTestId('grade-was').map((w) => w.textContent)).toEqual(['▲ was D · #8']) // only RB moved
  })

  it('has no roster toggle without pending trades', async () => {
    serve({ ...PENDING, trades: [] })
    renderPage(<TeamPage />)
    await screen.findByText('Jayden Daniels')
    expect(screen.queryByTestId('pending-trades')).not.toBeInTheDocument()
    expect(screen.queryByText('NEW')).not.toBeInTheDocument()
  })
})
