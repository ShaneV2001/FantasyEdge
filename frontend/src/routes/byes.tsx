import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'

import type { ByeWeekOut, SlotCellOut } from '@/api'
import { getByesOptions } from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PositionBadge } from '@/components/player/badges'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

const CELL: Record<SlotCellOut['status'], string> = {
  ok: 'bg-muted/40',
  thin: 'bg-warn/15 text-warn ring-1 ring-inset ring-warn/30',
  empty: 'bg-sell/15 text-sell ring-1 ring-inset ring-sell/40',
}

function lastName(name?: string) {
  if (!name) return ''
  const parts = name.split(' ')
  return parts.length > 1 ? parts.slice(1).join(' ') : name
}

export function ByesPage() {
  const team = useTeamStore((s) => s.team)!
  const q = useQuery(getByesOptions({ path: { team_id: team.teamId } }))
  const d = q.data
  const upcomingDanger = d?.weeks.filter((w) => w.danger) ?? []

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Bye-week planner"
        description="Your best legal lineup for every remaining week, given byes and injuries. Amber = only a below-replacement option; red = nobody eligible."
      />
      {q.isPending && <ListSkeleton rows={4} height="h-16" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {d && (
        <>
          {upcomingDanger.length > 0 ? (
            <Alert className="border-warn/40">
              <AlertTriangle className="text-warn" />
              <AlertTitle>
                {upcomingDanger.length} danger week{upcomingDanger.length > 1 ? 's' : ''} ahead
              </AlertTitle>
              <AlertDescription>
                {upcomingDanger.slice(0, 4).map((w) => (
                  <span key={w.week} className="block">
                    Week {w.week} ({w.weeks_away === 0 ? 'this week' : `${w.weeks_away} week${w.weeks_away > 1 ? 's' : ''} away`}): no viable{' '}
                    {w.danger_slots.join(', ')}
                    {w.starters_on_bye.length > 0 && ` — ${w.starters_on_bye.join(', ')} on bye`} (
                    {fmtNum(w.full_strength_points - w.lineup_points)} pts below full strength)
                  </span>
                ))}
              </AlertDescription>
            </Alert>
          ) : (
            <Alert className="border-buy/40">
              <CheckCircle2 className="text-buy" />
              <AlertTitle>No danger weeks</AlertTitle>
              <AlertDescription>Every starting slot can be filled with a viable player through week {d.last_week}.</AlertDescription>
            </Alert>
          )}
          <Card>
            <CardHeader>
              <CardTitle>Week × slot grid</CardTitle>
              <CardDescription>Weeks {d.week}–{d.last_week}. Projected lineup points shown under each week.</CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="w-full">
                <ByeGrid weeks={d.weeks} slots={d.slots} />
                <ScrollBar orientation="horizontal" />
              </ScrollArea>
            </CardContent>
          </Card>
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

function ByeGrid({ weeks, slots }: { weeks: ByeWeekOut[]; slots: string[] }) {
  return (
    <table data-testid="bye-grid" className="w-full border-separate border-spacing-1 text-xs">
      <thead>
        <tr>
          <th className="w-14 text-left font-medium text-muted-foreground">Slot</th>
          {weeks.map((w) => (
            <th key={w.week} className="min-w-20 font-medium">
              <div className={cn('flex flex-col items-center gap-0.5 rounded-md py-1', w.danger && 'bg-sell/10 text-sell')}>
                <span className="flex items-center gap-1">
                  {w.danger && <AlertTriangle className="size-3" />}
                  Wk {w.week}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">{fmtNum(w.lineup_points)}</span>
              </div>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {slots.map((slot, i) => (
          <tr key={`${slot}-${i}`}>
            <td className="font-mono text-muted-foreground">{weeks[0]?.cells[i]?.label ?? slot}</td>
            {weeks.map((w) => {
              const c = w.cells[i]
              return (
                <td key={w.week}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div className={cn('truncate rounded-md px-1.5 py-1 text-center', CELL[c.status])}>
                        {c.player ? lastName(c.player.name) : 'EMPTY'}
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>
                      {c.player
                        ? `${c.player.name} (${c.player.position}, ${c.player.nfl_team}) — ${fmtNum(c.ppg)} ppg${c.status === 'thin' ? ', below replacement level' : ''}`
                        : `No eligible player available for ${c.label} in week ${w.week}`}
                    </TooltipContent>
                  </Tooltip>
                </td>
              )
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
