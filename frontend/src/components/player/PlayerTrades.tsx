import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { ArrowLeftRight, Loader2 } from 'lucide-react'
import { useState } from 'react'

import type { PlayerDetailOut, TradeOut } from '@/api'
import { getPlayerTradesOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton } from '@/components/common/states'
import { TradeCard } from '@/components/team/TradeCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

const WANT = ['ANY', 'RB', 'WR', 'TE', 'QB'] as const
type Want = (typeof WANT)[number]

/** Search params that open a deal pre-filled in the Trade page's analyzer. */
export function analyzerSearch(t: TradeOut) {
  return {
    tab: 'analyzer',
    partner: t.partner?.team_id ?? '',
    give: t.me.gives.map((p) => p.player_id).join(','),
    receive: t.me.receives.map((p) => p.player_id).join(','),
  }
}

/** "Shop him" (he's yours) or "Trade for him" (he's on another team), generated on demand. */
export function PlayerTrades({ d, teamId, manual }: { d: PlayerDetailOut; teamId: string; manual: boolean }) {
  const [requested, setRequested] = useState(false)
  const [want, setWant] = useState<Want>('ANY')
  const navigate = useNavigate()
  const q = useQuery({
    ...getPlayerTradesOptions({ path: { team_id: teamId, player_id: d.player_id }, query: { want } }),
    enabled: requested,
    staleTime: 5 * 60_000,
  })
  const tradeable = ['QB', 'RB', 'WR', 'TE'].includes(d.position)
  const title = d.mine ? `Shop ${d.name}` : d.owner ? `Trade for ${d.name}` : 'Trades'
  const description = d.mine
    ? 'Deals that give him away for 1 or 2 players from any team, fair by market value and judged on both starting lineups.'
    : d.owner
      ? `What it would take to get him from ${d.owner}: packages of up to 3 of your players, fair by market value.`
      : null

  let body
  if (manual) {
    body = <p className="text-sm text-muted-foreground">Trades need a synced Sleeper or ESPN league. Use the Trade page's analyzer for a hypothetical deal.</p>
  } else if (!d.owner) {
    body = <p className="text-sm text-muted-foreground">{d.name} is a free agent: add him off waivers instead of trading for him.</p>
  } else if (!tradeable) {
    body = <p className="text-sm text-muted-foreground">Trade ideas cover QBs, RBs, WRs and TEs.</p>
  } else {
    body = (
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          {d.mine ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">I want</span>
              <ToggleGroup
                type="single"
                variant="outline"
                value={want}
                onValueChange={(v) => v && setWant(v as Want)}
                aria-label="Position you want back"
              >
                {WANT.map((w) => (
                  <ToggleGroupItem key={w} value={w} className="px-3">
                    {w === 'ANY' ? 'Any' : w}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
          ) : (
            <span />
          )}
          <Button onClick={() => (requested ? void q.refetch() : setRequested(true))} disabled={q.isFetching}>
            {q.isFetching ? <Loader2 className="animate-spin" /> : <ArrowLeftRight />}
            {requested ? 'Regenerate' : 'Generate trades'}
          </Button>
        </div>
        {requested && q.isPending && <ListSkeleton rows={2} height="h-48" />}
        {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
        {q.data?.message && <p className="text-sm text-muted-foreground">{q.data.message}</p>}
        {q.data && q.data.ideas.length === 0 && !q.data.message && (
          <EmptyState title="No deal improves your lineup">
            {d.mine
              ? 'Nobody has a player that makes your lineup better for him right now. Try another position.'
              : 'None of your packages for him leaves your lineup better off.'}
          </EmptyState>
        )}
        {q.data && q.data.ideas.length > 0 && (
          <p className="text-sm text-muted-foreground">
            Every offer is fair by market value; {q.data.ideas.filter((t) => t.partner_accepts).length} of{' '}
            {q.data.ideas.length} also improve their lineup. Most even first.
          </p>
        )}
        {q.data?.ideas.map((t) => (
          <TradeCard
            key={t.headline + (t.partner?.team_id ?? '')}
            trade={t}
            onOpenInAnalyzer={(tr) => void navigate({ to: '/trade', search: analyzerSearch(tr) })}
          />
        ))}
      </div>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ArrowLeftRight className="size-4" /> {title}
        </CardTitle>
        {description && tradeable && !manual && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{body}</CardContent>
    </Card>
  )
}
