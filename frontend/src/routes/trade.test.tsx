import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RosterPlayer, TradeOut } from '@/api'
import { useTeamStore } from '@/stores/team'
import { renderPage } from '@/test/render'

import { FindTrade, TradePage } from './trade'

const player = (id: string, name: string, position: string): RosterPlayer => ({
  player_id: id,
  name,
  position,
  ppg: 12,
  proj_ros_points: 120,
  next4_points: 48,
  games_remaining: 10,
  ros_value_par: 10,
  slot: 'bench',
  optimal_starter: false,
})

const ROSTER = [
  player('w1', 'Jaylen Waddle', 'WR'),
  player('q1', 'Tyler Shough', 'QB'),
  player('w2', 'Wan Dale', 'WR'),
  player('t1', 'Tucker Kraft', 'TE'),
]

const side = (name: string, give: string, get: string, delta: number) => ({
  team_id: name,
  team_name: name,
  gives: [{ player_id: give, name: give, position: 'WR' }],
  receives: [{ player_id: get, name: get, position: 'RB' }],
  lineup_before: 1000,
  lineup_after: 1000 + delta,
  lineup_delta: delta,
  model_value_out: 10,
  model_value_in: 12,
  market_value_out: null,
  market_value_in: null,
})

const IDEA: TradeOut = {
  verdict: 'accept',
  headline: 'Give Jaylen Waddle for Omarion Hampton',
  reasons: ['Your starting lineup gains 18.9 projected points rest of season; theirs loses 4.0.'],
  me: side('Me', 'w1', 'rb9', 18.9),
  partner: side('NFL Youngboy', 'rb9', 'w1', -4),
  partner_accepts: false,
}

describe('FindTrade', () => {
  let calls: { url: string; body: string | null }[]
  beforeEach(() => {
    calls = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request | string) => {
        const req = input instanceof Request ? input : new Request(input)
        const body = req.method === 'POST' ? await req.text() : null
        calls.push({ url: req.url, body })
        const data = req.url.includes('/trade/find')
          ? { team_id: 't', deadline_passed: false, searched_teams: 9, ideas: [IDEA] }
          : { roster: ROSTER, league_teams: [] }
        return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
      }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('needs 1 to 3 players, sends the position you want, and marks one-sided deals', async () => {
    const user = userEvent.setup()
    renderPage(<FindTrade teamId="t" manual={false} onOpenInAnalyzer={() => {}} />)
    const findBtn = await screen.findByRole('button', { name: /Find trades/ })
    expect(findBtn).toBeDisabled()

    for (const name of ['Jaylen Waddle', 'Tyler Shough', 'Wan Dale', 'Tucker Kraft']) {
      await user.click(screen.getByRole('button', { name: new RegExp(name) }))
    }
    expect(screen.getByText('You give (3/3)')).toBeInTheDocument() // a 4th pick is ignored
    expect(screen.getByRole('button', { name: /Tucker Kraft/ })).toHaveAttribute('aria-pressed', 'false')

    await user.click(screen.getByRole('radio', { name: 'TE' }))
    await user.click(findBtn)
    expect(await screen.findByText("Doesn't help their lineup")).toBeInTheDocument()
    const sent = JSON.parse(calls.find((c) => c.url.includes('/trade/find'))!.body!)
    expect(sent).toEqual({ team_id: 't', give: ['w1', 'q1', 'w2'], want_position: 'TE', receive_count: 1 })
  })

  it('explains that manual teams have no one to trade with', async () => {
    renderPage(<FindTrade teamId="t" manual onOpenInAnalyzer={() => {}} />)
    expect(await screen.findByText('Finding trade partners needs a league')).toBeInTheDocument()
  })
})

const OFFER = {
  id: 'o1',
  direction: 'received',
  partner_team_id: 'them',
  partner_name: 'Them',
  give: [{ player_id: 'w1', name: 'Jaylen Waddle', position: 'WR' }],
  receive: [{ player_id: 'rb9', name: 'Omarion Hampton', position: 'RB' }],
  drops: [],
  proposed_at: '2026-10-29T18:00:00',
  evaluation: IDEA,
  note: null,
}

describe('TradePage', () => {
  let offers: { team_id: string; supported: boolean; received: unknown[]; sent: unknown[] }
  beforeEach(() => {
    offers = { team_id: 'me', supported: true, received: [], sent: [] }
    useTeamStore.getState().setTeam({ teamId: 'me', leagueId: 'l', teamName: 'Mine', leagueName: 'L', platform: 'espn' })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request | string) => {
        const req = input instanceof Request ? input : new Request(input)
        const data = req.url.includes('/trade-offers')
          ? offers
          : req.url.includes('/team/them')
          ? { team_id: 'them', team_name: 'Them', roster: [player('rb9', 'Omarion Hampton', 'RB')], league_teams: [] }
          : req.url.includes('/team/me')
            ? { team_id: 'me', team_name: 'Mine', roster: ROSTER, league_teams: [{ team_id: 'them', team_name: 'Them', owner_name: 'o', is_mine: false }] }
            : { team_id: 'me', week: 6, deadline_passed: false, trade_deadline_week: 12, ideas: [], page: 0, has_more: false }
        return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
      }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('opens the analyzer with the deal from the URL', async () => {
    renderPage(<TradePage />, '/?tab=analyzer&partner=them&give=w1&receive=rb9')
    expect(await screen.findByRole('tab', { name: /Analyzer/, selected: true })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /Omarion Hampton/ })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: /Jaylen Waddle/ })).toHaveAttribute('aria-pressed', 'true')
  })

  it('lists offers waiting on you with the analyzer verdict and a count', async () => {
    offers.received = [OFFER]
    const user = userEvent.setup()
    renderPage(<TradePage />)
    const tab = await screen.findByRole('tab', { name: /Offers/ })
    expect(await screen.findByLabelText('1 waiting')).toBeInTheDocument()
    await user.click(tab)
    expect(await screen.findByText('Waiting on your answer (1)')).toBeInTheDocument()
    expect(screen.getByText('Them')).toBeInTheDocument()
    expect(screen.getByText(IDEA.headline)).toBeInTheDocument()
  })
})
