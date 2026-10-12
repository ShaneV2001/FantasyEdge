import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { BuyTargetRow, BuyTargetsOut } from '@/api'
import { renderPage as renderWithRouter } from '@/test/render'
import { useTeamStore } from '@/stores/team'

import { BuyTargetsPage } from './buy-targets'

const row = (name: string, gap: number, over: Partial<BuyTargetRow> = {}): BuyTargetRow => ({
  rank: 1,
  player_id: name,
  name,
  position: 'RB',
  nfl_team: 'GB',
  owner: 'Team Bravo',
  mine: false,
  model_points: 150,
  model_rank: 19,
  market_rank: 30,
  market_implied_points: 150 - gap,
  value_gap: gap,
  signal: gap > 0 ? 'buy' : 'sell',
  reasons: ['We project 150 rest-of-season points (RB19); FantasyCalc prices him like our RB30 (~110).', 'Second reason'],
  ppg: 12,
  availability_note: null,
  cells: [{ week: 6, opponent: 'CHI', index: 1.2, points: 13 }],
  tier: 'starter',
  ...over,
})

const empty = { has_market: true, starter_line: 30, buy: [], sell: [] }
const DATA: BuyTargetsOut = {
  team_id: 'sl-1-1',
  week: 6,
  last_week: 17,
  market_label: 'FantasyCalc',
  positions: {
    QB: empty,
    RB: {
      has_market: true,
      starter_line: 30,
      buy: [row('Josh Jacobs', 41), row('Deep Sleeper', 60, { model_points: 90, model_rank: 44, tier: 'depth' })],
      sell: [row('My Pricey Back', -25, { mine: true, owner: 'Your team' })] },
    WR: empty,
    TE: empty,
    K: { has_market: false, starter_line: 13, buy: [], sell: [] },
    DEF: { has_market: false, starter_line: 13, buy: [], sell: [] },
  },
}

describe('BuyTargetsPage', () => {
  beforeEach(() => {
    useTeamStore.getState().setTeam({ teamId: 'sl-1-1', leagueId: 'sl-1', teamName: 'A', leagueName: 'L', platform: 'sleeper' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(DATA), { headers: { 'Content-Type': 'application/json' } })))
  })
  afterEach(() => vi.unstubAllGlobals())

function renderPage() {
  return renderWithRouter(<BuyTargetsPage />)
}

  it('lists undervalued buys and your overvalued sells', async () => {
    renderPage()
    expect(await screen.findByText('Josh Jacobs')).toBeInTheDocument()
    expect(screen.getByText('+41')).toBeInTheDocument()
    expect(screen.getByText('My Pricey Back')).toBeInTheDocument()
    expect(screen.getByText('−25')).toBeInTheDocument()
    expect(screen.getAllByText('Second reason')).toHaveLength(3)
  })

  it('lists would-be starters before bench depth and sleepers', async () => {
    renderPage()
    await screen.findByText('Josh Jacobs')
    const starters = screen.getByRole('heading', { name: 'Starters' })
    const depth = screen.getByRole('heading', { name: 'Bench depth & sleepers' })
    expect(starters.compareDocumentPosition(depth) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const jacobs = screen.getByText('Josh Jacobs')
    expect(jacobs.compareDocumentPosition(screen.getByText('Deep Sleeper')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByText(/RB1–RB29/)).toBeInTheDocument()
  })

  it('explains positions without market values', async () => {
    renderPage()
    await screen.findByText('Josh Jacobs')
    await userEvent.click(screen.getByRole('tab', { name: 'DEF' }))
    expect(screen.getByText(/doesn't value DEFs/)).toBeInTheDocument()
  })
})
