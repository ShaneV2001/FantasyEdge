import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { History, Info } from 'lucide-react'
import { useState } from 'react'

import type { RecapOut, RecapPlayerOut, RecapWeekOut } from '@/api'
import { getRecapOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton } from '@/components/common/states'
import { PositionBadge } from '@/components/player/badges'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ConnectedTeam } from '@/stores/team'

const BAND: Record<NonNullable<RecapPlayerOut['band']>, { label: string; cls: string }> = {
  above: { label: 'Beat p90', cls: 'border-buy/40 text-buy' },
  in_range: { label: 'In range', cls: 'text-muted-foreground' },
  below: { label: 'Below p10', cls: 'border-sell/40 text-sell' },
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-xl font-semibold tabular-nums">{value}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  )
}

function names(ps: RecapPlayerOut[]) {
  return ps.map((p) => `${p.player.name} (${fmtNum(p.actual)})`).join(', ')
}

function WeekCard({ w }: { w: RecapWeekOut }) {
  const fe = w.fe_points - w.lineup_points
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Week {w.week}
          {w.result && (
            <Badge variant="outline" className={cn('ml-2', w.result === 'W' ? 'border-buy/40 text-buy' : w.result === 'L' && 'border-sell/40 text-sell')}>
              {w.result} {fmtNum(w.points)}–{fmtNum(w.opponent_points)}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>{w.opponent_name ? `vs ${w.opponent_name}` : null}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Stat label="Your lineup" value={fmtNum(w.lineup_points)} />
          <Stat label="Best possible" value={fmtNum(w.best_points)} hint={`${fmtNum(w.left_on_bench)} left on the bench`} />
          <Stat label="FantasyEdge's lineup" value={fmtNum(w.fe_points)} hint={`${fmtSigned(fe)} vs yours`} />
          <Stat
            label="Starters in range"
            value={`${w.starters.filter((s) => s.band === 'in_range').length}/${w.starters.filter((s) => s.band).length}`}
            hint="actual inside p10–p90"
          />
        </div>
        {w.should_have_started.length > 0 && (
          <p className="text-sm">
            <span className="font-medium">Should have started:</span> {names(w.should_have_started)}
            {w.instead_of.length > 0 && (
              <>
                {' '}
                <span className="text-muted-foreground">instead of {names(w.instead_of)}</span>
              </>
            )}
          </p>
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Starter</TableHead>
              <TableHead className="text-right">Projected</TableHead>
              <TableHead className="hidden text-right sm:table-cell">Range</TableHead>
              <TableHead className="text-right">Actual</TableHead>
              <TableHead className="hidden text-right md:table-cell" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {w.starters.map((s) => (
              <TableRow key={s.player.player_id}>
                <TableCell className="max-w-0">
                  <span className="flex items-center gap-2">
                    <PositionBadge position={s.player.position} className="shrink-0" />
                    <PlayerLink playerId={s.player.player_id} className="truncate">
                      {s.player.name}
                    </PlayerLink>
                  </span>
                </TableCell>
                <TableCell className="text-right font-mono">{fmtNum(s.projected)}</TableCell>
                <TableCell className="hidden text-right font-mono text-xs text-muted-foreground sm:table-cell">
                  {s.p10 != null ? `${fmtNum(s.p10)}–${fmtNum(s.p90)}` : '—'}
                </TableCell>
                <TableCell className="text-right font-mono font-medium">{fmtNum(s.actual)}</TableCell>
                <TableCell className="hidden text-right md:table-cell">
                  {s.band && (
                    <Badge variant="outline" className={BAND[s.band].cls}>
                      {BAND[s.band].label}
                    </Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

export function RecapView({ data, onWeek }: { data: RecapOut; onWeek: (w: number) => void }) {
  const s = data.season
  return (
    <div className="flex flex-col gap-6">
      {s && (
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-4">
            <div className="flex flex-col gap-1.5">
              <CardTitle>Season so far</CardTitle>
              <CardDescription>
                {s.weeks} week{s.weeks === 1 ? '' : 's'} of lineups, scored with your league's points.
              </CardDescription>
            </div>
            <Select value={String(data.week)} onValueChange={(v) => onWeek(Number(v))}>
              <SelectTrigger aria-label="Week to recap" className="w-28">
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
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-2 md:grid-cols-4">
            <Stat label="Points left on the bench" value={fmtNum(s.left_on_bench)} hint={`of ${fmtNum(s.best_points)} possible`} />
            <Stat
              label="FantasyEdge's lineups"
              value={fmtSigned(s.fe_points - s.lineup_points)}
              hint={`${fmtNum(s.fe_points)} vs your ${fmtNum(s.lineup_points)}`}
            />
            <Stat label="Projection error" value={s.mae != null ? fmtNum(s.mae) : '—'} hint="avg points off per starter" />
            <Stat
              label="Inside p10–p90"
              value={s.in_band != null ? `${Math.round(s.in_band * 100)}%` : '—'}
              hint={`${s.starters_rated} starter-weeks`}
            />
          </CardContent>
        </Card>
      )}
      {data.detail && <WeekCard w={data.detail} />}
      {(data.notes ?? []).map((n) => (
        <Alert key={n}>
          <Info />
          <AlertDescription>{n}</AlertDescription>
        </Alert>
      ))}
    </div>
  )
}

export function Recap({ team }: { team: ConnectedTeam }) {
  const [week, setWeek] = useState<number | undefined>(undefined)
  const q = useQuery({
    ...getRecapOptions({ path: { team_id: team.teamId }, query: week ? { week } : undefined }),
    placeholderData: keepPreviousData,
  })
  if (q.isPending) return <ListSkeleton rows={3} height="h-40" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (!q.data.detail) {
    return (
      <EmptyState title="Nothing to look back on yet" icon={<History className="size-6" />}>
        {q.data.notes?.[0]}
      </EmptyState>
    )
  }
  return <RecapView data={q.data} onWeek={setWeek} />
}
