import type { RosterPlayer } from '@/api'
import { InjuryTag, PlayerChip } from '@/components/player/badges'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'

/** "RB3": rank at his position by our rest-of-season projection. */
export function rosRankText(p: Pick<RosterPlayer, 'position' | 'model_rank'>) {
  return p.model_rank != null ? `${p.position}${p.model_rank}` : '—'
}

function Row({ p, slot, leaving }: { p: RosterPlayer; slot: string; leaving?: boolean }) {
  return (
    <li
      className={cn(
        'grid grid-cols-[3rem_minmax(0,1fr)_auto_auto] items-center gap-2 rounded-md px-2 py-1.5 text-sm',
        p.arriving && 'bg-buy/10 ring-1 ring-buy/30 ring-inset',
        leaving && 'opacity-60',
      )}
      data-testid={p.arriving ? 'lineup-arriving' : leaving ? 'lineup-leaving' : undefined}
    >
      <span className="font-mono text-[11px] font-semibold text-muted-foreground">{slot}</span>
      <span className="flex min-w-0 flex-wrap items-center gap-1.5">
        <PlayerChip player={p} className={cn(leaving && 'line-through')} />
        <InjuryTag status={p.injury_status} returnWeek={p.return_week} />
        {p.on_bye && <span className="font-mono text-[10px] text-muted-foreground uppercase">Bye</span>}
        {p.arriving && <span className="text-[11px] font-semibold text-buy">New</span>}
      </span>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="font-mono text-xs font-medium tabular-nums">{rosRankText(p)}</span>
        </TooltipTrigger>
        <TooltipContent>Rest-of-season rank at {p.position} (our projection)</TooltipContent>
      </Tooltip>
      <span className="w-12 text-right font-mono text-xs text-muted-foreground tabular-nums">{fmtNum(p.ppg)}</span>
    </li>
  )
}

/**
 * This week's best lineup slot by slot (QB, RB, RB … FLEX), then the bench, each player with his
 * rest-of-season position rank. With `was` (the roster before a trade), players who'd leave are
 * listed struck through under "Leaving"; arriving players are highlighted.
 */
export function LineupBySlot({ roster, was }: { roster: RosterPlayer[]; was?: RosterPlayer[] }) {
  const starters = roster.filter((p) => p.lineup_slot)
  const bench = roster.filter((p) => !p.lineup_slot)
  const ids = new Set(roster.map((p) => p.player_id))
  const leaving = (was ?? []).filter((p) => !ids.has(p.player_id))
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-[3rem_minmax(0,1fr)_auto_auto] gap-2 px-2 text-[11px] text-muted-foreground">
        <span>Slot</span>
        <span>Player</span>
        <span>ROS rank</span>
        <span className="w-12 text-right">Proj ppg</span>
      </div>
      <ul className="flex flex-col gap-0.5" aria-label="Starting lineup">
        {starters.map((p) => (
          <Row key={p.player_id} p={p} slot={p.lineup_slot!} />
        ))}
      </ul>
      {bench.length > 0 && (
        <>
          <h4 className="px-2 text-xs font-medium text-muted-foreground">Bench &amp; IR</h4>
          <ul className="flex flex-col gap-0.5" aria-label="Bench">
            {bench.map((p) => (
              <Row key={p.player_id} p={p} slot={p.slot === 'ir' ? 'IR' : p.slot === 'taxi' ? 'TAXI' : 'BN'} />
            ))}
          </ul>
        </>
      )}
      {leaving.length > 0 && (
        <>
          <h4 className="px-2 text-xs font-medium text-sell">Leaving</h4>
          <ul className="flex flex-col gap-0.5" aria-label="Leaving">
            {leaving.map((p) => (
              <Row key={p.player_id} p={p} slot="OUT" leaving />
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
