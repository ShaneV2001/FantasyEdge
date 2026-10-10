import { describe, expect, it } from 'vitest'

import { useTeamStore } from './team'

describe('team store', () => {
  it('persists the connected team to localStorage and clears it', () => {
    useTeamStore.getState().setTeam({
      teamId: 'sl-1-2',
      leagueId: 'sl-1',
      teamName: 'Team Bravo',
      leagueName: 'Fixture League',
      platform: 'sleeper',
    })
    expect(useTeamStore.getState().team?.teamId).toBe('sl-1-2')
    const saved = JSON.parse(localStorage.getItem('ff-edge:team') ?? '{}')
    expect(saved.state.team.teamName).toBe('Team Bravo')

    useTeamStore.getState().clear()
    expect(useTeamStore.getState().team).toBeNull()
  })
})
