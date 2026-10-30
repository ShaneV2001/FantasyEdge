import { useQuery } from '@tanstack/react-query'
import { useSearch } from '@tanstack/react-router'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useState } from 'react'

import { getByesOptions, getPendingTradesOptions } from '@/api/@tanstack/react-query.gen'
import { ByeGridCard } from '@/components/byes/ByeGrid'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PositionBadge } from '@/components/player/badges'
import { PlayerLink } from '@/components/player/PlayerLink'
import { PendingTradesBanner } from '@/components/trade/PendingTrades'
import { RosterOutlook } from '@/components/trade/TradeOutlook'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

export function ByesPage() {
  const team = useTeamStore((s) => s.team)!
  const q = useQuery(getByesOptions({ path: { team_id: team.teamId } }))
  // only ESPN reports trades that were accepted but haven't gone through yet
  const pending = useQuery({ ...getPendingTradesOptions({ path: { team_id: team.teamId } }), enabled: team.platform === 'espn' })
  const search = useSearch({ strict: false }) as Record<string, unknown>
  const [view, setView] = useState<'now' | 'after'>(search.view === 'after' ? 'after' : 'now')
  const d = q.data
  const holeWeeks = d?.weeks.filter((w) => w.danger) ?? []
  const after = pending.data?.outlook
  const showAfter = view === 'after' && after != null

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Bye-week planner"
        description="Your best lineup for each remaining week. Amber: a backup fills in for a starter on bye or injured. Red: nobody on your roster can fill the slot."
      />
      {pending.data && after && (
        <PendingTradesBanner
          data={pending.data}
          action={
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              className="mt-1 self-start"
              value={view}
              onValueChange={(v) => v && setView(v as 'now' | 'after')}
              aria-label="Roster to plan for"
            >
              <ToggleGroupItem value="now" className="px-2 text-xs">
                Current roster
              </ToggleGroupItem>
              <ToggleGroupItem value="after" className="px-2 text-xs">
                After accepted trades
              </ToggleGroupItem>
            </ToggleGroup>
          }
        />
      )}
      {q.isPending && <ListSkeleton rows={4} height="h-16" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {d && showAfter && <RosterOutlook outlook={after.me} slots={after.slots} first={d.week} last={d.last_week} title="Your team" />}
      {d && !showAfter && (
        <>
          {holeWeeks.length > 0 ? (
            <Alert className="border-warn/40">
              <AlertTriangle className="text-warn" />
              <AlertTitle>
                {holeWeeks.length} week{holeWeeks.length > 1 ? 's' : ''} with lineup holes
              </AlertTitle>
              <AlertDescription>
                {holeWeeks.slice(0, 4).map((w) => (
                  <span key={w.week} className="block">
                    Week {w.week} ({w.weeks_away === 0 ? 'this week' : `in ${w.weeks_away} week${w.weeks_away > 1 ? 's' : ''}`}): no
                    good option at {w.danger_slots.join(', ')}
                    {w.starters_on_bye.length > 0 && ` (${w.starters_on_bye.join(', ')} on bye)`}, {fmtNum(w.points_lost ?? 0)} pts
                    lost
                  </span>
                ))}
              </AlertDescription>
            </Alert>
          ) : (
            <Alert className="border-buy/40">
              <CheckCircle2 className="text-buy" />
              <AlertTitle>No lineup holes</AlertTitle>
              <AlertDescription>Your roster covers every bye and injury through week {d.last_week}.</AlertDescription>
            </Alert>
          )}
          <ByeGridCard weeks={d.weeks} slots={d.slots} first={d.week} last={d.last_week} />
          <Card>
            <CardHeader>
              <CardTitle>Roster byes</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
                {d.players.map((p) => (
                  <li key={p.player.player_id} className="flex items-center gap-2 text-sm">
                    <PositionBadge position={p.player.position} />
                    <PlayerLink playerId={p.player.player_id} className={cn('flex-1 truncate', p.done && 'text-muted-foreground')}>
                      {p.player.name}
                    </PlayerLink>
                    <span className="font-mono text-xs text-muted-foreground">
                      {p.bye_week == null ? '—' : p.done ? `wk ${p.bye_week} ✓` : `wk ${p.bye_week}`}
                    </span>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
