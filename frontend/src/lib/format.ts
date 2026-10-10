export const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'] as const
export type Position = (typeof POSITIONS)[number]

/** Tailwind classes per position — one fixed colour used everywhere. */
export const POSITION_CLASS: Record<string, string> = {
  QB: 'bg-pos-qb/15 text-pos-qb ring-pos-qb/30',
  RB: 'bg-pos-rb/15 text-pos-rb ring-pos-rb/30',
  WR: 'bg-pos-wr/15 text-pos-wr ring-pos-wr/30',
  TE: 'bg-pos-te/15 text-pos-te ring-pos-te/30',
  K: 'bg-pos-k/15 text-pos-k ring-pos-k/30',
  DEF: 'bg-pos-def/15 text-pos-def ring-pos-def/30',
}

export const POSITION_VAR: Record<string, string> = {
  QB: 'var(--pos-qb)',
  RB: 'var(--pos-rb)',
  WR: 'var(--pos-wr)',
  TE: 'var(--pos-te)',
  K: 'var(--pos-k)',
  DEF: 'var(--pos-def)',
}

export function fmtNum(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtSigned(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const s = fmtNum(Math.abs(n), digits)
  return n > 0 ? `+${s}` : n < 0 ? `−${s}` : s
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return Math.round(n).toLocaleString()
}

export function fmtRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return 'never'
  // API timestamps are naive UTC
  const t = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
  const s = Math.round((now.getTime() - t.getTime()) / 1000)
  if (s < 45) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} h ago`
  return `${Math.round(h / 24)} d ago`
}

export type Signal = 'buy' | 'sell' | 'hold'

/** Regression score → buy/sell/hold (same thresholds as the advisor: ±1). */
export function signalFor(score: number | null | undefined): Signal {
  if (score === null || score === undefined) return 'hold'
  if (score >= 1) return 'buy'
  if (score <= -1) return 'sell'
  return 'hold'
}

export const URGENCY_LABEL: Record<string, string> = {
  this_week: 'This week',
  before_byes: 'Before byes',
  before_deadline: 'Before deadline',
  rest_of_season: 'Rest of season',
}

export const GRADE_CLASS: Record<string, string> = {
  A: 'text-buy',
  B: 'text-buy/80',
  C: 'text-muted-foreground',
  D: 'text-sell/80',
  F: 'text-sell',
}

export function slotLabel(slot: string): string {
  return { SUPER_FLEX: 'SFLEX', WRRB_FLEX: 'W/R', REC_FLEX: 'W/T' }[slot] ?? slot
}
