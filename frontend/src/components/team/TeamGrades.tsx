import type { PositionGradeOut } from '@/api'
import { PositionBadge } from '@/components/player/badges'
import { Card, CardContent } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fmtNum, GRADE_CLASS } from '@/lib/format'
import { cn } from '@/lib/utils'

const ORDER = ['QB', 'RB', 'WR', 'TE']

export function TeamGrades({ grades, needs = [] }: { grades: Record<string, PositionGradeOut>; needs?: string[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {ORDER.filter((p) => grades[p]).map((pos) => {
        const g = grades[pos]
        const pct = Math.round(g.delta_pct * 100)
        return (
          <Tooltip key={pos}>
            <TooltipTrigger asChild>
              <Card className={cn('gap-0 py-0', needs.includes(pos) && 'ring-1 ring-sell/40')}>
                <CardContent className="flex items-center justify-between gap-3 p-4">
                  <div className="flex flex-col gap-1.5">
                    <PositionBadge position={pos} />
                    <span className="text-xs text-muted-foreground">
                      #{g.rank} of {g.teams} · {pct >= 0 ? '+' : ''}
                      {pct}% vs avg
                    </span>
                  </div>
                  <span className={cn('font-mono text-3xl font-semibold', GRADE_CLASS[g.grade])}>{g.grade}</span>
                </CardContent>
              </Card>
            </TooltipTrigger>
            <TooltipContent>
              Starters at {pos} project {fmtNum(g.points)} ppg vs league average {fmtNum(g.league_avg)}
              {needs.includes(pos) ? ' — a need' : ''}
            </TooltipContent>
          </Tooltip>
        )
      })}
    </div>
  )
}
