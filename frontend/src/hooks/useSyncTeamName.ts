import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { getSavedTeamsOptions } from '@/api/@tanstack/react-query.gen'
import { useTeamStore } from '@/stores/team'

/** A team renamed on Sleeper/ESPN gets its new name on the next sync: when the saved list
 * changes, carry the server's names into the stored team (shown in the sidebar). Lives in the
 * layout, since the sidebar isn't mounted on phones until it's opened. */
export function useSyncTeamName() {
  const teamId = useTeamStore((s) => s.team?.teamId)
  const setTeam = useTeamStore((s) => s.setTeam)
  const saved = useQuery({ ...getSavedTeamsOptions(), enabled: teamId != null })
  const active = saved.data?.find((t) => t.team_id === teamId)
  useEffect(() => {
    const cur = useTeamStore.getState().team
    if (cur && active && cur.teamId === active.team_id && (active.team_name !== cur.teamName || active.league_name !== cur.leagueName))
      setTeam({ ...cur, teamName: active.team_name, leagueName: active.league_name })
  }, [active, setTeam])
}
