import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { PositionGradeOut, RosterPlayer } from '@/api'
import { LineupBySlot } from '@/components/team/LineupBySlot'
import { renderPage } from '@/test/render'

import { RankChanges } from './TradePreview'

function player(p: Partial<RosterPlayer> & Pick<RosterPlayer, 'player_id' | 'name' | 'position'>): RosterPlayer {
  return {
    nfl_team: 'DET',
    ppg: 10,
    proj_ros_points: 100,
    next4_points: 40,
    games_remaining: 10,
    ros_value_par: 5,
    slot: 'bench',
    optimal_starter: false,
    on_bye: false,
    ...p,
  }
}

const grade = (rank: number, letter: PositionGradeOut['grade']): PositionGradeOut => ({
  position: 'RB',
  points: 30,
  league_avg: 28,
  rank,
  teams: 12,
  grade: letter,
  delta_pct: 0,
})

describe('LineupBySlot', () => {
  it('lists the lineup by slot with ROS ranks, marks arrivals and who leaves', async () => {
    const before = [
      player({ player_id: 'qb', name: 'QB One', position: 'QB', lineup_slot: 'QB', optimal_starter: true }),
      player({ player_id: 'rb1', name: 'Watson Brown', position: 'RB', lineup_slot: 'RB', optimal_starter: true, model_rank: 30 }),
    ]
    const after = [
      player({ player_id: 'qb', name: 'QB One', position: 'QB', lineup_slot: 'QB', optimal_starter: true }),
      player({ player_id: 'gibbs', name: 'Jahmyr Gibbs', position: 'RB', lineup_slot: 'RB', optimal_starter: true, model_rank: 3, arriving: true }),
      player({ player_id: 'wr9', name: 'Bench Guy', position: 'WR', model_rank: 60 }),
    ]
    renderPage(<LineupBySlot roster={after} was={before} />)

    const lineup = await screen.findByRole('list', { name: 'Starting lineup' })
    const gibbs = within(lineup).getByText('Jahmyr Gibbs').closest('li')!
    expect(gibbs).toHaveAttribute('data-testid', 'lineup-arriving')
    expect(within(gibbs).getByText('RB3')).toBeInTheDocument()
    expect(within(gibbs).getByText('New')).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Bench' })).getByText('WR60')).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Leaving' })).getByText('Watson Brown')).toBeInTheDocument()
  })
})

describe('RankChanges', () => {
  it('shows each position rank now and after, with the move', async () => {
    renderPage(<RankChanges before={{ RB: grade(6, 'C') }} after={{ RB: grade(2, 'A') }} />)
    const moves = await screen.findAllByTestId('rank-move')
    expect(moves.map((m) => m.textContent)).toContain('▲4')
    expect(screen.getByText('#6')).toBeInTheDocument()
    expect(screen.getByText('#2')).toBeInTheDocument()
  })
})
