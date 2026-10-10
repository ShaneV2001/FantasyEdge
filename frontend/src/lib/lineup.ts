/** Lineup-slot rules shared with the backend (signals/lineup.py) for live roster building. */

export const SLOT_ELIGIBILITY: Record<string, string[]> = {
  QB: ['QB'],
  RB: ['RB'],
  WR: ['WR'],
  TE: ['TE'],
  K: ['K'],
  DEF: ['DEF'],
  FLEX: ['RB', 'WR', 'TE'],
  WRRB_FLEX: ['RB', 'WR'],
  REC_FLEX: ['WR', 'TE'],
  SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'],
}

/** Editable lineup shape: starting-slot counts plus bench and IR depth. */
export interface LineupShape {
  slots: Record<string, number> // QB, RB, WR, TE, FLEX, SUPER_FLEX, K, DEF
  bench: number
  ir: number
}

export const SLOT_ORDER = ['QB', 'RB', 'WR', 'TE', 'FLEX', 'SUPER_FLEX', 'K', 'DEF'] as const

export const LINEUP_PRESETS: Record<string, { label: string; shape: LineupShape }> = {
  standard: {
    label: 'Standard',
    shape: { slots: { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 1, SUPER_FLEX: 0, K: 1, DEF: 1 }, bench: 6, ir: 1 },
  },
  superflex: {
    label: 'Superflex',
    shape: { slots: { QB: 1, RB: 2, WR: 3, TE: 1, FLEX: 1, SUPER_FLEX: 1, K: 0, DEF: 0 }, bench: 8, ir: 2 },
  },
  deep: {
    label: 'Deep bench',
    shape: { slots: { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 2, SUPER_FLEX: 0, K: 1, DEF: 1 }, bench: 10, ir: 2 },
  },
  noKdef: {
    label: 'No K/DEF',
    shape: { slots: { QB: 1, RB: 2, WR: 2, TE: 1, FLEX: 2, SUPER_FLEX: 0, K: 0, DEF: 0 }, bench: 6, ir: 1 },
  },
}

export function startingSlots(shape: LineupShape): string[] {
  return SLOT_ORDER.flatMap((s) => Array<string>(shape.slots[s] ?? 0).fill(s))
}

/** Sleeper-style roster_positions: starting slots, then BN × bench, then IR × ir. */
export function rosterPositions(shape: LineupShape): string[] {
  return [...startingSlots(shape), ...Array<string>(shape.bench).fill('BN'), ...Array<string>(shape.ir).fill('IR')]
}

const REACH: Record<string, number> = Object.fromEntries(
  ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'].map((p) => [
    p,
    Object.values(SLOT_ELIGIBILITY).filter((e) => e.includes(p)).length,
  ]),
)

export interface FitResult {
  assigned: { slot: string; playerId: string | null }[]
  unplaced: string[]
}

/** Place chosen starters into slots, most-restrictive slot first (mirrors fit_to_slots). */
export function fitToSlots(players: { id: string; position: string }[], slots: string[]): FitResult {
  const order = slots
    .map((s, i) => ({ s, i }))
    .sort((a, b) => SLOT_ELIGIBILITY[a.s].length - SLOT_ELIGIBILITY[b.s].length || a.i - b.i)
  const remaining = [...players]
  const assigned: FitResult['assigned'] = slots.map((slot) => ({ slot, playerId: null }))
  for (const { s, i } of order) {
    const cands = remaining.filter((p) => SLOT_ELIGIBILITY[s].includes(p.position))
    if (!cands.length) continue
    const pick = cands.reduce((a, b) => ((REACH[b.position] ?? 1) < (REACH[a.position] ?? 1) ? b : a))
    remaining.splice(remaining.indexOf(pick), 1)
    assigned[i] = { slot: s, playerId: pick.id }
  }
  return { assigned, unplaced: remaining.map((p) => p.id) }
}

export type Role = 'starter' | 'bench' | 'ir'

export interface RosterProblem {
  ok: boolean
  messages: string[]
}

/** Same checks the API enforces, so the form can explain problems before submitting. */
export function checkRoster(
  players: { id: string; position: string; role: Role; name: string }[],
  shape: LineupShape,
): RosterProblem {
  const slots = startingSlots(shape)
  const msgs: string[] = []
  const starters = players.filter((p) => p.role === 'starter')
  const bench = players.filter((p) => p.role === 'bench')
  const ir = players.filter((p) => p.role === 'ir')
  if (!slots.length) msgs.push('Add at least one starting slot.')
  if (starters.length > slots.length) msgs.push(`${starters.length} starters but only ${slots.length} starting slots.`)
  const { unplaced } = fitToSlots(starters, slots)
  if (unplaced.length) {
    const names = players.filter((p) => unplaced.includes(p.id)).map((p) => `${p.name} (${p.position})`)
    msgs.push(`No open lineup slot for ${names.join(', ')} — move to bench or add a slot.`)
  }
  if (bench.length > shape.bench) msgs.push(`${bench.length} bench players but only ${shape.bench} bench spots.`)
  if (ir.length > shape.ir) msgs.push(`${ir.length} players on IR but only ${shape.ir} IR spots.`)
  return { ok: msgs.length === 0, messages: msgs }
}

/** Where a newly added player should go: start if an eligible slot is open, else bench, else nowhere. */
export function defaultRole(
  newPlayer: { id: string; position: string },
  players: { id: string; position: string; role: Role }[],
  shape: LineupShape,
): Role | null {
  const starters = players.filter((p) => p.role === 'starter')
  if (!fitToSlots([...starters, newPlayer], startingSlots(shape)).unplaced.length) return 'starter'
  if (players.filter((p) => p.role === 'bench').length < shape.bench) return 'bench'
  return null
}

/** Inverse of rosterPositions(): count slots back into an editable shape. */
export function shapeFromRosterPositions(rp: string[]): LineupShape {
  const slots: Record<string, number> = Object.fromEntries(SLOT_ORDER.map((s) => [s, 0]))
  let bench = 0
  let ir = 0
  for (const s of rp) {
    if (s === 'BN' || s === 'TAXI') bench++
    else if (s === 'IR') ir++
    else if (s in slots) slots[s]++
    else if (s === 'WRRB_FLEX' || s === 'REC_FLEX') slots.FLEX++ // closest editable equivalent
  }
  return { slots, bench, ir }
}
