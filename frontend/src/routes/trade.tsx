import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Lightbulb, Loader2, Plus, RefreshCw, Scale, Search, Shuffle } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { toast } from 'sonner'

import type { PlayerRef, RosterPlayer, TradeFindRequest, TradeOut } from '@/api'
import {
  evaluateTradeMutation,
  findTradesMutation,
  getTeamOptions,
  refreshMutation,
  searchPlayersOptions,
  suggestTradesOptions,
} from '@/api/@tanstack/react-query.gen'
import { describeError } from '@/lib/errors'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
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

/** A deal handed to the analyzer from an idea or a finder result. */
export interface AnalyzerPrefill {
  key: string
  partnerId: string
  give: string[]
  receive: string[]
}

function toPrefill(t: TradeOut): AnalyzerPrefill {
  return {
    key: `${t.partner?.team_id}:${t.headline}:${Date.now()}`,
    partnerId: t.partner?.team_id ?? '',
    give: t.me.gives.map((p) => p.player_id),
    receive: t.me.receives.map((p) => p.player_id),
  }
}

export function TradePage() {
  const team = useTeamStore((s) => s.team)!
  const qc = useQueryClient()
  const [tab, setTab] = useState(team.platform === 'manual' ? 'analyzer' : 'ideas')
  const [page, setPage] = useState(0)
  const [prefill, setPrefill] = useState<AnalyzerPrefill | null>(null)
  const ideas = useQuery({
    ...suggestTradesOptions({ query: { team_id: team.teamId, page } }),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  })
  const refresh = useMutation({
    ...refreshMutation(),
    onSuccess: () => {
      setPage(0)
      void qc.invalidateQueries()
      toast.success('League re-synced: trade ideas recalculated')
    },
    onError: (e) => toast.error(describeError(e).message, { description: describeError(e).hint }),
  })
  const deadlinePassed = ideas.data?.deadline_passed
  const openInAnalyzer = (t: TradeOut) => {
    setPrefill(toPrefill(t))
    setTab('analyzer')
  }
  const nextPage = () => {
    if (ideas.data?.has_more) setPage((p) => p + 1)
    else {
      setPage(0)
      toast('Back to the best ideas', { description: "You've seen every deal that works for both teams right now." })
    }
  }

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
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="ideas">
            <Lightbulb /> Trade ideas
          </TabsTrigger>
          <TabsTrigger value="find">
            <Search /> Find a trade
          </TabsTrigger>
          <TabsTrigger value="analyzer">
            <Scale /> Analyzer
          </TabsTrigger>
        </TabsList>
        <TabsContent value="ideas" className="mt-4 flex flex-col gap-4">
          {team.platform !== 'manual' && !deadlinePassed && (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-muted-foreground">
                {page === 0 ? 'Best ideas first.' : `More ideas · set ${page + 1}.`} Only deals where both lineups gain after
                any forced drops, and neither team is left short in a bye week.
              </p>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={refresh.isPending}
                  onClick={() => refresh.mutate({ body: { scope: 'league', league_id: team.leagueId } })}
                  title="Re-sync rosters from your league, then recalculate"
                >
                  <RefreshCw className={refresh.isPending ? 'animate-spin' : ''} /> Refresh
                </Button>
                <Button size="sm" disabled={ideas.isFetching || !ideas.data?.ideas.length} onClick={nextPage}>
                  {ideas.isFetching ? <Loader2 className="animate-spin" /> : <Shuffle />}
                  Show different ideas
                </Button>
              </div>
            </div>
          )}
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
            <TradeCard key={t.headline + (t.partner?.team_id ?? '')} trade={t} onOpenInAnalyzer={openInAnalyzer} />
          ))}
        </TabsContent>
        <TabsContent value="find" className="mt-4">
          <FindTrade teamId={team.teamId} manual={team.platform === 'manual'} onOpenInAnalyzer={openInAnalyzer} />
        </TabsContent>
        <TabsContent value="analyzer" className="mt-4">
          <Analyzer key={prefill?.key ?? 'blank'} teamId={team.teamId} prefill={prefill} />
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

const WANT = ['RB', 'WR', 'TE', 'QB', 'ANY'] as const
type Want = TradeFindRequest['want_position']

export function FindTrade({
  teamId,
  manual,
  onOpenInAnalyzer,
}: {
  teamId: string
  manual: boolean
  onOpenInAnalyzer: (t: TradeOut) => void
}) {
  const mine = useQuery(getTeamOptions({ path: { team_id: teamId } }))
  const [give, setGive] = useState<Set<string>>(new Set())
  const [want, setWant] = useState<Want>('RB')
  const [count, setCount] = useState(1)
  const find = useMutation(findTradesMutation())

  if (manual) {
    return (
      <EmptyState title="Finding trade partners needs a league">
        Manual teams have no league rosters to search. Connect a Sleeper or ESPN league, or use the Analyzer for a
        hypothetical deal.
      </EmptyState>
    )
  }
  if (mine.isPending) return <ListSkeleton rows={2} height="h-40" />
  if (mine.isError) return <ErrorState error={mine.error} onRetry={() => void mine.refetch()} />

  const toggle = (id: string) => {
    const next = new Set(give)
    if (next.has(id)) next.delete(id)
    else if (next.size < 3) next.add(id)
    setGive(next)
    find.reset()
  }
  const valid = give.size >= 1 && give.size <= 3

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Find a trade</CardTitle>
          <CardDescription>
            Pick up to 3 of your players and what you want back. We search every team for deals that improve your
            lineup, the ones their lineup also likes first.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <PickList title={`You give (${give.size}/3)`} players={mine.data.roster} picked={give} onToggle={toggle} />
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">You want</span>
              <ToggleGroup
                type="single"
                variant="outline"
                value={want}
                onValueChange={(v) => {
                  if (v) setWant(v as Want)
                  find.reset()
                }}
                aria-label="Position you want"
              >
                {WANT.map((w) => (
                  <ToggleGroupItem key={w} value={w} className="px-3">
                    {w === 'ANY' ? 'Any' : w}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">Players back</span>
              <ToggleGroup
                type="single"
                variant="outline"
                value={String(count)}
                onValueChange={(v) => {
                  if (v) setCount(Number(v))
                  find.reset()
                }}
                aria-label="How many players back"
              >
                <ToggleGroupItem value="1" className="px-3">
                  1
                </ToggleGroupItem>
                <ToggleGroupItem value="2" className="px-3">
                  2
                </ToggleGroupItem>
              </ToggleGroup>
            </div>
            <Button
              className="self-start"
              disabled={!valid || find.isPending}
              onClick={() =>
                find.mutate({ body: { team_id: teamId, give: [...give], want_position: want, receive_count: count } })
              }
            >
              {find.isPending ? <Loader2 className="animate-spin" /> : <Search />}
              Find trades
            </Button>
            {!valid && <p className="text-xs text-muted-foreground">Pick 1 to 3 players to give.</p>}
          </div>
        </CardContent>
      </Card>
      {find.isError && <ErrorState error={find.error} />}
      {find.data && find.data.ideas.length === 0 && (
        <EmptyState title="No deal improves your lineup">
          Nobody in the league has a {want === 'ANY' ? 'player' : want} that makes your lineup better for those players.
          Try giving different players or asking for a different position.
        </EmptyState>
      )}
      {find.data && find.data.ideas.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Searched {find.data.searched_teams} teams. {find.data.ideas.filter((t) => t.partner_accepts).length} deal(s)
          help both lineups; the rest only help yours and are marked "Unlikely to accept".
        </p>
      )}
      {find.data?.ideas.map((t) => (
        <TradeCard key={t.headline + (t.partner?.team_id ?? '')} trade={t} onOpenInAnalyzer={onOpenInAnalyzer} />
      ))}
    </div>
  )
}

function Analyzer({ teamId, prefill }: { teamId: string; prefill?: AnalyzerPrefill | null }) {
  const mine = useQuery(getTeamOptions({ path: { team_id: teamId } }))
  const others = mine.data?.league_teams.filter((t) => !t.is_mine) ?? []
  const [partnerChoice, setPartnerChoice] = useState<string>(prefill?.partnerId ?? '')
  // Manual teams have no league partners, so they start in hypothetical mode.
  const partnerId = partnerChoice || (mine.data && others.length === 0 ? ANY : '')
  const hypothetical = partnerId === ANY
  const partner = useQuery({
    ...getTeamOptions({ path: { team_id: partnerId } }),
    enabled: !!partnerId && !hypothetical,
  })
  const [give, setGive] = useState<Set<string>>(new Set(prefill?.give ?? []))
  const [receive, setReceive] = useState<Set<string>>(new Set(prefill?.receive ?? []))
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
