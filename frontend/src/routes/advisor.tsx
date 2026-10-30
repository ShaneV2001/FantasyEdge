import { useQuery } from '@tanstack/react-query'
import {
  ArrowLeftRight,
  CalendarClock,
  ChevronDown,
  Info,
  ListChecks,
  ShoppingCart,
  TrendingDown,
  TrendingUp,
  UserPlus,
} from 'lucide-react'
import { useState } from 'react'

import type { ActionOut } from '@/api'
import { getAdviceOptions } from '@/api/@tanstack/react-query.gen'
import { EmptyState, ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { PlayerChip } from '@/components/player/badges'
import { TeamGrades } from '@/components/team/TeamGrades'
import { TradeDetail } from '@/components/team/TradeCard'
import { PendingTradesBanner, RosterViewToggle, usePendingTrades } from '@/components/trade/PendingTrades'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { URGENCY_LABEL } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

const TYPE_META: Record<ActionOut['type'], { icon: typeof Info; cls: string }> = {
  Trade: { icon: ArrowLeftRight, cls: 'text-primary bg-primary/10' },
  Sell: { icon: TrendingDown, cls: 'text-sell bg-sell/10' },
  Buy: { icon: TrendingUp, cls: 'text-buy bg-buy/10' },
  Waiver: { icon: UserPlus, cls: 'text-pos-wr bg-pos-wr/10' },
  Lineup: { icon: ListChecks, cls: 'text-pos-rb bg-pos-rb/10' },
  'Bye prep': { icon: CalendarClock, cls: 'text-warn bg-warn/10' },
}

export function AdvisorPage() {
  const team = useTeamStore((s) => s.team)!
  const pending = usePendingTrades(team)
  const after = pending.view === 'after'
  // today's advice stays loaded in the After view: its grades show what the trades change
  const current = useQuery(getAdviceOptions({ path: { team_id: team.teamId } }))
  const afterAdvice = useQuery({ ...getAdviceOptions({ path: { team_id: team.teamId }, query: { roster: 'after' } }), enabled: after })
  const advice = after ? afterAdvice : current
  const n = advice.data?.pending_trades ?? 0

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Advisor"
        description={
          advice.data
            ? `${team.teamName} · Week ${advice.data.week}${n ? ` · after ${n} accepted trade${n > 1 ? 's' : ''}` : ''} · ${advice.data.actions.length} recommended moves, highest priority first`
            : team.teamName
        }
      />
      {pending.has && pending.data && (
        <PendingTradesBanner data={pending.data} action={<RosterViewToggle view={pending.view} onChange={pending.setView} />} />
      )}
      {advice.isPending && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-[76px] rounded-xl" />
            ))}
          </div>
          <ListSkeleton rows={5} height="h-28" />
        </>
      )}
      {advice.isError && <ErrorState error={advice.error} onRetry={() => void advice.refetch()} />}
      {advice.data && (
        <>
          <section className="flex flex-col gap-2">
            <h2 className="text-sm font-medium text-muted-foreground">
              {advice.data.view === 'after' ? 'Team grade after the accepted trades' : 'Team grade'}
            </h2>
            <TeamGrades
              grades={advice.data.grades}
              overall={advice.data.overall_grade}
              basis={advice.data.grade_basis}
              needs={advice.data.needs}
              compare={advice.data.view === 'after' ? current.data?.grades : undefined}
              compareOverall={advice.data.view === 'after' ? current.data?.overall_grade : undefined}
            />
          </section>
          {(advice.data.notes ?? []).map((n) => (
            <Alert key={n}>
              <Info />
              <AlertDescription>{n}</AlertDescription>
            </Alert>
          ))}
          <section className="flex flex-col gap-3">
            {advice.data.actions.length === 0 ? (
              <EmptyState title="Nothing urgent this week" icon={<ShoppingCart className="size-6" />}>
                Your lineup is set, no bye holes are coming, and no player shows a strong regression signal. Check
                back after the next refresh.
              </EmptyState>
            ) : (
              advice.data.actions.map((a, i) => <ActionCard key={`${a.type}-${a.headline}`} action={a} rank={i + 1} />)
            )}
          </section>
        </>
      )}
    </div>
  )
}

function ConfidenceMeter({ level }: { level: ActionOut['confidence'] }) {
  const n = level === 'high' ? 3 : level === 'medium' ? 2 : 1
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title={`${level} confidence`}>
      <span className="flex gap-0.5">
        {[1, 2, 3].map((i) => (
          <span key={i} className={cn('h-2.5 w-1 rounded-sm', i <= n ? 'bg-foreground/80' : 'bg-muted')} />
        ))}
      </span>
      {level}
    </span>
  )
}

export function ActionCard({ action, rank }: { action: ActionOut; rank: number }) {
  const [open, setOpen] = useState(false)
  const meta = TYPE_META[action.type]
  const Icon = meta.icon
  return (
    <Card className="gap-0 py-0">
      <CardContent className="flex gap-4 p-4">
        <div className="flex flex-col items-center gap-2">
          <span className={cn('grid size-9 place-items-center rounded-lg', meta.cls)}>
            <Icon className="size-4" />
          </span>
          <span className="font-mono text-xs text-muted-foreground">#{rank}</span>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">{action.type}</Badge>
            <Badge
              variant="outline"
              className={cn(action.urgency === 'this_week' && 'border-warn/50 text-warn')}
            >
              {URGENCY_LABEL[action.urgency]}
            </Badge>
            <ConfidenceMeter level={action.confidence} />
          </div>
          <h3 className="font-semibold leading-snug">{action.headline}</h3>
          <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
            {action.reasons.map((r) => (
              <li key={r} className="flex gap-2">
                <span className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground/60" />
                <span>{r}</span>
              </li>
            ))}
          </ul>
          {action.players.length > 0 && !action.trade && (
            <div className="flex flex-wrap gap-1.5">
              {action.players.map((p) => (
                <PlayerChip key={p.player_id} player={p} />
              ))}
            </div>
          )}
          {action.trade && (
            <div className="flex flex-col gap-2">
              <Button variant="ghost" size="sm" className="self-start px-0" onClick={() => setOpen(!open)}>
                <ChevronDown className={cn('transition-transform', open && 'rotate-180')} />
                {open ? 'Hide' : 'Show'} trade breakdown
              </Button>
              {open && <TradeDetail trade={action.trade} />}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
