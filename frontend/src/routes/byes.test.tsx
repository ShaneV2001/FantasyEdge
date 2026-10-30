import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ByesOut, ByeWeekOut, PendingTradesOut, SlotCellOut } from '@/api'
import { useTeamStore } from '@/stores/team'
import { renderPage } from '@/test/render'

import { ByesPage } from './byes'

const ref = (name: string, position: string) => ({ player_id: name, name, position, nfl_team: 'DET' })
const cell = (label: string, name: string | null, over: Partial<SlotCellOut> = {}): SlotCellOut => ({
  slot: label,
  label,
  status: 'ok',
  player: name ? ref(name, label) : null,
  ppg: 10,
  ...over,
})

const week = (n: number, cells: SlotCellOut[], over: Partial<ByeWeekOut> = {}): ByeWeekOut => ({
  week: n,
  weeks_away: n - 6,
  cells,
  on_bye: [],
  starters_on_bye: [],
  danger: false,
  danger_slots: [],
  lineup_points: 120,
  full_strength_points: 120,
  points_lost: 0,
  ...over,
})

// RB is weak ("thin") every week, which used to paint it amber everywhere; now only byes count
const normal = (n: number) =>
  week(n, [cell('RB', 'Woody Marks', { status: 'thin' }), cell('WR', 'Amon-Ra St. Brown'), cell('TE', 'Sam LaPorta')])

const DATA: ByesOut = {
  team_id: 't',
  week: 6,
  last_week: 9,
  slots: ['RB', 'WR', 'TE'],
  players: [],
  danger_weeks: [7],
  weeks: [
    normal(6),
    week(
      7,
      [
        cell('RB', 'Woody Marks', { status: 'thin' }),
        cell('WR', 'Luther Burden', { replaces: 'Amon-Ra St. Brown', why: 'bye' }),
        cell('TE', null, { status: 'empty', hole: true, ppg: null }),
      ],
      { danger: true, danger_slots: ['TE'], starters_on_bye: ['Amon-Ra St. Brown', 'Sam LaPorta'], lineup_points: 98.6, points_lost: 21.4 },
    ),
    normal(8),
    normal(9),
  ],
}

describe('ByesPage', () => {
  beforeEach(() => {
    useTeamStore.getState().setTeam({ teamId: 't', leagueId: 'l', teamName: 'Team', leagueName: 'League', platform: 'sleeper' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(DATA), { headers: { 'Content-Type': 'application/json' } })))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('opens on the weeks a bye changes, colors only those cells, and shows points lost', async () => {
    renderPage(<ByesPage />)
    const grid = await screen.findByTestId('bye-grid')
    expect(within(grid).getByText('Wk 7')).toBeInTheDocument()
    expect(within(grid).queryByText('Wk 6')).not.toBeInTheDocument() // unchanged weeks are tucked away
    expect(within(grid).getByText('−21.4')).toBeInTheDocument()
    expect(within(grid).getByText('EMPTY').closest('[data-kind]')).toHaveAttribute('data-kind', 'hole')
    expect(within(grid).getByText(/for St. Brown · bye/)).toBeInTheDocument()
    // a weak starter all season is not a bye problem: no color
    expect(within(grid).getByText('Marks').closest('[data-kind]')).toHaveAttribute('data-kind', 'normal')
    expect(screen.getByText('1 week with lineup holes')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Show all 4 weeks (3 unchanged)' }))
    expect(within(grid).getByText('Wk 6')).toBeInTheDocument()
    expect(within(grid).getAllByText('full')).toHaveLength(3)
    await userEvent.click(screen.getByRole('button', { name: 'Only weeks with changes' }))
    expect(within(grid).queryByText('Wk 6')).not.toBeInTheDocument()
  })

  it('tells apart players who share a last name', async () => {
    const twoRobinsons = week(7, [cell('RB', 'Bijan Robinson'), cell('WR', "Wan'Dale Robinson"), cell('TE', 'Sam LaPorta')], {
      points_lost: 2,
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ...DATA, weeks: [twoRobinsons] }), { headers: { 'Content-Type': 'application/json' } }),
      ),
    )
    renderPage(<ByesPage />)
    const grid = await screen.findByTestId('bye-grid')
    expect(within(grid).getByText('B. Robinson')).toBeInTheDocument()
    expect(within(grid).getByText('W. Robinson')).toBeInTheDocument()
    expect(within(grid).getByText('LaPorta')).toBeInTheDocument()
  })

  it('shows every week when no bye changes anything', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ ...DATA, danger_weeks: [], weeks: [normal(6), normal(8)] }), {
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    renderPage(<ByesPage />)
    const grid = await screen.findByTestId('bye-grid')
    expect(within(grid).getByText('Wk 6')).toBeInTheDocument()
    expect(screen.getByText('No lineup holes')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Show all/ })).not.toBeInTheDocument()
  })
})

describe('ByesPage with accepted trades waiting on ESPN', () => {
  const ja = ref("Ja'Marr Chase", 'WR')
  const after7 = week(
    7,
    [
      cell('RB', 'Woody Marks', { status: 'thin' }),
      cell('WR', "Ja'Marr Chase"),
      cell('TE', null, { status: 'empty', hole: true, ppg: null, replaces: 'Sam LaPorta', why: 'bye' }),
    ],
    { danger: true, danger_slots: ['TE'], lineup_points: 104.2, points_lost: 18.1 },
  )
  const PENDING: PendingTradesOut = {
    team_id: 't',
    review_hours: 24,
    trades: [
      {
        id: 'p1',
        partner_team_id: 't2',
        partner_name: 'Rival',
        give: [ref('Amon-Ra St. Brown', 'WR')],
        receive: [ja],
        drops: [],
        accepted_at: '2026-10-28T20:00:00',
      },
    ],
    outlook: {
      week: 6,
      slots: DATA.slots,
      me: {
        team_id: 't',
        team_name: 'Team',
        gives: [ref('Amon-Ra St. Brown', 'WR')],
        receives: [ja],
        drops: [],
        before: DATA.weeks,
        after: [normal(6), after7, normal(8), normal(9)],
      },
      partner: null,
    },
  }

  beforeEach(() => {
    useTeamStore.getState().setTeam({ teamId: 't', leagueId: 'l', teamName: 'Team', leagueName: 'League', platform: 'espn' })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (req: Request) => Response.json(new URL(req.url).pathname.endsWith('/pending-trades') ? PENDING : DATA)),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists the pending trade and switches to the lineups after it', async () => {
    renderPage(<ByesPage />)
    const banner = await screen.findByTestId('pending-trades')
    expect(within(banner).getByText('1 accepted trade waiting on ESPN')).toBeInTheDocument()
    expect(within(banner).getByText("Give Amon-Ra St. Brown → get Ja'Marr Chase")).toBeInTheDocument()
    expect(within(banner).getByText(/reviews trades for 24 hours/)).toBeInTheDocument()

    await userEvent.click(within(banner).getByRole('radio', { name: 'After accepted trades' }))
    const weakest = await screen.findByRole('list', { name: 'Weakest weeks' })
    expect(within(weakest).getByText(/Week 7/)).toBeInTheDocument()
    expect(within(weakest).getByText('Out: Sam LaPorta (bye)')).toBeInTheDocument()
    expect(within(weakest).getByText('Nobody to start at TE')).toBeInTheDocument()
    expect(within(weakest).getByText(/\+5\.6 vs now/)).toBeInTheDocument() // 104.2 after vs 98.6 today
    const grid = screen.getByTestId('bye-grid')
    expect(within(grid).getByText('Chase')).toBeInTheDocument()
    expect(within(grid).getByText(/for LaPorta · bye/)).toBeInTheDocument() // the hole says who's missing
  })

  it('shows nothing extra without pending trades', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (req: Request) =>
        Response.json(new URL(req.url).pathname.endsWith('/pending-trades') ? { ...PENDING, trades: [], outlook: null } : DATA),
      ),
    )
    renderPage(<ByesPage />)
    await screen.findByTestId('bye-grid')
    expect(screen.queryByTestId('pending-trades')).not.toBeInTheDocument()
  })
})
