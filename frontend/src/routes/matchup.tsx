import { useQuery } from '@tanstack/react-query'
import { Info, Swords } from 'lucide-react'

import type { MatchupOut, MatchupPlayerOut, MatchupSideOut, ScheduleWeekOut, StandingOut } from '@/api'
import { getMatchupOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PositionBadge } from '@/components/player/badges'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

export const pct = (p: number) => `${Math.round(p * 100)}%`

const STATE_LABEL: Record<MatchupPlayerOut['state'], string> = {
  final: 'Final',
  live: 'Live',
  upcoming: '',
  bye: 'Bye',
  empty: '',
}

/** Your chance this week as a split bar: you on the left, them on the right. */
function WinBar({ p, me, them }: { p: number; me: string; them: string }) {
  return (
    <div className="flex flex-col gap-1.5" role="img" aria-label={`${pct(p)} chance to win`}>
      <div className="flex justify-between text-sm font-medium">
        <span>
          {me} <span className="font-mono">{pct(p)}</span>
        </span>
        <span>
          <span className="font-mono">{pct(1 - p)}</span> {them}
        </span>
      </div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
        <div className="bg-primary" style={{ width: pct(p) }} />
        <div className="bg-sell/60" style={{ width: pct(1 - p) }} />
      </div>
    </div>
  )
}

function Score({ side, align }: { side: MatchupSideOut; align: 'left' | 'right' }) {
  return (
    <div className={cn('flex flex-col', align === 'right' && 'items-end text-right')}>
      <span className="truncate text-sm text-muted-foreground">{side.team_name}</span>
      <span className="font-mono text-3xl font-semibold tabular-nums">{fmtNum(side.projected)}</span>
      <span className="text-xs text-muted-foreground">
        ±{fmtNum(side.sd, 0)} · {fmtNum(side.actual)} scored so far
      </span>
    </div>
  )
}

function PlayerCell({ p, align }: { p: MatchupPlayerOut | undefined; align: 'left' | 'right' }) {
  if (!p || !p.player) return <span className="text-muted-foreground">Empty</span>
  const label = STATE_LABEL[p.state]
  return (
    <div className={cn('flex min-w-0 items-center gap-2', align === 'right' && 'flex-row-reverse text-right')}>
      <PositionBadge position={p.player.position} className="shrink-0" />
      <div className="flex min-w-0 flex-col">
        <PlayerLink playerId={p.player.player_id} className="truncate font-medium">
          {p.player.name}
        </PlayerLink>
        <span className="font-mono text-xs text-muted-foreground">
          {p.state === 'final' ? fmtNum(p.actual ?? 0) : p.state === 'live' ? `${fmtNum(p.actual ?? 0)} · ${fmtNum(p.projected)} proj` : fmtNum(p.projected)}
          {label && <span className={cn('ml-1.5', p.state === 'live' && 'text-buy')}>{label}</span>}
        </span>
      </div>
    </div>
  )
}

function Lineups({ me, them }: { me: MatchupSideOut; them: MatchupSideOut }) {
  const rows = Math.max(me.lineup.length, them.lineup.length)
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{me.team_name}</TableHead>
          <TableHead className="w-14 text-center">Slot</TableHead>
          <TableHead className="text-right">{them.team_name}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {Array.from({ length: rows }, (_, i) => (
          <TableRow key={i}>
            <TableCell className="max-w-0 w-1/2">
              <PlayerCell p={me.lineup[i]} align="left" />
            </TableCell>
            <TableCell className="text-center font-mono text-xs text-muted-foreground">
              {me.lineup[i]?.slot ?? them.lineup[i]?.slot}
            </TableCell>
            <TableCell className="max-w-0 w-1/2">
              <PlayerCell p={them.lineup[i]} align="right" />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function Standings({ rows, playoffTeams }: { rows: StandingOut[]; playoffTeams: number }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8">#</TableHead>
          <TableHead>Team</TableHead>
          <TableHead className="text-right">Record</TableHead>
          <TableHead className="hidden text-right sm:table-cell">PF</TableHead>
          <TableHead className="hidden text-right md:table-cell">Proj. record</TableHead>
          <TableHead className="w-36 text-right">Playoffs</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((s, i) => (
          <TableRow key={s.team_id} className={cn(s.is_mine && 'bg-primary/5', i === playoffTeams - 1 && 'border-b-2')}>
            <TableCell className="font-mono text-muted-foreground">{i + 1}</TableCell>
            <TableCell className={cn('max-w-0 truncate', s.is_mine && 'font-semibold')}>{s.team_name}</TableCell>
            <TableCell className="text-right font-mono">
              {s.wins}-{s.losses}
            </TableCell>
            <TableCell className="hidden text-right font-mono sm:table-cell">{fmtNum(s.points_for, 0)}</TableCell>
            <TableCell className="hidden text-right font-mono md:table-cell">
              {fmtNum(s.proj_wins)}-{fmtNum(s.proj_losses)}
            </TableCell>
            <TableCell>
              <div className="flex items-center justify-end gap-2">
                <div className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-muted sm:block">
                  <div className="h-full bg-primary" style={{ width: pct(s.playoff_pct) }} />
                </div>
                <span className="w-10 text-right font-mono text-sm">{pct(s.playoff_pct)}</span>
              </div>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function ScheduleStrip({ weeks, current }: { weeks: ScheduleWeekOut[]; current: number }) {
  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {weeks.map((w) => {
        const tone = w.result
          ? w.result === 'W'
            ? 'border-buy/40 bg-buy/5'
            : w.result === 'L'
              ? 'border-sell/40 bg-sell/5'
              : ''
          : w.win_prob != null && w.win_prob < 0.4
            ? 'border-warn/40'
            : ''
        return (
          <li
            key={w.week}
            className={cn('flex flex-col gap-0.5 rounded-lg border p-2 text-xs', tone, w.week === current && 'ring-2 ring-primary/40')}
          >
            <span className="text-muted-foreground">Week {w.week}</span>
            <span className="truncate font-medium">{w.opponent_name ?? 'No game'}</span>
            {w.result ? (
              <span className="font-mono">
                {w.result} {fmtNum(w.points)}–{fmtNum(w.opponent_points)}
              </span>
            ) : (
              <span className="font-mono">{w.win_prob != null ? `${pct(w.win_prob)} to win` : '—'}</span>
            )}
          </li>
        )
      })}
    </ol>
  )
}

export function MatchupView({ data }: { data: MatchupOut }) {
  const standings = data.standings ?? []
  const schedule = data.schedule ?? []
  const mine = standings.find((s) => s.is_mine)
  return (
    <div className="flex flex-col gap-6">
      {data.me && data.opponent && data.win_prob != null && (
        <Card>
          <CardHeader>
            <CardTitle>Week {data.week}</CardTitle>
            <CardDescription>Expected final scores: points already scored plus each starter's projection.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div className="flex items-end justify-between gap-4">
              <Score side={data.me} align="left" />
              <Swords className="mb-3 size-5 shrink-0 text-muted-foreground" />
              <Score side={data.opponent} align="right" />
            </div>
            <WinBar p={data.win_prob} me="You" them="Them" />
            <Lineups me={data.me} them={data.opponent} />
          </CardContent>
        </Card>
      )}
      {standings.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Standings and playoff odds</CardTitle>
            <CardDescription>
              Top {data.playoff_teams} make the playoffs
              {mine ? `. You: ${pct(mine.playoff_pct)} to make it, ${pct(mine.top_seed_pct)} for the 1 seed.` : '.'}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Standings rows={standings} playoffTeams={data.playoff_teams ?? 0} />
          </CardContent>
        </Card>
      )}
      {schedule.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Your schedule</CardTitle>
            <CardDescription>Results so far, then your chance in each remaining regular-season week.</CardDescription>
          </CardHeader>
          <CardContent>
            <ScheduleStrip weeks={schedule} current={data.week} />
          </CardContent>
        </Card>
      )}
      {(data.notes ?? []).map((n) => (
        <Alert key={n}>
          <Info />
          <AlertDescription>{n}</AlertDescription>
        </Alert>
      ))}
    </div>
  )
}

export function MatchupPage() {
  const team = useTeamStore((s) => s.team)!
  const q = useQuery({ ...getMatchupOptions({ path: { team_id: team.teamId } }), refetchInterval: 5 * 60_000 })
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Matchup"
        description="Who you play, your chance to win, and your playoff odds."
        actions={q.data?.win_prob != null && <Badge variant="outline">{pct(q.data.win_prob)} to win this week</Badge>}
      />
      {q.isPending && <ListSkeleton rows={4} height="h-40" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && !q.data.has_schedule && (
        <EmptyState title="No head-to-head schedule">{q.data.notes?.[0]}</EmptyState>
      )}
      {q.data?.has_schedule && <MatchupView data={q.data} />}
    </div>
  )
}
