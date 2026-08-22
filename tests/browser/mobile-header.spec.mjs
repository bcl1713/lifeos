import { expect, test } from '@playwright/test';

const viewports = [320, 375];

for (const width of viewports) {
  test(`authenticated source header has usable controls and no page overflow at ${width}px`, async ({ page }) => {
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
    const menuButton = page.getByRole('button', { name: 'Open primary navigation' });
    await expect(menuButton).toBeVisible();
    await expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    const menuId = await menuButton.getAttribute('aria-controls');
    expect(menuId).toBeTruthy();
    await expect(page.locator(`#${menuId}`)).toBeHidden();
    const menuBox = await menuButton.boundingBox();
    expect(menuBox).not.toBeNull();
    expect(menuBox.width).toBeGreaterThanOrEqual(44);
    expect(menuBox.height).toBeGreaterThanOrEqual(44);

    let scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(width);

    await menuButton.press('Enter');
    await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    const controls = page.locator('header nav a, header nav button');
    await expect(controls).toHaveCount(8);
    for (const control of await controls.all()) {
      await expect(control).toBeVisible();
      const box = await control.boundingBox();
      expect(box).not.toBeNull();
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
    await expect(page.getByRole('link', { name: 'Today' })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(page.locator(`#${menuId}`)).toBeHidden();
    await expect(menuButton).toBeFocused();

    await menuButton.press(' ');
    await expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth).toBeLessThanOrEqual(width);

    for (const [name, path] of [
      ['Today', '/'],
      ['Projects', '/projects'],
      ['Areas', '/areas'],
      ['Tasks', '/tasks'],
      ['Goals', '/goals'],
      ['Routines', '/routines'],
      ['Data', '/data'],
    ]) {
      await page.getByRole('link', { name }).click();
      expect(new URL(page.url()).pathname).toBe(path);
      await page.getByRole('button', { name: 'Open primary navigation' }).click();
    }

    await page.goto('/sources/wiki/02-Areas/House/Index.md');
    await page.getByRole('button', { name: 'Open primary navigation' }).click();
    await page.getByRole('button', { name: 'Log out' }).click();
    await expect(page).toHaveURL(/\/login$/);
  });
}

test('mobile navigation remains available without JavaScript', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 320, height: 800 } });
  const page = await context.newPage();
  await page.goto('/login');
  await page.getByLabel('Username').fill('brian');
  await page.getByLabel('Password').fill('password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  const navigation = page.getByRole('navigation', { name: 'Primary navigation' });
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole('link')).toHaveCount(7);
  await expect(navigation.getByRole('button', { name: 'Log out' })).toBeVisible();
  await context.close();
});

test('a collapsed mobile navigation becomes available at desktop width', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto('/login');
  await page.getByLabel('Username').fill('brian');
  await page.getByLabel('Password').fill('password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeHidden();
  await page.setViewportSize({ width: 800, height: 800 });
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
});
