import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CloudDownload, Loader2, TriangleAlert } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

import type { StatusOut } from '@/api'
import { getStatusOptions, refreshMutation } from '@/api/@tanstack/react-query.gen'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { describeError } from '@/lib/errors'
import { fmtRelative } from '@/lib/format'

/** App status, polled faster while the API refreshes NFL data in the background. When a refresh
 * finishes, every page's data is refetched so the new week and stats show up without a reload. */
export function useStatus() {
  const qc = useQueryClient()
  const status = useQuery({
    ...getStatusOptions(),
    staleTime: 60_000,
    retry: false,
    refetchInterval: (q) => (q.state.data?.data_refreshing ? 15_000 : 5 * 60_000),
  })
  const was = useRef(false)
  const refreshing = !!status.data?.data_refreshing
  useEffect(() => {
    if (was.current && !refreshing) void qc.invalidateQueries()
    was.current = refreshing
  }, [refreshing, qc])
  return status
}

export function nflSyncedAt(s: StatusOut | undefined) {
  return s?.sources.find((x) => x.source === 'nflverse')?.last_synced_at
}

/** "Update NFL data": schedule, scores, stats, injury reports and the player list (slow: it
 * downloads nflverse's files). */
export function useNflRefresh() {
  const qc = useQueryClient()
  return useMutation({
    ...refreshMutation(),
    onSuccess: (res) => {
      void qc.invalidateQueries()
      if (res.ok) toast.success('NFL data updated', { description: res.detail.join(' · ') })
      else toast.warning('NFL data partly updated', { description: res.detail.join(' · ') })
    },
    onError: (e) => toast.error(describeError(e).message, { description: describeError(e).hint }),
  })
}

export function StaleDataBanner({ status }: { status: StatusOut | undefined }) {
  const refresh = useNflRefresh()
  if (!status) return null
  const busy = status.data_refreshing || refresh.isPending
  if (busy) {
    return (
      <Alert data-testid="data-refreshing">
        <Loader2 className="animate-spin" />
        <AlertTitle>Updating NFL data…</AlertTitle>
        <AlertDescription>
          Downloading the latest scores, stats and injury reports. Pages update by themselves when it's done.
        </AlertDescription>
      </Alert>
    )
  }
  if (!status.nfl_data_stale) return null
  return (
    <Alert className="border-warn/40" data-testid="data-stale">
      <TriangleAlert className="text-warn" />
      <AlertTitle>
        {status.unscored_week
          ? `Week ${status.unscored_week} results aren't in yet`
          : 'NFL data is out of date'}
      </AlertTitle>
      <AlertDescription className="flex flex-col gap-2">
        <span>
          Last updated {fmtRelative(nflSyncedAt(status))}. Until it updates, the week shown, projections and injury
          statuses can be behind. FantasyEdge checks every 30 minutes while it's running
          {status.refresh_error ? ` (last attempt failed: ${status.refresh_error})` : ''}.
        </span>
        <Button
          size="sm"
          variant="outline"
          className="self-start"
          onClick={() => refresh.mutate({ body: { scope: 'all' } })}
        >
          <CloudDownload /> Update NFL data now
        </Button>
      </AlertDescription>
    </Alert>
  )
}
