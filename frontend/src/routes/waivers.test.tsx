import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WaiverRow, WaiversOut } from '@/api'
import { faabFormula, fmtBid } from '@/lib/faab'
import { renderPage } from '@/test/render'
import { useTeamStore } from '@/stores/team'

import { WaiversPage } from './waivers'

const ref = (name: string, position = 'WR') => ({ player_id: name, name, position, nfl_team: 'CIN' })

const row = (rank: number, name: string, over: Partial<WaiverRow> = {}): WaiverRow => ({
  rank,
  player: ref(name),
  ppg: 11.2,
  ros_points: 120,
  gain: 44.5,
  gain_per_week: 4.05,
  drop: ref('Bench Guy', 'TE'),
  drop_ppg: 3.1,
  fixes_weeks: [],
  need: false,
  injury_status: null,
  bye_week: 10,
  signal: 'hold',
  faab: { low: 19, bid: 25, high: 31 },
  ...over,
})

const DATA: WaiversOut = {
  team_id: 'sl-1-1',
  week: 7,
  last_week: 17,
  rows: [
    row(1, 'Wide Out'),
    row(2, 'Bye Fixer', { player: ref('Bye Fixer', 'DEF'), fixes_weeks: [9], need: true, drop: null, faab: { low: 2, bid: 3, high: 4 } }),
  ],
  needs: ['WR'],
  faab: { uses_faab: true, budget: 100, remaining: 80, full_gain: 40, aggression: 0.5, min_bid: 1 },
  trending: [{ player: ref('Hot Rookie', 'RB'), adds: 41200, owner: 'Free agent', mine: false, ppg: 9.5, signal: 'buy' }],
  trending_fetched_at: new Date().toISOString(),
  as_of: new Date().toISOString(),
  message: null,
}

function serve(data: WaiversOut) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })))
}

describe('WaiversPage', () => {
  beforeEach(() => {
    useTeamStore.getState().setTeam({ teamId: 'sl-1-1', leagueId: 'sl-1', teamName: 'Team Alpha', leagueName: 'Fixture', platform: 'sleeper' })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('ranks pickups with the gain, the drop and a bid range', async () => {
    serve(DATA)
    renderPage(<WaiversPage />)
    expect(await screen.findByText('Wide Out')).toBeInTheDocument()
    expect(screen.getAllByText('+44.5')).toHaveLength(2)
    expect(screen.getByText('$19–31')).toBeInTheDocument()
    expect(screen.getByText('Fills wk 9')).toBeInTheDocument()
    expect(screen.getAllByText('Bench Guy').length).toBeGreaterThan(0)
    expect(screen.getByText(/\$80 of \$100 FAAB left/)).toBeInTheDocument()
    // trending, credited to Sleeper
    expect(screen.getByText('Hot Rookie')).toBeInTheDocument()
    expect(screen.getByText('+41,200')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sleeper API' })).toBeInTheDocument()
  })

  it('a player coming back later is tagged with his return week', async () => {
    serve({ ...DATA, rows: [row(1, 'Stash Back', { injury_status: 'IR', return_week: 13 })] })
    renderPage(<WaiversPage />)
    expect(await screen.findByText('Back wk 13')).toBeInTheDocument()
  })

  it('filters by position', async () => {
    serve(DATA)
    renderPage(<WaiversPage />)
    await screen.findByText('Wide Out')
    await userEvent.click(screen.getByRole('radio', { name: 'DEF' }))
    expect(screen.queryByText('Wide Out')).not.toBeInTheDocument()
    expect(screen.getByText('Bye Fixer')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'QB' }))
    expect(screen.getByText(/No free-agent QB improves your lineup/)).toBeInTheDocument()
  })

  it('explains the bid with the current settings', async () => {
    serve(DATA)
    renderPage(<WaiversPage />)
    await userEvent.click(await screen.findByRole('button', { name: /How bids are calculated/ }))
    expect(await screen.findByText('Bid = $80 × min(gain ÷ 40 pts, 1) × 0.5, at least $1.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Tune it in Settings/ })).toBeInTheDocument()
  })

  it('a waiver-priority league shows no bids', async () => {
    serve({ ...DATA, faab: { ...DATA.faab, uses_faab: false, remaining: null }, rows: DATA.rows.map((r) => ({ ...r, faab: null })) })
    renderPage(<WaiversPage />)
    await screen.findByText('Wide Out')
    expect(screen.queryByRole('columnheader', { name: 'Bid' })).not.toBeInTheDocument()
    expect(screen.getByText(/uses waiver priority/)).toBeInTheDocument()
  })

  it('a manual team gets a way to connect, and still sees trending adds', async () => {
    serve({ ...DATA, rows: [], message: "A manual team doesn't know who's on other rosters." })
    renderPage(<WaiversPage />)
    expect(await screen.findByText('No free agents for a manual team')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Connect a league' })).toBeInTheDocument()
    expect(screen.getByText('Hot Rookie')).toBeInTheDocument()
  })
})

describe('faab helpers', () => {
  it('formats the formula and ranges', () => {
    expect(faabFormula({ full_gain: 60, aggression: 0.3, min_bid: 2 })).toBe(
      'Bid = remaining budget × min(gain ÷ 60 pts, 1) × 0.3, at least $2.',
    )
    expect(fmtBid(5, 5)).toBe('$5')
    expect(fmtBid(4, 9)).toBe('$4–9')
  })
})
