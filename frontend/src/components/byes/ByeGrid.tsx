import { AlertTriangle } from 'lucide-react'
import { type ReactNode, useState } from 'react'

import type { ByeWeekOut, SlotCellOut } from '@/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'

/** A slot only gets a color when a bye or injury changes it: a backup fills in, or nobody can. */
function cellKind(c: SlotCellOut): 'hole' | 'fill' | 'none' | 'normal' {
  if (c.hole) return 'hole'
  if (c.replaces) return 'fill'
  if (!c.player) return 'none' // empty every week: a roster gap, not a bye problem
  return 'normal'
}

const CELL = {
  hole: 'bg-sell/15 text-sell ring-1 ring-inset ring-sell/40',
  fill: 'bg-warn/15 text-warn ring-1 ring-inset ring-warn/30',
  none: 'text-muted-foreground',
  normal: 'bg-muted/40',
} as const

/** A week a bye or injury changes: a backup starts, a slot goes empty, or points are lost. */
export function affected(w: ByeWeekOut) {
  return w.danger || (w.points_lost ?? 0) >= 0.1 || w.cells.some((c) => c.hole || c.replaces)
}

function lastName(name?: string) {
  if (!name) return ''
  const parts = name.split(' ')
  return parts.length > 1 ? parts.slice(1).join(' ') : name
}

/** Short names for the grid: last names, with a first initial when two players share one. */
export function shortNames(weeks: ByeWeekOut[]) {
  const full = new Set(weeks.flatMap((w) => w.cells.flatMap((c) => [c.player?.name, c.replaces ?? undefined])).filter(Boolean) as string[])
  const count = new Map<string, number>()
  for (const n of full) count.set(lastName(n), (count.get(lastName(n)) ?? 0) + 1)
  return (name?: string | null) => {
    if (!name) return ''
    const last = lastName(name)
    return (count.get(last) ?? 0) > 1 ? `${name[0]}. ${last}` : last
  }
}

/** The week × slot grid in a card, opening on the weeks a bye or injury changes. */
export function ByeGridCard({
  weeks,
  slots,
  first,
  last,
  title = 'Lineup by week',
  action,
}: {
  weeks: ByeWeekOut[]
  slots: string[]
  first: number
  last: number
  title?: string
  /** Shown in the card header, right of the title (e.g. a before/after toggle) */
  action?: ReactNode
}) {
  const [showAll, setShowAll] = useState(false)
  const hit = weeks.filter(affected)
  const shown = showAll || hit.length === 0 ? weeks : hit
  const hidden = weeks.length - hit.length
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-1.5">
          <CardTitle>{title}</CardTitle>
          <CardDescription>
            {hit.length === 0
              ? `Weeks ${first}–${last}: no bye or injury changes your lineup.`
              : showAll
                ? `Weeks ${first}–${last}. Points lost compared with your full-strength lineup.`
                : `The ${hit.length} week${hit.length > 1 ? 's' : ''} a bye or injury changes your lineup, with the points lost.`}
          </CardDescription>
        </div>
        {action}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ScrollArea className="w-full">
          <ByeGrid weeks={shown} slots={slots} />
          <ScrollBar orientation="horizontal" />
        </ScrollArea>
        {hit.length > 0 && hidden > 0 && (
          <Button variant="ghost" size="sm" className="self-start" onClick={() => setShowAll((v) => !v)}>
            {showAll ? 'Only weeks with changes' : `Show all ${weeks.length} weeks (${hidden} unchanged)`}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

export function ByeGrid({ weeks, slots }: { weeks: ByeWeekOut[]; slots: string[] }) {
  const short = shortNames(weeks)
  return (
    <table data-testid="bye-grid" className="w-full border-separate border-spacing-1 text-xs">
      <thead>
        <tr>
          <th className="w-14 text-left font-medium text-muted-foreground">Slot</th>
          {weeks.map((w) => {
            const lost = w.points_lost ?? 0
            return (
              <th key={w.week} className="min-w-24 font-medium">
                <div className={cn('flex flex-col items-center gap-0.5 rounded-md py-1', w.danger && 'bg-sell/10 text-sell')}>
                  <span className="flex items-center gap-1">
                    {w.danger && <AlertTriangle className="size-3" />}
                    Wk {w.week}
                  </span>
                  <span
                    className={cn('font-mono text-[10px]', lost >= 0.1 ? (w.danger ? 'text-sell' : 'text-warn') : 'text-muted-foreground')}
                  >
                    {lost >= 0.1 ? `−${fmtNum(lost)}` : affected(w) ? 'no loss' : 'full'}
                  </span>
                </div>
              </th>
            )
          })}
        </tr>
      </thead>
      <tbody>
        {slots.map((slot, i) => (
          <tr key={`${slot}-${i}`}>
            <td className="font-mono text-muted-foreground">{weeks[0]?.cells[i]?.label ?? slot}</td>
            {weeks.map((w) => {
              const c = w.cells[i]
              const kind = cellKind(c)
              return (
                <td key={w.week}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <div data-kind={kind} className={cn('truncate rounded-md px-1.5 py-1 text-center', CELL[kind])}>
                        {kind === 'hole' ? 'EMPTY' : kind === 'none' ? '—' : short(c.player?.name)}
                        {(kind === 'fill' || (kind === 'hole' && c.replaces)) && (
                          <span className="block truncate text-[10px] opacity-80">
                            for {short(c.replaces)} · {c.why}
                          </span>
                        )}
                      </div>
                    </TooltipTrigger>
                    <TooltipContent>{cellTip(c, w.week)}</TooltipContent>
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

function cellTip(c: SlotCellOut, week: number) {
  if (c.hole) return `Nobody on your roster can play ${c.label} in week ${week}${c.replaces ? ` (${c.replaces}: ${c.why})` : ''}`
  if (!c.player) return `No ${c.label} on your roster`
  const who = `${c.player.name} (${c.player.position}, ${c.player.nfl_team}): ${fmtNum(c.ppg)} ppg`
  return c.replaces ? `${who}, filling in for ${c.replaces} (${c.why})` : who
}
