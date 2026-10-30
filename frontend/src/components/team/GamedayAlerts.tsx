import { useQuery } from '@tanstack/react-query'
import { Siren } from 'lucide-react'

import type { GamedayAlertOut, PivotOut } from '@/api'
import { getGamedayAlertsOptions } from '@/api/@tanstack/react-query.gen'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { apiDate, fmtNum, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ConnectedTeam } from '@/stores/team'

const SEVERITY: Record<GamedayAlertOut['severity'], string> = {
  out: 'border-sell/50 text-sell',
  high: 'border-sell/50 text-sell',
  medium: 'border-warn/50 text-warn',
  low: 'text-muted-foreground',
}

export function kickoffLabel(iso: string | null | undefined) {
  return iso
    ? apiDate(iso).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })
    : null
}

function PivotLine({ label, p }: { label: string; p: PivotOut }) {
  const k = kickoffLabel(p.kickoff)
  return (
    <span>
      {label}: <PlayerLink playerId={p.player.player_id}>{p.player.name}</PlayerLink> ({fmtNum(p.points)}{' '}
      projected{k ? `, ${k}` : ''})
    </span>
  )
}

/** "2 starters might not play": status, practice, kickoff and who to start instead. Refreshes
 * every 5 minutes (statuses change through Sunday morning); hidden when nothing is flagged. */
export function GamedayAlerts({ team }: { team: ConnectedTeam }) {
  const q = useQuery({
    ...getGamedayAlertsOptions({ path: { team_id: team.teamId } }),
    refetchInterval: 5 * 60_000,
    staleTime: 60_000,
  })
  const alerts = q.data?.alerts ?? []
  if (alerts.length === 0) return null
  const serious = alerts.filter((a) => a.severity !== 'low').length
  return (
    <Alert className="border-sell/40" data-testid="gameday-alerts">
      <Siren className="text-sell" />
      <AlertTitle>
        {serious
          ? `${serious} starter${serious > 1 ? 's' : ''} might not play in week ${q.data!.week}`
          : `Practice reports to watch in week ${q.data!.week}`}
      </AlertTitle>
      <AlertDescription>
        <ul className="flex flex-col gap-3">
          {alerts.map((a) => {
            const k = kickoffLabel(a.kickoff)
            return (
              <li key={a.player.player_id} className="flex flex-col gap-0.5">
                <span className="flex flex-wrap items-center gap-2 text-foreground">
                  <Badge variant="outline" className={cn('font-mono', SEVERITY[a.severity])}>
                    {a.status}
                  </Badge>
                  <span className="text-muted-foreground">{a.slot}</span>
                  <PlayerLink playerId={a.player.player_id} className="font-medium">
                    {a.player.name}
                  </PlayerLink>
                  {k && <span className="text-xs text-muted-foreground">kicks off {k}</span>}
                  {a.status_since && (
                    <span className="text-xs text-muted-foreground">· status changed {fmtRelative(a.status_since)}</span>
                  )}
                </span>
                {a.reasons.slice(1).map((r) => (
                  <span key={r}>{r}</span>
                ))}
                {a.pivot ? <PivotLine label="Start instead" p={a.pivot} /> : <span>No bench player can fill this slot.</span>}
                {a.late_pivot && <PivotLine label="Or wait for inactives with" p={a.late_pivot} />}
                {a.free_agent && <PivotLine label="Free agent" p={a.free_agent} />}
              </li>
            )
          })}
        </ul>
      </AlertDescription>
    </Alert>
  )
}
