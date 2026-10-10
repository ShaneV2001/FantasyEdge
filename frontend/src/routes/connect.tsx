import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Check, Loader2, UserRound } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import type { LeagueChoiceOut } from '@/api'
import { connectLeagueMutation, selectTeamMutation } from '@/api/@tanstack/react-query.gen'
import { ErrorState, PageHeader } from '@/components/common/states'
import { ManualRosterBuilder } from '@/components/team/ManualRosterBuilder'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
          <ManualRosterBuilder />
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
