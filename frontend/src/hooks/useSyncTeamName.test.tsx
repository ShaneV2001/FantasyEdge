import { waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SavedTeamOut } from '@/api'
import { useTeamStore } from '@/stores/team'
import { renderPage } from '@/test/render'

import { useSyncTeamName } from './useSyncTeamName'

const SAVED: SavedTeamOut[] = [
  { team_id: 'es-1-2026-3', team_name: 'New Name', league_id: 'es-1-2026', league_name: 'Office League', platform: 'espn', season: 2026, last_synced_at: null, has_login: true },
]

function Probe() {
  useSyncTeamName()
  return null
}

describe('useSyncTeamName', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('picks up a team renamed on ESPN', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(SAVED)))
    useTeamStore.getState().setTeam({ teamId: 'es-1-2026-3', leagueId: 'es-1-2026', teamName: 'Old Name', leagueName: 'Old League', platform: 'espn' })
    renderPage(<Probe />)
    await waitFor(() => expect(useTeamStore.getState().team).toMatchObject({ teamName: 'New Name', leagueName: 'Office League' }))
  })
})
