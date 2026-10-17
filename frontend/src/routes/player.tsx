import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { Area, Bar, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from 'recharts'

import type { PlayerDetailOut } from '@/api'
import { getPlayerOptions } from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton } from '@/components/common/states'
import { Analytics } from '@/components/player/analytics'
import { AvailabilityControl } from '@/components/player/AvailabilityControl'
import { InjuryTag, PositionBadge, SignalBadge } from '@/components/player/badges'
import { Matchups, injuryStatus } from '@/components/player/matchups'
import { PlayerTrades } from '@/components/player/PlayerTrades'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtInt, fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

const STAT_LABEL: Record<string, string> = {
  pass_cmp: 'Cmp',
  pass_att: 'Att',
  pass_yds: 'Pass yds',
  pass_td: 'Pass TD',
  interceptions: 'INT',
  carries: 'Car',
  rush_yds: 'Rush yds',
  rush_td: 'Rush TD',
  targets: 'Tgt',
  receptions: 'Rec',
  rec_yds: 'Rec yds',
  rec_td: 'Rec TD',
  snap_pct: 'Snap %',
  fgm: 'FG',
  fgm_50p: 'FG 50+',
  fgmiss: 'FG miss',
  xpm: 'XP',
  xpmiss: 'XP miss',
  def_sack: 'Sacks',
  def_int: 'INT',
  def_fum_rec: 'Fum rec',
  def_td: 'TD',
  pts_allow: 'Pts allowed',
  yds_allow: 'Yds allowed',
}

function fmtStat(key: string, v: number | null | undefined) {
  if (v == null) return '—'
  return key === 'snap_pct' ? `${Math.round(v * 100)}%` : fmtInt(v)
}

function initials(name: string) {
  return name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

/** Headshot, falling back to the team logo, then initials. */
export function PlayerImage({ d }: { d: Pick<PlayerDetailOut, 'name' | 'headshot_url' | 'team_logo_url'> }) {
  const sources = [d.headshot_url, d.team_logo_url].filter((s): s is string => !!s)
  const [i, setI] = useState(0)
  if (i >= sources.length) {
    return (
      <div className="grid size-24 shrink-0 place-items-center rounded-xl bg-muted font-semibold text-muted-foreground" aria-label={`${d.name} (no photo)`}>
        {initials(d.name)}
      </div>
    )
  }
  return (
    <img
      src={sources[i]}
      alt={d.name}
      onError={() => setI(i + 1)}
      className="size-24 shrink-0 rounded-xl bg-muted object-cover object-top"
    />
  )
}

const chartConfig = {
  actual: { label: 'Actual', color: 'var(--chart-1)' },
  projected: { label: 'Projected', color: 'var(--chart-2)' },
  band: { label: 'p10–p90', color: 'var(--chart-2)' },
} satisfies ChartConfig

function PointsChart({ d }: { d: PlayerDetailOut }) {
  const data = [
    ...d.weeks.map((w) => ({
      label: `W${w.week}`,
      opp: w.opponent,
      actual: w.played ? w.actual : null,
      projected: w.projected,
      band: w.p10 != null && w.p90 != null ? [w.p10, w.p90] : null,
    })),
    ...d.upcoming
      .filter((c) => !d.weeks.some((w) => w.week === c.week))
      .map((c) => ({ label: `W${c.week}`, opp: c.opponent ?? 'BYE', actual: null, projected: c.opponent ? c.points : null, band: null })),
  ]
  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-64 w-full">
      <ComposedChart data={data} margin={{ left: -16, right: 8, top: 8 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={8} fontSize={11} />
        <YAxis tickLine={false} axisLine={false} width={44} />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(label, payload) => {
                const opp = (payload?.[0]?.payload as { opp?: string } | undefined)?.opp
                return opp ? `${label} vs ${opp}` : label
              }}
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} />
        <Area dataKey="band" type="monotone" fill="var(--color-band)" fillOpacity={0.15} stroke="none" connectNulls isAnimationActive={false} />
        <Bar dataKey="actual" fill="var(--color-actual)" radius={4} maxBarSize={28} isAnimationActive={false} />
        <Line dataKey="projected" type="monotone" stroke="var(--color-projected)" strokeWidth={2} dot={{ r: 3 }} connectNulls isAnimationActive={false} />
      </ComposedChart>
    </ChartContainer>
  )
}

function Fact({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-sm tabular-nums">{value}</span>
    </div>
  )
}

export function PlayerView({ d, trades, availability }: { d: PlayerDetailOut; trades?: ReactNode; availability?: ReactNode }) {
  const played = d.weeks.filter((w) => w.played)
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardContent className="flex flex-col gap-4 pt-6 sm:flex-row sm:items-start">
          <PlayerImage d={d} />
          <div className="flex flex-1 flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">{d.name}</h1>
              <PositionBadge position={d.position} />
              <InjuryTag status={injuryStatus(d.availability_note)} returnWeek={d.return_week} />
              <SignalBadge signal={d.signal} reasons={d.signal_reasons} showHold />
            </div>
            <p className="text-sm text-muted-foreground">
              {[d.nfl_team, d.age != null && `${d.age} yrs`, d.years_exp != null && (d.years_exp === 0 ? 'rookie' : `${d.years_exp} yrs exp`), d.depth_chart_order && `depth #${d.depth_chart_order}`, d.bye_week && `bye W${d.bye_week}`]
                .filter(Boolean)
                .join(' · ')}
              {' · '}
              {d.mine ? 'Your team' : d.owner ?? 'Not rostered'}
            </p>
            <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
              <Fact label="Proj ppg" value={fmtNum(d.ppg)} />
              <Fact label="p10–p90" value={`${fmtNum(d.p10)}–${fmtNum(d.p90)}`} />
              <Fact label="ROS pts" value={fmtNum(d.model_ros_points, 0)} />
              <Fact label={`Our ${d.position} rank`} value={d.model_rank ?? '—'} />
              <Fact label="Market rank" value={d.market_rank ?? '—'} />
              <Fact
                label="Value gap"
                value={<span className={cn((d.value_gap ?? 0) > 0 ? 'text-buy' : (d.value_gap ?? 0) < 0 ? 'text-sell' : '')}>{fmtSigned(d.value_gap, 0)}</span>}
              />
            </div>
            {availability}
            {d.signal_reasons.length > 0 && (
              <ul className="list-disc pl-4 text-sm text-muted-foreground">
                {d.signal_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>

      {trades}

      <Card>
        <CardHeader>
          <CardTitle>Projected vs actual</CardTitle>
          <CardDescription>
            Bars: fantasy points scored (your league's scoring). Line: what we projected before each week, using only
            earlier games; the shaded band is our 10th–90th percentile range. Weeks ahead show the matchup-adjusted
            projection.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PointsChart d={d} />
        </CardContent>
      </Card>

      {d.analytics && (
        <Card>
          <CardHeader>
            <CardTitle>Analytics</CardTitle>
            <CardDescription>
              How he's being used and what he does with it. Rates are totals over the window, not averages of weekly
              rates; ▲/▼ marks a value at least 10% above or below his season.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Analytics a={d.analytics} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Upcoming matchups</CardTitle>
        </CardHeader>
        <CardContent>
          <Matchups cells={d.upcoming} position={d.position} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Game log</CardTitle>
        </CardHeader>
        <CardContent>
          {played.length === 0 ? (
            <p className="text-sm text-muted-foreground">No games this season yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Wk</TableHead>
                  <TableHead>Opp</TableHead>
                  {d.statline_keys.map((k) => (
                    <TableHead key={k} className="text-right">
                      {STAT_LABEL[k] ?? k}
                    </TableHead>
                  ))}
                  <TableHead className="text-right">Proj</TableHead>
                  <TableHead className="text-right">Pts</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {played.map((w) => (
                  <TableRow key={w.week}>
                    <TableCell className="font-mono">{w.week}</TableCell>
                    <TableCell className="font-mono text-xs">{w.opponent ?? '—'}</TableCell>
                    {d.statline_keys.map((k) => (
                      <TableCell key={k} className="text-right font-mono tabular-nums">
                        {fmtStat(k, w.statline?.[k])}
                      </TableCell>
                    ))}
                    <TableCell className="text-right font-mono tabular-nums text-muted-foreground">{fmtNum(w.projected)}</TableCell>
                    <TableCell
                      className={cn(
                        'text-right font-mono font-semibold tabular-nums',
                        w.projected != null && w.actual != null && (w.actual >= w.projected ? 'text-buy' : 'text-sell'),
                      )}
                    >
                      {fmtNum(w.actual)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function PlayerPage() {
  const { playerId } = useParams({ from: '/players/$playerId' })
  const team = useTeamStore((s) => s.team)!
  const q = useQuery(getPlayerOptions({ path: { team_id: team.teamId, player_id: playerId } }))
  return (
    <div className="flex flex-col gap-4">
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/rankings">
            <ArrowLeft /> Rankings
          </Link>
        </Button>
      </div>
      {q.isPending && <ListSkeleton rows={3} height="h-40" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && (
        <PlayerView
          d={q.data}
          availability={<AvailabilityControl key={`${q.data.player_id}-avail`} d={q.data} />}
          trades={<PlayerTrades key={q.data.player_id} d={q.data} teamId={team.teamId} manual={team.platform === 'manual'} />}
        />
      )}
    </div>
  )
}
