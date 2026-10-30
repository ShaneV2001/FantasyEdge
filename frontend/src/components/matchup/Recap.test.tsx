import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { RecapOut, RecapPlayerOut } from '@/api'
import { renderPage } from '@/test/render'

import { RecapView } from './Recap'

const p = (id: string, name: string, actual: number, band: RecapPlayerOut['band'] = 'in_range'): RecapPlayerOut => ({
  player: { player_id: id, name, position: 'WR', nfl_team: 'KC' },
  actual,
  projected: 12,
  p10: 4,
  p90: 21,
  band,
})

const DATA: RecapOut = {
  team_id: 'me',
  week: 4,
  weeks: [1, 2, 3, 4],
  detail: {
    week: 4,
    opponent_name: 'Rivals',
    result: 'L',
    points: 101.2,
    opponent_points: 110.4,
    lineup_points: 101.2,
    best_points: 124.7,
    left_on_bench: 23.5,
    fe_points: 115.0,
    fe_lineup: [],
    starters: [p('a', 'Boom Guy', 31, 'above'), p('b', 'Bust Guy', 1.2, 'below')],
    should_have_started: [p('c', 'Bench Star', 24.7)],
    instead_of: [p('b', 'Bust Guy', 1.2, 'below')],
  },
  by_week: [],
  season: {
    weeks: 4, lineup_points: 420, best_points: 480, fe_points: 431.5, left_on_bench: 60,
    starters_rated: 36, mae: 5.4, in_band: 0.78,
  },
  notes: ['Projections are what FantasyEdge would have said before each week.'],
}

describe('RecapView', () => {
  it('sums up the season and explains the week', async () => {
    renderPage(<RecapView data={DATA} onWeek={vi.fn()} />)
    expect(await screen.findByText('Season so far')).toBeInTheDocument()
    expect(screen.getByText('+11.5')).toBeInTheDocument() // FantasyEdge's lineups vs yours
    expect(screen.getByText('78%')).toBeInTheDocument()
    expect(screen.getByText('23.5 left on the bench')).toBeInTheDocument()
    expect(screen.getByText(/Bench Star \(24.7\)/)).toBeInTheDocument()
    expect(screen.getByText(/instead of Bust Guy \(1.2\)/)).toBeInTheDocument()
    expect(screen.getByText('Beat p90')).toBeInTheDocument()
    expect(screen.getByText('Below p10')).toBeInTheDocument()
  })
})
