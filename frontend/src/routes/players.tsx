import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { createColumnHelper, useTable, type SortingState, type Updater } from '@tanstack/react-table'
import { ChevronLeft, ChevronRight, Search, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { z } from 'zod'

import type { PlayerTableRow } from '@/api'
import { getPlayersTableOptions } from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { InjuryTag, PositionBadge, SignalBadge } from '@/components/player/badges'
import { OwnerLabel } from '@/components/player/matchups'
import { PlayerLink } from '@/components/player/PlayerLink'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { DataTable, sortableFeatures } from '@/components/ui/data-table'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { POSITIONS, fmtInt, fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

export const PAGE_SIZE = 50
const SORTS = ['ros', 'ppg', 'value', 'market', 'verdict', 'name'] as const
type Sort = (typeof SORTS)[number]
type Avail = 'all' | 'mine' | 'other' | 'fa'

/** URL search params for /players. Defaults stay out of the URL; bad values fall back to them. */
export const playersSearchSchema = z.object({
  q: z.string().max(60).optional().catch(undefined),
  pos: z.enum(POSITIONS).optional().catch(undefined),
  team: z.string().max(4).optional().catch(undefined),
  avail: z.enum(['all', 'mine', 'other', 'fa']).optional().catch(undefined),
  sort: z.enum(SORTS).optional().catch(undefined),
  dir: z.enum(['asc', 'desc']).optional().catch(undefined),
  page: z.coerce.number().int().min(0).optional().catch(undefined),
})
export type PlayersSearch = z.infer<typeof playersSearchSchema>

function parseSearch(raw: unknown): PlayersSearch {
  const r = playersSearchSchema.safeParse(raw ?? {})
  return r.success ? r.data : {}
}

/** Drop defaults/empties so the URL only carries what the user changed. */
export function cleanSearch(s: PlayersSearch): PlayersSearch {
  const out: PlayersSearch = {}
  if (s.q?.trim()) out.q = s.q.trim()
  if (s.pos) out.pos = s.pos
  if (s.team) out.team = s.team
  if (s.avail && s.avail !== 'all') out.avail = s.avail
  if (s.sort && s.sort !== 'ros') out.sort = s.sort
  if (s.dir && s.dir !== (s.sort === 'name' ? 'asc' : 'desc')) out.dir = s.dir
  if (s.page) out.page = s.page
  return out
}

const AVAIL_LABEL: Record<Avail, string> = { all: 'All', mine: 'My team', other: 'Other teams', fa: 'Free agents' }

const col = createColumnHelper<typeof sortableFeatures, PlayerTableRow>()

function useColumns(marketLabel: string) {
  return useMemo(
    () =>
      col.columns([
        col.accessor('name', {
          id: 'name',
          header: 'Player',
          meta: { label: 'name', className: 'min-w-36 whitespace-normal' },
          cell: ({ row: { original: r } }) => (
            <div className="flex min-w-0 items-start gap-2">
              <PositionBadge position={r.position} className="mt-0.5 shrink-0" />
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="flex flex-wrap items-center gap-x-2 font-medium">
                  <PlayerLink playerId={r.player_id}>{r.name}</PlayerLink>
                  <InjuryTag status={r.injury_status} returnWeek={r.return_week} />
                </span>
                <span className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  {r.nfl_team ?? 'FA'}
                  {r.bye_week != null && <span>· bye {r.bye_week}</span>}
                  <OwnerLabel owner={r.owner} mine={r.mine} />
                </span>
              </div>
            </div>
          ),
        }),
        col.accessor('ppg', {
          id: 'ppg',
          header: 'PPG',
          meta: { className: 'hidden text-right font-mono tabular-nums sm:table-cell', label: 'projected points per game' },
          cell: (c) => fmtNum(c.getValue()),
        }),
        col.accessor('ros_points', {
          id: 'ros',
          header: () => (
            <>
              ROS<span className="hidden sm:inline"> pts</span>
            </>
          ),
          meta: { className: 'text-right font-mono tabular-nums', label: 'rest-of-season points' },
          cell: (c) => fmtNum(c.getValue()),
        }),
        col.accessor('ros_value_par', {
          id: 'value',
          header: 'Value',
          meta: { className: 'hidden text-right font-mono tabular-nums md:table-cell', label: 'value over replacement' },
          cell: (c) => fmtSigned(c.getValue()),
        }),
        col.accessor('market_value', {
          id: 'market',
          header: marketLabel,
          meta: { className: 'hidden text-right font-mono tabular-nums md:table-cell', label: 'market value' },
          cell: (c) => fmtInt(c.getValue()),
        }),
        col.accessor('signal', {
          id: 'verdict',
          header: 'Verdict',
          meta: { className: 'text-right', label: 'verdict' },
          cell: ({ row: { original: r } }) => <SignalBadge signal={r.signal} showHold />,
        }),
        ]),
    [marketLabel],
  )
}

function PlayersTable({
  rows,
  marketLabel,
  sort,
  desc,
  onSort,
  empty,
}: {
  rows: PlayerTableRow[]
  marketLabel: string
  sort: Sort
  desc: boolean
  onSort: (sort: Sort, desc: boolean) => void
  empty: React.ReactNode
}) {
  const columns = useColumns(marketLabel)
  const sorting: SortingState = [{ id: sort, desc }]
  const table = useTable({
    features: sortableFeatures,
    columns,
    data: rows,
    getRowId: (r) => r.player_id,
    manualSorting: true,
    enableSortingRemoval: false,
    sortDescFirst: true,
    state: { sorting },
    onSortingChange: (updater: Updater<SortingState>) => {
      const next = typeof updater === 'function' ? updater(sorting) : updater
      const s = next[0]
      if (!s) return
      // a new column starts best-first (A→Z for names); the same column flips direction
      const fresh = s.id !== sort
      onSort(s.id as Sort, fresh ? s.id !== 'name' : s.desc)
    },
  })
  return <DataTable table={table} rowClassName={(r) => (r.mine ? 'bg-primary/5' : undefined)} empty={empty} />
}

export function PlayersPage() {
  const team = useTeamStore((s) => s.team)!
  const manual = team.platform === 'manual'
  const search = parseSearch(useSearch({ strict: false }))
  const navigate = useNavigate()
  const sort: Sort = search.sort ?? 'ros'
  const desc = (search.dir ?? (sort === 'name' ? 'asc' : 'desc')) === 'desc'
  const avail: Avail = manual && (search.avail === 'other' || search.avail === 'fa') ? 'all' : (search.avail ?? 'all')
  const page = search.page ?? 0

  const update = (patch: PlayersSearch, keepPage = false) =>
    void navigate({
      to: '.',
      search: cleanSearch({ ...search, ...patch, page: keepPage ? (patch.page ?? search.page) : undefined }),
      replace: true,
    } as never)

  // the search box updates the URL after a short pause, not on every keystroke
  const [text, setText] = useState(search.q ?? '')
  useEffect(() => setText(search.q ?? ''), [search.q])
  useEffect(() => {
    if (text.trim() === (search.q ?? '')) return
    const t = setTimeout(() => update({ q: text }), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])

  const q = useQuery({
    ...getPlayersTableOptions({
      path: { team_id: team.teamId },
      query: {
        q: search.q || undefined,
        pos: search.pos,
        team: search.team,
        avail,
        sort,
        dir: desc ? 'desc' : 'asc',
        page,
        size: PAGE_SIZE,
      },
    }),
    placeholderData: keepPreviousData,
  })
  const data = q.data
  const filtered = !!(search.q || search.pos || search.team || avail !== 'all')
  const first = page * PAGE_SIZE

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Players"
        description="Every player we project, in your league's scoring. Search, filter by position, NFL team or who has him, and sort by projection, rest-of-season points, value over replacement, market value or our buy/hold/sell verdict."
      />
      <Card>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="relative w-full lg:max-w-xs">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Search players"
                aria-label="Search players"
                className="pr-8 pl-8"
              />
              {text && (
                <button
                  type="button"
                  className="absolute top-1/2 right-2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setText('')
                    update({ q: undefined })
                  }}
                  aria-label="Clear search"
                >
                  <X className="size-4" />
                </button>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ToggleGroup
                type="single"
                variant="outline"
                value={search.pos ?? 'ALL'}
                onValueChange={(v) => v && update({ pos: v === 'ALL' ? undefined : (v as PlayersSearch['pos']) })}
                aria-label="Position"
              >
                {['ALL', ...POSITIONS].map((p) => (
                  <ToggleGroupItem key={p} value={p} className="px-2 text-xs">
                    {p === 'ALL' ? 'All' : p}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <Select value={search.team ?? 'all'} onValueChange={(v) => update({ team: v === 'all' ? undefined : v })}>
                <SelectTrigger aria-label="NFL team" className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All teams</SelectItem>
                  {(data?.nfl_teams ?? (search.team ? [search.team] : [])).map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <ToggleGroup
                type="single"
                variant="outline"
                value={avail}
                onValueChange={(v) => v && update({ avail: v as Avail })}
                aria-label="Availability"
              >
                {(manual ? (['all', 'mine'] as const) : (['all', 'mine', 'other', 'fa'] as const)).map((a) => (
                  <ToggleGroupItem key={a} value={a} className="px-2 text-xs">
                    {AVAIL_LABEL[a]}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            </div>
          </div>

          {q.isPending && <ListSkeleton rows={8} height="h-10" />}
          {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
          {data && (
            <div className={cn('flex flex-col gap-3 transition-opacity', q.isPlaceholderData && 'opacity-60')}>
              <PlayersTable
                rows={data.rows}
                marketLabel={data.market_label}
                sort={sort}
                desc={desc}
                onSort={(s, d) => update({ sort: s, dir: d ? 'desc' : 'asc' })}
                empty={
                  <span className="flex flex-col items-center gap-2">
                    No players match these filters.
                    {filtered && (
                      <Button size="sm" variant="outline" onClick={() => void navigate({ to: '.', search: {}, replace: true } as never)}>
                        Clear filters
                      </Button>
                    )}
                  </span>
                }
              />
              {data.total > 0 && (
                <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
                  <span>
                    {first + 1}–{Math.min(first + PAGE_SIZE, data.total)} of {data.total}
                    {manual && ' · a manual team can’t see who else owns a player'}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={page === 0}
                      onClick={() => update({ page: page - 1 }, true)}
                      aria-label="Previous page"
                    >
                      <ChevronLeft /> <span className="hidden sm:inline">Previous</span>
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={first + PAGE_SIZE >= data.total}
                      onClick={() => update({ page: page + 1 }, true)}
                      aria-label="Next page"
                    >
                      <span className="hidden sm:inline">Next</span> <ChevronRight />
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
