import { Clock } from 'lucide-react'
import type { ReactNode } from 'react'

import type { PendingTradesOut, PlayerRef } from '@/api'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { apiDate } from '@/lib/format'

const names = (ps: PlayerRef[]) => ps.map((p) => p.name).join(', ')

function day(iso: string | null | undefined) {
  return iso ? apiDate(iso).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) : null
}

/** "2 accepted trades waiting on ESPN": what each one sends and brings back. */
export function PendingTradesBanner({ data, action }: { data: PendingTradesOut; action?: ReactNode }) {
  const n = data.trades.length
  if (n === 0) return null
  return (
    <Alert className="border-warn/40" data-testid="pending-trades">
      <Clock className="text-warn" />
      <AlertTitle>
        {n} accepted trade{n > 1 ? 's' : ''} waiting on ESPN
      </AlertTitle>
      <AlertDescription className="flex flex-col gap-1.5">
        <ul className="flex flex-col gap-1">
          {data.trades.map((t) => (
            <li key={t.id}>
              <span className="text-foreground">
                Give {names(t.give) || 'nobody'} → get {names(t.receive) || 'nobody'}
              </span>
              {t.partner_name && ` with ${t.partner_name}`}
              {(t.drops ?? []).length > 0 && `, dropping ${names(t.drops)}`}
              {day(t.accepted_at) && ` · accepted ${day(t.accepted_at)}`}
            </li>
          ))}
        </ul>
        <span>
          Your roster changes once ESPN processes {n > 1 ? 'them' : 'it'}
          {data.review_hours ? ` (this league reviews trades for ${data.review_hours} hours)` : ''}.
        </span>
        {action}
      </AlertDescription>
    </Alert>
  )
}
