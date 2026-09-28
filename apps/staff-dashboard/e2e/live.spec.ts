import { expect, test } from '@playwright/test';
import type { APIRequestContext } from '@playwright/test';

/**
 * Authenticated dashboard E2E against the live Docker backend
 * (http://localhost:8000). Requires the live-stack seed users:
 * prime.owner@live.example.com / nest.owner@live.example.com.
 * These are THROWAWAY local-dev-only accounts (never production).
 * Password via E2E_STAFF_PASSWORD, falling back to the documented
 * local default so one-command local runs keep working.
 * Skipped gracefully when the backend is unreachable.
 */

const BACKEND = 'http://localhost:8000';
const PASSWORD = process.env.E2E_STAFF_PASSWORD ?? 'LiveCheck-1234!';

async function backendUp(request: APIRequestContext): Promise<boolean> {
  try {
    const res = await request.get(`${BACKEND}/health`, { timeout: 5000 });
    return res.ok();
  } catch {
    return false;
  }
}

test.describe('authenticated dashboard (live backend)', () => {
  test('prime owner signs in and sees real overview data', async ({ page, request }) => {
    test.skip(!(await backendUp(request)), 'live backend not reachable');
    await page.goto('/login');
    await page.getByLabel(/email/i).fill('prime.owner@live.example.com');
    await page.getByLabel(/password/i).fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
    // Business identity is unambiguous (header breadcrumb is always visible).
    await expect(
      page.getByRole('navigation', { name: 'Breadcrumb' }).getByText('Prime Fitness'),
    ).toBeVisible();
    // Real KPIs render (seeded live data from the intake checks).
    await expect(page.getByText('New leads')).toBeVisible();
    await expect(page.getByText('Recent leads')).toBeVisible();
    // Navigation reaches the modules (via whichever nav is visible).
    const mobileNav = page.getByRole('navigation', { name: 'Primary mobile' });
    const nav = (await mobileNav.isVisible())
      ? mobileNav
      : page.getByRole('navigation', { name: 'Primary' });
    await expect(nav.getByRole('link', { name: 'Leads' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Tasks' })).toBeVisible();
    await page.goto('/leads');
    await expect(page.getByRole('heading', { name: 'Leads' })).toBeVisible();
    await page.goto('/tasks');
    await expect(page.getByRole('heading', { name: 'Tasks' })).toBeVisible();
  });

  test('nest owner sees the nest business, not prime data', async ({ page, request }) => {
    test.skip(!(await backendUp(request)), 'live backend not reachable');
    await page.goto('/login');
    await page.getByLabel(/email/i).fill('nest.owner@live.example.com');
    await page.getByLabel(/password/i).fill(PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
    await expect(
      page.getByRole('navigation', { name: 'Breadcrumb' }).getByText('Nest Library'),
    ).toBeVisible();
    await expect(page.getByText('Prime Fitness')).toHaveCount(0);
  });
});
