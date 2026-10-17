import type { Page } from '@playwright/test'

import startsit from './fixtures/startsit.json' with { type: 'json' }
import team from './fixtures/team.json' with { type: 'json' }

export const DEMO_TEAM = {
  teamId: 'demo-1',
  leagueId: 'demo',
  teamName: 'Demo Team',
  leagueName: 'Demo League',
  platform: 'sleeper',
}

/** Select the demo team (as if connected) and answer API calls from the JSON fixtures. */
export async function mockApi(page: Page) {
  await page.addInitScript((t) => {
    localStorage.setItem('fantasyedge:team', JSON.stringify({ state: { team: t }, version: 1 }))
  }, DEMO_TEAM)
  await page.route('http://localhost:8000/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    const body = path.endsWith('/startsit') ? startsit : path === `/team/${DEMO_TEAM.teamId}` ? team : null
    if (body) await route.fulfill({ json: body })
    else await route.fulfill({ status: 404, json: { detail: 'not mocked', kind: 'unknown' } })
  })
}
