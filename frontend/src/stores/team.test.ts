import { describe, expect, it, vi } from 'vitest'

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
    const saved = JSON.parse(localStorage.getItem('fantasyedge:team') ?? '{}')
    expect(saved.state.team.teamName).toBe('Team Bravo')

    useTeamStore.getState().clear()
    expect(useTeamStore.getState().team).toBeNull()
  })

  it('carries a team saved under the old ff-edge key over to the new key', async () => {
    localStorage.clear()
    const saved = JSON.stringify({ state: { team: { teamId: 'mn-1', leagueId: 'mn-1', teamName: 'Old', leagueName: 'L', platform: 'manual' } }, version: 1 })
    localStorage.setItem('ff-edge:team', saved)
    vi.resetModules()
    const { useTeamStore: fresh } = await import('./team')
    expect(fresh.getState().team?.teamName).toBe('Old')
    expect(localStorage.getItem('ff-edge:team')).toBeNull()
  })
})
