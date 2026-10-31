import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderPage } from '@/test/render'

import { StockBadge, seasonRankText } from './badges'

describe('StockBadge', () => {
  it('shows the direction and size of last week’s move, and nothing for a flat week', async () => {
    renderPage(
      <>
        <StockBadge t={{ stock: 'up', stock_delta: 2.14, stock_reason: 'Scored 31.0 vs 14.0 projected in week 7' }} />
        <StockBadge t={{ stock: 'down', stock_delta: -1.6 }} />
        <StockBadge t={{ stock: 'flat', stock_delta: 0.2 }} />
      </>,
    )
    expect(await screen.findByLabelText('Stock up 2.1 points per game')).toHaveTextContent('▲2.1')
    expect(screen.getByLabelText('Stock down 1.6 points per game')).toHaveTextContent('▼1.6')
    expect(screen.queryByLabelText(/Stock flat/)).toBeNull()
  })

  it('formats a season rank', () => {
    expect(seasonRankText('RB', { season_rank: 14 })).toBe('RB14')
    expect(seasonRankText('RB', {})).toBe('—')
  })
})
