import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PlayerDetailOut, PlayerTradesOut, TradeOut } from '@/api'
import { renderPage } from '@/test/render'

import { PlayerTrades, analyzerSearch } from './PlayerTrades'

const player = (over: Partial<PlayerDetailOut>): PlayerDetailOut => ({
  player_id: 'p1',
  name: 'Omarion Hampton',
  position: 'RB',
  nfl_team: 'LAC',
  headshot_url: null,
  team_logo_url: null,
  age: 23,
  years_exp: 1,
  depth_chart_order: 1,
  injury_status: null,
  availability_note: null,
  bye_week: 12,
  owner: 'NFL Youngboy',
  mine: false,
  ppg: 14,
  p10: 6,
  p90: 22,
  model_ros_points: 160,
  ros_value_par: 40,
  market_value: 2000,
  model_rank: 18,
  market_rank: 20,
  market_implied_points: 150,
  value_gap: 10,
  signal: 'hold',
  signal_reasons: [],
  flags: [],
  statline_keys: [],
  weeks: [],
  upcoming: [],
  ...over,
})

const side = (team: string, give: string, get: string) => ({
  team_id: team,
  team_name: team,
  gives: [{ player_id: give, name: give, position: 'WR' }],
  receives: [{ player_id: get, name: get, position: 'RB' }],
  lineup_before: 1000,
  lineup_after: 1010,
  lineup_delta: 10,
  model_value_out: 10,
  model_value_in: 12,
  market_value_out: null,
  market_value_in: null,
})

const IDEA: TradeOut = {
  verdict: 'accept',
  headline: 'Give Jaylen Waddle for Omarion Hampton',
  reasons: ['Your starting lineup gains 10.0 projected points rest of season; theirs gains 3.0.'],
  me: side('mine', 'w1', 'p1'),
  partner: side('their-team', 'p1', 'w1'),
  partner_accepts: true,
}

describe('PlayerTrades', () => {
  let urls: string[]
  beforeEach(() => {
    urls = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request | string) => {
        const req = input instanceof Request ? input : new Request(input)
        urls.push(req.url)
        const data: PlayerTradesOut = { team_id: 't', player: { player_id: 'p1', name: 'Omarion Hampton', position: 'RB' }, mode: 'buy', owner: 'NFL Youngboy', ideas: [IDEA] }
        return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
      }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it("trades for another team's player only when asked", async () => {
    const user = userEvent.setup()
    renderPage(<PlayerTrades d={player({})} teamId="t" manual={false} />)
    expect(await screen.findByText('Trade for Omarion Hampton')).toBeInTheDocument()
    expect(screen.queryByRole('radio')).not.toBeInTheDocument() // no position filter when buying
    expect(urls).toEqual([]) // nothing runs until you ask
    await user.click(screen.getByRole('button', { name: /Generate trades/ }))
    expect(await screen.findByText('Give Jaylen Waddle for Omarion Hampton')).toBeInTheDocument()
    expect(urls[0]).toContain('/team/t/players/p1/trades')
  })

  it('says every offer is fair, or names the closest package when none is', async () => {
    const user = userEvent.setup()
    renderPage(<PlayerTrades d={player({})} teamId="t" manual={false} />)
    await user.click(await screen.findByRole('button', { name: /Generate trades/ }))
    expect(await screen.findByText(/Every offer is fair by market value/)).toBeInTheDocument()
  })

  it('shows why there is no fair package', async () => {
    const note = "No fair package within 15%. Closest: A (6,100) for Omarion Hampton (9,671); you'd be short by 37%."
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        const data: PlayerTradesOut = { team_id: 't', player: { player_id: 'p1', name: 'Omarion Hampton', position: 'RB' }, mode: 'buy', owner: 'NFL Youngboy', ideas: [], message: note }
        return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
      }),
    )
    const user = userEvent.setup()
    renderPage(<PlayerTrades d={player({})} teamId="t" manual={false} />)
    await user.click(await screen.findByRole('button', { name: /Generate trades/ }))
    expect(await screen.findByText(note)).toBeInTheDocument()
    expect(screen.queryByText('No deal improves your lineup')).not.toBeInTheDocument()
  })

  it('shops your own player with a position filter', async () => {
    renderPage(<PlayerTrades d={player({ mine: true, owner: 'My team', name: "Ja'Marr Chase" })} teamId="t" manual={false} />)
    expect(await screen.findByText("Shop Ja'Marr Chase")).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'RB' })).toBeInTheDocument()
  })

  it('sends free agents to waivers instead', async () => {
    renderPage(<PlayerTrades d={player({ owner: null })} teamId="t" manual={false} />)
    expect(await screen.findByText(/free agent: add him off waivers/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Generate trades/ })).not.toBeInTheDocument()
  })

  it('hands a deal to the analyzer through the URL', () => {
    expect(analyzerSearch(IDEA)).toEqual({ tab: 'analyzer', partner: 'their-team', give: 'w1', receive: 'p1' })
  })
})
