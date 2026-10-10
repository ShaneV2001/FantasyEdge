import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Check, Loader2, Search, UserRound, X } from 'lucide-react'
import { useDeferredValue, useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import type { LeagueChoiceOut, ManualLeagueRequest, PlayerRef } from '@/api'
import {
  connectLeagueMutation,
  manualLeagueMutation,
  searchPlayersOptions,
  selectTeamMutation,
} from '@/api/@tanstack/react-query.gen'
import { ErrorState, PageHeader } from '@/components/common/states'
import { PositionBadge } from '@/components/player/badges'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { describeError } from '@/lib/errors'
import { slotLabel } from '@/lib/format'
import { useTeamStore } from '@/stores/team'

export function ConnectPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <PageHeader
        title="Connect your team"
        description="Pull your league from Sleeper, or enter a roster by hand for any platform. Nothing leaves your machine except calls to the public data sources."
      />
      <Tabs defaultValue="sleeper">
        <TabsList>
          <TabsTrigger value="sleeper">Sleeper</TabsTrigger>
          <TabsTrigger value="manual">Manual entry</TabsTrigger>
        </TabsList>
        <TabsContent value="sleeper" className="mt-4">
          <SleeperConnect />
        </TabsContent>
        <TabsContent value="manual" className="mt-4">
          <ManualEntry />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ───────── Sleeper ─────────

const usernameSchema = z.object({ username: z.string().trim().min(1, 'Enter your Sleeper username').max(64) })

function SleeperConnect() {
  const form = useForm<z.infer<typeof usernameSchema>>({
    resolver: zodResolver(usernameSchema),
    defaultValues: { username: '' },
  })
  const connect = useMutation(connectLeagueMutation())

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Sleeper username</CardTitle>
          <CardDescription>We look up your leagues for the current season via Sleeper's public API.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-2 sm:flex-row"
            onSubmit={form.handleSubmit((v) => connect.mutate({ body: { platform: 'sleeper', username: v.username } }))}
          >
            <div className="relative flex-1">
              <UserRound className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label="Sleeper username"
                placeholder="e.g. sleeperuser123"
                className="pl-8"
                autoComplete="off"
                {...form.register('username')}
              />
            </div>
            <Button type="submit" disabled={connect.isPending}>
              {connect.isPending && <Loader2 className="animate-spin" />}
              Find my leagues
            </Button>
          </form>
          {form.formState.errors.username && (
            <p className="mt-2 text-sm text-sell">{form.formState.errors.username.message}</p>
          )}
        </CardContent>
      </Card>

      {connect.isError && <ErrorState error={connect.error} />}
      {connect.data && connect.data.leagues.length === 0 && (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            No leagues found for <b>{connect.data.username}</b> this season. Check the username, or use manual entry.
          </CardContent>
        </Card>
      )}
      {connect.data?.leagues.map((lg) => (
        <LeagueCard key={lg.league_id} league={lg} username={connect.data.username} />
      ))}
    </div>
  )
}

function LeagueCard({ league, username }: { league: LeagueChoiceOut; username: string }) {
  const mine = league.teams.find((t) => t.is_user)
  const [rosterId, setRosterId] = useState(mine?.external_roster_id ?? league.teams[0]?.external_roster_id ?? '')
  const setTeam = useTeamStore((s) => s.setTeam)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const select = useMutation({
    ...selectTeamMutation(),
    onSuccess: (ref) => {
      const t = league.teams.find((x) => x.external_roster_id === rosterId)
      setTeam({
        teamId: ref.team_id,
        leagueId: ref.league_id,
        teamName: t?.team_name ?? 'My team',
        leagueName: league.name,
        platform: 'sleeper',
        username,
      })
      void qc.invalidateQueries()
      toast.success(`Connected ${t?.team_name ?? 'team'}`)
      void navigate({ to: '/advisor' })
    },
    onError: (e) => toast.error(describeError(e).message),
  })
  const starters = league.roster_positions.filter((p) => !['BN', 'IR', 'TAXI'].includes(p))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {league.name}
          <Badge variant="outline" className="font-mono">
            {league.season}
          </Badge>
        </CardTitle>
        <CardDescription>
          {league.num_teams} teams · {league.scoring} · {starters.map(slotLabel).join(' ')}
        </CardDescription>
      </CardHeader>
      <CardFooter className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Select value={rosterId} onValueChange={setRosterId}>
          <SelectTrigger className="w-full sm:w-72" aria-label="Your team">
            <SelectValue placeholder="Pick your team" />
          </SelectTrigger>
          <SelectContent>
            {league.teams.map((t) => (
              <SelectItem key={t.external_roster_id} value={t.external_roster_id}>
                {t.team_name} {t.is_user ? '(you)' : `· ${t.owner_name}`}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          disabled={!rosterId || select.isPending}
          onClick={() => select.mutate({ path: { league_id: league.league_id }, body: { external_roster_id: rosterId } })}
        >
          {select.isPending ? <Loader2 className="animate-spin" /> : <Check />}
          Use this team
        </Button>
      </CardFooter>
    </Card>
  )
}

// ───────── Manual ─────────

const ROSTER_PRESETS: Record<string, { label: string; slots: string[] }> = {
  standard: {
    label: '1QB · 2RB · 2WR · TE · FLEX · K · DEF',
    slots: ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DEF', ...Array(6).fill('BN')],
  },
  superflex: {
    label: 'Superflex · 2RB · 3WR · TE · FLEX',
    slots: ['QB', 'RB', 'RB', 'WR', 'WR', 'WR', 'TE', 'FLEX', 'SUPER_FLEX', ...Array(6).fill('BN')],
  },
  twoflex: {
    label: '1QB · 2RB · 2WR · TE · 2 FLEX (no K/DEF)',
    slots: ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'FLEX', ...Array(6).fill('BN')],
  },
}

function ManualEntry() {
  const [name, setName] = useState('My team')
  const [numTeams, setNumTeams] = useState('12')
  const [scoring, setScoring] = useState<'standard' | 'half_ppr' | 'ppr'>('half_ppr')
  const [preset, setPreset] = useState('standard')
  const [picked, setPicked] = useState<PlayerRef[]>([])
  const [q, setQ] = useState('')
  const deferredQ = useDeferredValue(q)
  const search = useQuery({ ...searchPlayersOptions({ query: { q: deferredQ, limit: 15 } }), placeholderData: (prev) => prev })
  const setTeam = useTeamStore((s) => s.setTeam)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const create = useMutation({
    ...manualLeagueMutation(),
    onSuccess: (ref) => {
      setTeam({ teamId: ref.team_id, leagueId: ref.league_id, teamName: name, leagueName: 'Manual league', platform: 'manual' })
      void qc.invalidateQueries()
      toast.success('Team created')
      void navigate({ to: '/advisor' })
    },
  })
  const pickedIds = new Set(picked.map((p) => p.player_id))

  function submit() {
    const body: ManualLeagueRequest = {
      name,
      num_teams: Number(numTeams),
      roster_positions: ROSTER_PRESETS[preset].slots,
      scoring,
      player_ids: picked.map((p) => p.player_id),
    }
    create.mutate({ body })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Build your roster</CardTitle>
        <CardDescription>
          Works for ESPN, Yahoo or anything else. Without league rosters we can't see free agents or other teams, so
          waiver and trade-partner advice is limited.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5 md:grid-cols-2">
        <div className="flex flex-col gap-4">
          <div className="grid gap-1.5">
            <Label htmlFor="team-name">Team name</Label>
            <Input id="team-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label>League size</Label>
              <Select value={numTeams} onValueChange={setNumTeams}>
                <SelectTrigger aria-label="League size">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[8, 10, 12, 14, 16].map((n) => (
                    <SelectItem key={n} value={String(n)}>
                      {n} teams
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label>Scoring</Label>
              <ToggleGroup
                type="single"
                variant="outline"
                value={scoring}
                onValueChange={(v) => v && setScoring(v as typeof scoring)}
              >
                <ToggleGroupItem value="standard">Std</ToggleGroupItem>
                <ToggleGroupItem value="half_ppr">½ PPR</ToggleGroupItem>
                <ToggleGroupItem value="ppr">PPR</ToggleGroupItem>
              </ToggleGroup>
            </div>
          </div>
          <div className="grid gap-1.5">
            <Label>Lineup</Label>
            <Select value={preset} onValueChange={setPreset}>
              <SelectTrigger aria-label="Lineup slots">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(ROSTER_PRESETS).map(([k, v]) => (
                  <SelectItem key={k} value={k}>
                    {v.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label>
              Your players <span className="text-muted-foreground">({picked.length})</span>
            </Label>
            {picked.length === 0 ? (
              <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                Search and add the players on your roster.
              </p>
            ) : (
              <ul className="flex flex-col divide-y rounded-md border">
                {picked.map((p) => (
                  <li key={p.player_id} className="flex items-center gap-2 px-2 py-1.5 text-sm">
                    <PositionBadge position={p.position} />
                    <span className="flex-1 truncate">{p.name}</span>
                    <span className="text-xs text-muted-foreground">{p.nfl_team}</span>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-6"
                      aria-label={`Remove ${p.name}`}
                      onClick={() => setPicked(picked.filter((x) => x.player_id !== p.player_id))}
                    >
                      <X />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <Command shouldFilter={false} className="h-[420px] rounded-lg border">
          <CommandInput placeholder="Search players…" value={q} onValueChange={setQ} />
          <CommandList className="max-h-none">
            <CommandEmpty>{search.isFetching ? 'Searching…' : 'No players found.'}</CommandEmpty>
            {search.isError && <div className="p-3 text-sm text-sell">{describeError(search.error).message}</div>}
            <CommandGroup heading={q ? 'Results' : 'Top players by market value'}>
              {(search.data ?? []).map((p) => (
                <CommandItem
                  key={p.player_id}
                  value={p.player_id}
                  disabled={pickedIds.has(p.player_id)}
                  onSelect={() => !pickedIds.has(p.player_id) && setPicked([...picked, p])}
                >
                  <PositionBadge position={p.position} />
                  <span className="flex-1">{p.name}</span>
                  <span className="text-xs text-muted-foreground">{p.nfl_team}</span>
                  {pickedIds.has(p.player_id) ? <Check className="text-buy" /> : <Search className="opacity-0" />}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </CardContent>
      <CardFooter className="flex flex-col items-stretch gap-3">
        {create.isError && <ErrorState error={create.error} />}
        <Button disabled={picked.length < 5 || create.isPending} onClick={submit} className="self-end">
          {create.isPending && <Loader2 className="animate-spin" />}
          Analyze my team
        </Button>
      </CardFooter>
    </Card>
  )
}
