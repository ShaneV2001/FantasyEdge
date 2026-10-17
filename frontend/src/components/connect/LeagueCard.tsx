import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Check, Loader2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import type { LeagueChoiceOut } from '@/api'
import { selectTeamMutation } from '@/api/@tanstack/react-query.gen'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { describeError } from '@/lib/errors'
import { slotLabel } from '@/lib/format'
import { type ConnectedTeam, useTeamStore } from '@/stores/team'

/** One league from Sleeper or ESPN: pick your team and start using it. */
export function LeagueCard({
  league,
  platform,
  username,
}: {
  league: LeagueChoiceOut
  platform: ConnectedTeam['platform']
  username?: string
}) {
  const mine = league.teams.find((t) => t.is_user)
  const [rosterId, setRosterId] = useState(mine?.external_roster_id ?? league.teams[0]?.external_roster_id ?? '')
  const setTeam = useTeamStore((s) => s.setTeam)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const select = useMutation({
    ...selectTeamMutation(),
    onSuccess: (ref) => {
      const t = league.teams.find((x) => x.external_roster_id === rosterId)
      setTeam({
        teamId: ref.team_id,
        leagueId: ref.league_id,
        teamName: t?.team_name ?? 'My team',
        leagueName: league.name,
        platform,
        username,
      })
      void qc.invalidateQueries()
      toast.success(`Connected ${t?.team_name ?? 'team'}`)
      void navigate({ to: '/advisor' })
    },
    onError: (e) => toast.error(describeError(e).message),
  })
  const starters = league.roster_positions.filter((p) => !['BN', 'IR', 'TAXI'].includes(p))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {league.name}
          <Badge variant="outline" className="font-mono">
            {league.season}
          </Badge>
          <Badge variant="secondary">{platform === 'espn' ? 'ESPN' : 'Sleeper'}</Badge>
        </CardTitle>
        <CardDescription>
          {league.num_teams} teams · {league.scoring} · {starters.map(slotLabel).join(' ')}
        </CardDescription>
      </CardHeader>
      <CardFooter className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Select value={rosterId} onValueChange={setRosterId}>
          <SelectTrigger className="w-full sm:w-72" aria-label="Your team">
            <SelectValue placeholder="Pick your team" />
          </SelectTrigger>
          <SelectContent>
            {league.teams.map((t) => (
              <SelectItem key={t.external_roster_id} value={t.external_roster_id}>
                {t.team_name} {t.is_user ? '(you)' : `· ${t.owner_name}`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          disabled={!rosterId || select.isPending}
          onClick={() => select.mutate({ path: { league_id: league.league_id }, body: { external_roster_id: rosterId } })}
        >
          {select.isPending ? <Loader2 className="animate-spin" /> : <Check />}
          Use this team
        </Button>
      </CardFooter>
    </Card>
  )
}
