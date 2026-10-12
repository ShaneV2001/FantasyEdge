import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { Fragment, useMemo, useState } from 'react'

import type { RosterPlayer } from '@/api'
import { InjuryTag, PositionBadge, SignalBadge } from '@/components/player/badges'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fmtInt, fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'

type SortKey = 'default' | 'ppg' | 'proj_ros_points' | 'ros_value_par' | 'market_value' | 'bye_week'

function ProjectionBand({ p }: { p: RosterPlayer }) {
  const max = 40
  const lo = Math.min(p.p10 ?? p.ppg, max)
  const hi = Math.min(p.p90 ?? p.ppg, max)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-2">
          <span className="w-10 text-right font-mono tabular-nums">{fmtNum(p.ppg)}</span>
          <span className="relative hidden h-1.5 w-20 rounded-full bg-muted sm:block">
            <span
              className="absolute h-full rounded-full bg-primary/35"
              style={{ left: `${(lo / max) * 100}%`, width: `${Math.max(((hi - lo) / max) * 100, 2)}%` }}
            />
            <span
              className="absolute top-1/2 size-2 -translate-y-1/2 rounded-full bg-primary"
              style={{ left: `calc(${(Math.min(p.ppg, max) / max) * 100}% - 4px)` }}
            />
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent className="font-mono text-xs">
        <div>Projected {fmtNum(p.ppg)} ppg (10th–90th: {fmtNum(p.p10)}–{fmtNum(p.p90)})</div>
        <div>
          Last 3: {fmtNum(p.l3_ppg)} · Season: {fmtNum(p.season_ppg)} · Usage-implied: {fmtNum(p.usage_ppg)}
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

function Trend({ p }: { p: RosterPlayer }) {
  if (p.l3_ppg == null || p.season_ppg == null) return null
  const d = p.l3_ppg - p.season_ppg
  if (Math.abs(d) < 1.5) return null
  return d > 0 ? (
    <ArrowUp className="size-3 text-buy" aria-label="Trending up" />
  ) : (
    <ArrowDown className="size-3 text-sell" aria-label="Trending down" />
  )
}

export function RosterTable({ roster, week }: { roster: RosterPlayer[]; week: number }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'default', desc: true })
  const rows = useMemo(() => {
    if (sort.key === 'default') return roster
    const k = sort.key
    return [...roster].sort((a, b) => {
      const av = (a[k] as number | null | undefined) ?? -Infinity
      const bv = (b[k] as number | null | undefined) ?? -Infinity
      return sort.desc ? bv - av : av - bv
    })
  }, [roster, sort])

  const head = (key: SortKey, label: string, className?: string) => (
    <TableHead className={cn('text-right', className)}>
      <button
        type="button"
        className="inline-flex items-center gap-1 hover:text-foreground"
        onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))}
      >
        {label}
        {sort.key === key ? sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" /> : <ArrowUpDown className="size-3 opacity-40" />}
      </button>
    </TableHead>
  )

  const hasStarters = roster.some((r) => r.slot === 'starter')
  const firstBench = sort.key === 'default' ? rows.findIndex((p) => !p.optimal_starter) : -1
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-12">Pos</TableHead>
          <TableHead>Player</TableHead>
          {head('ppg', 'Proj ppg')}
          {head('proj_ros_points', 'ROS pts', 'hidden md:table-cell')}
          {head('ros_value_par', 'ROS value')}
          {head('market_value', 'Market', 'hidden lg:table-cell')}
          {head('bye_week', 'Bye', 'hidden sm:table-cell')}
          <TableHead className="text-right">Signal</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((p, i) => {
          const divider = i > 0 && i === firstBench
          const rankGap = p.market_rank != null && p.model_rank != null ? p.model_rank - p.market_rank : null
          const section =
            sort.key === 'default' && i === 0 && p.optimal_starter
              ? 'Best lineup'
              : divider
                ? `Bench${roster.some((r) => r.slot === 'ir') ? ' & IR' : ''}`
                : null
          return (
            <Fragment key={p.player_id}>
            {section && (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={8} className="pt-4 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                  {section}
                </TableCell>
              </TableRow>
            )}
            <TableRow>
              <TableCell>
                <PositionBadge position={p.position} />
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-1.5">
                  <span className={cn('font-medium', !p.optimal_starter && 'text-muted-foreground')}>{p.name}</span>
                  <Trend p={p} />
                  <InjuryTag status={p.injury_status} />
                  {p.slot === 'ir' && (
                    <span className="rounded bg-muted px-1 font-mono text-[10px] font-semibold text-muted-foreground" title="On your IR slot">
                      IR SLOT
                    </span>
                  )}
                  {hasStarters && p.slot === 'starter' && !p.optimal_starter && (
                    <span className="rounded bg-warn/15 px-1 text-[10px] font-semibold text-warn" title="You're starting him, but a bench player projects higher">
                      STARTING
                    </span>
                  )}
                  {hasStarters && p.slot === 'bench' && p.optimal_starter && (
                    <span className="rounded bg-buy/15 px-1 text-[10px] font-semibold text-buy" title="Benched, but projects as one of your best starters">
                      BENCHED
                    </span>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">
                  {p.nfl_team ?? 'FA'}
                  {p.availability_note && <> · {p.availability_note}</>}
                </div>
              </TableCell>
              <TableCell className="text-right">
                <div className="flex justify-end">
                  <ProjectionBand p={p} />
                </div>
              </TableCell>
              <TableCell className="hidden text-right font-mono tabular-nums md:table-cell">
                {fmtNum(p.proj_ros_points, 0)}
              </TableCell>
              <TableCell
                className={cn('text-right font-mono tabular-nums', p.ros_value_par < 0 && 'text-muted-foreground')}
              >
                {fmtNum(p.ros_value_par, 0)}
              </TableCell>
              <TableCell className="hidden text-right lg:table-cell">
                {p.market_value != null ? (
                  <Tooltip>
                    <TooltipTrigger className="font-mono tabular-nums">
                      {fmtInt(p.market_value)}
                      {rankGap != null && Math.abs(rankGap) >= 5 && (
                        <span className={cn('ml-1 text-[10px]', rankGap > 0 ? 'text-sell' : 'text-buy')}>
                          {rankGap > 0 ? '▲' : '▼'}
                        </span>
                      )}
                    </TooltipTrigger>
                    <TooltipContent>
                      Market rank {p.position}
                      {p.market_rank} · our rank {p.position}
                      {p.model_rank}
                      {rankGap != null && rankGap >= 5 && ' — market likes him more than we do'}
                      {rankGap != null && rankGap <= -5 && ' — market undervalues him'}
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="hidden text-right font-mono sm:table-cell">
                {p.bye_week == null ? (
                  '—'
                ) : p.bye_week < week ? (
                  <span className="text-muted-foreground line-through">{p.bye_week}</span>
                ) : (
                  <span className={cn(p.bye_week - week <= 2 && 'text-warn')}>{p.bye_week}</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                <SignalBadge signal={p.signal} reasons={p.signal_reasons} />
              </TableCell>
            </TableRow>
            </Fragment>
          )
        })}
      </TableBody>
    </Table>
  )
}
