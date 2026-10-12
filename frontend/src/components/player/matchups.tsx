import type { MatchupCell } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'

const EASY = 1.1
const HARD = 0.9

/** Easy / neutral / hard styling for an opponent's points-allowed index. */
export function matchupTone(index: number | null | undefined): 'easy' | 'hard' | 'neutral' {
  if (index == null) return 'neutral'
  if (index >= EASY) return 'easy'
  if (index <= HARD) return 'hard'
  return 'neutral'
}

/** 'Questionable this week (85%…)' → 'Questionable'; 'On IR: assumed out…' → 'IR'. */
export function injuryStatus(note: string | null | undefined): string | null {
  if (!note) return null
  const m = /^On ([^:]+):/.exec(note) ?? /^(\w+) this week/.exec(note)
  return m ? m[1] : null
}

const TONE_CLASS = {
  easy: 'bg-buy/15 text-buy ring-1 ring-inset ring-buy/30',
  hard: 'bg-sell/15 text-sell ring-1 ring-inset ring-sell/30',
  neutral: 'bg-muted/50 text-muted-foreground',
} as const

export function MatchupChip({ cell, position }: { cell: MatchupCell; position: string }) {
  const tone = matchupTone(cell.index)
  const what = position === 'DEF' ? 'DEF points scored against this offense' : `points allowed to ${position}s`
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn('inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px]', TONE_CLASS[tone])}>
          <span className="opacity-70">W{cell.week}</span>
          {cell.opponent ?? 'BYE'}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {cell.opponent
          ? `Week ${cell.week} vs ${cell.opponent}: ${fmtNum(cell.index, 2)}× the average ${what} · ${fmtNum(cell.points)} projected`
          : `Week ${cell.week}: bye`}
      </TooltipContent>
    </Tooltip>
  )
}

export function Matchups({ cells, position, className }: { cells: MatchupCell[]; position: string; className?: string }) {
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {cells.map((c) => (
        <MatchupChip key={c.week} cell={c} position={position} />
      ))}
    </div>
  )
}

export function OwnerLabel({ owner, mine }: { owner?: string | null; mine: boolean }) {
  if (mine) return <Badge className="bg-primary/15 text-primary hover:bg-primary/15">Your team</Badge>
  if (owner === 'Free agent') return <Badge variant="outline" className="border-buy/40 text-buy">Free agent</Badge>
  if (owner) return <span className="text-xs text-muted-foreground">{owner}</span>
  return null
}
