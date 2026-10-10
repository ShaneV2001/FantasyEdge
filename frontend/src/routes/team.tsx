import { useQuery } from '@tanstack/react-query'

import { getRegressionOptions, getTeamOptions } from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PositionStrengthChart } from '@/components/team/PositionStrengthChart'
import { RegressionList } from '@/components/team/RegressionList'
import { RosterTable } from '@/components/team/RosterTable'
import { TeamGrades } from '@/components/team/TeamGrades'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { fmtNum } from '@/lib/format'
import { useTeamStore } from '@/stores/team'

export function TeamPage() {
  const team = useTeamStore((s) => s.team)!
  const q = useQuery(getTeamOptions({ path: { team_id: team.teamId } }))
  const reg = useQuery(getRegressionOptions({ path: { team_id: team.teamId } }))
  const data = q.data

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={data?.team_name ?? team.teamName}
        description={
          data
            ? `${data.record} · ${data.league.name} · ${data.league.scoring} · starting lineup projects ${fmtNum(data.starter_points)} ppg`
            : 'Loading roster…'
        }
        actions={
          data?.market.source && (
            <Badge variant="outline" title="Market values source">
              Market: {data.market.source === 'fantasycalc' ? 'FantasyCalc' : data.market.source}
              {data.market.stale && ' (fallback)'}
            </Badge>
          )
        }
      />
      {q.isPending && <ListSkeleton rows={6} height="h-12" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {data && (
        <>
          <TeamGrades grades={data.grades} needs={data.needs} />
          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Roster</CardTitle>
                <CardDescription>
                  Best lineup on top. ROS value = projected rest-of-season points above a replacement-level player at
                  the position for your league.
                </CardDescription>
              </CardHeader>
              <CardContent className="px-2 sm:px-6">
                <RosterTable roster={data.roster} week={data.league.week} />
              </CardContent>
            </Card>
            <div className="flex flex-col gap-6">
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
      <Card>
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
                <RegressionList rows={reg.data.league} showOwner />
              </TabsContent>
            </Tabs>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
