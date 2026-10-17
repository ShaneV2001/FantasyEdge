import { expect, test, type Locator, type Page } from '@playwright/test'

/** Screenshots of the demo league (scripts/demo_league.py): fictional teams, public player data. */
const API = 'http://localhost:8000'
const OUT = '../docs/screenshots'
const TEAM = {
  teamId: 'demo-league-5',
  leagueId: 'demo-league',
  teamName: 'Demo Team',
  leagueName: 'Demo League',
  platform: 'demo',
}

test.beforeAll(async ({ request }) => {
  const r = await request.get(`${API}/team/${TEAM.teamId}`)
  expect(r.ok(), 'run `python tasks.py demo` first: the demo app must be running').toBeTruthy()
  expect((await r.json()).league.platform).toBe('demo') // never a real league
})

test.beforeEach(async ({ page }) => {
  await page.addInitScript((t) => {
    localStorage.setItem('fantasyedge:team', JSON.stringify({ state: { team: t }, version: 1 }))
  }, TEAM)
})

/** Screenshot of the page from the top of `from` (or the page top) to the bottom of `to`. */
async function clip(page: Page, to: Locator, path: string, from?: Locator, max = 1800) {
  await page.evaluate('window.scrollTo(0, 0)')
  const fromBox = from ? (await from.boundingBox())! : null
  const top = fromBox ? fromBox.y + Number(await page.evaluate('window.scrollY')) : 0
  const x = fromBox ? Math.max(fromBox.x - 16, 0) : 0
  const width = fromBox ? Math.min(fromBox.width + 32, 1440 - x) : 1440
  const box = (await to.boundingBox())!
  const bottom = box.y + box.height + Number(await page.evaluate('window.scrollY')) + 16
  await page.screenshot({
    path,
    fullPage: true,
    clip: { x, y: Math.max(top - 16, 0), width, height: Math.min(bottom - top + 16, max) },
  })
}

test('advisor', async ({ page }) => {
  await page.goto('/advisor')
  await expect(page.locator('main [aria-busy=true]')).toHaveCount(0, { timeout: 120_000 }) // skeletons gone
  await expect(page.locator('main').getByText(/Sell high|Trade idea|^Add |^Start /).first()).toBeVisible()
  await page.screenshot({ path: `${OUT}/advisor.png` })
})

test('players', async ({ page }) => {
  await page.goto('/players')
  await expect(page.locator('tbody tr').nth(10)).toBeVisible({ timeout: 120_000 })
  await page.screenshot({ path: `${OUT}/players.png` })
})

test('waivers', async ({ page }) => {
  await page.goto('/waivers')
  await expect(page.locator('tbody tr').nth(5)).toBeVisible({ timeout: 120_000 })
  await page.screenshot({ path: `${OUT}/waivers.png` })
})

test('start/sit', async ({ page }) => {
  await page.goto('/startsit')
  await expect(page.getByTestId('slot-0')).toBeVisible({ timeout: 120_000 })
  await page.screenshot({ path: `${OUT}/startsit.png` })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.getByTestId('slot-0')).toBeVisible({ timeout: 120_000 })
  await page.screenshot({ path: `${OUT}/startsit-mobile.png` })
})

test('trade finder', async ({ page }) => {
  await page.goto('/trade?tab=find')
  const give = page.getByRole('button', { pressed: false }).filter({ has: page.locator('span.font-mono') })
  await expect(give.nth(5)).toBeVisible({ timeout: 120_000 })
  // offer two depth players for an upgrade at any position
  await give.nth(4).click()
  await give.nth(2).click()
  await page.getByRole('button', { name: 'Find trades' }).click()
  await expect(page.getByText(/Searched \d+ teams|No deal improves/)).toBeVisible({ timeout: 120_000 })
  const cards = page.locator('main [data-slot=card]')
  await clip(page, cards.nth((await cards.count()) > 1 ? 1 : 0), `${OUT}/trade-finder.png`)
})

test('player page trades', async ({ page, request }) => {
  // a rival's player for whom at least one deal helps both lineups (that's the interesting card)
  const team = await (await request.get(`${API}/team/${TEAM.teamId}`)).json()
  let target: string | undefined
  for (const other of team.league_teams.filter((t: { is_mine: boolean }) => !t.is_mine)) {
    const roster = (await (await request.get(`${API}/team/${other.team_id}`)).json()).roster as {
      player_id: string
      position: string
      ppg: number
    }[]
    const best = roster.filter((p) => ['RB', 'WR'].includes(p.position)).sort((a, b) => b.ppg - a.ppg)
    for (const p of best.slice(1, 4)) {
      const r = await (await request.get(`${API}/team/${TEAM.teamId}/players/${p.player_id}/trades`)).json()
      if (r.ideas.some((i: { partner_accepts: boolean }) => i.partner_accepts)) {
        target = p.player_id
        break
      }
    }
    if (target) break
  }
  expect(target, 'no rival player with a mutually good deal').toBeTruthy()
  await page.goto(`/players/${target}`)
  await page.getByRole('button', { name: 'Generate trades' }).click()
  await expect(page.getByText(/deal\(s\) help both lineups/)).toBeVisible({ timeout: 120_000 })
  const card = page.locator('[data-slot=card-title]', { hasText: 'Trade for' }).locator('xpath=ancestor::*[@data-slot="card"][1]')
  const firstDeal = card.locator('[data-slot=card]').first()
  await clip(page, (await firstDeal.count()) ? firstDeal : card, `${OUT}/player-trades.png`, card)
})
