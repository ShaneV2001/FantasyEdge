import type { PlayerFlagsOut } from '@/api'
import { PositionBadge, SignalBadge } from '@/components/player/badges'
import { PlayerLink } from '@/components/player/PlayerLink'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'

const KIND_LABEL: Record<string, string> = {
  td_over_expected: 'TD over expected',
  efficiency: 'Efficiency',
  usage_mismatch: 'Usage vs production',
}

export function RegressionList({ rows, showOwner = false }: { rows: PlayerFlagsOut[]; showOwner?: boolean }) {
  const flagged = rows.filter((r) => r.flags.length > 0)
  if (flagged.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">No regression flags right now.</p>
  }
  return (
    <ul className="flex flex-col divide-y">
      {flagged.map((r) => (
        <li key={r.player.player_id} className="flex flex-col gap-2 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <PositionBadge position={r.player.position} />
            <PlayerLink playerId={r.player.player_id} className="font-medium">
              {r.player.name}
            </PlayerLink>
            <span className="text-xs text-muted-foreground">{r.player.nfl_team}</span>
            {showOwner && (
              <span className="text-xs text-muted-foreground">· {r.team_name ?? 'Free agent'}</span>
            )}
            <span className="ml-auto flex items-center gap-2">
              {r.tdoe != null && (
                <span
                  className={cn('font-mono text-xs', r.tdoe >= 2 ? 'text-sell' : r.tdoe <= -2 ? 'text-buy' : 'text-muted-foreground')}
                  title="Actual TDs minus expected TDs"
                >
                  TDOE {r.tdoe > 0 ? '+' : ''}
                  {fmtNum(r.tdoe)}
                </span>
              )}
              <SignalBadge signal={r.signal} showHold />
            </span>
          </div>
          <ul className="flex flex-col gap-1 pl-1">
            {r.flags.map((f) => (
              <li key={`${f.kind}-${f.metric}`} className="flex gap-2 text-sm">
                <span
                  className={cn(
                    'mt-0.5 h-fit shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
                    f.direction > 0 ? 'bg-buy/10 text-buy' : 'bg-sell/10 text-sell',
                  )}
                >
                  {KIND_LABEL[f.kind] ?? f.kind}
                </span>
                <span className="text-muted-foreground">{f.message}</span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}
