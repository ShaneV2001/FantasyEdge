import { ArrowDownLeft, ArrowUpRight } from 'lucide-react'

import type { TradeOut, TradeSideOut } from '@/api'
import { PlayerChip } from '@/components/player/badges'
import { Badge } from '@/components/ui/badge'
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
      </div>
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

export function TradeDetail({ trade }: { trade: TradeOut }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-2">
        <Side side={trade.me} title="You" />
        <Side side={trade.partner} title={trade.partner.team_name} />
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

export function TradeCard({ trade }: { trade: TradeOut }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <VerdictBadge verdict={trade.verdict} />
          {trade.headline}
          {(trade.tags ?? []).map((t) => (
            <Badge key={t} variant="outline" className="font-mono">
              {t}
            </Badge>
          ))}
        </CardTitle>
        <CardDescription>with {trade.partner.team_name}</CardDescription>
      </CardHeader>
      <CardContent>
        <TradeDetail trade={trade} />
      </CardContent>
    </Card>
  )
}
