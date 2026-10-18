import { expect, test, type Page } from '@playwright/test'

import { mockApi } from './mock-api.ts'

/**
 * On phones the sidebar is a slide-over sheet that locks the page while it's open. Tapping a link
 * in it must close it, so the page underneath scrolls again (it used to stay open over the page).
 */
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

async function pageIsFree(page: Page) {
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.locator('body')).not.toHaveAttribute('data-scroll-locked', /.*/)
  expect(await page.evaluate('getComputedStyle(document.body).pointerEvents')).not.toBe('none')
  await page.evaluate('window.scrollTo(0, 0)')
  await page.mouse.move(370, 500)
  await page.mouse.wheel(0, 600)
  await expect.poll(() => page.evaluate('window.scrollY')).toBeGreaterThan(0)
}

async function openSidebar(page: Page) {
  await page.getByRole('button', { name: 'Toggle Sidebar' }).first().click()
  await expect(page.getByRole('dialog')).toBeVisible()
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('a sidebar link to another page closes the sidebar and the page scrolls', async ({ page }) => {
  await page.goto('/settings')
  await openSidebar(page)
  await page.getByRole('link', { name: 'Start/Sit' }).click()
  await page.waitForURL('**/startsit')
  await expect(page.getByTestId('slot-0')).toBeVisible()
  await pageIsFree(page)
})

test('tapping the page you are on closes the sidebar too', async ({ page }) => {
  await page.goto('/startsit')
  await expect(page.getByTestId('slot-0')).toBeVisible()
  await openSidebar(page)
  await page.getByRole('link', { name: 'Start/Sit' }).click()
  await pageIsFree(page)
})

test('Escape closes the sidebar', async ({ page }) => {
  await page.goto('/startsit')
  await expect(page.getByTestId('slot-0')).toBeVisible()
  await openSidebar(page)
  await page.keyboard.press('Escape')
  await pageIsFree(page)
})
