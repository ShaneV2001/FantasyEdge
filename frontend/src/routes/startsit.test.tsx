import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { StartSitOut, StartSitPlayer } from '@/api'
import { renderPage } from '@/test/render'
import { useTeamStore } from '@/stores/team'

import { StartSitPage } from './startsit'

const pl = (id: string, position: string, points: number, over: Partial<StartSitPlayer> = {}): StartSitPlayer => ({
  player: { player_id: id, name: id, position, nfl_team: 'KC' },
  points,
  opponent: 'LV',
  matchup_index: 1.1,
  on_bye: false,
  injury_status: null,
  locked: false,
  reserved: false,
  ...over,
})

const DATA: StartSitOut = {
  team_id: 'sl-1-1',
  week: 7,
  weeks: [7, 8],
  slots: [
    { slot: 'QB', label: 'QB', eligible: ['QB'] },
    { slot: 'RB', label: 'RB', eligible: ['RB'] },
    { slot: 'WR', label: 'WR', eligible: ['WR'] },
    { slot: 'FLEX', label: 'FLEX', eligible: ['RB', 'TE', 'WR'] },
  ],
  players: [
    pl('Quarter Back', 'QB', 20),
    pl('Run Ner', 'RB', 15),
    pl('Wide Out', 'WR', 14),
    pl('Bench Star', 'WR', 12),
    pl('Slow Back', 'RB', 9),
    pl('Thursday Guy', 'TE', 0, { locked: true }),
    pl('Hurt Guy', 'WR', 0, { reserved: true, injury_status: 'IR' }),
  ],
  current: ['Quarter Back', 'Run Ner', 'Wide Out', 'Slow Back'],
  optimal: ['Quarter Back', 'Run Ner', 'Wide Out', 'Bench Star'],
  current_points: 58,
  optimal_points: 61,
  gap: 3,
  has_lineup: true,
}

const stat = (label: string) => within(screen.getByText(label).parentElement!).getAllByText(/\d/)[0].textContent

describe('StartSitPage', () => {
  beforeEach(() => {
    useTeamStore.getState().setTeam({ teamId: 'sl-1-1', leagueId: 'sl-1', teamName: 'Team Alpha', leagueName: 'Fixture', platform: 'espn' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(DATA), { headers: { 'Content-Type': 'application/json' } })))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('says the planner never changes the real lineup', async () => {
    renderPage(<StartSitPage />)
    expect(await screen.findByText(/Planner — changes here don't change your lineup on ESPN/)).toBeInTheDocument()
    await screen.findByText('This lineup')
    expect(stat('This lineup')).toBe('58.0')
    expect(stat('Best lineup')).toBe('61.0')
  })

  it('tap a bench player, then a slot: the total updates; undo, redo and reset work', async () => {
    renderPage(<StartSitPage />)
    await screen.findByText('Bench Star')
    await userEvent.click(screen.getByRole('button', { name: /^Bench Star/ }))
    await userEvent.click(screen.getByRole('button', { name: /^Slow Back/ })) // swap into the FLEX
    expect(stat('This lineup')).toBe('61.0')
    expect(within(screen.getByTestId('slot-3')).getByText('Bench Star')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Undo/ }))
    expect(stat('This lineup')).toBe('58.0')
    await userEvent.keyboard('{Control>}{Shift>}z{/Shift}{/Control}') // redo
    expect(stat('This lineup')).toBe('61.0')
    await userEvent.keyboard('{Control>}z{/Control}') // undo
    expect(stat('This lineup')).toBe('58.0')

    await userEvent.click(screen.getByRole('button', { name: /Use best lineup/ }))
    expect(stat('This lineup')).toBe('61.0')
    await userEvent.click(screen.getByRole('button', { name: /Reset to my real lineup/ }))
    expect(stat('This lineup')).toBe('58.0')
  })

  it('rejects a move the slot does not allow', async () => {
    renderPage(<StartSitPage />)
    await screen.findByText('Bench Star')
    await userEvent.click(screen.getByRole('button', { name: /^Bench Star/ }))
    await userEvent.click(screen.getByRole('button', { name: /^Run Ner/ })) // WR into the RB slot
    expect(within(screen.getByTestId('slot-1')).getByText('Run Ner')).toBeInTheDocument()
    expect(stat('This lineup')).toBe('58.0')
  })

  it('locked and IR players cannot be picked up', async () => {
    renderPage(<StartSitPage />)
    await screen.findByText('Thursday Guy')
    await userEvent.click(screen.getByRole('button', { name: /^Thursday Guy/ }))
    expect(screen.getByRole('button', { name: /^Thursday Guy/ })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText("IR / taxi (can't start)")).toBeInTheDocument()
    expect(screen.getByText(/have kicked off \(or finished\) this week/)).toBeInTheDocument()
  })

  it('copies the lineup as text', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    renderPage(<StartSitPage />)
    await screen.findByText('Bench Star')
    await userEvent.click(screen.getByRole('button', { name: /Copy lineup/ }))
    expect(writeText).toHaveBeenCalledWith(expect.stringContaining('Week 7 lineup · 58.0 projected pts\nQB: Quarter Back (KC) · 20.0'))
  })
})
