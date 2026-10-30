import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { useQuery } from '@tanstack/react-query'
import { Copy, Info, Lock, Redo2, RotateCcw, Sparkles, Undo2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import type { StartSitOut, StartSitPlayer } from '@/api'
import { getStartsitOptions } from '@/api/@tanstack/react-query.gen'
import { ErrorState, ListSkeleton, PageHeader } from '@/components/common/states'
import { InjuryTag, PositionBadge } from '@/components/player/badges'
import { matchupTone } from '@/components/player/matchups'
import { GamedayAlerts } from '@/components/team/GamedayAlerts'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useHistory } from '@/hooks/useHistory'
import { fmtNum, fmtSigned, platformName } from '@/lib/format'
import { canMove, lineupText, move, sameLineup, total, type Lineup, type PlanRules, type Target } from '@/lib/startsit'
import { cn } from '@/lib/utils'
import { useTeamStore } from '@/stores/team'

const TONE = { easy: 'text-buy', hard: 'text-sell', neutral: 'text-muted-foreground' } as const

function PlayerCard({
  p,
  selected,
  dragging,
  onSelect,
}: {
  p: StartSitPlayer
  selected?: boolean
  dragging?: boolean
  onSelect?: () => void
}) {
  const fixed = p.locked || p.reserved
  const { attributes, listeners, setNodeRef } = useDraggable({ id: p.player.player_id, disabled: fixed })
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={`${p.player.name}, ${fmtNum(p.points)} points${p.locked ? ', locked' : ''}`}
      onClick={onSelect}
      className={cn(
        'flex w-full min-w-0 touch-none items-center gap-2 rounded-md border bg-card px-2 py-1.5 text-left text-sm select-none',
        fixed ? 'cursor-not-allowed opacity-80' : 'cursor-grab active:cursor-grabbing',
        selected && 'ring-2 ring-primary',
        dragging && 'opacity-40',
      )}
    >
      <PositionBadge position={p.player.position} className="shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="flex items-center gap-1.5 truncate font-medium">
          <span className="truncate">{p.player.name}</span>
          <InjuryTag status={p.injury_status} returnWeek={p.return_week} />
          {p.locked && <Lock className="size-3 shrink-0 text-muted-foreground" aria-hidden />}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {p.player.nfl_team}
          {p.on_bye ? (
            <span className="ml-1 font-semibold text-warn">BYE</span>
          ) : p.opponent ? (
            <span className={cn('ml-1', TONE[matchupTone(p.matchup_index)])}>vs {p.opponent}</span>
          ) : null}
          {p.locked && ' · played'}
          {p.reserved && ' · IR'}
        </span>
      </div>
      <span className="shrink-0 font-mono text-sm tabular-nums">{fmtNum(p.points)}</span>
    </div>
  )
}

function SlotRow({
  index,
  label,
  eligible,
  player,
  state,
  onTap,
  children,
}: {
  index: number
  label: string
  eligible: string[]
  player?: StartSitPlayer
  state: 'idle' | 'valid' | 'invalid'
  onTap: () => void
  children?: React.ReactNode
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot-${index}` })
  return (
    <div
      ref={setNodeRef}
      data-testid={`slot-${index}`}
      onClick={(e) => {
        if (e.target === e.currentTarget || !player) onTap()
      }}
      className={cn(
        'flex items-center gap-2 rounded-lg border border-transparent p-1 transition-colors',
        state === 'valid' && 'border-dashed border-primary/50 bg-primary/5',
        state === 'valid' && isOver && 'border-solid bg-primary/15',
        state === 'invalid' && 'opacity-40',
      )}
    >
      <span className="w-12 shrink-0 text-center font-mono text-xs font-semibold text-muted-foreground" title={eligible.join(' / ')}>
        {label}
      </span>
      {children ?? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onTap()
          }}
          className="flex h-11 flex-1 items-center rounded-md border border-dashed px-3 text-xs text-muted-foreground"
        >
          Empty: {eligible.join(' / ')}
        </button>
      )}
    </div>
  )
}

function BenchZone({ state, children }: { state: 'idle' | 'valid' | 'invalid'; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: 'bench' })
  return (
    <div
      ref={setNodeRef}
      data-testid="bench"
      className={cn(
        'flex min-h-16 flex-col gap-1.5 rounded-lg border border-transparent p-1 transition-colors',
        state === 'valid' && 'border-dashed border-primary/50 bg-primary/5',
        state === 'valid' && isOver && 'border-solid bg-primary/15',
      )}
    >
      {children}
    </div>
  )
}

function Stat({ label, value, delta, tone }: { label: string; value: number; delta?: number; tone?: 'good' | 'bad' }) {
  return (
    <div className="flex flex-col rounded-lg border bg-card/60 px-3 py-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="font-mono text-xl font-semibold tabular-nums">{fmtNum(value)}</span>
      {delta != null && (
        <span className={cn('font-mono text-xs tabular-nums', tone === 'good' ? 'text-buy' : tone === 'bad' ? 'text-sell' : 'text-muted-foreground')}>
          {fmtSigned(delta)} vs this lineup
        </span>
      )}
    </div>
  )
}

function Planner({ data, platform }: { data: StartSitOut; platform: string }) {
  const start = data.has_lineup ? data.current : data.optimal
  const h = useHistory<Lineup>(start)
  const lineup = h.state
  const [active, setActive] = useState<string | null>(null) // being dragged
  const [selected, setSelected] = useState<string | null>(null) // tap-to-move

  useEffect(() => h.reset(data.has_lineup ? data.current : data.optimal), [data]) // eslint-disable-line react-hooks/exhaustive-deps

  const byId = useMemo(() => Object.fromEntries(data.players.map((p) => [p.player.player_id, p])), [data])
  const points = useMemo(() => Object.fromEntries(data.players.map((p) => [p.player.player_id, p.points])), [data])
  const rules: PlanRules = useMemo(
    () => ({
      slots: data.slots.map((s) => s.slot),
      positionOf: Object.fromEntries(data.players.map((p) => [p.player.player_id, p.player.position])),
      locked: new Set(data.players.filter((p) => p.locked).map((p) => p.player.player_id)),
      reserved: new Set(data.players.filter((p) => p.reserved).map((p) => p.player.player_id)),
    }),
    [data],
  )

  const apply = (playerId: string, target: Target) => {
    const next = move(lineup, rules, playerId, target)
    if (next) h.set(next)
    return !!next
  }

  // Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || (e.target as HTMLElement)?.closest('input, textarea')) return
      const k = e.key.toLowerCase()
      if (k === 'z' && !e.shiftKey) {
        e.preventDefault()
        h.undo()
      } else if ((k === 'z' && e.shiftKey) || k === 'y') {
        e.preventDefault()
        h.redo()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [h.undo, h.redo]) // eslint-disable-line react-hooks/exhaustive-deps

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 6 } }),
    useSensor(KeyboardSensor),
  )
  const moving = active ?? selected
  const slotState = (i: number) =>
    moving == null ? 'idle' : canMove(lineup, rules, moving, { slot: i }) ? 'valid' : 'invalid'
  const benchState = moving == null ? 'idle' : canMove(lineup, rules, moving, 'bench') ? 'valid' : 'invalid'

  const onDragStart = (e: DragStartEvent) => {
    setSelected(null)
    setActive(String(e.active.id))
  }
  const onDragEnd = (e: DragEndEvent) => {
    setActive(null)
    const over = e.over?.id
    if (!over) return
    const target: Target = over === 'bench' ? 'bench' : { slot: Number(String(over).replace('slot-', '')) }
    if (!apply(String(e.active.id), target)) toast.error("That player can't go there")
  }
  const tap = (playerId: string) => {
    if (selected === playerId) return setSelected(null)
    if (selected && lineup.includes(playerId) && apply(selected, { slot: lineup.indexOf(playerId) })) {
      return setSelected(null)
    }
    setSelected(rules.locked.has(playerId) || rules.reserved.has(playerId) ? null : playerId)
  }
  const tapTarget = (target: Target) => {
    if (!selected) return
    if (!apply(selected, target)) toast.error("That player can't go there")
    setSelected(null)
  }

  const now = total(lineup, points)
  const bench = data.players.filter((p) => !lineup.includes(p.player.player_id) && !p.reserved)
  const reserved = data.players.filter((p) => p.reserved)
  const labels = data.slots.map((s) => s.label)
  const anyLocked = data.players.some((p) => p.locked)

  const copy = async () => {
    const info = Object.fromEntries(
      data.players.map((p) => [p.player.player_id, { name: p.player.name, team: p.player.nfl_team, points: p.points }]),
    )
    try {
      await navigator.clipboard.writeText(lineupText(data.week, lineup, labels, info))
      toast.success('Lineup copied')
    } catch {
      toast.error("Couldn't copy: your browser blocked the clipboard")
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="This lineup" value={now} />
        {data.has_lineup && (
          <Stat
            label={`Your ${platformName(platform)} lineup`}
            value={data.current_points}
            delta={data.current_points - now}
            tone={data.current_points > now ? 'good' : data.current_points < now ? 'bad' : undefined}
          />
        )}
        <Stat
          label="Best lineup"
          value={data.optimal_points}
          delta={data.optimal_points - now}
          tone={data.optimal_points - now > 0.05 ? 'good' : undefined}
        />
      </div>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={h.undo} disabled={!h.canUndo} title="Undo (Ctrl+Z)">
          <Undo2 /> Undo
        </Button>
        <Button size="sm" variant="outline" onClick={h.redo} disabled={!h.canRedo} title="Redo (Ctrl+Shift+Z)">
          <Redo2 /> Redo
        </Button>
        <Button size="sm" variant="outline" onClick={() => h.set(data.optimal)} disabled={sameLineup(lineup, data.optimal)}>
          <Sparkles /> Use best lineup
        </Button>
        {data.has_lineup && (
          <Button size="sm" variant="outline" onClick={() => h.set(data.current)} disabled={sameLineup(lineup, data.current)}>
            <RotateCcw /> Reset to my real lineup
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => void copy()}>
          <Copy /> Copy lineup
        </Button>
      </div>

      <DndContext sensors={sensors} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragCancel={() => setActive(null)}>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Lineup · week {data.week}</CardTitle>
              <CardDescription>
                Drag a player onto a slot, or tap a player and then a slot. Only positions the slot accepts can go in it.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-1">
              {data.slots.map((s, i) => {
                const pid = lineup[i]
                const p = pid ? byId[pid] : undefined
                return (
                  <SlotRow
                    key={i}
                    index={i}
                    label={s.label}
                    eligible={s.eligible}
                    player={p}
                    state={slotState(i)}
                    onTap={() => tapTarget({ slot: i })}
                  >
                    {p && (
                      <div className="min-w-0 flex-1">
                        <PlayerCard
                          p={p}
                          selected={selected === pid}
                          dragging={active === pid}
                          onSelect={() => tap(pid!)}
                        />
                      </div>
                    )}
                  </SlotRow>
                )
              })}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Bench</CardTitle>
              <CardDescription>Drop a starter here to sit him.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <BenchZone state={benchState}>
                {bench.length === 0 && <p className="py-4 text-center text-xs text-muted-foreground">Nobody on the bench.</p>}
                {bench.map((p) => (
                  <PlayerCard
                    key={p.player.player_id}
                    p={p}
                    selected={selected === p.player.player_id}
                    dragging={active === p.player.player_id}
                    onSelect={() => tap(p.player.player_id)}
                  />
                ))}
                {selected && lineup.includes(selected) && (
                  <Button size="sm" variant="ghost" className="self-start" onClick={() => tapTarget('bench')}>
                    Move to bench
                  </Button>
                )}
              </BenchZone>
              {reserved.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-muted-foreground">IR / taxi (can't start)</span>
                  {reserved.map((p) => (
                    <PlayerCard key={p.player.player_id} p={p} />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
        <DragOverlay>{active && byId[active] ? <PlayerCard p={byId[active]} /> : null}</DragOverlay>
      </DndContext>
      {anyLocked && (
        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <Lock className="mt-0.5 size-3.5 shrink-0" />
          Players marked “played” have kicked off (or finished) this week, so they’re locked where they are, and a
          finished game counts 0 points still to play.
        </p>
      )}
    </div>
  )
}

export function StartSitPage() {
  const team = useTeamStore((s) => s.team)!
  const [week, setWeek] = useState<number | undefined>(undefined)
  const q = useQuery(getStartsitOptions({ path: { team_id: team.teamId }, query: week ? { week } : undefined }))
  const platform = platformName(team.platform)
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Start/Sit"
        description="Plan this week's lineup: your real lineup, the best one we project (matchups, byes and injuries counted), and a board to try your own."
        actions={
          q.data && (
            <Select value={String(q.data.week)} onValueChange={(v) => setWeek(Number(v))}>
              <SelectTrigger aria-label="Week" className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {q.data.weeks.map((w) => (
                  <SelectItem key={w} value={String(w)}>
                    Week {w}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )
        }
      />
      {(!q.data || q.data.week === q.data.weeks[0]) && <GamedayAlerts team={team} />}
      <Alert>
        <Info />
        <AlertTitle>Planner — changes here don't change your lineup on {team.platform === 'manual' || team.platform === 'demo' ? 'ESPN/Sleeper' : platform}.</AlertTitle>
        <AlertDescription>
          It's a what-if board. Set your real lineup in the {team.platform === 'manual' || team.platform === 'demo' ? 'ESPN or Sleeper' : platform} app.
        </AlertDescription>
      </Alert>
      {q.isPending && <ListSkeleton rows={6} height="h-12" />}
      {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
      {q.data && <Planner data={q.data} platform={team.platform} />}
    </div>
  )
}
