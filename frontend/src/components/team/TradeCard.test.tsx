import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { TradeOut } from '@/api'
import { renderPage } from '@/test/render'

import { TradeCard } from './TradeCard'

const side = (team: string, give: string, get: string[]) => ({
  team_id: team,
  team_name: team,
  gives: [{ player_id: give, name: give, position: 'WR' }],
  receives: get.map((g) => ({ player_id: g, name: g, position: 'RB' })),
  lineup_before: 1000,
  lineup_after: 1012,
  lineup_delta: 12,
  model_value_out: 10,
  model_value_in: 20,
  market_value_out: null,
  market_value_in: null,
})

const TRADE: TradeOut = {
  verdict: 'accept',
  headline: 'Give Waddle for Hampton + Pacheco',
  reasons: ['Your starting lineup gains 12.0 projected points rest of season.'],
  me: {
    ...side('Mine', 'Waddle', ['Hampton', 'Pacheco']),
    drops: [
      { player: { player_id: 'k2', name: 'Backup Kicker', position: 'K' }, reason: 'extra kicker' },
      { player: { player_id: 'w9', name: 'Bench Receiver', position: 'WR' }, reason: 'lowest market value on your bench' },
    ],
  },
  partner: side('Theirs', 'Hampton', ['Waddle']),
  partner_accepts: true,
}

describe('TradeCard', () => {
  it('says who must be dropped and why', async () => {
    renderPage(<TradeCard trade={TRADE} />)
    expect(await screen.findByText('Must drop')).toBeInTheDocument()
    expect(screen.getByText('Backup Kicker')).toBeInTheDocument()
    expect(screen.getByText('extra kicker')).toBeInTheDocument()
    expect(screen.getByText('Bench Receiver')).toBeInTheDocument()
    expect(screen.getByText('lowest market value on your bench')).toBeInTheDocument()
  })

  it('no drop, no Must drop', async () => {
    renderPage(<TradeCard trade={{ ...TRADE, me: { ...TRADE.me, drops: [] } }} />)
    await screen.findByText('Give Waddle for Hampton + Pacheco')
    expect(screen.queryByText('Must drop')).not.toBeInTheDocument()
  })

  it('says why the other team would likely say no', async () => {
    const priced = (out: number, inn: number) => ({ ...TRADE.me, market_value_out: out, market_value_in: inn })
    const { unmount } = renderPage(
      <TradeCard trade={{ ...TRADE, partner_accepts: false, fair_value: false, me: priced(1314, 9671) }} />,
    )
    expect(await screen.findByText('Below their value')).toBeInTheDocument()
    unmount()
    const r2 = renderPage(<TradeCard trade={{ ...TRADE, partner_accepts: false, fair_value: false, me: priced(9000, 3000) }} />)
    expect(await screen.findByText('You overpay')).toBeInTheDocument()
    r2.unmount()
    renderPage(<TradeCard trade={{ ...TRADE, partner_accepts: false, fair_value: true }} />)
    expect(await screen.findByText("Doesn't help their lineup")).toBeInTheDocument()
  })

  it('no chip when they would likely accept', async () => {
    renderPage(<TradeCard trade={{ ...TRADE, fair_value: true }} />)
    await screen.findByText('Give Waddle for Hampton + Pacheco')
    expect(screen.queryByText('Below their value')).not.toBeInTheDocument()
    expect(screen.queryByText("Doesn't help their lineup")).not.toBeInTheDocument()
  })

  it('warns when drops were chosen without market values', async () => {
    renderPage(<TradeCard trade={{ ...TRADE, market_values_missing: true }} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Market values unavailable; drops based on projections only.',
    )
  })

  it('no warning with market values, or without a drop', async () => {
    renderPage(<TradeCard trade={TRADE} />)
    await screen.findByText('Must drop')
    expect(screen.queryByText(/Market values unavailable/)).not.toBeInTheDocument()
    const noDrop = { ...TRADE, market_values_missing: true, me: { ...TRADE.me, drops: [] } }
    renderPage(<TradeCard trade={noDrop} />)
    await screen.findAllByText('Give Waddle for Hampton + Pacheco')
    expect(screen.queryByText(/Market values unavailable/)).not.toBeInTheDocument()
  })
})
