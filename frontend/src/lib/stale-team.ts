import { toast } from 'sonner'

import { useTeamStore } from '@/stores/team'

interface NotFoundBody {
  detail?: unknown
  kind?: unknown
}

/** True when an API error says the saved team (or its league) no longer exists. */
export function isStaleTeamError(err: unknown): boolean {
  const team = useTeamStore.getState().team
  if (!team || !err || typeof err !== 'object') return false
  const { kind, detail } = err as NotFoundBody
  if (typeof detail !== 'string') return false
  if (kind === 'team') return detail.includes(team.teamId)
  if (kind === 'league') return detail.includes(team.leagueId)
  return false
}

/**
 * Global query/mutation error hook: a saved team that the API no longer knows (e.g. after the
 * local database was reset) is forgotten and the user is sent back to Connect, instead of every
 * page showing a "not found" error.
 */
export function makeStaleTeamHandler(goToConnect: () => Promise<void> | void) {
  let handling = false
  return async (err: unknown) => {
    if (handling || !isStaleTeamError(err)) return
    handling = true // several queries for the same team fail at once; react to the first
    toast.info('Your saved team no longer exists', {
      id: 'stale-team',
      description: 'Connect your team again to continue.',
    })
    try {
      // Leave the team pages before forgetting the team: they read it while still mounted.
      await goToConnect()
      useTeamStore.getState().clear()
    } finally {
      handling = false
    }
  }
}
