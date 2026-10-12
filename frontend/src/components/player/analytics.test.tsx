import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { PlayerAnalyticsOut } from '@/api'
import { renderPage } from '@/test/render'

import { Analytics } from './analytics'

const A: PlayerAnalyticsOut = {
  groups: [
    { key: 'usage', label: 'Usage', metrics: ['target_share'] },
    { key: 'yac', label: 'Yards after catch', metrics: ['yac_per_rec'] },
  ],
  windows: [
    { label: 'L3', games: 3, metrics: { target_share: 0.3, yac_per_rec: null } },
    { label: 'Season', games: 6, metrics: { target_share: 0.2, yac_per_rec: 4.25 } },
  ],
}

describe('Analytics', () => {
  it('shows the last-3 window by default with the season value and a trend', async () => {
    renderPage(<Analytics a={A} />)
    expect(await screen.findByText('30%')).toBeInTheDocument()
    expect(screen.getByText('Season 20%')).toBeInTheDocument()
    expect(screen.getByLabelText('up vs season')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument() // missing YAC
  })

  it('switches to the season window', async () => {
    renderPage(<Analytics a={A} />)
    fireEvent.click(await screen.findByRole('radio', { name: /Season/ }))
    expect(screen.getByText('20%')).toBeInTheDocument()
    expect(screen.getByText('4.3')).toBeInTheDocument()
    expect(screen.queryByText(/^Season \d/)).not.toBeInTheDocument()
  })
})
