import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SettingFieldOut, SettingsOut } from '@/api'
import { renderPage } from '@/test/render'

import { SettingsPage } from './settings'

const field = (key: string, group: string, value: number, over: Partial<SettingFieldOut> = {}): SettingFieldOut => ({
  key,
  group,
  label: key.replace(/_/g, ' '),
  help: `Help for ${key}`,
  default: value,
  min: 0,
  max: 50,
  integer: false,
  tuned: false,
  value,
  ...over,
})

const DATA: SettingsOut = {
  fields: [
    field('usage_weight', 'Projections', 0.5, { max: 1, tuned: true }),
    field('gap_min_points', 'Buy/sell & targets', 10),
    field('ir_weeks_out', 'Injuries', 4, { integer: true, max: 17 }),
  ],
  warning: null,
  path: 'C:/x/data/settings.json',
}

let fetchMock: ReturnType<typeof vi.fn>

function respond(data: SettingsOut) {
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
}

describe('SettingsPage', () => {
  beforeEach(() => {
    fetchMock = vi.fn(async (req: Request) => (req.method === 'GET' ? respond(DATA) : respond(DATA)))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('groups settings and shows defaults and the backtest note', async () => {
    renderPage(<SettingsPage />)
    expect(await screen.findByText('Projections')).toBeInTheDocument()
    expect(screen.getByText('Buy/sell & targets')).toBeInTheDocument()
    expect(screen.getByText(/walk-forward backtest/)).toBeInTheDocument()
    expect(screen.getByLabelText('gap min points')).toHaveValue(10)
  })

  it('saves only the changed values', async () => {
    renderPage(<SettingsPage />)
    const input = await screen.findByLabelText('gap min points')
    await userEvent.clear(input)
    await userEvent.type(input, '20')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    const put = fetchMock.mock.calls.map((c) => c[0] as Request).find((r) => r.method === 'PUT')
    expect(put).toBeDefined()
    expect(await put!.json()).toEqual({ gap_min_points: 20 })
  })

  it('blocks saving out-of-range values', async () => {
    renderPage(<SettingsPage />)
    const input = await screen.findByLabelText('ir weeks out')
    await userEvent.clear(input)
    await userEvent.type(input, '2.5')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('shows a warning when the settings file was unreadable', async () => {
    fetchMock.mockImplementation(async () => respond({ ...DATA, warning: 'settings.json could not be used' }))
    renderPage(<SettingsPage />)
    expect(await screen.findByText(/could not be used/)).toBeInTheDocument()
  })
})
