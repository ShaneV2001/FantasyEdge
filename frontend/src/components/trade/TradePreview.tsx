import type { DropOut, PositionGradeOut, TeamOut, TradePreviewOut } from '@/api'
import { PlayerChip, PositionBadge } from '@/components/player/badges'
import { LineupBySlot } from '@/components/team/LineupBySlot'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { fmtNum, GRADE_CLASS, GRADE_ORDER } from '@/lib/format'
import { cn } from '@/lib/utils'

function Grade({ g }: { g: PositionGradeOut }) {
  return (
    <span className="inline-flex items-baseline gap-1 font-mono tabular-nums">
      <span className={cn('font-semibold', GRADE_CLASS[g.grade])}>{g.grade}</span>
      <span className="text-xs text-muted-foreground">#{g.rank}</span>
    </span>
  )
}

/** Position grades and league ranks before → after, with ▲/▼ where the rank moves. */
export function RankChanges({
  before,
  after,
  overallBefore,
  overallAfter,
}: {
  before: Record<string, PositionGradeOut>
  after: Record<string, PositionGradeOut>
  overallBefore?: PositionGradeOut | null
  overallAfter?: PositionGradeOut | null
}) {
  const rows: [React.ReactNode, PositionGradeOut | undefined | null, PositionGradeOut | undefined | null][] = [
    [<span className="text-xs font-semibold uppercase">Overall</span>, overallBefore, overallAfter],
    ...GRADE_ORDER.filter((p) => after[p] || before[p]).map(
      (p) => [<PositionBadge position={p} />, before[p], after[p]] as [React.ReactNode, PositionGradeOut | undefined, PositionGradeOut | undefined],
    ),
  ]
  const teams = (overallAfter ?? Object.values(after)[0])?.teams
  return (
    <table className="w-full text-sm" aria-label="Position ranks before and after">
      <thead>
        <tr className="text-left text-[11px] text-muted-foreground">
          <th className="pb-1 font-normal">Position</th>
          <th className="pb-1 font-normal">Now</th>
          <th className="pb-1 font-normal">After trade</th>
          <th className="pb-1 text-right font-normal">{teams ? `of ${teams}` : ''}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, b, a], i) => {
          if (!a) return null
          const move = b ? b.rank - a.rank : 0
          return (
            <tr key={i} className="border-t border-border/50">
              <td className="py-1.5">{label}</td>
              <td className="py-1.5">{b ? <Grade g={b} /> : '—'}</td>
              <td className="py-1.5">
                <Grade g={a} />
              </td>
              <td
                className={cn(
                  'py-1.5 text-right font-mono text-xs font-semibold',
                  move > 0 ? 'text-buy' : move < 0 ? 'text-sell' : 'text-muted-foreground',
                )}
                data-testid="rank-move"
              >
                {move > 0 ? `▲${move}` : move < 0 ? `▼${-move}` : '—'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function Drops({ drops }: { drops: DropOut[] }) {
  if (!drops.length) return null
  return (
    <div className="flex flex-col gap-1 rounded-md border border-warn/40 bg-warn/5 p-2 text-xs">
      <span className="font-medium text-warn">Must drop to stay at the roster limit</span>
      {drops.map((d) => (
        <span key={d.player.player_id} className="flex flex-wrap items-center gap-1.5">
          <PlayerChip player={d.player} /> <span className="text-muted-foreground">{d.reason}</span>
        </span>
      ))}
    </div>
  )
}

function TeamAfter({ after, before, drops, label }: { after: TeamOut; before?: TeamOut; drops: DropOut[]; label: string }) {
  const delta = before ? after.starter_points - before.starter_points : 0
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {label}: {after.team_name}
        </CardTitle>
        <CardDescription>
          Best lineup projects {fmtNum(after.starter_points)} ppg
          {before && (
            <span className={cn('ml-1 font-medium', delta > 0.05 ? 'text-buy' : delta < -0.05 ? 'text-sell' : '')}>
              ({delta >= 0 ? '+' : '−'}
              {fmtNum(Math.abs(delta))} vs {fmtNum(before.starter_points)} now)
            </span>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-2 sm:px-6">
        <RankChanges
          before={before?.grades ?? {}}
          after={after.grades}
          overallBefore={before?.overall_grade}
          overallAfter={after.overall_grade}
        />
        <Drops drops={drops} />
        <LineupBySlot roster={after.roster} was={before?.roster} />
      </CardContent>
    </Card>
  )
}

/** Both teams as if the trade went through: rank changes, forced drops and the new lineups. */
export function TradePreview({
  data,
  mineBefore,
  partnerBefore,
}: {
  data: TradePreviewOut
  mineBefore?: TeamOut
  partnerBefore?: TeamOut
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="trade-preview">
      <TeamAfter label="You" after={data.me} before={mineBefore} drops={data.me_drops ?? []} />
      {data.partner ? (
        <TeamAfter label="Partner" after={data.partner} before={partnerBefore} drops={data.partner_drops ?? []} />
      ) : (
        <div className="grid place-items-center rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          Hypothetical trade: only your roster changes.
        </div>
      )}
    </div>
  )
}
