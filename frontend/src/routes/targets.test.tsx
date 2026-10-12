import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TargetRow, TargetsOut } from '@/api'
import { TooltipProvider } from '@/components/ui/tooltip'
import { useTeamStore } from '@/stores/team'

import { TargetsPage, injuryStatus, matchupTone } from './targets'

const row = (rank: number, name: string, over: Partial<TargetRow> = {}): TargetRow => ({
  rank,
  player_id: name,
  name,
  position: 'RB',
  nfl_team: 'ATL',
  owner: 'Team Bravo',
  mine: false,
  points: 100 - rank,
  neutral_points: 95 - rank,
  schedule_delta: 5,
  avg_index: 1.1,
  games: 10,
  ppg: 15,
  availability_note: null,
  cells: [{ week: 6, opponent: 'CAR', index: 1.3, points: 18 }],
  ...over,
})

const DATA: TargetsOut = {
  team_id: 'sl-1-1',
  week: 6,
  last_week: 7,
  weeks: [6, 7],
  positions: Object.fromEntries(
    ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'].map((p) => [
      p,
      {
        alpha: p === 'TE' ? 0 : 0.5,
        ros: [row(1, `${p} ROS star`, { mine: true, owner: 'Your team' }), row(2, `${p} free agent`, { owner: 'Free agent' })],
        weekly: [
          { week: 6, rows: [row(1, `${p} week-6 pick`)] },
          { week: 7, rows: [row(1, `${p} week-7 pick`)] },
        ],
      },
    ]),
  ),
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <TargetsPage />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('TargetsPage', () => {
  beforeEach(() => {
    useTeamStore.getState().setTeam({
      teamId: 'sl-1-1',
      leagueId: 'sl-1',
      teamName: 'Team Alpha',
      leagueName: 'Fixture League',
      platform: 'sleeper',
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(DATA), { headers: { 'Content-Type': 'application/json' } })))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the rest-of-season ranking, then a single week', async () => {
    renderPage()
    expect(await screen.findByText('RB ROS star')).toBeInTheDocument()
    expect(screen.getByText('Your team')).toBeInTheDocument()
    expect(screen.getByText('Free agent')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'WR' }))
    expect(screen.getByText('WR ROS star')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('radio', { name: 'By week' }))
    expect(screen.getByText('WR week-6 pick')).toBeInTheDocument()
    expect(screen.queryByText('WR ROS star')).not.toBeInTheDocument()
  })

  it('explains positions where matchups are ignored', async () => {
    renderPage()
    await screen.findByText('RB ROS star')
    await userEvent.click(screen.getByRole('tab', { name: 'TE' }))
    expect(screen.getByText(/haven't predicted TE scoring/)).toBeInTheDocument()
  })
})

describe('helpers', () => {
  it('classifies matchups and reads injury notes', () => {
    expect(matchupTone(1.25)).toBe('easy')
    expect(matchupTone(0.8)).toBe('hard')
    expect(matchupTone(1)).toBe('neutral')
    expect(injuryStatus('On IR: assumed out 4 more weeks')).toBe('IR')
    expect(injuryStatus('Questionable this week (85% chance-weighted)')).toBe('Questionable')
    expect(injuryStatus(null)).toBeNull()
  })
})
