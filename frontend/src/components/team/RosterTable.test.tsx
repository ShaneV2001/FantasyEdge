import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { RosterPlayer } from '@/api'
import { renderPage } from '@/test/render'

import { RosterTable } from './RosterTable'

function player(p: Partial<RosterPlayer> & Pick<RosterPlayer, 'player_id' | 'name' | 'position'>): RosterPlayer {
  return {
    nfl_team: 'KC',
    ppg: 10,
    proj_ros_points: 100,
    next4_points: 40,
    games_remaining: 10,
    ros_value_par: 5,
    bye_week: 9,
    slot: 'starter',
    optimal_starter: true,
    on_bye: false,
    ...p,
  }
}

describe('RosterTable', () => {
  it('keeps a player on bye out of the best lineup and tags him BYE', async () => {
    // Server order: this week's best lineup first, then the bench.
    const roster = [
      player({ player_id: 'wr2', name: 'Fill In', position: 'WR', ppg: 8 }),
      player({ player_id: 'def2', name: 'Rams', position: 'DEF', ppg: 4.6 }),
      player({ player_id: 'wr1', name: "Ja'Marr Chase", position: 'WR', ppg: 16.3, slot: 'bench', optimal_starter: false, on_bye: true, bye_week: 6 }),
      player({ player_id: 'def1', name: 'Vikings', position: 'DEF', ppg: 5.3, slot: 'bench', optimal_starter: false, on_bye: true, bye_week: 6 }),
    ]
    renderPage(<RosterTable roster={roster} week={6} />)

    expect(await screen.findByText('Best lineup · week 6')).toBeInTheDocument()
    for (const name of ["Ja'Marr Chase", 'Vikings']) {
      const row = screen.getByText(name).closest('tr')!
      expect(within(row).getByText('BYE')).toBeInTheDocument()
      expect(within(row).queryByText('BENCHED')).not.toBeInTheDocument()
    }
    for (const name of ['Fill In', 'Rams']) {
      const row = screen.getByText(name).closest('tr')!
      expect(within(row).queryByText('STARTING')).not.toBeInTheDocument()
      expect(within(row).queryByText('BYE')).not.toBeInTheDocument()
    }
  })
})
