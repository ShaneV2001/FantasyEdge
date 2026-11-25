import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { ArrowLeftRight } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { z } from 'zod'

import type { PositionGradeOut, TeamSummary } from '@/api'
import { getTeamOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PositionBadge } from '@/components/player/badges'
import { LineupBySlot } from '@/components/team/LineupBySlot'
import { TeamGrades } from '@/components/team/TeamGrades'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { fmtNum, GRADE_CLASS, GRADE_ORDER } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

export const leagueSearchSchema = z.object({
  team: z.string().max(80).optional().catch(undefined),
})

type SortKey = 'overall' | 'record' | 'ppg' | string

function gradeOf(t: TeamSummary, key: string): PositionGradeOut | null | undefined {
  return key === 'overall' ? t.overall_grade : t.grades[key]
}

function sortTeams(teams: TeamSummary[], key: SortKey): TeamSummary[] {
  const by = (t: TeamSummary): number => {
    if (key === 'record') return -(t.wins - t.losses) * 1e4 - t.points_for / 1e3
    if (key === 'ppg') return -t.starter_points
    return gradeOf(t, key)?.rank ?? 99
  }
  return [...teams].sort((a, b) => by(a) - by(b))
}

function GradeCell({ g }: { g?: PositionGradeOut | null }) {
  if (!g) return <span className="text-muted-foreground">—</span>
  return (
    <span className="inline-flex items-baseline gap-1 font-mono tabular-nums" title={`${fmtNum(g.points)} ppg · #${g.rank} of ${g.teams}`}>
      <span className={cn('font-semibold', GRADE_CLASS[g.grade])}>{g.grade}</span>
      <span className="text-xs text-muted-foreground">#{g.rank}</span>
    </span>
  )
}

function SortHead({ k, sort, onSort, children, className }: { k: SortKey; sort: SortKey; onSort: (k: SortKey) => void; children: React.ReactNode; className?: string }) {
  return (
    <TableHead className={className} aria-sort={sort === k ? 'ascending' : undefined}>
      <button type="button" className={cn('inline-flex items-center gap-1 hover:text-foreground', sort === k && 'font-semibold text-foreground')} onClick={() => onSort(k)}>
        {children}
        {sort === k && <span aria-hidden>↓</span>}
      </button>
    </TableHead>
  )
}

function TeamDetail({ teamId, isMine }: { teamId: string; isMine: boolean }) {
  const q = useQuery(getTeamOptions({ path: { team_id: teamId } }))
  if (q.isPending) return <ListSkeleton rows={4} height="h-12" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  const t = q.data
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">
            {t.team_name} {isMine && <Badge variant="secondary">You</Badge>}
          </h2>
          <p className="text-sm text-muted-foreground">
            {t.owner_name} · {t.record} · best lineup projects {fmtNum(t.starter_points)} ppg
          </p>
        </div>
        {!isMine && (
          <Button asChild size="sm">
            <Link to="/trade" search={{ tab: 'analyzer', partner: teamId } as never}>
              <ArrowLeftRight /> Trade with this team
            </Link>
          </Button>
        )}
      </div>
      <TeamGrades grades={t.grades} overall={t.overall_grade} basis={t.grade_basis} needs={t.needs} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Lineup by slot</CardTitle>
            <CardDescription>This week's best lineup, then the bench. ROS rank = rest-of-season rank at the position.</CardDescription>
          </CardHeader>
          <CardContent className="px-2 sm:px-6">
            <LineupBySlot roster={t.roster} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Depth</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-sm">
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">Needs</span>
              <span className="text-right">{t.needs.length ? t.needs.join(', ') : 'None'}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-muted-foreground">Surplus to trade</span>
              <span className="text-right">{t.surplus.length ? t.surplus.join(', ') : 'None'}</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export function LeaguePage() {
  const team = useTeamStore((s) => s.team)!
  const search = leagueSearchSchema.safeParse(useSearch({ strict: false }))
  const selected = search.success ? search.data.team : undefined
  const navigate = useNavigate()
  const q = useQuery(getTeamOptions({ path: { team_id: team.teamId } }))
  const [sort, setSort] = useState<SortKey>('overall')
  const detailRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (selected) detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [selected])

  const teams = q.data?.league_teams ?? []
  const cols = GRADE_ORDER.filter((p) => teams.some((t) => t.grades[p]))
  const select = (id: string) => void navigate({ to: '/league', search: { team: id } as never, replace: true })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="League"
        description={
          q.data
            ? `${q.data.league.name} · ${teams.length} teams · position grades and ranks for every team's best lineup. Pick a team to see its roster.`
            : 'Loading the league…'
        }
      />
      {q.isPending && <ListSkeleton rows={8} height="h-10" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && teams.length <= 1 && (
        <EmptyState title="No other teams">
          A manually entered team has no league to compare with. Connect a Sleeper or ESPN league to see the other rosters.
        </EmptyState>
      )}
      {q.data && teams.length > 1 && (
        <Card>
          <CardContent className="px-0 sm:px-2">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="min-w-44">Team</TableHead>
                    <SortHead k="record" sort={sort} onSort={setSort}>
                      Record
                    </SortHead>
                    <SortHead k="overall" sort={sort} onSort={setSort}>
                      Overall
                    </SortHead>
                    {cols.map((p) => (
                      <SortHead key={p} k={p} sort={sort} onSort={setSort}>
                        <PositionBadge position={p} />
                      </SortHead>
                    ))}
                    <SortHead k="ppg" sort={sort} onSort={setSort} className="text-right">
                      Lineup ppg
                    </SortHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortTeams(teams, sort).map((t) => (
                    <TableRow
                      key={t.team_id}
                      className={cn('cursor-pointer', t.is_mine && 'bg-primary/5', selected === t.team_id && 'bg-muted')}
                      onClick={() => select(t.team_id)}
                      data-state={selected === t.team_id ? 'selected' : undefined}
                    >
                      <TableCell>
                        <button type="button" className="flex flex-col text-left" onClick={(e) => (e.stopPropagation(), select(t.team_id))}>
                          <span className="font-medium">
                            {t.team_name} {t.is_mine && <Badge variant="secondary" className="ml-1">You</Badge>}
                          </span>
                          <span className="text-xs text-muted-foreground">{t.owner_name}</span>
                        </button>
                      </TableCell>
                      <TableCell className="font-mono text-xs tabular-nums">
                        {t.wins}-{t.losses}
                      </TableCell>
                      <TableCell>
                        <GradeCell g={t.overall_grade} />
                      </TableCell>
                      {cols.map((p) => (
                        <TableCell key={p}>
                          <GradeCell g={t.grades[p]} />
                        </TableCell>
                      ))}
                      <TableCell className="text-right font-mono text-xs tabular-nums">{fmtNum(t.starter_points)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
      <div ref={detailRef} className="scroll-mt-20">
        {selected && teams.some((t) => t.team_id === selected) && (
          <TeamDetail teamId={selected} isMine={selected === team.teamId} />
        )}
      </div>
    </div>
  )
}
