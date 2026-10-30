import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CalendarDays, Pencil } from 'lucide-react'

import { getRegressionOptions, getTeamOptions } from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PositionStrengthChart } from '@/components/team/PositionStrengthChart'
import { BackToTop } from '@/components/common/BackToTop'
import { LeagueRegressionList, RegressionList } from '@/components/team/RegressionList'
import { RosterTable } from '@/components/team/RosterTable'
import { TeamGrades } from '@/components/team/TeamGrades'
import { PendingTradesBanner, RosterViewToggle, usePendingTrades } from '@/components/trade/PendingTrades'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { platformName } from '@/lib/format'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { fmtNum } from '@/lib/format'
import { useTeamStore } from '@/stores/team'

export function TeamPage() {
  const team = useTeamStore((s) => s.team)!
  const pending = usePendingTrades(team)
  const after = pending.view === 'after'
  const path = { team_id: team.teamId }
  // today's roster stays loaded in the After view: its grades and points show what the trades change
  const current = useQuery(getTeamOptions({ path }))
  const afterTeam = useQuery({ ...getTeamOptions({ path, query: { roster: 'after' } }), enabled: after })
  const q = after ? afterTeam : current
  const reg = useQuery({ ...getRegressionOptions({ path, query: after ? { roster: 'after' } : undefined }) })
  const data = q.data
  const was = data?.view === 'after' ? current.data : undefined
  const n = data?.pending_trades ?? 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={data?.team_name ?? team.teamName}
        description={
          data
            ? `${data.record} · ${data.league.name} · ${data.league.scoring}${n ? ` · after ${n} accepted trade${n > 1 ? 's' : ''}` : ''} · starting lineup projects ${fmtNum(data.starter_points)} ppg${was ? ` (was ${fmtNum(was.starter_points)})` : ''}`
            : 'Loading roster…'
        }
        actions={
          data && (
            <>
              {data.market.source && (
                <Badge variant="outline" title="Market values source">
                  Market: {data.market.source === 'fantasycalc' ? 'FantasyCalc' : data.market.source}
                  {data.market.stale && ' (fallback)'}
                </Badge>
              )}
              {data.league.platform === 'manual' ? (
                <Button asChild size="sm">
                  <Link to="/team/edit">
                    <Pencil /> Edit team
                  </Link>
                </Button>
              ) : (
                <Badge
                  variant="secondary"
                  title={`Roster changes come from ${platformName(data.league.platform)}: use Update in the sidebar`}
                >
                  Synced from {platformName(data.league.platform)}
                </Badge>
              )}
            </>
          )
        }
      />
      {q.isPending && <ListSkeleton rows={6} height="h-12" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {pending.has && pending.data && (
        <PendingTradesBanner
          data={pending.data}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <RosterViewToggle view={pending.view} onChange={pending.setView} />
              <Button asChild size="sm" variant="ghost" className="mt-1">
                <Link to="/byes" search={{ view: 'after' }}>
                  <CalendarDays /> Week-by-week lineups
                </Link>
              </Button>
            </div>
          }
        />
      )}
      {data && (
        <>
          <TeamGrades
            grades={data.grades}
            overall={data.overall_grade}
            basis={data.grade_basis}
            needs={data.needs}
            compare={was?.grades}
            compareOverall={was?.overall_grade}
          />
          {/* the roster needs the full width for its columns until the screen is very wide */}
          <div className="grid gap-6 2xl:grid-cols-3">
            <Card className="2xl:col-span-2">
              <CardHeader>
                <CardTitle>{was ? 'Roster after the accepted trades' : 'Roster'}</CardTitle>
                <CardDescription>
                  This week's best lineup on top (players on bye or ruled out can't start). ROS value = projected rest-of-season points above a replacement-level player at
                  the position for your league.
                </CardDescription>
              </CardHeader>
              <CardContent className="px-2 sm:px-6">
                <RosterTable roster={data.roster} week={data.league.week} />
              </CardContent>
            </Card>
            <div className="grid gap-6 md:grid-cols-2 2xl:flex 2xl:flex-col">
              <Card>
                <CardHeader>
                  <CardTitle>Position strength</CardTitle>
                  <CardDescription>Starter ppg vs league average</CardDescription>
                </CardHeader>
                <CardContent>
                  <PositionStrengthChart grades={data.grades} />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Depth</CardTitle>
                </CardHeader>
                <CardContent className="flex flex-col gap-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Needs</span>
                    <span>{data.needs.length ? data.needs.join(', ') : 'None'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Surplus to trade</span>
                    <span>{data.surplus.length ? data.surplus.join(', ') : 'None'}</span>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
      {/* overflow-visible: the league tab's filter bar sticks below the page header while you scroll */}
      <Card className="overflow-visible">
        <CardHeader>
          <CardTitle>Regression report</CardTitle>
          <CardDescription>
            TD over expected (±{reg.data?.thresholds.tdoe ?? 2} TDs), efficiency outliers (|z| ≥{' '}
            {reg.data?.thresholds.efficiency_z ?? 1.5}) and usage vs production mismatches.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {reg.isPending && <ListSkeleton rows={3} height="h-14" />}
          {reg.isError && <ErrorState error={reg.error} onRetry={() => void reg.refetch()} />}
          {reg.data && (
            <Tabs defaultValue="mine">
              <TabsList>
                <TabsTrigger value="mine">My roster</TabsTrigger>
                <TabsTrigger value="league">Rest of league</TabsTrigger>
              </TabsList>
              <TabsContent value="mine">
                <RegressionList rows={reg.data.roster} />
              </TabsContent>
              <TabsContent value="league">
                <LeagueRegressionList rows={reg.data.league} />
              </TabsContent>
            </Tabs>
          )}
        </CardContent>
      </Card>
      <BackToTop />
    </div>
  )
}
