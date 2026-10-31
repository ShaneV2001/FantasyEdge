import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'
import { useState } from 'react'

import type { RankingRow, RankingsOut } from '@/api'
import { getRankingsOptions } from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { InjuryTag, SignalBadge, StockBadge, seasonRankText } from '@/components/player/badges'
import { Matchups, OwnerLabel, injuryStatus } from '@/components/player/matchups'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { POSITIONS, fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

function RankingsTable({ rows, position, view }: { rows: RankingRow[]; position: string; view: 'ros' | 'week' }) {
  if (rows.length === 0) {
    return <p className="py-8 text-center text-sm text-muted-foreground">No {position}s play this week.</p>
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-10">#</TableHead>
          <TableHead>Player</TableHead>
          <TableHead className="hidden md:table-cell">{view === 'ros' ? 'Next matchups' : 'Matchup'}</TableHead>
          <TableHead className="text-right">{view === 'ros' ? 'ROS' : 'Proj'}<span className="hidden md:inline"> pts</span></TableHead>
          <TableHead className="text-right">
            <Tooltip>
              <TooltipTrigger className="underline decoration-dotted underline-offset-2">
                <span className="md:hidden">+/−</span>
                <span className="hidden md:inline">Schedule</span>
              </TooltipTrigger>
              <TooltipContent>Points the schedule adds (or costs) vs an average set of opponents</TooltipContent>
            </Tooltip>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.player_id} className={cn(r.mine && 'bg-primary/5')}>
            <TableCell className="font-mono text-muted-foreground">{r.rank}</TableCell>
            <TableCell>
              <div className="flex flex-col gap-0.5">
                <span className="flex items-center gap-2 font-medium">
                  <PlayerLink playerId={r.player_id}>{r.name}</PlayerLink>
                  <StockBadge t={r} />
                  <InjuryTag status={injuryStatus(r.availability_note)} />
                  <SignalBadge signal={r.signal} />
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  {r.nfl_team} · {fmtNum(r.ppg)} ppg
                  {r.season_ppg != null && (
                    <span title="Actual points per game this season, and his rank at the position by it">
                      · season {fmtNum(r.season_ppg)} ({seasonRankText(position, r)})
                    </span>
                  )}
                  <OwnerLabel owner={r.owner} mine={r.mine} />
                </span>
                <Matchups cells={r.cells} position={position} className="mt-1 md:hidden" />
              </div>
            </TableCell>
            <TableCell className="hidden md:table-cell">
              <Matchups cells={r.cells} position={position} />
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums">{fmtNum(r.points)}</TableCell>
            <TableCell
              className={cn(
                'text-right font-mono tabular-nums',
                r.schedule_delta > 0.05 ? 'text-buy' : r.schedule_delta < -0.05 ? 'text-sell' : 'text-muted-foreground',
              )}
            >
              {fmtSigned(r.schedule_delta)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export const TOP_CHOICES = [10, 15, 20, 30] as const

function Rankings({ data, top, onTop, loading }: { data: RankingsOut; top: number; onTop: (n: number) => void; loading: boolean }) {
  const [position, setPosition] = useState<string>('RB')
  const [view, setView] = useState<'ros' | 'week'>('ros')
  const [week, setWeek] = useState(String(data.week))
  const pos = data.positions[position]
  const rows = view === 'ros' ? pos?.ros ?? [] : pos?.weekly.find((w) => String(w.week) === week)?.rows ?? []

  return (
    <Card>
      <CardHeader className="gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs value={position} onValueChange={setPosition}>
            <TabsList>
              {POSITIONS.map((p) => (
                <TabsTrigger key={p} value={p}>
                  {p}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <div className="flex flex-wrap items-center gap-2">
            <ToggleGroup
              type="single"
              variant="outline"
              value={String(top)}
              onValueChange={(v) => v && onTop(Number(v))}
              aria-label="How many players to show"
            >
              {TOP_CHOICES.map((n) => (
                <ToggleGroupItem key={n} value={String(n)} className="px-2.5 font-mono" aria-label={`Top ${n}`}>
                  {n}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <ToggleGroup type="single" variant="outline" value={view} onValueChange={(v) => v && setView(v as 'ros' | 'week')}>
              <ToggleGroupItem value="ros">Rest of season</ToggleGroupItem>
              <ToggleGroupItem value="week">By week</ToggleGroupItem>
            </ToggleGroup>
            {view === 'week' && (
              <Select value={week} onValueChange={setWeek}>
                <SelectTrigger aria-label="Week" className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {data.weeks.map((w) => (
                    <SelectItem key={w} value={String(w)}>
                      Week {w}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
        </div>
        <div>
          <CardTitle>
            Top {data.top ?? top} {position} · {view === 'ros' ? `weeks ${data.week}–${data.last_week}` : `week ${week}`}
            {loading && <span className="ml-2 text-xs font-normal text-muted-foreground">loading top {top}…</span>}
          </CardTitle>
          <CardDescription>
            {view === 'ros'
              ? 'Projected points for the rest of the fantasy season, adjusted for every remaining opponent, byes and injuries.'
              : `Projected points for week ${week}, adjusted for the opponent.${week === String(data.week) ? ' Players whose game this week is already final are not listed.' : ''}`}
          </CardDescription>
        </div>
        {pos && pos.alpha === 0 && (
          <p className="flex items-start gap-2 rounded-md border border-dashed p-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" />
            Matchups haven't predicted {position} scoring in our backtests (2023–2025), so this ranking ignores the
            schedule. Matchup colors are shown for reference only.
          </p>
        )}
      </CardHeader>
      <CardContent>
        <RankingsTable rows={rows} position={position} view={view} />
      </CardContent>
    </Card>
  )
}

const TOP_KEY = 'fantasyedge:rankings-top'

function savedTop(): number {
  try {
    const n = Number(localStorage.getItem(TOP_KEY))
    return (TOP_CHOICES as readonly number[]).includes(n) ? n : 10
  } catch {
    return 10 // storage unavailable: default
  }
}

export function RankingsPage() {
  const team = useTeamStore((s) => s.team)!
  const [top, setTop] = useState(savedTop)
  const q = useQuery({
    ...getRankingsOptions({ path: { team_id: team.teamId }, query: { top } }),
    placeholderData: keepPreviousData,
  })
  const chooseTop = (n: number) => {
    setTop(n)
    try {
      localStorage.setItem(TOP_KEY, String(n))
    } catch {
      // not remembered this time; still works
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Rankings"
        description="The top players at each position (10, 15, 20 or 30) by schedule-adjusted projection, for each week and the rest of the season. Green opponents are soft matchups, red are tough. The badge is the player's buy/hold/sell verdict (our projection vs the market)."
      />
      {q.isPending && <ListSkeleton rows={6} height="h-12" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && <Rankings data={q.data} top={top} onTop={chooseTop} loading={q.isPlaceholderData} />}
    </div>
  )
}
