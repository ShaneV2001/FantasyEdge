import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SavedTeamOut } from '@/api'
import { SidebarProvider } from '@/components/ui/sidebar'
import { renderPage } from '@/test/render'
import { useTeamStore } from '@/stores/team'

import { TeamSwitcher, toConnected } from './TeamSwitcher'

const SAVED: SavedTeamOut[] = [
  { team_id: 'es-1-2026-3', team_name: 'Gridiron Gang', league_id: 'es-1-2026', league_name: 'Office League', platform: 'espn', season: 2026, last_synced_at: null, has_login: true },
  { team_id: 'mn-abc-1', team_name: 'Bench Mob', league_id: 'mn-abc', league_name: 'Bench Mob', platform: 'manual', season: 2026, last_synced_at: null, has_login: false },
]

let calls: Request[] = []
function serve() {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (req: Request) => {
      calls.push(req)
      const path = new URL(req.url).pathname
      if (path === '/teams/saved') return Response.json(SAVED)
      if (req.method === 'DELETE') return Response.json({ league_id: 'es-1-2026', platform: 'espn', teams_removed: 10 })
      if (req.method === 'PATCH') return Response.json({ team_id: 'mn-abc-1', league_id: 'mn-abc' })
      return Response.json({}, { status: 404 })
    }),
  )
}

const render = () =>
  renderPage(
    <SidebarProvider>
      <TeamSwitcher />
    </SidebarProvider>,
  )

async function openMenu() {
  await userEvent.click(await screen.findByRole('button', { name: /Switch team/ }))
}

describe('TeamSwitcher', () => {
  beforeEach(() => {
    useTeamStore.getState().setTeam(toConnected(SAVED[0]))
    serve()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('lists your saved teams and switches between them', async () => {
    render()
    await openMenu()
    const menu = await screen.findByRole('menu')
    expect(within(menu).getByText('Gridiron Gang')).toBeInTheDocument()
    expect(within(menu).getByLabelText('Current team')).toBeInTheDocument()
    expect(within(menu).queryByText(/Rename team/)).not.toBeInTheDocument() // ESPN names come from ESPN
    await userEvent.click(within(menu).getByText('Bench Mob'))
    expect(useTeamStore.getState().team).toMatchObject({ teamId: 'mn-abc-1', platform: 'manual' })
  })

  it('forgetting a league says what is removed, then moves to another saved team', async () => {
    render()
    await openMenu()
    await userEvent.click(await screen.findByRole('menuitem', { name: /Forget this league/ }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/including your saved ESPN login/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Nothing changes on ESPN/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Forget league' }))
    await waitFor(() => expect(useTeamStore.getState().team?.teamId).toBe('mn-abc-1'))
    const del = calls.find((r) => r.method === 'DELETE')!
    expect(new URL(del.url).pathname).toBe('/team/es-1-2026-3')
  })

  it('renames a manual team', async () => {
    useTeamStore.getState().setTeam(toConnected(SAVED[1]))
    render()
    await openMenu()
    await userEvent.click(await screen.findByRole('menuitem', { name: /Rename team/ }))
    const input = await screen.findByLabelText('Team name')
    await userEvent.clear(input)
    await userEvent.type(input, 'Waiver Wire Kings')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(useTeamStore.getState().team?.teamName).toBe('Waiver Wire Kings'))
    const patch = calls.find((r) => r.method === 'PATCH')!
    expect(await patch.json()).toEqual({ name: 'Waiver Wire Kings' })
    expect(screen.queryByText(/Delete team/)).not.toBeInTheDocument()
  })
})
