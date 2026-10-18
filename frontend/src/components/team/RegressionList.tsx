import { Info } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { PlayerFlagsOut } from '@/api'
import { PositionBadge, SignalBadge } from '@/components/player/badges'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { fmtNum } from '@/lib/format'
import { NO_FILTERS, PAGE, type RegressionFilters, filterRegression, teamOptions } from '@/lib/regression'
import { cn } from '@/lib/utils'

const KIND_LABEL: Record<string, string> = {
  td_over_expected: 'TD over expected',
  efficiency: 'Efficiency',
  usage_mismatch: 'Usage vs production',
}

/** Backtest result shown wherever flags are: only the sell-high side has predicted anything. */
export function BuyLowNote() {
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <Info className="mt-0.5 size-3.5 shrink-0" />
      Sell-high flags have predicted declines in our backtest (2023–2025). Buy-low flags were a coin flip,
      so treat them as context, not a reason to trade.
    </p>
  )
}

function FlagRow({ r, showOwner }: { r: PlayerFlagsOut; showOwner: boolean }) {
  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <PositionBadge position={r.player.position} />
        <PlayerLink playerId={r.player.player_id} className="font-medium">
          {r.player.name}
        </PlayerLink>
        <span className="text-xs text-muted-foreground">{r.player.nfl_team}</span>
        {showOwner && <span className="text-xs text-muted-foreground">· {r.team_name ?? 'Free agent'}</span>}
        <span className="ml-auto flex items-center gap-2">
          {r.tdoe != null && (
            <span
              className={cn('font-mono text-xs', r.tdoe >= 2 ? 'text-sell' : r.tdoe <= -2 ? 'text-buy' : 'text-muted-foreground')}
              title="Actual TDs minus expected TDs"
            >
              TDOE {r.tdoe > 0 ? '+' : ''}
              {fmtNum(r.tdoe)}
            </span>
          )}
          <SignalBadge signal={r.signal} showHold />
        </span>
      </div>
      <ul className="flex flex-col gap-1 pl-1">
        {r.flags.map((f) => (
          <li key={`${f.kind}-${f.metric}`} className="flex gap-2 text-sm">
            <span
              className={cn(
                'mt-0.5 h-fit shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide uppercase',
                f.direction > 0 ? 'bg-buy/10 text-buy' : 'bg-sell/10 text-sell',
              )}
            >
              {KIND_LABEL[f.kind] ?? f.kind}
            </span>
            <span className="text-muted-foreground">{f.message}</span>
          </li>
        ))}
      </ul>
    </li>
  )
}

/** Your roster's flags, strongest first. */
export function RegressionList({ rows, showOwner = false }: { rows: PlayerFlagsOut[]; showOwner?: boolean }) {
  const flagged = filterRegression(rows, NO_FILTERS)
  if (flagged.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">No regression flags right now.</p>
  }
  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col divide-y">
        {flagged.map((r) => (
          <FlagRow key={r.player.player_id} r={r} showOwner={showOwner} />
        ))}
      </ul>
      <BuyLowNote />
    </div>
  )
}

/** The rest of the league: the 20 strongest flags first, filters, and "Show more". */
export function LeagueRegressionList({ rows }: { rows: PlayerFlagsOut[] }) {
  const [filters, setFilters] = useState<RegressionFilters>(NO_FILTERS)
  const [shown, setShown] = useState(PAGE)
  const set = (patch: Partial<RegressionFilters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setShown(PAGE)
  }
  const matches = useMemo(() => filterRegression(rows, filters), [rows, filters])
  const { teams, freeAgents } = useMemo(() => teamOptions(rows), [rows])
  const filtered = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS)

  return (
    <div className="flex flex-col gap-2">
      <div className="sticky top-12 z-[5] -mx-1 flex flex-wrap items-center gap-2 border-b bg-card px-1 py-2">
        <ToggleGroup
          type="single"
          variant="outline"
          value={filters.pos}
          onValueChange={(v) => v && set({ pos: v as RegressionFilters['pos'] })}
          aria-label="Position"
        >
          {(['ALL', 'QB', 'RB', 'WR', 'TE'] as const).map((p) => (
            <ToggleGroupItem key={p} value={p} className="px-2 text-xs">
              {p === 'ALL' ? 'All' : p}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <ToggleGroup
          type="single"
          variant="outline"
          value={filters.dir}
          onValueChange={(v) => v && set({ dir: v as RegressionFilters['dir'] })}
          aria-label="Direction"
        >
          <ToggleGroupItem value="all" className="px-2 text-xs">
            Both
          </ToggleGroupItem>
          <ToggleGroupItem value="sell" className="px-2 text-xs">
            Sell-high
          </ToggleGroupItem>
          <ToggleGroupItem value="buy" className="px-2 text-xs">
            Buy-low
          </ToggleGroupItem>
        </ToggleGroup>
        <Select value={filters.team} onValueChange={(v) => set({ team: v })}>
          <SelectTrigger aria-label="Team" className="h-8 w-40 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All teams</SelectItem>
            {freeAgents && <SelectItem value="fa">Free agents</SelectItem>}
            {teams.map((t) => (
              <SelectItem key={t.id} value={t.id}>
                {t.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="ml-auto text-xs text-muted-foreground">
          {Math.min(shown, matches.length)} of {matches.length}
        </span>
      </div>
      {filters.dir === 'buy' && <BuyLowNote />}
      {matches.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-6 text-center text-sm text-muted-foreground">
          No flagged players match these filters.
          {filtered && (
            <Button size="sm" variant="outline" onClick={() => set(NO_FILTERS)}>
              Clear filters
            </Button>
          )}
        </div>
      ) : (
        <ul className="flex flex-col divide-y">
          {matches.slice(0, shown).map((r) => (
            <FlagRow key={r.player.player_id} r={r} showOwner />
          ))}
        </ul>
      )}
      {shown < matches.length && (
        <Button variant="outline" size="sm" className="self-center" onClick={() => setShown((n) => n + PAGE)}>
          Show more ({Math.min(PAGE, matches.length - shown)})
        </Button>
      )}
      {filters.dir !== 'buy' && <BuyLowNote />}
    </div>
  )
}
