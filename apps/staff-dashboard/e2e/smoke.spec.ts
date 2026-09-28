import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';

/**
 * Dashboard smoke E2E (no backend required):
 * - anonymous users land on /login with an accessible form
 * - no horizontal overflow at 360 / 768 / 1280
 * - empty submit is rejected client-side (no request storm)
 */

async function assertNoOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth - doc.clientWidth;
  });
  expect(overflow, 'page must not overflow horizontally').toBeLessThanOrEqual(1);
}

test('login renders, validates, and redirects anonymous users', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await expect(page.getByLabel(/email/i)).toBeVisible();
  await expect(page.getByLabel(/password/i)).toBeVisible();
  await assertNoOverflow(page);

  // Empty submit: client-side required validation, stays on the page.
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/login$/);

  // Unknown credentials: honest backend error or unreachable (no backend here).
  await page.getByLabel(/email/i).fill('staff@example.com');
  await page.getByLabel(/password/i).fill('wrong-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert').first()).toBeVisible({ timeout: 20_000 });
  await assertNoOverflow(page);
});

test('login layout fits small phones without overflow', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await assertNoOverflow(page);
  // Touch targets meet the 40px minimum.
  const height = await page.getByRole('button', { name: 'Sign in' }).evaluate((el) => el.getBoundingClientRect().height);
  expect(height).toBeGreaterThanOrEqual(40);
});
