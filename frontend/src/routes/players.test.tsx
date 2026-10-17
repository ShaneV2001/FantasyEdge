import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PlayerTableRow, PlayersTableOut } from '@/api'
import { renderPage } from '@/test/render'
import { useTeamStore } from '@/stores/team'

import { PlayersPage, cleanSearch, playersSearchSchema } from './players'

const row = (name: string, over: Partial<PlayerTableRow> = {}): PlayerTableRow => ({
  player_id: name,
  name,
  position: 'WR',
  nfl_team: 'CIN',
  owner: 'Free agent',
  mine: false,
  ppg: 14.2,
  ros_points: 150.5,
  ros_value_par: 40,
  market_value: 5200,
  signal: 'buy',
  value_gap: 12,
  injury_status: null,
  bye_week: 10,
  ...over,
})

const DATA: PlayersTableOut = {
  team_id: 'sl-1-1',
  rows: [row('Waiver Wideout'), row('My Runner', { position: 'RB', owner: 'Your team', mine: true, signal: 'hold' })],
  total: 120,
  page: 0,
  size: 50,
  nfl_teams: ['CIN', 'KC'],
  market_label: 'FantasyCalc',
}

let fetchMock: ReturnType<typeof vi.fn>
const urls = () => fetchMock.mock.calls.map(([req]) => new URL(req instanceof Request ? req.url : String(req)))
const lastQuery = () => Object.fromEntries(urls().at(-1)!.searchParams)

function setTeam(platform: 'sleeper' | 'manual') {
  useTeamStore.getState().setTeam({ teamId: 'sl-1-1', leagueId: 'sl-1', teamName: 'Team Alpha', leagueName: 'Fixture', platform })
}

describe('PlayersPage', () => {
  beforeEach(() => {
    setTeam('sleeper')
    fetchMock = vi.fn(async () => new Response(JSON.stringify(DATA), { headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('reads filters and sort from the URL', async () => {
    renderPage(<PlayersPage />, '/?pos=WR&avail=fa&sort=ppg&team=CIN&page=1')
    expect(await screen.findByText('Waiver Wideout')).toBeInTheDocument()
    expect(lastQuery()).toMatchObject({ pos: 'WR', avail: 'fa', sort: 'ppg', dir: 'desc', team: 'CIN', page: '1', size: '50' })
    expect(screen.getByText('Your team')).toBeInTheDocument()
    expect(screen.getByText(/51–100 of 120/)).toBeInTheDocument()
  })

  it('clicking a column header sorts by it, best first, then flips', async () => {
    renderPage(<PlayersPage />)
    await screen.findByText('Waiver Wideout')
    expect(lastQuery()).toMatchObject({ sort: 'ros', dir: 'desc', avail: 'all' })

    await userEvent.click(screen.getByRole('button', { name: 'Sort by market value' }))
    await waitFor(() => expect(lastQuery()).toMatchObject({ sort: 'market', dir: 'desc' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sort by market value' }))
    await waitFor(() => expect(lastQuery()).toMatchObject({ sort: 'market', dir: 'asc' }))
  })

  it('paging and filters go to the server', async () => {
    renderPage(<PlayersPage />)
    await screen.findByText('Waiver Wideout')
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
    await waitFor(() => expect(lastQuery().page).toBe('1'))
    await userEvent.click(screen.getByRole('radio', { name: 'RB' }))
    await waitFor(() => expect(lastQuery()).toMatchObject({ pos: 'RB', page: '0' })) // a new filter starts on page 1
    await userEvent.type(screen.getByLabelText('Search players'), 'chase')
    await waitFor(() => expect(lastQuery().q).toBe('chase'))
  })

  it('a manual team only filters by its own players', async () => {
    setTeam('manual')
    renderPage(<PlayersPage />, '/?avail=fa')
    await screen.findByText('Waiver Wideout')
    expect(lastQuery().avail).toBe('all') // can't know who else owns a player
    expect(screen.queryByRole('radio', { name: 'Free agents' })).not.toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'My team' })).toBeInTheDocument()
  })
})

describe('players search params', () => {
  it('bad values fall back to defaults', () => {
    expect(playersSearchSchema.parse({ pos: 'OL', sort: 'height', page: '-3', dir: 'up' })).toEqual({})
    expect(playersSearchSchema.parse({ pos: 'TE', page: '2' })).toEqual({ pos: 'TE', page: 2 })
  })

  it('keeps defaults out of the URL', () => {
    expect(cleanSearch({ q: '  ', avail: 'all', sort: 'ros', dir: 'desc', page: 0 })).toEqual({})
    expect(cleanSearch({ sort: 'name', dir: 'asc' })).toEqual({ sort: 'name' })
    expect(cleanSearch({ sort: 'ppg', dir: 'asc', avail: 'fa', q: ' Bijan ' })).toEqual({ sort: 'ppg', dir: 'asc', avail: 'fa', q: 'Bijan' })
  })
})
