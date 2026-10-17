import { useMutation, useQueryClient } from '@tanstack/react-query'
import { HeartPulse } from 'lucide-react'
import { toast } from 'sonner'

import type { PlayerDetailOut } from '@/api'
import { clearPlayerAvailabilityMutation, setPlayerAvailabilityMutation } from '@/api/@tanstack/react-query.gen'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { describeError } from '@/lib/errors'

export const SEASON_OUT = 99
const LAST_WEEK = 18

type Choice = 'report' | 'season' | 'week'

/** What we assume about his availability, in words. */
export function assumption(d: Pick<PlayerDetailOut, 'return_week' | 'availability_note'>): string {
  if (d.return_week != null && d.return_week >= SEASON_OUT) return 'Out for the season'
  if (d.return_week != null) return `Out until week ${d.return_week}`
  return d.availability_note ?? 'Healthy: plays every remaining game'
}

/**
 * The injury report for a player, what FantasyEdge assumes from it, and the user's own what-if
 * ("out for the season" / "back in week N"). The what-if only changes FantasyEdge's projections.
 */
export function AvailabilityControl({ d }: { d: PlayerDetailOut }) {
  const qc = useQueryClient()
  const thisWeek = d.upcoming[0]?.week ?? 1
  const weeks = Array.from({ length: Math.max(LAST_WEEK - thisWeek, 0) }, (_, i) => thisWeek + 1 + i)
  const choice: Choice = d.override_out_for_season ? 'season' : d.override_return_week != null ? 'week' : 'report'
  const done = () => {
    void qc.invalidateQueries()
    toast.success('Saved as your what-if', { description: 'Every page now uses it. ESPN and Sleeper are unchanged.' })
  }
  const onError = (err: unknown) => toast.error(describeError(err).message, { description: describeError(err).hint })
  const save = useMutation({ ...setPlayerAvailabilityMutation(), onSuccess: done, onError })
  const clear = useMutation({
    ...clearPlayerAvailabilityMutation(),
    onSuccess: () => {
      void qc.invalidateQueries()
      toast.success('Back to the injury report')
    },
    onError,
  })
  const path = { player_id: d.player_id }
  const busy = save.isPending || clear.isPending

  const pick = (v: string) => {
    if (v === 'report') clear.mutate({ path })
    else if (v === 'season') save.mutate({ path, body: { out_for_season: true } })
    else save.mutate({ path, body: { return_week: d.override_return_week ?? weeks[Math.min(3, weeks.length - 1)] } })
  }

  const report = [d.injury_status, d.injury_detail].filter(Boolean).join(' · ')
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-muted/30 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="flex items-center gap-1.5 font-medium">
          <HeartPulse className="size-4 text-muted-foreground" /> Availability
        </span>
        <span className="text-muted-foreground">
          Injury report: <span className="text-foreground">{report || 'none'}</span>
        </span>
        <span className="text-muted-foreground">
          We assume: <span className="text-foreground">{assumption(d)}</span>
          {d.availability_source === 'rule' && ' (season-ending injury in the report)'}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Select value={choice} onValueChange={pick} disabled={busy}>
          <SelectTrigger aria-label="Your what-if" className="w-52">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="report">Use the injury report</SelectItem>
            <SelectItem value="season">Out for the season</SelectItem>
            {weeks.length > 0 && <SelectItem value="week">Back in a later week</SelectItem>}
          </SelectContent>
        </Select>
        {choice === 'week' && (
          <Select
            value={String(d.override_return_week)}
            onValueChange={(v) => save.mutate({ path, body: { return_week: Number(v) } })}
            disabled={busy}
          >
            <SelectTrigger aria-label="Return week" className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {weeks.map((w) => (
                <SelectItem key={w} value={String(w)}>
                  Week {w}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <span className="text-xs text-muted-foreground">
          Your what-if: changes FantasyEdge&apos;s projections only, not ESPN/Sleeper.
        </span>
      </div>
    </div>
  )
}
