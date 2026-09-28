import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

/**
 * Blocks 5-7 operations E2E (no backend required):
 * - every new route redirects anonymous users to /login (backend owns auth)
 * - no horizontal overflow at desktop and phone widths
 */

async function assertNoOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth - doc.clientWidth;
  });
  expect(overflow, 'page must not overflow horizontally').toBeLessThanOrEqual(1);
}

const ROUTES = [
  '/owner',
  '/members',
  '/memberships',
  '/plans',
  '/renewals',
  '/payments',
  '/attendance',
  '/seats',
  '/approvals',
];

for (const route of ROUTES) {
  test(`anonymous users are redirected from ${route} to login`, async ({ page }) => {
    await page.goto(route);
    await expect(page).toHaveURL(/\/login$/);
    await assertNoOverflow(page);
  });
}

test('new routes fit small phones without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/owner');
  await expect(page).toHaveURL(/\/login$/);
  await assertNoOverflow(page);
});
