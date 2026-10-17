import { describe, expect, it } from 'vitest'

import { history } from '@/hooks/useHistory'

import { canMove, canPlace, lineupText, move, sameLineup, total, type PlanRules } from './startsit'

const rules: PlanRules = {
  slots: ['QB', 'RB', 'WR', 'TE', 'FLEX'],
  positionOf: { qb: 'QB', rb1: 'RB', rb2: 'RB', wr1: 'WR', wr2: 'WR', te: 'TE', ir: 'WR', done: 'RB' },
  locked: new Set(['done']),
  reserved: new Set(['ir']),
}
const lineup = ['qb', 'rb1', 'wr1', 'te', 'rb2']

describe('canPlace', () => {
  it('follows slot eligibility', () => {
    expect(canPlace('RB', 'FLEX')).toBe(true)
    expect(canPlace('QB', 'FLEX')).toBe(false)
    expect(canPlace('QB', 'SUPER_FLEX')).toBe(true)
    expect(canPlace('WR', 'TE')).toBe(false)
    expect(canPlace(undefined, 'WR')).toBe(false)
  })
})

describe('move', () => {
  it('a bench player replaces a starter, who goes to the bench', () => {
    expect(move(lineup, rules, 'wr2', { slot: 4 })).toEqual(['qb', 'rb1', 'wr1', 'te', 'wr2'])
  })

  it('rejects a player the slot does not take', () => {
    expect(move(lineup, rules, 'wr2', { slot: 3 })).toBeNull() // WR into TE
    expect(move(lineup, rules, 'qb', { slot: 4 })).toBeNull() // QB into FLEX
    expect(canMove(lineup, rules, 'wr2', { slot: 0 })).toBe(false)
  })

  it('swaps two starters when both fit, else the displaced one is benched', () => {
    // RB in FLEX <-> RB slot: both fit both
    expect(move(lineup, rules, 'rb2', { slot: 1 })).toEqual(['qb', 'rb2', 'wr1', 'te', 'rb1'])
    // WR from the WR slot into FLEX: the RB there can't play WR, so he sits
    expect(move(lineup, rules, 'wr1', { slot: 4 })).toEqual(['qb', 'rb1', null, 'te', 'wr1'])
  })

  it('locked players never move and are never replaced', () => {
    const withDone = ['qb', 'done', 'wr1', 'te', 'rb2']
    expect(move(withDone, rules, 'done', 'bench')).toBeNull()
    expect(move(withDone, rules, 'rb1', { slot: 1 })).toBeNull()
    expect(move(withDone, rules, 'done', { slot: 4 })).toBeNull()
  })

  it('IR players cannot start', () => {
    expect(move(lineup, rules, 'ir', { slot: 2 })).toBeNull()
  })

  it('benching a starter empties his slot; no-ops are rejected', () => {
    expect(move(lineup, rules, 'te', 'bench')).toEqual(['qb', 'rb1', 'wr1', null, 'rb2'])
    expect(move(lineup, rules, 'wr2', 'bench')).toBeNull() // already on the bench
    expect(move(lineup, rules, 'qb', { slot: 0 })).toBeNull() // same slot
  })
})

describe('totals and text', () => {
  const points = { qb: 20, rb1: 15.5, wr1: 12, te: 6.25, rb2: 9, wr2: 11 }
  it('adds up the starters', () => {
    expect(total(lineup, points)).toBe(62.75)
    expect(total(['qb', null, null, null, null], points)).toBe(20)
    expect(sameLineup(lineup, [...lineup])).toBe(true)
    expect(sameLineup(lineup, ['qb', 'rb1', 'wr1', 'te', 'wr2'])).toBe(false)
  })

  it('copies the lineup as text', () => {
    const info = { qb: { name: 'Josh Allen', team: 'BUF', points: 20 }, rb1: { name: 'Bijan Robinson', team: 'ATL', points: 15.5 } }
    expect(lineupText(7, ['qb', 'rb1', null], ['QB', 'RB', 'FLEX'], info)).toBe(
      'Week 7 lineup · 35.5 projected pts\nQB: Josh Allen (BUF) · 20.0\nRB: Bijan Robinson (ATL) · 15.5\nFLEX: (empty)',
    )
  })
})

describe('undo / redo history', () => {
  it('steps back and forward, and a new move clears redo', () => {
    let h = history.init('a')
    h = history.push(h, 'b')
    h = history.push(h, 'c')
    h = history.undo(h)
    expect(h.present).toBe('b')
    h = history.undo(h)
    expect(h.present).toBe('a')
    expect(history.undo(h)).toBe(h) // nothing left to undo
    h = history.redo(h)
    expect(h.present).toBe('b')
    h = history.push(h, 'x')
    expect(h.future).toEqual([])
    expect(history.redo(h)).toBe(h)
    expect(h.past).toEqual(['a', 'b'])
  })
})
