import { AlertTriangle } from 'lucide-react'
import { useState } from 'react'

import type { ByeWeekOut, RosterOutlookOut, TradeOutlookOut } from '@/api'
import { affected, ByeGridCard } from '@/components/byes/ByeGrid'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'

type View = 'after' | 'before'

/** Everyone a week is missing from the full-strength lineup, and why ("Bijan Robinson (bye)"). */
export function missing(w: ByeWeekOut): string[] {
  return w.cells.filter((c) => c.replaces).map((c) => `${c.replaces} (${c.why})`)
}

/** The weeks that hurt most after the trade: biggest drop from full strength first. */
export function worstWeeks(after: ByeWeekOut[], n = 3): ByeWeekOut[] {
  return after
    .filter(affected)
    .sort((a, b) => (b.points_lost ?? 0) - (a.points_lost ?? 0) || a.week - b.week)
    .slice(0, n)
}

function when(w: ByeWeekOut) {
  return w.weeks_away === 0 ? 'this week' : `in ${w.weeks_away} week${w.weeks_away > 1 ? 's' : ''}`
}

function WorstWeeks({ outlook }: { outlook: RosterOutlookOut }) {
  const before = new Map(outlook.before.map((w) => [w.week, w]))
  const worst = worstWeeks(outlook.after)
  if (worst.length === 0) return <p className="text-sm text-muted-foreground">No bye or injury changes this lineup in any remaining week.</p>
  return (
    <ul className="flex flex-col gap-2" aria-label="Weakest weeks">
      {worst.map((w) => {
        const was = before.get(w.week)?.lineup_points
        const out = missing(w)
        const holes = w.cells.filter((c) => c.hole).map((c) => c.label)
        return (
          <li key={w.week} className={cn('rounded-md px-3 py-2 text-sm ring-1 ring-inset', w.danger ? 'bg-sell/10 ring-sell/30' : 'bg-warn/10 ring-warn/30')}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="flex items-center gap-1.5 font-medium">
                {w.danger && <AlertTriangle className="size-3.5 text-sell" />}
                Week {w.week} <span className="font-normal text-muted-foreground">({when(w)})</span>
              </span>
              <span className="font-mono text-xs tabular-nums">
                {fmtNum(w.lineup_points)} pts
                {was != null && Math.abs(w.lineup_points - was) >= 0.1 && (
                  <span className={w.lineup_points > was ? 'text-buy' : 'text-sell'}> ({fmtSigned(w.lineup_points - was)} vs now)</span>
                )}
                <span className="text-muted-foreground"> · −{fmtNum(w.points_lost ?? 0)} vs full strength</span>
              </span>
            </div>
            {out.length > 0 && <p className="text-muted-foreground">Out: {out.join(', ')}</p>}
            {holes.length > 0 && <p className="text-sell">Nobody to start at {holes.join(', ')}</p>}
          </li>
        )
      })}
    </ul>
  )
}

/** One team's lineups week by week after a trade (or before it), with the weakest weeks first. */
export function RosterOutlook({
  outlook,
  slots,
  first,
  last,
  title,
}: {
  outlook: RosterOutlookOut
  slots: string[]
  first: number
  last: number
  title: string
}) {
  const [view, setView] = useState<View>('after')
  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>{title}: weakest weeks after the trade</CardTitle>
          <CardDescription>
            Points are the projected best lineup, with players on bye or hurt sitting out.
            {(outlook.drops ?? []).length > 0 && ` Assumes you cut ${outlook.drops.map((d) => d.player.name).join(' and ')} to make room.`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <WorstWeeks outlook={outlook} />
        </CardContent>
      </Card>
      <ByeGridCard
        weeks={view === 'after' ? outlook.after : outlook.before}
        slots={slots}
        first={first}
        last={last}
        title={`${title}: lineup by week`}
        action={
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            value={view}
            onValueChange={(v) => v && setView(v as View)}
            aria-label={`${title}: roster to show`}
          >
            <ToggleGroupItem value="before" className="px-2 text-xs">
              Before
            </ToggleGroupItem>
            <ToggleGroupItem value="after" className="px-2 text-xs">
              After
            </ToggleGroupItem>
          </ToggleGroup>
        }
      />
    </div>
  )
}

/** Both teams' week-by-week lineups for a trade (the partner only when it's a real league team). */
export function TradeOutlook({ data, lastWeek }: { data: TradeOutlookOut; lastWeek?: number }) {
  const last = lastWeek ?? data.me.after.at(-1)?.week ?? data.week
  return (
    <div className="flex flex-col gap-4" data-testid="trade-outlook">
      <RosterOutlook outlook={data.me} slots={data.slots} first={data.week} last={last} title="You" />
      {data.partner && <RosterOutlook outlook={data.partner} slots={data.slots} first={data.week} last={last} title={data.partner.team_name} />}
    </div>
  )
}
