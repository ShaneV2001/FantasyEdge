import { Info } from 'lucide-react'

import type { PositionGradeOut } from '@/api'
import { PositionBadge } from '@/components/player/badges'
import { Card, CardContent } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { FLEX_GRADES, fmtNum, GRADE_CLASS, GRADE_ORDER } from '@/lib/format'
import { cn } from '@/lib/utils'


function zText(z: number) {
  return `${z >= 0 ? '+' : '−'}${Math.abs(z).toFixed(1)}σ`
}

function GradeCard({
  label,
  g,
  need,
  detail,
}: {
  label: React.ReactNode
  g: PositionGradeOut
  need?: boolean
  detail: string
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Card className={cn('gap-0 py-0', need && 'ring-1 ring-sell/40')}>
          <CardContent className="flex items-center justify-between gap-3 p-4">
            <div className="flex flex-col gap-1.5">
              {label}
              <span className="text-xs text-muted-foreground">
                #{g.rank} of {g.teams} · {zText(g.z ?? 0)}
              </span>
            </div>
            <span className={cn('font-mono text-3xl font-semibold', GRADE_CLASS[g.grade])}>{g.grade}</span>
          </CardContent>
        </Card>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs">{detail}</TooltipContent>
    </Tooltip>
  )
}

function gradeDetail(pos: string, g: PositionGradeOut, need: boolean) {
  const vs = `${fmtNum(g.points)} vs ${fmtNum(g.league_avg)} average`
  if ((FLEX_GRADES as readonly string[]).includes(pos)) {
    return `${pos} slot: ${vs} — the players your best lineup puts in your ${pos} spot(s).`
  }
  if (pos === 'K' || pos === 'DEF') return `${pos} strength ${vs} — your starting ${pos}.`
  return `${pos} strength ${vs} — your best ${pos}s weighted by the lineup spots they fill (incl. a share of FLEX), so depth counts and FLEX usage doesn't skew it.${need ? ' Flagged as a need.' : ''}`
}

export function TeamGrades({
  grades,
  overall,
  basis,
  needs = [],
}: {
  grades: Record<string, PositionGradeOut>
  overall?: PositionGradeOut | null
  basis?: string
  needs?: string[]
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {overall && (
          <GradeCard
            label={<span className="text-xs font-semibold tracking-wide uppercase">Overall</span>}
            g={overall}
            detail={`Full-strength starting lineup projects ${fmtNum(overall.points)} ppg vs ${fmtNum(overall.league_avg)} average (${zText(overall.z ?? 0)}).`}
          />
        )}
        {GRADE_ORDER.filter((p) => grades[p]).map((pos) => {
          const g = grades[pos]
          return (
            <GradeCard
              key={pos}
              label={<PositionBadge position={pos} />}
              g={g}
              need={needs.includes(pos)}
              detail={gradeDetail(pos, g, needs.includes(pos))}
            />
          )
        })}
      </div>
      {basis && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Info className="size-3" />
          Graded against {basis}. A ≥ +1σ · B ≥ +0.35σ · C within ±0.35σ · D ≥ −1σ · F below.
        </p>
      )}
    </div>
  )
}
