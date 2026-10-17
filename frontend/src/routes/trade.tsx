import { useMutation, useQuery } from '@tanstack/react-query'
import { Check, Lightbulb, Loader2, Plus, Scale } from 'lucide-react'
import { useDeferredValue, useState } from 'react'

import type { PlayerRef, RosterPlayer } from '@/api'
import {
  evaluateTradeMutation,
  getTeamOptions,
  searchPlayersOptions,
  suggestTradesOptions,
} from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PlayerChip, PositionBadge } from '@/components/player/badges'
import { TradeCard } from '@/components/team/TradeCard'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
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
                ? 'Manual teams have no league rosters to trade with. Connect a Sleeper or ESPN league for trade ideas.'
                : 'We only suggest deals where both starting lineups gain points and market values are close enough to be realistic.'}
            </EmptyState>
          )}
          {ideas.data?.ideas.map((t) => (
            <TradeCard key={t.headline + (t.partner?.team_id ?? '')} trade={t} />
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

const ANY = '__any__'

/** Receive side for a hypothetical trade: search the whole player pool. */
function AnyPlayerPicker({
  exclude,
  picked,
  onAdd,
  onRemove,
}: {
  exclude: Set<string>
  picked: PlayerRef[]
  onAdd: (p: PlayerRef) => void
  onRemove: (id: string) => void
}) {
  const [q, setQ] = useState('')
  const deferredQ = useDeferredValue(q)
  const search = useQuery({
    ...searchPlayersOptions({ query: { q: deferredQ, limit: 12 } }),
    placeholderData: (prev) => prev,
  })
  const pickedIds = new Set(picked.map((p) => p.player_id))
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">You get (any player)</span>
      {picked.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {picked.map((p) => (
            <button
              key={p.player_id}
              type="button"
              onClick={() => onRemove(p.player_id)}
              className="rounded-md ring-primary/40 hover:ring-1"
              aria-label={`Remove ${p.name}`}
            >
              <PlayerChip player={p} className="bg-primary/10" link={false} />
            </button>
          ))}
        </div>
      )}
      <Command shouldFilter={false} className="h-80 rounded-md border">
        <CommandInput placeholder="Search players to receive…" value={q} onValueChange={setQ} />
        <CommandList className="max-h-none">
          <CommandEmpty>{search.isFetching ? 'Searching…' : 'No players found.'}</CommandEmpty>
          <CommandGroup>
            {(search.data ?? [])
              .filter((p) => !exclude.has(p.player_id))
              .map((p) => (
                <CommandItem
                  key={p.player_id}
                  value={p.player_id}
                  onSelect={() => (pickedIds.has(p.player_id) ? onRemove(p.player_id) : onAdd(p))}
                >
                  <PositionBadge position={p.position} />
                  <span className="flex-1">{p.name}</span>
                  <span className="text-xs text-muted-foreground">{p.nfl_team}</span>
                  {pickedIds.has(p.player_id) ? (
                    <Check className="text-primary" />
                  ) : (
                    <Plus className="text-muted-foreground" />
                  )}
                </CommandItem>
              ))}
          </CommandGroup>
        </CommandList>
      </Command>
    </div>
  )
}

function Analyzer({ teamId }: { teamId: string }) {
  const mine = useQuery(getTeamOptions({ path: { team_id: teamId } }))
  const others = mine.data?.league_teams.filter((t) => !t.is_mine) ?? []
  const [partnerChoice, setPartnerChoice] = useState<string>('')
  // Manual teams have no league partners, so they start in hypothetical mode.
  const partnerId = partnerChoice || (mine.data && others.length === 0 ? ANY : '')
  const hypothetical = partnerId === ANY
  const partner = useQuery({
    ...getTeamOptions({ path: { team_id: partnerId } }),
    enabled: !!partnerId && !hypothetical,
  })
  const [give, setGive] = useState<Set<string>>(new Set())
  const [receive, setReceive] = useState<Set<string>>(new Set())
  const [anyReceive, setAnyReceive] = useState<PlayerRef[]>([])
  const evaluate = useMutation(evaluateTradeMutation())

  const toggle = (set: Set<string>, update: (s: Set<string>) => void, id: string) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    update(next)
    evaluate.reset()
  }

  if (mine.isPending) return <ListSkeleton rows={2} height="h-40" />
  if (mine.isError) return <ErrorState error={mine.error} onRetry={() => void mine.refetch()} />

  const receiveIds = hypothetical ? anyReceive.map((p) => p.player_id) : [...receive]
  const myIds = new Set(mine.data.roster.map((p) => p.player_id))
  const nothingPicked = hypothetical ? give.size + receiveIds.length === 0 : receiveIds.length === 0

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Build a trade</CardTitle>
          <CardDescription>
            Trade with a league team, or choose <b>Any player (hypothetical)</b> to test a deal for anyone: free
            agents, players in another league, or a manually entered team. Up to 5 players per side.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Select
            value={partnerId}
            onValueChange={(v) => {
              setPartnerChoice(v)
              setReceive(new Set())
              setAnyReceive([])
              evaluate.reset()
            }}
          >
            <SelectTrigger className="w-full sm:w-80" aria-label="Trade partner">
              <SelectValue placeholder="Choose a trade partner" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>Any player (hypothetical)</SelectItem>
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
            {hypothetical ? (
              <AnyPlayerPicker
                exclude={myIds}
                picked={anyReceive}
                onAdd={(p) => {
                  if (anyReceive.length < 5) setAnyReceive([...anyReceive, p])
                  evaluate.reset()
                }}
                onRemove={(id) => {
                  setAnyReceive(anyReceive.filter((p) => p.player_id !== id))
                  evaluate.reset()
                }}
              />
            ) : partnerId ? (
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
            disabled={nothingPicked || give.size > 5 || receiveIds.length > 5 || evaluate.isPending}
            onClick={() => evaluate.mutate({ body: { team_id: teamId, give: [...give], receive: receiveIds } })}
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
