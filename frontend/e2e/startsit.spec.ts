import { expect, test, type Locator, type Page } from '@playwright/test'

import { mockApi } from './mock-api.ts'

async function drag(page: Page, from: Locator, to: Locator) {
  const a = (await from.boundingBox())!
  const b = (await to.boundingBox())!
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(a.x + a.width / 2 + 10, a.y + a.height / 2 + 10, { steps: 5 }) // past the drag threshold
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 15 })
  await page.mouse.up()
}

// both columns (lineup and bench) fully on screen, so the pointer never leaves the viewport
test.use({ viewport: { width: 1280, height: 1100 } })

const thisLineup = (page: Page) => page.getByText('This lineup').locator('..').locator('span').nth(1)

test.beforeEach(async ({ page }) => {
  await mockApi(page)
  await page.goto('/startsit')
  await expect(page.getByText(/Planner — changes here don't change your lineup/)).toBeVisible()
  await expect(thisLineup(page)).toHaveText('65.6')
})

test('dragging a bench player into a slot updates the total; undo puts it back', async ({ page }) => {
  await drag(page, page.getByRole('button', { name: /^Bench Star/ }), page.getByTestId('slot-4'))
  await expect(page.getByTestId('slot-4')).toContainText('Bench Star')
  await expect(thisLineup(page)).toHaveText('69.2')
  await page.getByRole('button', { name: /Undo/ }).click()
  await expect(page.getByTestId('slot-4')).toContainText('Slow Back')
  await expect(thisLineup(page)).toHaveText('65.6')
})

test('a drop the slot does not accept is rejected', async ({ page }) => {
  await drag(page, page.getByRole('button', { name: /^Bench Star/ }), page.getByTestId('slot-3')) // WR -> TE
  await expect(page.getByText("That player can't go there")).toBeVisible()
  await expect(page.getByTestId('slot-3')).toContainText('Tight End')
  await expect(thisLineup(page)).toHaveText('65.6')
})

test('a starter dragged to the bench leaves his slot empty', async ({ page }) => {
  await drag(page, page.getByRole('button', { name: /^Tight End/ }), page.getByTestId('bench'))
  await expect(page.getByTestId('slot-3')).toContainText('Empty')
  await expect(thisLineup(page)).toHaveText('58.1')
  await page.getByRole('button', { name: /Reset to my real lineup/ }).click()
  await expect(thisLineup(page)).toHaveText('65.6')
})
