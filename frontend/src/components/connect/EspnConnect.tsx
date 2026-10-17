import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, KeyRound, Loader2, LockKeyhole, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import type { CredentialsOut, EspnConnectResponse } from '@/api'
import {
  connectEspnMutation,
  espnDefaultsOptions,
  getCredentialsOptions,
  getCredentialsQueryKey,
  putCredentialsMutation,
} from '@/api/@tanstack/react-query.gen'
import { ErrorState } from '@/components/common/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { describeError } from '@/lib/errors'
import { useTeamStore } from '@/stores/team'

import { LeagueCard } from './LeagueCard'

const espnSchema = z
  .object({
    leagueId: z.string().trim().regex(/^\d+$/, 'The league ID is the number after leagueId= in your league URL'),
    season: z.coerce.number().int().min(2018).max(2100),
    espnS2: z.string().trim(),
    swid: z.string().trim(),
  })
  .refine((v) => !v.espnS2 === !v.swid, { message: 'Private leagues need both cookies (espn_s2 and SWID)', path: ['swid'] })

type EspnForm = z.input<typeof espnSchema>

export function EspnConnect() {
  const defaults = useQuery(espnDefaultsOptions())
  const team = useTeamStore((s) => s.team)
  const connect = useMutation({
    ...connectEspnMutation(),
    onError: (e) => toast.error(describeError(e).message),
  })

  return (
    <div className="flex flex-col gap-4">
      {team?.platform === 'espn' && <SavedLogin leagueId={team.leagueId} />}
      <Card>
        <CardHeader>
          <CardTitle>ESPN league</CardTitle>
          <CardDescription>
            Read-only: FantasyEdge pulls your league from ESPN and never changes anything there. Private leagues need two
            login cookies from your browser; they're stored only in the database on this computer.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {defaults.isPending ? (
            <div className="h-40 animate-pulse rounded-lg bg-muted" aria-busy="true" aria-label="Loading" />
          ) : (
            <EspnForm
              key={defaults.data?.league_id ?? 'none'}
              leagueId={defaults.data?.league_id ?? ''}
              season={defaults.data?.season ?? new Date().getFullYear()}
              cookiesInEnv={!!defaults.data?.cookies_in_env}
              pending={connect.isPending}
              onSubmit={(v) =>
                connect.mutate({
                  body: { league_id: v.leagueId, season: v.season, espn_s2: v.espnS2 || null, swid: v.swid || null },
                })
              }
            />
          )}
          <CookieHelp />
        </CardContent>
      </Card>

      {connect.isError && <ErrorState error={connect.error} />}
      {connect.data && <ConnectResult data={connect.data} />}
    </div>
  )
}

function EspnForm({
  leagueId,
  season,
  cookiesInEnv,
  pending,
  onSubmit,
}: {
  leagueId: string
  season: number
  cookiesInEnv: boolean
  pending: boolean
  onSubmit: (v: z.output<typeof espnSchema>) => void
}) {
  const form = useForm<EspnForm, unknown, z.output<typeof espnSchema>>({
    resolver: zodResolver(espnSchema),
    defaultValues: { leagueId, season, espnS2: '', swid: '' },
  })
  const err = form.formState.errors
  return (
    <form className="grid gap-3 sm:grid-cols-2" onSubmit={form.handleSubmit(onSubmit)}>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="espn-league">League ID</Label>
        <Input id="espn-league" inputMode="numeric" placeholder="e.g. 12345678" autoComplete="off" {...form.register('leagueId')} />
        {err.leagueId && <p className="text-sm text-sell">{err.leagueId.message}</p>}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="espn-season">Season</Label>
        <Input id="espn-season" type="number" inputMode="numeric" {...form.register('season')} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="espn-s2">espn_s2 cookie</Label>
        <Input
          id="espn-s2"
          type="password"
          autoComplete="off"
          placeholder={cookiesInEnv ? 'Using the one in your .env' : 'Private leagues only'}
          {...form.register('espnS2')}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="espn-swid">SWID cookie</Label>
        <Input
          id="espn-swid"
          type="password"
          autoComplete="off"
          placeholder={cookiesInEnv ? 'Using the one in your .env' : '{XXXXXXXX-XXXX-…} with the braces'}
          {...form.register('swid')}
        />
        {err.swid && <p className="text-sm text-sell">{err.swid.message}</p>}
      </div>
      <div className="flex flex-col gap-2 sm:col-span-2 sm:flex-row sm:items-center">
        <Button type="submit" disabled={pending}>
          {pending ? <Loader2 className="animate-spin" /> : <LockKeyhole />}
          Connect ESPN league
        </Button>
        <span className="text-xs text-muted-foreground">
          {cookiesInEnv
            ? 'Cookies were found in your local .env file; leave the cookie fields empty to use them.'
            : 'Public leagues only need the league ID and season.'}
        </span>
      </div>
    </form>
  )
}

export function CookieHelp() {
  return (
    <details id="espn-help" className="group rounded-lg border bg-muted/30 px-3 py-2 text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium">
        <ChevronRight className="size-4 transition-transform group-open:rotate-90" />
        How do I find these?
      </summary>
      <div className="mt-2 flex flex-col gap-3 pb-1 text-muted-foreground">
        <ol className="flex list-decimal flex-col gap-1 pl-5">
          <li>On a computer, log in at fantasy.espn.com and open your league.</li>
          <li>
            <b>League ID</b>: the number after <code>leagueId=</code> in the address bar.
          </li>
          <li>
            Open the browser's developer tools (<kbd>F12</kbd>).
          </li>
          <li>
            <b>Chrome / Edge</b>: <i>Application</i> tab → <i>Cookies</i> → <code>https://fantasy.espn.com</code>.{' '}
            <b>Firefox</b>: <i>Storage</i> tab → <i>Cookies</i> → <code>https://fantasy.espn.com</code>.
          </li>
          <li>
            Copy the values of <code>espn_s2</code> and <code>SWID</code> (keep SWID's curly braces).
          </li>
        </ol>
        <p>
          The cookies stay on this computer (in the local database) and are only ever sent to ESPN. After saving, the
          app shows just their last 4 characters. ESPN logins expire every few months — when that happens you'll see
          "Your ESPN login has expired"; paste fresh cookies with <b>Replace cookies</b>.
        </p>
      </div>
    </details>
  )
}

function ConnectResult({ data }: { data: EspnConnectResponse }) {
  return (
    <>
      {data.unmatched.length > 0 && (
        <Card className="border-amber-500/40">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <TriangleAlert className="size-4 text-amber-500" />
              {data.unmatched.length} player{data.unmatched.length === 1 ? '' : 's'} not matched
            </CardTitle>
            <CardDescription>
              These ESPN players aren't in our player data yet (often rookies or recent signings). They stay on the
              roster with no projection; running a data update usually fixes it.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm">
            {data.unmatched.map((p) => `${p.name} (${p.position ?? '?'}, ${p.nfl_team ?? 'FA'})`).join(' · ')}
          </CardContent>
        </Card>
      )}
      {data.scoring_notes.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Scoring rules in this league we can't model yet (scored as 0): {data.scoring_notes.join(', ')}.
        </p>
      )}
      <LeagueCard league={data.league} platform="espn" />
    </>
  )
}

function SavedLogin({ leagueId }: { leagueId: string }) {
  const creds = useQuery(getCredentialsOptions({ path: { league_id: leagueId } }))
  if (!creds.data) return null
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3 text-sm">
          <KeyRound className="size-4 text-muted-foreground" />
          <MaskedCookies creds={creds.data} />
        </div>
        <ReplaceCookies leagueId={leagueId} />
      </CardContent>
    </Card>
  )
}

function MaskedCookies({ creds }: { creds: CredentialsOut }) {
  if (!creds.saved) return <span className="text-muted-foreground">No ESPN login saved for this league (public league).</span>
  return (
    <span>
      Saved ESPN login · espn_s2 <code>••••{creds.espn_s2_last4}</code> · SWID <code>••••{creds.swid_last4}</code>
    </span>
  )
}

function ReplaceCookies({ leagueId }: { leagueId: string }) {
  const [open, setOpen] = useState(false)
  const [s2, setS2] = useState('')
  const [swid, setSwid] = useState('')
  const qc = useQueryClient()
  const replace = useMutation({
    ...putCredentialsMutation(),
    onSuccess: () => {
      toast.success('ESPN login updated')
      setOpen(false)
      setS2('')
      setSwid('')
      void qc.invalidateQueries({ queryKey: getCredentialsQueryKey({ path: { league_id: leagueId } }) })
      void qc.invalidateQueries()
    },
  })
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Replace cookies
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Replace ESPN cookies</DialogTitle>
          <DialogDescription>
            Paste fresh <code>espn_s2</code> and <code>SWID</code> values. They're checked with ESPN before being saved.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            replace.mutate({ path: { league_id: leagueId }, body: { espn_s2: s2.trim(), swid: swid.trim() } })
          }}
        >
          <Label htmlFor="replace-s2">espn_s2</Label>
          <Input id="replace-s2" type="password" autoComplete="off" value={s2} onChange={(e) => setS2(e.target.value)} />
          <Label htmlFor="replace-swid">SWID</Label>
          <Input id="replace-swid" type="password" autoComplete="off" value={swid} onChange={(e) => setSwid(e.target.value)} />
          {replace.isError && <p className="text-sm text-sell">{describeError(replace.error).message}</p>}
          <CookieHelp />
          <DialogFooter>
            <Button type="submit" disabled={replace.isPending || !s2.trim() || !swid.trim()}>
              {replace.isPending && <Loader2 className="animate-spin" />}
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
