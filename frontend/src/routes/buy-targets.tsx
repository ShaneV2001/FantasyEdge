import { useQuery } from '@tanstack/react-query'
import { Info } from 'lucide-react'
import { useState } from 'react'

import type { BuyTargetRow, BuyTargetsOut } from '@/api'
import { getBuyTargetsOptions } from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { InjuryTag, SignalBadge } from '@/components/player/badges'
import { Matchups, OwnerLabel, injuryStatus } from '@/components/player/matchups'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { POSITIONS, fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

function ValueTable({ rows, position, marketLabel }: { rows: BuyTargetRow[]; position: string; marketLabel: string }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-10">#</TableHead>
          <TableHead>Player</TableHead>
          <TableHead className="text-right">
            Our ROS<span className="hidden md:inline"> pts</span>
          </TableHead>
          <TableHead className="hidden text-right md:table-cell">{marketLabel} prices like</TableHead>
          <TableHead className="text-right">Gap</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.player_id} className="align-top">
            <TableCell className="font-mono text-muted-foreground">{r.rank}</TableCell>
            <TableCell>
              <div className="flex flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2 font-medium">
                  <PlayerLink playerId={r.player_id}>{r.name}</PlayerLink>
                  <InjuryTag status={injuryStatus(r.availability_note)} />
                  <SignalBadge signal={r.signal} reasons={r.reasons} />
                </span>
                <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {r.nfl_team} · {fmtNum(r.ppg)} ppg · our {position}
                  {r.model_rank} vs market {position}
                  {r.market_rank}
                  <OwnerLabel owner={r.owner} mine={r.mine} />
                </span>
                <ul className="list-disc pl-4 text-xs text-muted-foreground">
                  {r.reasons.slice(1, 3).map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
                <Matchups cells={r.cells} position={position} />
              </div>
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums">{fmtNum(r.model_points, 0)}</TableCell>
            <TableCell className="hidden text-right font-mono tabular-nums text-muted-foreground md:table-cell">
              {position}
              {r.market_rank} · {fmtNum(r.market_implied_points, 0)}
            </TableCell>
            <TableCell
              className={cn(
                'text-right font-mono font-semibold tabular-nums',
                (r.value_gap ?? 0) > 0 ? 'text-buy' : 'text-sell',
              )}
            >
              {fmtSigned(r.value_gap, 0)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function BuyTargets({ data }: { data: BuyTargetsOut }) {
  const [position, setPosition] = useState<string>('RB')
  const pos = data.positions[position]

  return (
    <div className="flex flex-col gap-6">
      <Tabs value={position} onValueChange={setPosition}>
        <TabsList>
          {POSITIONS.map((p) => (
            <TabsTrigger key={p} value={p}>
              {p}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {pos && !pos.has_market ? (
        <Card className="border-dashed bg-transparent">
          <CardContent className="flex items-start gap-2 py-6 text-sm text-muted-foreground">
            <Info className="mt-0.5 size-4 shrink-0" />
            {data.market_label} doesn't value {position}s, so there's no buy/sell call here. Use Rankings to stream
            them week to week by matchup.
          </CardContent>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Buy: undervalued {position}s</CardTitle>
              <CardDescription>
                Players you don't own whose rest-of-season projection (schedule included) beats the price{' '}
                {data.market_label} puts on them by at least 10 points or 10%. "Prices like" is the player we rank
                where the market ranks him.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {pos && pos.buy.length > 0 ? (
                <ValueTable rows={pos.buy} position={position} marketLabel={data.market_label} />
              ) : (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  No {position} is clearly undervalued right now.
                </p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Sell: your overvalued {position}s</CardTitle>
              <CardDescription>
                Your players the market prices above what we project. Trading them should return more than they're
                worth to you.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {pos && pos.sell.length > 0 ? (
                <ValueTable rows={pos.sell} position={position} marketLabel={data.market_label} />
              ) : (
                <p className="py-6 text-center text-sm text-muted-foreground">None of your {position}s are overvalued.</p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

export function BuyTargetsPage() {
  const team = useTeamStore((s) => s.team)!
  const q = useQuery(getBuyTargetsOptions({ path: { team_id: team.teamId } }))

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Buy targets"
        description="Players the market undervalues compared with our rest-of-season projection, and your players it overvalues. A player's buy/hold/sell verdict is the same on every page."
      />
      {q.isPending && <ListSkeleton rows={6} height="h-12" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && <BuyTargets data={q.data} />}
    </div>
  )
}
