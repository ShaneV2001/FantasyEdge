import { useMutation, useQuery } from '@tanstack/react-query'
import { Lightbulb, Loader2, Scale } from 'lucide-react'
import { useState } from 'react'

import type { RosterPlayer } from '@/api'
import { evaluateTradeMutation, getTeamOptions, suggestTradesOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PositionBadge } from '@/components/player/badges'
import { TradeCard } from '@/components/team/TradeCard'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

export function TradePage() {
  const team = useTeamStore((s) => s.team)!
  const ideas = useQuery({ ...suggestTradesOptions({ query: { team_id: team.teamId } }), staleTime: 5 * 60_000 })
  const deadlinePassed = ideas.data?.deadline_passed

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Trades"
        description="Every trade is judged by what it does to both teams' rest-of-season starting lineups, with byes and injuries included."
      />
      {deadlinePassed && (
        <Alert>
          <AlertTitle>Trade deadline passed</AlertTitle>
          <AlertDescription>
            Your league's deadline was week {ideas.data?.trade_deadline_week}. Trade ideas are hidden; the analyzer still
            works for what-ifs.
          </AlertDescription>
        </Alert>
      )}
      <Tabs defaultValue={team.platform === 'manual' ? 'analyzer' : 'ideas'}>
        <TabsList>
          <TabsTrigger value="ideas">
            <Lightbulb /> Trade ideas
          </TabsTrigger>
          <TabsTrigger value="analyzer">
            <Scale /> Analyzer
          </TabsTrigger>
        </TabsList>
        <TabsContent value="ideas" className="mt-4 flex flex-col gap-4">
          {ideas.isPending && <ListSkeleton rows={3} height="h-48" />}
          {ideas.isError && <ErrorState error={ideas.error} onRetry={() => void ideas.refetch()} />}
          {ideas.data && ideas.data.ideas.length === 0 && (
            <EmptyState title={deadlinePassed ? 'No trade ideas after the deadline' : 'No mutually beneficial trades found'}>
              {team.platform === 'manual'
                ? 'Manual teams have no league rosters to trade with. Connect a Sleeper league for trade ideas.'
                : 'We only suggest deals where both starting lineups gain points and market values are close enough to be realistic.'}
            </EmptyState>
          )}
          {ideas.data?.ideas.map((t) => (
            <TradeCard key={t.headline + t.partner.team_id} trade={t} />
          ))}
        </TabsContent>
        <TabsContent value="analyzer" className="mt-4">
          <Analyzer teamId={team.teamId} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function PickList({
  title,
  players,
  picked,
  onToggle,
}: {
  title: string
  players: RosterPlayer[]
  picked: Set<string>
  onToggle: (id: string) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">{title}</span>
      <ul className="flex max-h-96 flex-col overflow-y-auto rounded-md border">
        {players
          .filter((p) => ['QB', 'RB', 'WR', 'TE'].includes(p.position))
          .map((p) => {
            const on = picked.has(p.player_id)
            return (
              <li key={p.player_id}>
                <button
                  type="button"
                  aria-pressed={on}
                  onClick={() => onToggle(p.player_id)}
                  className={cn(
                    'flex w-full items-center gap-2 border-b px-2 py-1.5 text-left text-sm last:border-b-0 hover:bg-muted/50',
                    on && 'bg-primary/10',
                  )}
                >
                  <span className={cn('size-3.5 rounded-sm border', on && 'border-primary bg-primary')} />
                  <PositionBadge position={p.position} />
                  <span className="flex-1 truncate">{p.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">{fmtNum(p.ppg)}</span>
                </button>
              </li>
            )
          })}
      </ul>
    </div>
  )
}

function Analyzer({ teamId }: { teamId: string }) {
  const mine = useQuery(getTeamOptions({ path: { team_id: teamId } }))
  const [partnerId, setPartnerId] = useState<string>('')
  const partner = useQuery({ ...getTeamOptions({ path: { team_id: partnerId } }), enabled: !!partnerId })
  const [give, setGive] = useState<Set<string>>(new Set())
  const [receive, setReceive] = useState<Set<string>>(new Set())
  const evaluate = useMutation(evaluateTradeMutation())
  const others = mine.data?.league_teams.filter((t) => !t.is_mine) ?? []

  const toggle = (set: Set<string>, update: (s: Set<string>) => void, id: string) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    update(next)
    evaluate.reset()
  }

  if (mine.isPending) return <ListSkeleton rows={2} height="h-40" />
  if (mine.isError) return <ErrorState error={mine.error} onRetry={() => void mine.refetch()} />
  if (others.length === 0) {
    return (
      <EmptyState title="No trade partners">
        This team isn't part of a synced league. Connect your Sleeper league to analyze trades.
      </EmptyState>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Build a trade</CardTitle>
          <CardDescription>Pick a partner, then the players going each way (up to 5 per side).</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Select
            value={partnerId}
            onValueChange={(v) => {
              setPartnerId(v)
              setReceive(new Set())
              evaluate.reset()
            }}
          >
            <SelectTrigger className="w-full sm:w-80" aria-label="Trade partner">
              <SelectValue placeholder="Choose a trade partner" />
            </SelectTrigger>
            <SelectContent>
              {others.map((t) => (
                <SelectItem key={t.team_id} value={t.team_id}>
                  {t.team_name} · {t.owner_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="grid gap-4 md:grid-cols-2">
            <PickList
              title="You give"
              players={mine.data.roster}
              picked={give}
              onToggle={(id) => toggle(give, setGive, id)}
            />
            {partnerId ? (
              partner.isPending ? (
                <ListSkeleton rows={1} height="h-64" />
              ) : partner.data ? (
                <PickList
                  title={`You get from ${partner.data.team_name}`}
                  players={partner.data.roster}
                  picked={receive}
                  onToggle={(id) => toggle(receive, setReceive, id)}
                />
              ) : (
                <ErrorState error={partner.error} />
              )
            ) : (
              <div className="grid place-items-center rounded-md border border-dashed p-6 text-sm text-muted-foreground">
                Choose a partner to see their roster
              </div>
            )}
          </div>
          <Button
            className="self-end"
            disabled={receive.size === 0 || give.size > 5 || receive.size > 5 || evaluate.isPending}
            onClick={() =>
              evaluate.mutate({ body: { team_id: teamId, give: [...give], receive: [...receive] } })
            }
          >
            {evaluate.isPending && <Loader2 className="animate-spin" />}
            Evaluate trade
          </Button>
        </CardContent>
      </Card>
      {evaluate.isError && <ErrorState error={evaluate.error} />}
      {evaluate.data && <TradeCard trade={evaluate.data} />}
    </div>
  )
}
