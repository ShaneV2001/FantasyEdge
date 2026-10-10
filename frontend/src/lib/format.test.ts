import { describe, expect, it } from 'vitest'

import { fmtNum, fmtRelative, fmtSigned, signalFor, slotLabel } from './format'

describe('formatters', () => {
  it('formats numbers and missing values', () => {
    expect(fmtNum(12.345)).toBe('12.3')
    expect(fmtNum(null)).toBe('—')
    expect(fmtNum(7, 0)).toBe('7')
  })

  it('signs deltas with a real minus sign', () => {
    expect(fmtSigned(4.25)).toBe('+4.3')
    expect(fmtSigned(-2)).toBe('−2.0')
    expect(fmtSigned(0)).toBe('0.0')
  })

  it('maps regression scores to buy/sell/hold at ±1', () => {
    expect(signalFor(1.2)).toBe('buy')
    expect(signalFor(-1)).toBe('sell')
    expect(signalFor(0.5)).toBe('hold')
    expect(signalFor(undefined)).toBe('hold')
  })

  it('treats naive API timestamps as UTC', () => {
    const now = new Date('2026-10-10T12:00:00Z')
    expect(fmtRelative('2026-10-10T11:50:00', now)).toBe('10 min ago')
    expect(fmtRelative('2026-10-10T09:00:00Z', now)).toBe('3 h ago')
    expect(fmtRelative(null, now)).toBe('never')
  })

  it('labels flex slots compactly', () => {
    expect(slotLabel('SUPER_FLEX')).toBe('SFLEX')
    expect(slotLabel('RB')).toBe('RB')
  })
})
