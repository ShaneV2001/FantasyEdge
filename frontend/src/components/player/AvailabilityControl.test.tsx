import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PlayerDetailOut } from '@/api'
import { InjuryTag } from '@/components/player/badges'
import { injuryStatus } from '@/components/player/matchups'
import { renderPage } from '@/test/render'

import { AvailabilityControl, assumption } from './AvailabilityControl'

const player = (over: Partial<PlayerDetailOut> = {}) =>
  ({
    player_id: 'p1',
    name: 'Torn Knee',
    injury_status: 'IR',
    injury_detail: 'Knee - ACL, surgery',
    availability_note: 'Out for the season (Knee - ACL, surgery)',
    return_week: 99,
    availability_source: 'rule',
    override_return_week: null,
    override_out_for_season: false,
    upcoming: [{ week: 7, opponent: 'KC', index: 1, points: 0 }],
    ...over,
  }) as unknown as PlayerDetailOut

afterEach(() => vi.unstubAllGlobals())

describe('AvailabilityControl', () => {
  it('shows the injury report and what we assume from it', async () => {
    renderPage(<AvailabilityControl d={player()} />)
    expect(await screen.findByText('IR · Knee - ACL, surgery')).toBeInTheDocument()
    expect(screen.getByText('Out for the season')).toBeInTheDocument()
    expect(screen.getByText(/season-ending injury in the report/)).toBeInTheDocument()
    expect(screen.getByText(/changes FantasyEdge's projections only, not ESPN\/Sleeper/)).toBeInTheDocument()
  })

  it('saves "out for the season" as your what-if', async () => {
    const fetchMock = vi.fn(
      async (_req: Request) => new Response(JSON.stringify({ player_id: 'p1', out_for_season: true, return_week: null }), { headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderPage(<AvailabilityControl d={player({ injury_status: null, injury_detail: null, return_week: null, availability_source: null, availability_note: null })} />)
    expect(await screen.findByText('Healthy: plays every remaining game')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('combobox', { name: 'Your what-if' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Out for the season' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const req = fetchMock.mock.calls[0][0] as Request
    expect(req.method).toBe('PUT')
    expect(new URL(req.url).pathname).toBe('/players/p1/availability')
    expect(await req.json()).toEqual({ out_for_season: true })
  })

  it('an existing week what-if shows its week; back to the report clears it', async () => {
    const fetchMock = vi.fn(
      async (_req: Request) => new Response(JSON.stringify({ player_id: 'p1', out_for_season: false, return_week: null }), { headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderPage(<AvailabilityControl d={player({ return_week: 12, availability_source: 'override', override_return_week: 12 })} />)
    expect(await screen.findByRole('combobox', { name: 'Return week' })).toHaveTextContent('Week 12')
    expect(screen.getByText('Out until week 12')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('combobox', { name: 'Your what-if' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Use the injury report' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe('DELETE')
  })
})

describe('injury tags', () => {
  it('a season-ending injury shows OUT · SEASON', () => {
    render(<InjuryTag status="IR" returnWeek={99} />)
    expect(screen.getByText('Out · season')).toBeInTheDocument()
  })

  it('notes map to tags', () => {
    expect(injuryStatus('Out for the season (Knee - ACL, surgery)')).toBe('SEASON')
    expect(injuryStatus('Out until week 12 (your what-if)')).toBe('Out')
    expect(injuryStatus('On IR: assumed out 4 more weeks')).toBe('IR')
    expect(assumption({ return_week: null, availability_note: 'On IR: assumed out 4 more weeks' })).toBe('On IR: assumed out 4 more weeks')
  })
})
