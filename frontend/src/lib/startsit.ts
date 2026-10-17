/** Start/Sit planner rules: which moves are allowed and what a lineup totals. Pure functions. */
import { SLOT_ELIGIBILITY } from '@/lib/lineup'

/** One entry per lineup slot: the player id in it, or null when empty. */
export type Lineup = (string | null)[]

export interface PlanRules {
  slots: string[]
  positionOf: Record<string, string>
  locked: ReadonlySet<string> // game already final: can't move, can't be replaced
  reserved: ReadonlySet<string> // IR / taxi: can't start
}

export type Target = { slot: number } | 'bench'

export function canPlace(position: string | undefined, slot: string): boolean {
  return !!position && (SLOT_ELIGIBILITY[slot] ?? []).includes(position)
}

/** Whether `playerId` may be dropped on `target` (used to light up valid targets while dragging). */
export function canMove(lineup: Lineup, rules: PlanRules, playerId: string, target: Target): boolean {
  return move(lineup, rules, playerId, target) !== null
}

/**
 * Move a player onto a slot or the bench. Returns the new lineup, or null if the move isn't allowed
 * (wrong position, a locked player involved, an IR player into a slot, or nothing changes).
 * Whoever was in the target slot swaps into the mover's old slot when he fits there; otherwise he
 * goes to the bench.
 */
export function move(lineup: Lineup, rules: PlanRules, playerId: string, target: Target): Lineup | null {
  if (rules.locked.has(playerId)) return null
  const from = lineup.indexOf(playerId)
  const next = [...lineup]
  if (target === 'bench') {
    if (from < 0) return null
    next[from] = null
    return next
  }
  const to = target.slot
  if (to < 0 || to >= rules.slots.length || to === from) return null
  if (rules.reserved.has(playerId) || !canPlace(rules.positionOf[playerId], rules.slots[to])) return null
  const occupant = lineup[to]
  if (occupant && rules.locked.has(occupant)) return null
  next[to] = playerId
  if (from >= 0) {
    next[from] = occupant && canPlace(rules.positionOf[occupant], rules.slots[from]) ? occupant : null
  }
  return next
}

export function total(lineup: Lineup, points: Record<string, number>): number {
  return Math.round(lineup.reduce((sum, p) => sum + (p ? (points[p] ?? 0) : 0), 0) * 100) / 100
}

export function sameLineup(a: Lineup, b: Lineup): boolean {
  return a.length === b.length && a.every((p, i) => p === b[i])
}

/** Starters as plain text, one slot per line, for pasting into a group chat or the platform. */
export function lineupText(
  week: number,
  lineup: Lineup,
  labels: string[],
  info: Record<string, { name: string; team?: string | null; points: number }>,
): string {
  const lines = lineup.map((p, i) => {
    const who = p ? info[p] : undefined
    return `${labels[i]}: ${who ? `${who.name}${who.team ? ` (${who.team})` : ''} · ${who.points.toFixed(1)}` : '(empty)'}`
  })
  const sum = lineup.reduce((s, p) => s + (p ? (info[p]?.points ?? 0) : 0), 0)
  return [`Week ${week} lineup · ${sum.toFixed(1)} projected pts`, ...lines].join('\n')
}
