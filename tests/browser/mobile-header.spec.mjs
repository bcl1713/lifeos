import { expect, test } from '@playwright/test';

const viewports = [320, 375];

for (const width of viewports) {
  test(`authenticated source header has no page overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await page.goto('/login');
    await page.getByLabel('Username').fill('brian');
    await page.getByLabel('Password').fill('password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.goto('/sources/wiki/02-Areas/House/Index.md');
    await expect(page.locator('article.markdown-body')).toContainText('Canonical content.');
    await expect(page.locator('article.markdown-body')).toContainText('Unsafe link scheme');
    await expect(page.locator('article.markdown-body a[href^="javascript:"]')).toHaveCount(0);
    await expect(page.locator('header nav a, header nav button')).toHaveCount(8);
    for (const control of await page.locator('header nav a, header nav button').all()) {
      await expect(control).toBeVisible();
    }

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(width);

    await page.getByRole('button', { name: 'Log out' }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
}
