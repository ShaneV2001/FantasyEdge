import { fireEvent, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'

import type { PlayerDetailOut } from '@/api'
import { renderPage } from '@/test/render'

import { PlayerImage, PlayerView } from './player'

const D: PlayerDetailOut = {
  player_id: 'p1',
  name: 'Bijan Robinson',
  position: 'RB',
  nfl_team: 'ATL',
  headshot_url: 'https://sleepercdn.com/content/nfl/players/9509.jpg',
  team_logo_url: 'https://sleepercdn.com/images/team_logos/nfl/atl.png',
  age: 24,
  years_exp: 3,
  depth_chart_order: 1,
  injury_status: null,
  availability_note: null,
  bye_week: 11,
  owner: null,
  mine: true,
  ppg: 22.2,
  p10: 7.6,
  p90: 36.9,
  model_ros_points: 261,
  ros_value_par: 133,
  market_value: 10583,
  model_rank: 2,
  market_rank: 2,
  market_implied_points: 261,
  value_gap: 0,
  signal: 'hold',
  signal_reasons: ['We project 261 rest-of-season points (RB2); FantasyCalc prices him like our RB2 (~261): fairly priced (+0).'],
  flags: [],
  statline_keys: ['carries', 'rush_yds', 'rush_td', 'snap_pct'],
  weeks: [
    { week: 1, opponent: 'TB', played: true, actual: 18.4, projected: null, p10: null, p90: null, statline: { carries: 20, rush_yds: 104, rush_td: 0, snap_pct: 0.81 } },
    { week: 2, opponent: 'MIN', played: true, actual: 31.5, projected: 21.0, p10: 8, p90: 34, statline: { carries: 22, rush_yds: 143, rush_td: 2, snap_pct: 0.85 } },
  ],
  upcoming: [{ week: 6, opponent: 'SF', index: 1.2, points: 23.4 }],
}

describe('PlayerView', () => {
  beforeAll(() => {
    // recharts' ResponsiveContainer needs a size in jsdom
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, value: 600 })
  })

  it('shows bio, verdict, reasons and the game log', async () => {
    renderPage(<PlayerView d={D} />)
    expect(await screen.findByRole('heading', { name: 'Bijan Robinson' })).toBeInTheDocument()
    expect(screen.getByText(/24 yrs · 3 yrs exp · depth #1 · bye W11/)).toBeInTheDocument()
    expect(screen.getByText('hold')).toBeInTheDocument()
    expect(screen.getByText(/fairly priced/)).toBeInTheDocument()
    expect(screen.getByText('143')).toBeInTheDocument() // week-2 rush yards
    expect(screen.getByText('85%')).toBeInTheDocument() // snap share
    expect(screen.getByText('Projected vs actual')).toBeInTheDocument()
  })
})

describe('PlayerImage', () => {
  it('falls back from headshot to team logo to initials', async () => {
    renderPage(<PlayerImage d={D} />)
    const img = await screen.findByRole('img', { name: 'Bijan Robinson' })
    expect(img).toHaveAttribute('src', D.headshot_url)
    fireEvent.error(img)
    expect(screen.getByRole('img', { name: 'Bijan Robinson' })).toHaveAttribute('src', D.team_logo_url)
    fireEvent.error(screen.getByRole('img', { name: 'Bijan Robinson' }))
    expect(screen.getByText('BR')).toBeInTheDocument()
  })
})
