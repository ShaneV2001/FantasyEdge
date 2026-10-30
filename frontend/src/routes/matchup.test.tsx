import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { MatchupOut, MatchupSideOut } from '@/api'
import { renderPage } from '@/test/render'

import { MatchupView } from './matchup'

const ref = (id: string, name: string, position = 'RB') => ({ player_id: id, name, position, nfl_team: 'KC' })

const side = (team: string, name: string, players: [string, string, MatchupSideOut['lineup'][number]['state']][]): MatchupSideOut => ({
  team_id: team,
  team_name: name,
  projected: 118.4,
  sd: 21,
  actual: 31.2,
  lineup: players.map(([id, n, state]) => ({ slot: 'RB', player: ref(id, n), projected: 12, actual: state === 'upcoming' ? null : 14.5, state })),
})

const DATA: MatchupOut = {
  team_id: 'me',
  week: 8,
  has_schedule: true,
  me: side('me', 'My Team', [['a', 'Done Guy', 'final'], ['b', 'Sunday Guy', 'upcoming']]),
  opponent: side('them', 'Rivals', [['c', 'Their Guy', 'live'], ['d', 'Other Guy', 'upcoming']]),
  win_prob: 0.62,
  standings: [
    { team_id: 'them', team_name: 'Rivals', is_mine: false, wins: 6, losses: 1, points_for: 900, proj_wins: 10.2, proj_losses: 3.8, playoff_pct: 0.97, top_seed_pct: 0.6 },
    { team_id: 'me', team_name: 'My Team', is_mine: true, wins: 4, losses: 3, points_for: 850, proj_wins: 7.9, proj_losses: 6.1, playoff_pct: 0.41, top_seed_pct: 0.02 },
  ],
  schedule: [
    { week: 7, opponent_id: 'x', opponent_name: 'Old Foe', result: 'W', points: 120.5, opponent_points: 99.1, win_prob: null },
    { week: 8, opponent_id: 'them', opponent_name: 'Rivals', win_prob: 0.62, result: null },
  ],
  playoff_teams: 4,
  regular_season_weeks: 14,
  sims: 5000,
  notes: ['Divisions aren’t modelled.'],
}

describe('MatchupView', () => {
  it('shows the win chance, both lineups, the standings with odds and the schedule', async () => {
    renderPage(<MatchupView data={DATA} />)
    expect(await screen.findByRole('img', { name: '62% chance to win' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Done Guy' })).toBeInTheDocument()
    expect(screen.getByText('Final')).toBeInTheDocument()
    expect(screen.getByText('Live')).toBeInTheDocument()
    expect(screen.getByText(/You: 41% to make it, 2% for the 1 seed/)).toBeInTheDocument()
    expect(screen.getByText('97%')).toBeInTheDocument()
    expect(screen.getByText(/W 120.5–99.1/)).toBeInTheDocument()
    expect(screen.getByText('62% to win')).toBeInTheDocument()
    expect(screen.getByText('Divisions aren’t modelled.')).toBeInTheDocument()
  })
})
