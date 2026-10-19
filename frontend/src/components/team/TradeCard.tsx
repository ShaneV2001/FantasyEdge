import { AlertTriangle, ArrowDownLeft, ArrowUpRight, Scale, UserMinus } from 'lucide-react'
import type { ReactNode } from 'react'

import type { TradeOut, TradeSideOut } from '@/api'
import { PlayerChip } from '@/components/player/badges'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { fmtInt, fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'

const VERDICT: Record<TradeOut['verdict'], { label: string; cls: string }> = {
  accept: { label: 'Accept', cls: 'bg-buy/15 text-buy ring-buy/30' },
  lean_accept: { label: 'Lean accept', cls: 'bg-buy/10 text-buy/90 ring-buy/20' },
  neutral: { label: 'Neutral', cls: 'bg-muted text-muted-foreground ring-border' },
  decline: { label: 'Decline', cls: 'bg-sell/15 text-sell ring-sell/30' },
}

export function VerdictBadge({ verdict }: { verdict: TradeOut['verdict'] }) {
  const v = VERDICT[verdict]
  return (
    <span className={cn('inline-flex h-6 items-center rounded-md px-2 text-xs font-semibold ring-1 ring-inset', v.cls)}>
      {v.label}
    </span>
  )
}

function Side({ side, title }: { side: TradeSideOut; title: string }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-background/40 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-muted-foreground">{title}</span>
        <span
          className={cn(
            'font-mono text-sm font-semibold',
            side.lineup_delta > 0 ? 'text-buy' : side.lineup_delta < 0 ? 'text-sell' : 'text-muted-foreground',
          )}
          title="Change in projected rest-of-season starting-lineup points"
        >
          {fmtSigned(side.lineup_delta)} pts
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          <ArrowUpRight className="size-3" /> Gives
        </span>
        <div className="flex flex-wrap gap-1">
          {side.gives.map((p) => (
            <PlayerChip key={p.player_id} player={p} />
          ))}
        </div>
        <span className="mt-1 flex items-center gap-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          <ArrowDownLeft className="size-3" /> Gets
        </span>
        <div className="flex flex-wrap gap-1">
          {side.receives.map((p) => (
            <PlayerChip key={p.player_id} player={p} />
          ))}
        </div>
        {(side.drops ?? []).length > 0 && (
          <>
            <span
              className="mt-1 flex items-center gap-1 text-[11px] uppercase tracking-wide text-warn"
              title="Over the roster limit after the trade: this player's points are already taken out of the lineup change"
            >
              <UserMinus className="size-3" /> Must drop
            </span>
            <div className="flex flex-col gap-1">
              {side.drops!.map((p, i) => (
                <span key={p.player_id} className="flex flex-wrap items-center gap-x-2">
                  <PlayerChip player={p} className="opacity-80" />
                  {side.drop_reasons?.[i] && (
                    <span className="text-[11px] text-muted-foreground">{side.drop_reasons[i]}</span>
                  )}
                </span>
              ))}
            </div>
          </>
        )}
      </div>
      <WeekStrip side={side} />
      <dl className="mt-1 grid grid-cols-2 gap-x-3 text-xs">
        <dt className="text-muted-foreground">Lineup ROS</dt>
        <dd className="text-right font-mono">
          {fmtNum(side.lineup_before, 0)} → {fmtNum(side.lineup_after, 0)}
        </dd>
        <dt className="text-muted-foreground">Model value</dt>
        <dd className="text-right font-mono">
          {fmtNum(side.model_value_out, 0)} → {fmtNum(side.model_value_in, 0)}
        </dd>
        {side.market_value_out != null && (
          <>
            <dt className="text-muted-foreground">Market value</dt>
            <dd className="text-right font-mono">
              {fmtInt(side.market_value_out)} → {fmtInt(side.market_value_in)}
            </dd>
          </>
        )}
      </dl>
    </div>
  )
}

/** Weeks this trade changes the projected lineup by at least half a point, plus weeks it leaves short. */
function WeekStrip({ side }: { side: TradeSideOut }) {
  const short = new Set(side.new_short_weeks ?? [])
  const fixed = new Set(side.fixed_short_weeks ?? [])
  const weeks = (side.weekly ?? []).filter((w) => Math.abs(w.after - w.before) >= 0.5 || short.has(w.week) || fixed.has(w.week))
  if (weeks.length === 0) return null
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Week by week</span>
      <div className="flex flex-wrap gap-1" aria-label="Lineup change by week">
        {weeks.map((w) => {
          const d = w.after - w.before
          return (
            <span
              key={w.week}
              title={`Week ${w.week}: ${fmtNum(w.before)} → ${fmtNum(w.after)} projected${short.has(w.week) ? ' (a lineup slot goes unfilled)' : fixed.has(w.week) ? ' (fills a hole you had)' : ''}`}
              className={cn(
                'rounded px-1.5 py-0.5 font-mono text-[10px] tabular-nums ring-1 ring-inset',
                short.has(w.week)
                  ? 'bg-sell/15 text-sell ring-sell/40'
                  : d > 0
                    ? 'bg-buy/10 text-buy ring-buy/20'
                    : 'bg-sell/10 text-sell ring-sell/20',
              )}
            >
              W{w.week} {fmtSigned(d)}
              {short.has(w.week) && ' short'}
            </span>
          )
        })}
      </div>
    </div>
  )
}

export function TradeDetail({ trade }: { trade: TradeOut }) {
  const drops = (trade.me.drops ?? []).length + (trade.partner?.drops ?? []).length
  return (
    <div className="flex flex-col gap-3">
      {trade.market_values_missing && drops > 0 && (
        <Alert className="border-warn/40">
          <AlertTriangle className="text-warn" />
          <AlertDescription>Market values unavailable; drops based on projections only.</AlertDescription>
        </Alert>
      )}
      <div className={cn('grid gap-3', trade.partner && 'md:grid-cols-2')}>
        <Side side={trade.me} title="You" />
        {trade.partner && <Side side={trade.partner} title={trade.partner.team_name} />}
      </div>
      <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
        {trade.reasons.map((r) => (
          <li key={r} className="flex gap-2">
            <span className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground/60" />
            {r}
          </li>
        ))}
      </ul>
      {trade.danger_weeks_before != null && trade.danger_weeks_after != null && (
        <p className="text-xs text-muted-foreground">
          Bye/injury danger weeks: {trade.danger_weeks_before} → {trade.danger_weeks_after}
        </p>
      )}
    </div>
  )
}

export function TradeCard({
  trade,
  onOpenInAnalyzer,
  actions,
}: {
  trade: TradeOut
  /** Show an "Open in analyzer" button that hands this deal to the analyzer */
  onOpenInAnalyzer?: (trade: TradeOut) => void
  actions?: ReactNode
}) {
  return (
    <Card className={cn(trade.partner_accepts === false && 'border-dashed')}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <VerdictBadge verdict={trade.verdict} />
          {trade.headline}
          {(trade.tags ?? []).map((t) => (
            <Badge key={t} variant="outline" className="font-mono">
              {t}
            </Badge>
          ))}
          {trade.partner_accepts === false && (
            <Badge variant="outline" className="border-warn/40 text-warn" title="Their projected lineup doesn't improve">
              Unlikely to accept
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          {trade.partner ? `with ${trade.partner.team_name}` : 'Hypothetical trade — only your side is modelled'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <TradeDetail trade={trade} />
        {(onOpenInAnalyzer || actions) && (
          <div className="flex flex-wrap justify-end gap-2">
            {actions}
            {onOpenInAnalyzer && (
              <Button size="sm" variant="outline" onClick={() => onOpenInAnalyzer(trade)}>
                <Scale /> Open in analyzer
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
