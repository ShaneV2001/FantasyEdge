import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { AlertTriangle, Check, Loader2, Minus, MoreHorizontal, Plus, X } from 'lucide-react'
import { useDeferredValue, useMemo, useState } from 'react'
import { toast } from 'sonner'

import type { PlayerRef } from '@/api'
import { manualLeagueMutation, searchPlayersOptions, updateRosterMutation } from '@/api/@tanstack/react-query.gen'
import { ErrorState } from '@/components/common/states'
import { PositionBadge } from '@/components/player/badges'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { describeError } from '@/lib/errors'
import { slotLabel } from '@/lib/format'
import {
  checkRoster,
  defaultRole,
  fitToSlots,
  LINEUP_PRESETS,
  type LineupShape,
  type Role,
  rosterPositions,
  SLOT_ORDER,
  startingSlots,
} from '@/lib/lineup'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

export interface Picked extends PlayerRef {
  role: Role
}

export type Scoring = 'standard' | 'half_ppr' | 'ppr'

/** Pre-filled values when editing an existing manual team. */
export interface BuilderInitial {
  teamId: string
  name: string
  numTeams: number
  scoring: Scoring
  playoffWeekStart: number
  tradeDeadlineWeek: number | null
  shape: LineupShape
  picked: Picked[]
}

const MAX_SLOT = 4
const MAX_BENCH = 15
const MAX_IR = 5

function Stepper({
  label,
  value,
  min = 0,
  max,
  onChange,
}: {
  label: string
  value: number
  min?: number
  max: number
  onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border bg-background/40 px-2 py-1">
      <span className="font-mono text-xs font-medium">{label}</span>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-6"
          aria-label={`Fewer ${label}`}
          disabled={value <= min}
          onClick={() => onChange(value - 1)}
        >
          <Minus />
        </Button>
        <span className="w-5 text-center font-mono text-sm tabular-nums" aria-label={`${label} count`}>
          {value}
        </span>
        <Button
          type="button"
          size="icon"
          variant="ghost"
          className="size-6"
          aria-label={`More ${label}`}
          disabled={value >= max}
          onClick={() => onChange(value + 1)}
        >
          <Plus />
        </Button>
      </div>
    </div>
  )
}

function PlayerRow({
  p,
  slot,
  onRole,
  onRemove,
  canStart,
}: {
  p: Picked
  slot?: string
  onRole: (r: Role) => void
  onRemove: () => void
  canStart: boolean
}) {
  return (
    <li className="flex items-center gap-2 px-2 py-1.5 text-sm">
      {slot !== undefined && <span className="w-12 font-mono text-[11px] text-muted-foreground">{slotLabel(slot)}</span>}
      <PositionBadge position={p.position} />
      <span className="flex-1 truncate">{p.name}</span>
      <span className="text-xs text-muted-foreground">{p.nfl_team}</span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="icon" variant="ghost" className="size-6" aria-label={`Move ${p.name}`}>
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {p.role !== 'starter' && (
            <DropdownMenuItem disabled={!canStart} onSelect={() => onRole('starter')}>
              Move to starting lineup
            </DropdownMenuItem>
          )}
          {p.role !== 'bench' && <DropdownMenuItem onSelect={() => onRole('bench')}>Move to bench</DropdownMenuItem>}
          {p.role !== 'ir' && <DropdownMenuItem onSelect={() => onRole('ir')}>Move to IR</DropdownMenuItem>}
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onSelect={onRemove}>
            <X /> Remove from roster
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  )
}

export function ManualRosterBuilder({ initial }: { initial?: BuilderInitial }) {
  const editing = !!initial
  const [name, setName] = useState(initial?.name ?? 'My team')
  const [numTeams, setNumTeams] = useState(String(initial?.numTeams ?? 12))
  const [scoring, setScoring] = useState<Scoring>(initial?.scoring ?? 'half_ppr')
  const [playoffStart, setPlayoffStart] = useState(String(initial?.playoffWeekStart ?? 15))
  const [shape, setShape] = useState<LineupShape>(initial?.shape ?? LINEUP_PRESETS.standard.shape)
  const [picked, setPicked] = useState<Picked[]>(initial?.picked ?? [])
  const [q, setQ] = useState('')
  const deferredQ = useDeferredValue(q)
  const search = useQuery({
    ...searchPlayersOptions({ query: { q: deferredQ, limit: 15 } }),
    placeholderData: (prev) => prev,
  })
  const setTeam = useTeamStore((s) => s.setTeam)
  const navigate = useNavigate()
  const qc = useQueryClient()
  const create = useMutation({
    ...manualLeagueMutation(),
    onSuccess: (ref) => {
      setTeam({ teamId: ref.team_id, leagueId: ref.league_id, teamName: name, leagueName: 'Manual league', platform: 'manual' })
      void qc.invalidateQueries()
      toast.success('Team created')
      void navigate({ to: '/advisor' })
    },
  })
  const update = useMutation({
    ...updateRosterMutation(),
    onSuccess: (ref) => {
      setTeam({ teamId: ref.team_id, leagueId: ref.league_id, teamName: name, leagueName: 'Manual league', platform: 'manual' })
      void qc.invalidateQueries()
      toast.success('Team updated')
      void navigate({ to: '/team' })
    },
  })
  const saving = create.isPending || update.isPending
  const saveError = create.error ?? update.error

  const slots = useMemo(() => startingSlots(shape), [shape])
  const starters = picked.filter((p) => p.role === 'starter')
  const bench = picked.filter((p) => p.role === 'bench')
  const ir = picked.filter((p) => p.role === 'ir')
  const fit = useMemo(
    () => fitToSlots(starters.map((p) => ({ id: p.player_id, position: p.position })), slots),
    [starters, slots],
  )
  const check = checkRoster(
    picked.map((p) => ({ id: p.player_id, position: p.position, role: p.role, name: p.name })),
    shape,
  )
  const byId = new Map(picked.map((p) => [p.player_id, p]))
  const pickedIds = new Set(picked.map((p) => p.player_id))

  /** Change the lineup shape; starters that no longer fit drop to the bench. */
  function updateShape(next: LineupShape) {
    const nextSlots = startingSlots(next)
    const { unplaced } = fitToSlots(starters.map((p) => ({ id: p.player_id, position: p.position })), nextSlots)
    if (unplaced.length) {
      setPicked(picked.map((p) => (unplaced.includes(p.player_id) ? { ...p, role: 'bench' } : p)))
      toast.info(`${unplaced.length} starter${unplaced.length > 1 ? 's' : ''} moved to the bench`)
    }
    setShape(next)
  }

  function add(p: PlayerRef) {
    if (pickedIds.has(p.player_id)) return
    const role = defaultRole({ id: p.player_id, position: p.position }, picked.map((x) => ({ id: x.player_id, position: x.position, role: x.role })), shape)
    if (!role) {
      toast.error('Roster is full', { description: 'Add bench spots or remove a player first.' })
      return
    }
    setPicked([...picked, { ...p, role }])
  }

  function canStart(p: Picked) {
    const trial = [...starters, p].map((x) => ({ id: x.player_id, position: x.position }))
    return fitToSlots(trial, slots).unplaced.length === 0
  }

  const setRole = (id: string, role: Role) => setPicked(picked.map((p) => (p.player_id === id ? { ...p, role } : p)))
  const remove = (id: string) => setPicked(picked.filter((p) => p.player_id !== id))

  function submit() {
    const body = {
      name,
      num_teams: Number(numTeams),
      roster_positions: rosterPositions(shape),
      scoring,
      playoff_week_start: Number(playoffStart),
      trade_deadline_week: initial?.tradeDeadlineWeek ?? null,
      player_ids: picked.map((p) => p.player_id),
      starters: starters.map((p) => p.player_id),
      ir: ir.map((p) => p.player_id),
    }
    if (initial) update.mutate({ path: { team_id: initial.teamId }, body })
    else create.mutate({ body })
  }

  const totalSpots = slots.length + shape.bench + shape.ir

  return (
    <Card>
      <CardHeader>
        <CardTitle>{editing ? 'Edit your team' : 'Build your roster'}</CardTitle>
        <CardDescription>
          Works for ESPN, Yahoo or anything else. Set your league's lineup and bench depth, then add players. Without
          league rosters we can't see free agents or other teams, so waiver and trade-partner advice is limited.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {/* league basics */}
        <div className="grid gap-4 sm:grid-cols-4">
          <div className="grid gap-1.5">
            <Label htmlFor="team-name">Team name</Label>
            <Input id="team-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="grid gap-1.5">
            <Label>League size</Label>
            <Select value={numTeams} onValueChange={setNumTeams}>
              <SelectTrigger aria-label="League size">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[8, 10, 12, 14, 16].map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n} teams
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-1.5">
            <Label>Scoring</Label>
            <ToggleGroup type="single" variant="outline" value={scoring} onValueChange={(v) => v && setScoring(v as typeof scoring)}>
              <ToggleGroupItem value="standard">Std</ToggleGroupItem>
              <ToggleGroupItem value="half_ppr">½ PPR</ToggleGroupItem>
              <ToggleGroupItem value="ppr">PPR</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div className="grid gap-1.5">
            <Label>Playoffs start</Label>
            <Select value={playoffStart} onValueChange={setPlayoffStart}>
              <SelectTrigger aria-label="Playoffs start">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[13, 14, 15, 16].map((w) => (
                  <SelectItem key={w} value={String(w)}>
                    Week {w}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* lineup shape */}
        <section className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label>
              Lineup &amp; bench{' '}
              <span className="font-normal text-muted-foreground">
                ({slots.length} starters · {shape.bench} bench · {shape.ir} IR = {totalSpots} roster spots)
              </span>
            </Label>
            <div className="flex flex-wrap gap-1">
              {Object.entries(LINEUP_PRESETS).map(([k, v]) => (
                <Button key={k} type="button" size="sm" variant="outline" className="h-7" onClick={() => updateShape(v.shape)}>
                  {v.label}
                </Button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-5">
            {SLOT_ORDER.map((s) => (
              <Stepper
                key={s}
                label={slotLabel(s)}
                value={shape.slots[s] ?? 0}
                max={MAX_SLOT}
                onChange={(v) => updateShape({ ...shape, slots: { ...shape.slots, [s]: v } })}
              />
            ))}
            <Stepper label="Bench" value={shape.bench} max={MAX_BENCH} onChange={(v) => updateShape({ ...shape, bench: v })} />
            <Stepper label="IR" value={shape.ir} max={MAX_IR} onChange={(v) => updateShape({ ...shape, ir: v })} />
          </div>
        </section>

        {/* roster + search */}
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="flex flex-col gap-4">
            <RosterGroup title="Starting lineup" count={`${starters.length}/${slots.length}`}>
              {slots.length === 0 ? (
                <Empty>Add at least one starting slot above.</Empty>
              ) : (
                fit.assigned.map(({ slot, playerId }, i) => {
                  const p = playerId ? byId.get(playerId) : undefined
                  return p ? (
                    <PlayerRow key={`${slot}-${i}`} p={p} slot={slot} onRole={(r) => setRole(p.player_id, r)} onRemove={() => remove(p.player_id)} canStart />
                  ) : (
                    <li key={`${slot}-${i}`} className="flex items-center gap-2 px-2 py-1.5 text-sm text-muted-foreground">
                      <span className="w-12 font-mono text-[11px]">{slotLabel(slot)}</span>
                      <span className="italic">Empty</span>
                    </li>
                  )
                })
              )}
            </RosterGroup>
            <RosterGroup title="Bench" count={`${bench.length}/${shape.bench}`} over={bench.length > shape.bench}>
              {bench.length === 0 ? (
                <Empty>{shape.bench === 0 ? 'This league has no bench spots.' : 'Bench players appear here.'}</Empty>
              ) : (
                bench.map((p) => (
                  <PlayerRow key={p.player_id} p={p} onRole={(r) => setRole(p.player_id, r)} onRemove={() => remove(p.player_id)} canStart={canStart(p)} />
                ))
              )}
            </RosterGroup>
            {(shape.ir > 0 || ir.length > 0) && (
              <RosterGroup title="IR" count={`${ir.length}/${shape.ir}`} over={ir.length > shape.ir}>
                {ir.length === 0 ? (
                  <Empty>Injured players you're stashing go here (they don't use a bench spot).</Empty>
                ) : (
                  ir.map((p) => (
                    <PlayerRow key={p.player_id} p={p} onRole={(r) => setRole(p.player_id, r)} onRemove={() => remove(p.player_id)} canStart={canStart(p)} />
                  ))
                )}
              </RosterGroup>
            )}
          </div>
          <Command shouldFilter={false} className="h-[460px] rounded-lg border">
            <CommandInput placeholder="Search players to add…" value={q} onValueChange={setQ} />
            <CommandList className="max-h-none">
              <CommandEmpty>{search.isFetching ? 'Searching…' : 'No players found.'}</CommandEmpty>
              {search.isError && <div className="p-3 text-sm text-sell">{describeError(search.error).message}</div>}
              <CommandGroup heading={q ? 'Results' : 'Top players by market value — type to search (K/DEF too)'}>
                {(search.data ?? []).map((p) => (
                  <CommandItem key={p.player_id} value={p.player_id} disabled={pickedIds.has(p.player_id)} onSelect={() => add(p)}>
                    <PositionBadge position={p.position} />
                    <span className="flex-1">{p.name}</span>
                    <span className="text-xs text-muted-foreground">{p.nfl_team}</span>
                    {pickedIds.has(p.player_id) ? <Check className="text-buy" /> : <Plus className="text-muted-foreground" />}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </div>
      </CardContent>
      <CardFooter className="flex flex-col items-stretch gap-3">
        {picked.length > 0 && !check.ok && (
          <ul className="flex flex-col gap-1 text-sm text-warn">
            {check.messages.map((m) => (
              <li key={m} className="flex gap-2">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {m}
              </li>
            ))}
          </ul>
        )}
        {saveError && <ErrorState error={saveError} />}
        <div className="flex items-center justify-end gap-3">
          <span className="text-xs text-muted-foreground">
            {picked.length}/{totalSpots} roster spots filled
          </span>
          {editing && (
            <Button variant="outline" onClick={() => void navigate({ to: '/team' })}>
              Cancel
            </Button>
          )}
          <Button disabled={picked.length < 5 || !check.ok || saving} onClick={submit}>
            {saving && <Loader2 className="animate-spin" />}
            {editing ? 'Save changes' : 'Analyze my team'}
          </Button>
        </div>
      </CardFooter>
    </Card>
  )
}

function RosterGroup({
  title,
  count,
  over,
  children,
}: {
  title: string
  count: string
  over?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium">{title}</span>
        <span className={cn('font-mono text-xs text-muted-foreground', over && 'text-sell')}>{count}</span>
      </div>
      <ul className="flex flex-col divide-y rounded-md border">{children}</ul>
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <li className="px-3 py-2.5 text-sm text-muted-foreground">{children}</li>
}
