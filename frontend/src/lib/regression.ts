import type { PlayerFlagsOut } from '@/api'

export const PAGE = 20

export interface RegressionFilters {
  pos: 'ALL' | 'QB' | 'RB' | 'WR' | 'TE'
  /** sell: his biggest flag says he'll cool off; buy: it says he'll bounce back */
  dir: 'all' | 'sell' | 'buy'
  /** 'all', 'fa' (free agents) or a fantasy team id */
  team: string
}

export const NO_FILTERS: RegressionFilters = { pos: 'ALL', dir: 'all', team: 'all' }

/** Flagged players matching the filters, strongest flag first (ties by name). */
export function filterRegression(rows: PlayerFlagsOut[], f: RegressionFilters): PlayerFlagsOut[] {
  return rows
    .filter((r) => r.flags.length > 0)
    .filter((r) => f.pos === 'ALL' || r.player.position === f.pos)
    .filter((r) => f.dir === 'all' || (f.dir === 'sell' ? (r.direction ?? 0) < 0 : (r.direction ?? 0) > 0))
    .filter((r) => f.team === 'all' || (f.team === 'fa' ? !r.team_id : r.team_id === f.team))
    .sort((a, b) => (b.strength ?? 0) - (a.strength ?? 0) || a.player.name.localeCompare(b.player.name))
}

/** Fantasy teams that hold a flagged player, for the team filter (plus whether any are free agents). */
export function teamOptions(rows: PlayerFlagsOut[]): { teams: { id: string; name: string }[]; freeAgents: boolean } {
  const seen = new Map<string, string>()
  let freeAgents = false
  for (const r of rows) {
    if (!r.flags.length) continue
    if (r.team_id) seen.set(r.team_id, r.team_name ?? r.team_id)
    else freeAgents = true
  }
  const teams = [...seen].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name))
  return { teams, freeAgents }
}
