import { useQuery } from '@tanstack/react-query'
import { useSearch } from '@tanstack/react-router'
import { Clock } from 'lucide-react'
import { type ReactNode, useState } from 'react'

import type { PendingTradesOut, PlayerRef } from '@/api'
import { getPendingTradesOptions } from '@/api/@tanstack/react-query.gen'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { apiDate } from '@/lib/format'
import type { ConnectedTeam } from '@/stores/team'

export type RosterView = 'now' | 'after'

/** Accepted trades still waiting on ESPN (only ESPN reports them) and which roster the page shows:
 * today's, or the one after they go through (`?view=after` opens on it). */
export function usePendingTrades(team: ConnectedTeam) {
  const pending = useQuery({ ...getPendingTradesOptions({ path: { team_id: team.teamId } }), enabled: team.platform === 'espn' })
  const search = useSearch({ strict: false }) as Record<string, unknown>
  const [chosen, setView] = useState<RosterView>(search.view === 'after' ? 'after' : 'now')
  const has = (pending.data?.trades.length ?? 0) > 0
  const view: RosterView = has ? chosen : 'now'
  return { data: pending.data, has, view, setView }
}

/** Current roster | After accepted trades. */
export function RosterViewToggle({ view, onChange }: { view: RosterView; onChange: (v: RosterView) => void }) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      size="sm"
      className="mt-1 self-start"
      value={view}
      onValueChange={(v) => v && onChange(v as RosterView)}
      aria-label="Roster to plan for"
    >
      <ToggleGroupItem value="now" className="px-2 text-xs">
        Current roster
      </ToggleGroupItem>
      <ToggleGroupItem value="after" className="px-2 text-xs">
        After accepted trades
      </ToggleGroupItem>
    </ToggleGroup>
  )
}

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
