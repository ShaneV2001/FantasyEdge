import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { PlayerFlagsOut } from '@/api'
import { NO_FILTERS, filterRegression, teamOptions } from '@/lib/regression'
import { renderPage } from '@/test/render'

import { LeagueRegressionList, RegressionList } from './RegressionList'

const row = (name: string, strength: number, over: Partial<PlayerFlagsOut> = {}): PlayerFlagsOut => ({
  player: { player_id: name, name, position: 'WR', nfl_team: 'KC' },
  team_id: 't1',
  team_name: 'Team One',
  on_my_team: false,
  regression_score: 1,
  signal: 'hold',
  strength,
  direction: -1,
  flags: [
    {
      kind: 'td_over_expected',
      metric: 'tdoe',
      direction: (over.direction as number) ?? -1,
      value: strength * 2,
      message: `${name} flag`,
      numbers: {},
      size: strength,
    },
  ],
  ...over,
})

// 45 flagged players with distinct strengths, mixed positions, directions and teams
const MANY = Array.from({ length: 45 }, (_, i) =>
  row(`P${String(i).padStart(2, '0')}`, 1 + i / 10, {
    player: { player_id: `p${i}`, name: `P${String(i).padStart(2, '0')}`, position: i % 2 ? 'RB' : 'WR', nfl_team: 'KC' },
    direction: i % 3 === 0 ? 1 : -1,
    team_id: i % 5 === 0 ? null : i % 2 ? 't1' : 't2',
    team_name: i % 5 === 0 ? null : i % 2 ? 'Team One' : 'Team Two',
  }),
)

describe('filterRegression', () => {
  it('sorts by strength and filters by position, direction and team', () => {
    const all = filterRegression(MANY, NO_FILTERS)
    expect(all.map((r) => r.strength)).toEqual([...all.map((r) => r.strength)].sort((a, b) => b! - a!))
    expect(all[0].player.name).toBe('P44')
    expect(filterRegression(MANY, { ...NO_FILTERS, pos: 'RB' }).every((r) => r.player.position === 'RB')).toBe(true)
    expect(filterRegression(MANY, { ...NO_FILTERS, dir: 'buy' }).every((r) => r.direction! > 0)).toBe(true)
    expect(filterRegression(MANY, { ...NO_FILTERS, dir: 'sell' }).every((r) => r.direction! < 0)).toBe(true)
    expect(filterRegression(MANY, { ...NO_FILTERS, team: 'fa' }).every((r) => r.team_id === null)).toBe(true)
    expect(filterRegression(MANY, { ...NO_FILTERS, team: 't2' }).every((r) => r.team_id === 't2')).toBe(true)
    expect(filterRegression([row('unflagged', 0, { flags: [] })], NO_FILTERS)).toEqual([])
  })

  it('lists the teams that hold flagged players', () => {
    expect(teamOptions(MANY)).toEqual({
      teams: [
        { id: 't1', name: 'Team One' },
        { id: 't2', name: 'Team Two' },
      ],
      freeAgents: true,
    })
  })
})

describe('LeagueRegressionList', () => {
  it('shows the 20 strongest, then 20 more at a time', async () => {
    renderPage(<LeagueRegressionList rows={MANY} />)
    expect(await screen.findByText('P44')).toBeInTheDocument()
    expect(screen.getByText('20 of 45')).toBeInTheDocument()
    expect(screen.queryByText('P24')).not.toBeInTheDocument() // 21st strongest
    await userEvent.click(screen.getByRole('button', { name: 'Show more (20)' }))
    expect(screen.getByText('P24')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show more (5)' }))
    expect(screen.getByText('45 of 45')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Show more/ })).not.toBeInTheDocument()
  })

  it('filters reset paging, and buy-low comes with the honest note', async () => {
    renderPage(<LeagueRegressionList rows={MANY} />)
    await screen.findByText('P44')
    await userEvent.click(screen.getByRole('radio', { name: 'RB' }))
    expect(screen.getByText(/of 22$/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'Buy-low' }))
    const list = screen.getAllByRole('list')[0]
    expect(within(list).queryByText('P44')).not.toBeInTheDocument()
    expect(screen.getAllByText(/Buy-low flags were a coin flip/).length).toBeGreaterThan(0)
  })

  it('an empty result offers to clear the filters', async () => {
    renderPage(<LeagueRegressionList rows={[row('Only WR', 2)]} />)
    await userEvent.click(await screen.findByRole('radio', { name: 'QB' }))
    expect(screen.getByText('No flagged players match these filters.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(screen.getByText('Only WR')).toBeInTheDocument()
  })
})

describe('RegressionList (your roster)', () => {
  it('strongest first, with the note', async () => {
    renderPage(<RegressionList rows={[row('Weak', 1.1), row('Strong', 3)]} />)
    const names = (await screen.findAllByRole('link')).map((a) => a.textContent)
    expect(names).toEqual(['Strong', 'Weak'])
    expect(screen.getByText(/treat them as context/)).toBeInTheDocument()
  })
})
