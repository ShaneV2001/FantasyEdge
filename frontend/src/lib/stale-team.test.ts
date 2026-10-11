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
  it('goes to Connect, then forgets the saved team, once per burst of errors', async () => {
    useTeamStore.getState().setTeam(team)
    const order: string[] = []
    const goToConnect = vi.fn(async () => {
      order.push(useTeamStore.getState().team ? 'navigate (team still set)' : 'navigate (cleared)')
    })
    const handle = makeStaleTeamHandler(goToConnect)
    const gone = { detail: 'Team not found: mn-abc-1', kind: 'team' }
    await Promise.all([handle(gone), handle(gone)])
    expect(useTeamStore.getState().team).toBeNull()
    expect(goToConnect).toHaveBeenCalledOnce()
    expect(order).toEqual(['navigate (team still set)'])
  })

  it('reacts to a missing league too', () => {
    useTeamStore.getState().setTeam(team)
    expect(isStaleTeamError({ detail: 'League not found: mn-abc', kind: 'league' })).toBe(true)
  })

  it('ignores other errors, including a missing partner team', async () => {
    useTeamStore.getState().setTeam(team)
    const goToConnect = vi.fn()
    const handle = makeStaleTeamHandler(goToConnect)
    await handle({ detail: 'Team not found: sl-9-3', kind: 'team' })
    await handle({ detail: 'unknown player(s): x' })
    await handle(new TypeError('Failed to fetch'))
    expect(useTeamStore.getState().team?.teamId).toBe('mn-abc-1')
    expect(goToConnect).not.toHaveBeenCalled()
  })
})
