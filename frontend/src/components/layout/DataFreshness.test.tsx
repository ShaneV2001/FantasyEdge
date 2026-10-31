import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { StatusOut } from '@/api'
import { renderPage } from '@/test/render'

import { StaleDataBanner } from './DataFreshness'

const BASE: StatusOut = {
  season: 2026,
  week: 7,
  sources: [{ source: 'nflverse', last_synced_at: '2026-10-21T02:57:34', status: 'ok', detail: '' }],
  attribution: [],
  data_refreshing: false,
  nfl_data_stale: true,
  unscored_week: 7,
}

describe('StaleDataBanner', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('says which week is missing and updates on request', async () => {
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: Request) => {
        calls.push(`${input.method} ${new URL(input.url).pathname} ${await input.text()}`)
        return new Response(JSON.stringify({ scope: 'all', ok: true, detail: ['stats: ok'] }), {
          headers: { 'Content-Type': 'application/json' },
        })
      }),
    )
    renderPage(<StaleDataBanner status={BASE} />)
    expect(await screen.findByText("Week 7 results aren't in yet")).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Update NFL data now/ }))
    expect(calls).toContain('POST /refresh {"scope":"all"}')
  })

  it('shows progress while refreshing and nothing when fresh', async () => {
    const { unmount } = renderPage(<StaleDataBanner status={{ ...BASE, data_refreshing: true }} />)
    expect(await screen.findByText('Updating NFL data…')).toBeInTheDocument()
    unmount()
    const fresh = renderPage(<StaleDataBanner status={{ ...BASE, nfl_data_stale: false, unscored_week: null }} />)
    await new Promise((r) => setTimeout(r, 50))
    expect(fresh.container.querySelector('[data-testid^="data-"]')).toBeNull()
  })
})
