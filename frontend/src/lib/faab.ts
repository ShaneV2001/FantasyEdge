/** How FAAB bids are suggested (mirrors backend/signals/waivers.py::faab_bid). */
export const FAAB_FORMULA =
  'Bid = remaining budget × min(net gain ÷ full-bid gain, 1) × aggression, never below the minimum bid or above what you have left. The range shown is 75%–125% of that.'

export interface FaabSettings {
  full_gain: number
  aggression: number
  min_bid: number
}

/** The formula with the user's current numbers filled in. */
export function faabFormula(s: FaabSettings, remaining?: number | null): string {
  const budget = remaining != null ? `$${remaining}` : 'remaining budget'
  return `Bid = ${budget} × min(gain ÷ ${s.full_gain} pts, 1) × ${s.aggression}, at least $${s.min_bid}.`
}

export function fmtBid(low: number, high: number): string {
  return low === high ? `$${low}` : `$${low}–${high}`
}
