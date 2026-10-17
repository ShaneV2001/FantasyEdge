import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { Loader2, UserRound } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { connectLeagueMutation } from '@/api/@tanstack/react-query.gen'
import { ErrorState, PageHeader } from '@/components/common/states'
import { EspnConnect } from '@/components/connect/EspnConnect'
import { LeagueCard } from '@/components/connect/LeagueCard'
import { ManualRosterBuilder } from '@/components/team/ManualRosterBuilder'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

const TABS = ['sleeper', 'espn', 'manual'] as const
type Tab = (typeof TABS)[number]

export function ConnectPage() {
  const search = useSearch({ strict: false }) as { tab?: string }
  const navigate = useNavigate()
  const tab: Tab = TABS.includes(search.tab as Tab) ? (search.tab as Tab) : 'sleeper'
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <PageHeader
        title="Connect your team"
        description="Pull your league from Sleeper or ESPN, or enter a roster by hand for any platform. Data only flows in: FantasyEdge never changes anything on Sleeper or ESPN."
      />
      <Tabs value={tab} onValueChange={(t) => void navigate({ to: '/connect', search: { tab: t }, replace: true })}>
        <TabsList>
          <TabsTrigger value="sleeper">Sleeper</TabsTrigger>
          <TabsTrigger value="espn">ESPN</TabsTrigger>
          <TabsTrigger value="manual">Manual entry</TabsTrigger>
        </TabsList>
        <TabsContent value="sleeper" className="mt-4">
          <SleeperConnect />
        </TabsContent>
        <TabsContent value="espn" className="mt-4">
          <EspnConnect />
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
        <LeagueCard key={lg.league_id} league={lg} platform="sleeper" username={connect.data.username} />
      ))}
    </div>
  )
}
