import { TrendingDown, TrendingUp } from 'lucide-react'

import type { PlayerRef } from '@/api'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { POSITION_CLASS, type Signal, signalFor } from '@/lib/format'
import { cn } from '@/lib/utils'

export function PositionBadge({ position, className }: { position: string; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex h-5 min-w-9 items-center justify-center rounded-md px-1.5 font-mono text-[11px] font-semibold ring-1 ring-inset',
        POSITION_CLASS[position] ?? 'bg-muted text-muted-foreground ring-border',
        className,
      )}
    >
      {position}
    </span>
  )
}

const SIGNAL_STYLE: Record<Signal, string> = {
  buy: 'bg-buy/15 text-buy ring-buy/30',
  sell: 'bg-sell/15 text-sell ring-sell/30',
  hold: 'bg-muted text-muted-foreground ring-border',
}

export function SignalBadge({ score, showHold = false }: { score: number | null | undefined; showHold?: boolean }) {
  const signal = signalFor(score)
  if (signal === 'hold' && !showHold) return null
  const Icon = signal === 'buy' ? TrendingUp : signal === 'sell' ? TrendingDown : null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'inline-flex h-5 items-center gap-1 rounded-md px-1.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset',
            SIGNAL_STYLE[signal],
          )}
        >
          {Icon && <Icon className="size-3" />}
          {signal}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        Regression score {score?.toFixed(2) ?? '0'} ({signal === 'buy' ? 'production should improve' : signal === 'sell' ? 'production likely to cool off' : 'no strong signal'})
      </TooltipContent>
    </Tooltip>
  )
}

export function PlayerChip({ player, className }: { player: PlayerRef; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-md bg-muted/60 py-0.5 pr-2 pl-0.5 text-xs', className)}>
      <PositionBadge position={player.position} className="h-4 min-w-7 text-[10px]" />
      <span className="font-medium">{player.name}</span>
      {player.nfl_team && <span className="text-muted-foreground">{player.nfl_team}</span>}
    </span>
  )
}

export function InjuryTag({ status }: { status?: string | null }) {
  if (!status) return null
  const severe = ['Out', 'IR', 'PUP', 'Sus', 'NFI', 'Doubtful'].includes(status)
  return (
    <span
      className={cn(
        'rounded px-1 font-mono text-[10px] font-semibold uppercase',
        severe ? 'bg-sell/15 text-sell' : 'bg-warn/15 text-warn',
      )}
      title={status}
    >
      {status === 'Questionable' ? 'Q' : status === 'Doubtful' ? 'D' : status}
    </span>
  )
}
