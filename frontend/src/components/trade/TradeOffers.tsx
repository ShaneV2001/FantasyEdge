import { useQuery } from '@tanstack/react-query'
import { Inbox, Send } from 'lucide-react'

import type { TradeOfferOut, TradeOut } from '@/api'
import { getTradeOffersOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton } from '@/components/common/states'
import { TradeCard } from '@/components/team/TradeCard'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { apiDate } from '@/lib/format'
import type { ConnectedTeam } from '@/stores/team'

/** Open ESPN trade offers (only ESPN reports them): `received` waits on your answer. */
export function useTradeOffers(team: ConnectedTeam | null) {
  return useQuery({
    ...getTradeOffersOptions({ path: { team_id: team?.teamId ?? '' } }),
    enabled: team?.platform === 'espn',
    staleTime: 5 * 60_000,
  })
}

function when(iso: string | null | undefined) {
  return iso ? apiDate(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) : null
}

function Offer({ offer, onOpenInAnalyzer }: { offer: TradeOfferOut; onOpenInAnalyzer: (t: TradeOut) => void }) {
  const sent = offer.direction === 'sent'
  const Icon = sent ? Send : Inbox
  return (
    <div className="flex flex-col gap-2" data-testid="trade-offer">
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon className="size-4" />
        {sent ? 'You offered' : 'Offer from'} <span className="font-medium text-foreground">{offer.partner_name ?? 'another team'}</span>
        {when(offer.proposed_at) && ` · ${when(offer.proposed_at)}`}
      </p>
      {offer.evaluation ? (
        <TradeCard trade={offer.evaluation} onOpenInAnalyzer={onOpenInAnalyzer} />
      ) : (
        <Alert>
          <AlertDescription>
            Give {offer.give.map((p) => p.name).join(', ') || 'nobody'} → get{' '}
            {offer.receive.map((p) => p.name).join(', ') || 'nobody'}. {offer.note}
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}

/** The Offers tab: offers waiting on you first, then the ones you sent. */
export function TradeOffers({ team, onOpenInAnalyzer }: { team: ConnectedTeam; onOpenInAnalyzer: (t: TradeOut) => void }) {
  const offers = useTradeOffers(team)
  if (team.platform !== 'espn') {
    return (
      <EmptyState title="Offers need an ESPN league">
        Sleeper doesn't share open trade offers through its API. Paste an offer into the Analyzer to grade it.
      </EmptyState>
    )
  }
  if (offers.isPending) return <ListSkeleton rows={2} height="h-48" />
  if (offers.isError) return <ErrorState error={offers.error} onRetry={() => void offers.refetch()} />
  const { received, sent } = offers.data
  if (received.length + sent.length === 0) {
    return (
      <EmptyState title="No open offers" icon={<Inbox className="size-6" />}>
        When another team sends you a trade on ESPN, it shows up here graded by the analyzer. Use Update in the sidebar to
        check for new ones.
      </EmptyState>
    )
  }
  return (
    <div className="flex flex-col gap-6">
      {received.length > 0 && (
        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-medium text-muted-foreground">Waiting on your answer ({received.length})</h2>
          {received.map((o) => (
            <Offer key={o.id} offer={o} onOpenInAnalyzer={onOpenInAnalyzer} />
          ))}
        </section>
      )}
      {sent.length > 0 && (
        <section className="flex flex-col gap-4">
          <h2 className="text-sm font-medium text-muted-foreground">You sent ({sent.length})</h2>
          {sent.map((o) => (
            <Offer key={o.id} offer={o} onOpenInAnalyzer={onOpenInAnalyzer} />
          ))}
        </section>
      )}
    </div>
  )
}
