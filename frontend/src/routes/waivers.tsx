import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ArrowRight, Flame, Info, Plug } from 'lucide-react'
import { useState } from 'react'

import type { TrendingRow, WaiverRow, WaiversOut } from '@/api'
import { getWaiversOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { InjuryTag, PlayerChip, PositionBadge, SignalBadge } from '@/components/player/badges'
import { OwnerLabel } from '@/components/player/matchups'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { FAAB_FORMULA, faabFormula, fmtBid } from '@/lib/faab'
import { POSITIONS, fmtNum, fmtRelative } from '@/lib/format'
import { useTeamStore } from '@/stores/team'

function weeksText(weeks: number[]) {
  return weeks.length === 1 ? `wk ${weeks[0]}` : `wks ${weeks.join(', ')}`
}

function FaabHelp({ data }: { data: WaiversOut }) {
  const f = data.faab
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs text-muted-foreground">
          <Info className="size-3.5" /> How bids are calculated
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 text-sm" align="end">
        <p className="font-medium">{faabFormula(f, f.remaining)}</p>
        <p className="mt-2 text-muted-foreground">{FAAB_FORMULA}</p>
        <p className="mt-2 text-muted-foreground">
          Gain is the net rest-of-season points the pickup adds to your starting lineup, after the drop. These are
          suggestions: your league's bidding habits matter more than any formula.
        </p>
        <Button variant="link" size="sm" className="mt-1 h-auto px-0" asChild>
          <Link to="/settings">
            Tune it in Settings <ArrowRight className="size-3.5" />
          </Link>
        </Button>
      </PopoverContent>
    </Popover>
  )
}

function WaiverTable({ rows, faab }: { rows: WaiverRow[]; faab: boolean }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-8">#</TableHead>
          <TableHead>Add</TableHead>
          <TableHead className="text-right">Gain</TableHead>
          <TableHead className="hidden md:table-cell">Drop</TableHead>
          {faab && <TableHead className="text-right">Bid</TableHead>}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.player.player_id}>
            <TableCell className="align-top font-mono text-muted-foreground">{r.rank}</TableCell>
            <TableCell className="whitespace-normal">
              <div className="flex items-start gap-2">
                <PositionBadge position={r.player.position} className="mt-0.5 shrink-0" />
                <div className="flex min-w-0 flex-col gap-0.5">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1 font-medium">
                    <PlayerLink playerId={r.player.player_id}>{r.player.name}</PlayerLink>
                    <InjuryTag status={r.injury_status} returnWeek={r.return_week} />
                    {r.return_week != null && r.return_week < 99 && (
                      <Badge variant="outline" className="border-warn/40 text-warn">
                        Back wk {r.return_week}
                      </Badge>
                    )}
                    <SignalBadge signal={r.signal} />
                    {r.fixes_weeks.length > 0 && (
                      <Badge variant="outline" className="border-warn/40 text-warn">
                        Fills {weeksText(r.fixes_weeks)}
                      </Badge>
                    )}
                    {r.need && r.fixes_weeks.length === 0 && (
                      <Badge variant="outline" className="border-primary/40 text-primary">
                        Need
                      </Badge>
                    )}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {r.player.nfl_team} · {fmtNum(r.ppg)} ppg{r.bye_week != null && ` · bye ${r.bye_week}`}
                  </span>
                  <span className="text-xs text-muted-foreground md:hidden">
                    {r.drop ? `Drop ${r.drop.name}${r.drop_reason ? ` (${r.drop_reason})` : ''}` : 'Open roster spot: no drop'}
                  </span>
                </div>
              </div>
            </TableCell>
            <TableCell className="text-right align-top">
              <div className="font-mono font-semibold text-buy tabular-nums">+{fmtNum(r.gain)}</div>
              <div className="text-xs text-muted-foreground tabular-nums">{fmtNum(r.gain_per_week)}/wk</div>
            </TableCell>
            <TableCell className="hidden align-top md:table-cell">
              {r.drop ? (
                <div className="flex flex-col gap-0.5">
                  <PlayerChip player={r.drop} />
                  <span className="pl-1 text-xs text-muted-foreground">
                    {[r.drop_ppg != null && `${fmtNum(r.drop_ppg)} ppg`, r.drop_reason].filter(Boolean).join(' · ')}
                  </span>
                </div>
              ) : (
                <span className="text-xs text-muted-foreground">Open roster spot</span>
              )}
            </TableCell>
            {faab && (
              <TableCell className="text-right align-top font-mono tabular-nums">
                {r.faab ? fmtBid(r.faab.low, r.faab.high) : '—'}
              </TableCell>
            )}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

function Trending({ rows, fetchedAt }: { rows: TrendingRow[]; fetchedAt?: string | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Flame className="size-4 text-warn" /> Trending adds
        </CardTitle>
        <CardDescription>
          Most-added players across all Sleeper leagues in the last 24 hours. Data from the{' '}
          <a href="https://docs.sleeper.com/" target="_blank" rel="noreferrer" className="underline underline-offset-2">
            Sleeper API
          </a>
          {fetchedAt && ` · fetched ${fmtRelative(fetchedAt)}`}.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No trending data yet. Press <span className="font-medium">Update</span> in the sidebar to fetch it.
          </p>
        ) : (
          <ol className="flex flex-col divide-y">
            {rows.map((t, i) => (
              <li key={t.player.player_id} className="flex items-center gap-3 py-2 text-sm">
                <span className="w-5 font-mono text-xs text-muted-foreground">{i + 1}</span>
                <PositionBadge position={t.player.position} />
                <div className="flex min-w-0 flex-1 flex-col">
                  <PlayerLink playerId={t.player.player_id} className="truncate font-medium">
                    {t.player.name}
                  </PlayerLink>
                  <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                    {t.player.nfl_team}
                    {t.ppg != null && ` · ${fmtNum(t.ppg)} ppg`}
                    <OwnerLabel owner={t.owner} mine={t.mine} />
                  </span>
                </div>
                <span className="font-mono text-xs text-muted-foreground tabular-nums">
                  +{t.adds.toLocaleString()}
                </span>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}

function Waivers({ data }: { data: WaiversOut }) {
  const [pos, setPos] = useState('ALL')
  const rows = pos === 'ALL' ? data.rows : data.rows.filter((r) => r.player.position === pos)
  const faab = data.faab.uses_faab
  const weeks = data.last_week - data.week + 1

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
      {data.message ? (
        <EmptyState title="No free agents for a manual team" icon={<Plug className="size-6" />}>
          <p>{data.message}</p>
          <Button size="sm" className="mt-3" asChild>
            <Link to="/connect">Connect a league</Link>
          </Button>
        </EmptyState>
      ) : (
        <Card className="min-w-0">
          <CardHeader className="gap-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>Best pickups for your lineup</CardTitle>
              {faab && <FaabHelp data={data} />}
            </div>
            <CardDescription>
              Gain is what each free agent adds to your starting lineup over weeks {data.week}–{data.last_week} ({weeks}{' '}
              weeks), after the drop a manager would make: an extra K or D/ST, surplus depth, or your lowest-value bench player. Bye weeks and injuries are counted.
              {faab
                ? data.faab.remaining != null && ` You have $${data.faab.remaining} of $${data.faab.budget} FAAB left.`
                : ' Your league uses waiver priority, not FAAB.'}
            </CardDescription>
            <ToggleGroup
              type="single"
              variant="outline"
              value={pos}
              onValueChange={(v) => v && setPos(v)}
              aria-label="Position"
              className="flex-wrap justify-start"
            >
              {['ALL', ...POSITIONS].map((p) => (
                <ToggleGroupItem key={p} value={p} className="px-2 text-xs">
                  {p === 'ALL' ? 'All' : p}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {rows.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {pos === 'ALL'
                  ? 'No free agent improves your lineup right now. Check again after waivers clear, or press Update to re-sync rosters.'
                  : `No free-agent ${pos} improves your lineup right now.`}
              </p>
            ) : (
              <WaiverTable rows={rows} faab={faab} />
            )}
            <p className="text-xs text-muted-foreground">
              Free agents as of the last roster sync ({fmtRelative(data.as_of)}). Players on waivers are included. Press
              Update in the sidebar to re-sync.
            </p>
          </CardContent>
        </Card>
      )}
      <Trending rows={data.trending} fetchedAt={data.trending_fetched_at} />
    </div>
  )
}

export function WaiversPage() {
  const team = useTeamStore((s) => s.team)!
  const q = useQuery(getWaiversOptions({ path: { team_id: team.teamId } }))
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Waivers"
        description="Free agents ranked by how much they'd add to your starting lineup for the rest of the season, who you'd drop for each, and a FAAB bid range."
      />
      {q.isPending && <ListSkeleton rows={6} height="h-14" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && <Waivers data={q.data} />}
    </div>
  )
}
