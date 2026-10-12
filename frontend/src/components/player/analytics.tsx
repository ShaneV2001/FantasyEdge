import { useState } from 'react'

import type { PlayerAnalyticsOut } from '@/api'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { fmtNum } from '@/lib/format'
import { cn } from '@/lib/utils'

type Kind = 'pct' | 'dec1' | 'dec2'

const METRIC: Record<string, { label: string; kind: Kind; help: string }> = {
  snap_pct: { label: 'Snap %', kind: 'pct', help: "Share of the offense's snaps he was on the field for, averaged per game." },
  rush_share: { label: 'Rush share', kind: 'pct', help: "His carries as a share of his team's carries in the same games." },
  target_share: { label: 'Target share', kind: 'pct', help: "His targets as a share of his team's targets in the same games." },
  air_yards_share: {
    label: 'Air-yards share',
    kind: 'pct',
    help: "His share of the team's air yards: how far throws to him travel past the line of scrimmage.",
  },
  wopr: {
    label: 'WOPR',
    kind: 'dec2',
    help: 'Weighted opportunity rating: 1.5 × target share + 0.7 × air-yards share. About 0.7 or more is a lead receiver role.',
  },
  cmp_pct: { label: 'Completion %', kind: 'pct', help: 'Completions per pass attempt.' },
  yds_per_att: { label: 'Yards / attempt', kind: 'dec1', help: 'Passing yards per pass attempt.' },
  adot: { label: 'aDOT', kind: 'dec1', help: 'Average depth of target: air yards per target (per pass attempt for a QB).' },
  catch_rate: { label: 'Catch rate', kind: 'pct', help: 'Receptions per target.' },
  yds_per_target: { label: 'Yards / target', kind: 'dec1', help: 'Receiving yards per target.' },
  yds_per_carry: { label: 'Yards / carry', kind: 'dec1', help: 'Rushing yards per carry.' },
  epa_per_play: {
    label: 'EPA / play',
    kind: 'dec2',
    help: 'Expected points added per pass, sack, carry or target. Above 0 means his plays moved the offense more than an average play.',
  },
  yac_per_game: { label: 'YAC / game', kind: 'dec1', help: 'Yards gained after the catch per game (for a QB, on his completions).' },
  yac_pct: { label: 'YAC share of yards', kind: 'pct', help: 'Share of his passing yards that came after the catch.' },
  yac_per_rec: { label: 'YAC / reception', kind: 'dec1', help: 'Yards gained after the catch per reception.' },
  rz_carries: { label: 'RZ carries / game', kind: 'dec1', help: "Carries inside the opponent's 20, per game." },
  rz_targets: { label: 'RZ targets / game', kind: 'dec1', help: "Targets inside the opponent's 20, per game." },
  gl_carries: { label: 'Goal-line carries / game', kind: 'dec1', help: "Carries inside the opponent's 5, per game." },
  rz_td: { label: 'RZ TDs / game', kind: 'dec2', help: 'Touchdowns scored on red-zone carries and targets, per game.' },
}

function fmt(kind: Kind, v: number | null | undefined) {
  if (v == null) return '—'
  if (kind === 'pct') return `${Math.round(v * 100)}%`
  return fmtNum(v, kind === 'dec2' ? 2 : 1)
}

/** ▲/▼ when the window is at least 10% away from the season value. */
function trend(v: number | null | undefined, s: number | null | undefined): 'up' | 'down' | null {
  if (v == null || s == null || s === 0) return null
  const d = (v - s) / Math.abs(s)
  return d >= 0.1 ? 'up' : d <= -0.1 ? 'down' : null
}

function Tile({ k, v, season }: { k: string; v: number | null | undefined; season?: number | null }) {
  const meta = METRIC[k] ?? { label: k, kind: 'dec1' as Kind, help: '' }
  const t = season === undefined ? null : trend(v, season)
  return (
    <div className="rounded-md border p-3">
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="w-fit cursor-help text-xs text-muted-foreground underline decoration-dotted underline-offset-2">
            {meta.label}
          </div>
        </TooltipTrigger>
        <TooltipContent className="max-w-64">{meta.help}</TooltipContent>
      </Tooltip>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="font-mono text-lg tabular-nums">{fmt(meta.kind, v)}</span>
        {t && (
          <span
            aria-label={t === 'up' ? 'up vs season' : 'down vs season'}
            className={cn('text-xs', t === 'up' ? 'text-emerald-500' : 'text-rose-500')}
          >
            {t === 'up' ? '▲' : '▼'}
          </span>
        )}
      </div>
      {season !== undefined && <div className="text-xs text-muted-foreground">Season {fmt(meta.kind, season)}</div>}
    </div>
  )
}

export function Analytics({ a }: { a: PlayerAnalyticsOut }) {
  const [label, setLabel] = useState(a.windows[0]?.label)
  const win = a.windows.find((w) => w.label === label) ?? a.windows[0]
  const season = a.windows[a.windows.length - 1]
  const compare = win.label !== 'Season'
  return (
    <div className="flex flex-col gap-4">
      <ToggleGroup
        type="single"
        variant="outline"
        aria-label="Games window"
        value={win.label}
        onValueChange={(v) => v && setLabel(v as typeof win.label)}
        className="self-start"
      >
        {a.windows.map((w) => (
          <ToggleGroupItem key={w.label} value={w.label}>
            {w.label === 'Season' ? `Season (${w.games} g)` : `Last ${w.games}`}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      {a.groups.map((g) => (
        <section key={g.key}>
          <h3 className="mb-2 text-sm font-medium">{g.label}</h3>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {g.metrics.map((k) => (
              <Tile key={k} k={k} v={win.metrics[k]} season={compare ? season.metrics[k] : undefined} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}
