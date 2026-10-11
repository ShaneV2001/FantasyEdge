import { describe, expect, it, vi } from 'vitest'

import { useTeamStore } from '@/stores/team'

import { isStaleTeamError, makeStaleTeamHandler } from './stale-team'

const team = {
  teamId: 'mn-abc-1',
  leagueId: 'mn-abc',
  teamName: 'Mine',
  leagueName: 'Manual league',
  platform: 'manual' as const,
}

describe('stale team handling', () => {
  it('clears the saved team and goes to Connect when the API says it is gone', () => {
    useTeamStore.getState().setTeam(team)
    const goToConnect = vi.fn()
    makeStaleTeamHandler(goToConnect)({ detail: 'Team not found: mn-abc-1', kind: 'team' })
    expect(useTeamStore.getState().team).toBeNull()
    expect(goToConnect).toHaveBeenCalledOnce()
  })

  it('reacts to a missing league too', () => {
    useTeamStore.getState().setTeam(team)
    expect(isStaleTeamError({ detail: 'League not found: mn-abc', kind: 'league' })).toBe(true)
  })

  it('ignores other errors, including a missing partner team', () => {
    useTeamStore.getState().setTeam(team)
    const goToConnect = vi.fn()
    const handle = makeStaleTeamHandler(goToConnect)
    handle({ detail: 'Team not found: sl-9-3', kind: 'team' })
    handle({ detail: 'unknown player(s): x' })
    handle(new TypeError('Failed to fetch'))
    expect(useTeamStore.getState().team?.teamId).toBe('mn-abc-1')
    expect(goToConnect).not.toHaveBeenCalled()
  })
})
