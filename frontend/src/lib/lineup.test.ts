import { describe, expect, it } from 'vitest'

import { checkRoster, defaultRole, fitToSlots, LINEUP_PRESETS, rosterPositions, type Role, shapeFromRosterPositions } from './lineup'

const std = LINEUP_PRESETS.standard.shape

const P = (id: string, position: string, role: Role = 'starter') => ({ id, position, role, name: id })

describe('lineup helpers', () => {
  it('builds Sleeper-style roster positions with variable bench and IR depth', () => {
    const rp = rosterPositions({ ...std, bench: 3, ir: 2 })
    expect(rp.filter((s) => s === 'BN')).toHaveLength(3)
    expect(rp.filter((s) => s === 'IR')).toHaveLength(2)
    expect(rp.slice(0, 9)).toEqual(['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'FLEX', 'K', 'DEF'])
  })

  it('fits an extra RB into FLEX and rejects a second QB without SUPER_FLEX', () => {
    const fit = fitToSlots([P('r1', 'RB'), P('r2', 'RB'), P('r3', 'RB')], ['RB', 'RB', 'FLEX'])
    expect(fit.unplaced).toEqual([])
    expect(fitToSlots([P('q1', 'QB'), P('q2', 'QB')], ['QB', 'FLEX']).unplaced).toEqual(['q2'])
  })

  it('places new players in the lineup first, then on the bench, then refuses', () => {
    const shape = { slots: { QB: 1 }, bench: 1, ir: 0 }
    expect(defaultRole(P('q1', 'QB'), [], shape)).toBe('starter')
    expect(defaultRole(P('q2', 'QB'), [P('q1', 'QB')], shape)).toBe('bench')
    expect(defaultRole(P('q3', 'QB'), [P('q1', 'QB'), P('q2', 'QB', 'bench')], shape)).toBeNull()
  })

  it('explains roster problems the API would reject', () => {
    const shape = { slots: { QB: 1, RB: 1 }, bench: 1, ir: 0 }
    const res = checkRoster([P('q1', 'QB'), P('q2', 'QB'), P('r1', 'RB', 'bench'), P('r2', 'RB', 'ir')], shape)
    expect(res.ok).toBe(false)
    expect(res.messages.join(' ')).toMatch(/No open lineup slot for q2/)
    expect(res.messages.join(' ')).toMatch(/only 0 IR spots/)
    expect(checkRoster([P('q1', 'QB'), P('r1', 'RB'), P('r2', 'RB', 'bench')], shape).ok).toBe(true)
  })
})

describe('shapeFromRosterPositions', () => {
  it('round-trips with rosterPositions', () => {
    const shape = { ...std, bench: 4, ir: 2 }
    expect(shapeFromRosterPositions(rosterPositions(shape))).toEqual(shape)
  })
})
