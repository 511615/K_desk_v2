import { expect, test } from '@playwright/test'

test('account detail URL remains the server-rendered legacy page', async ({ page }) => {
  const response = await page.goto('/account/302360?platform=MT5&server=DBG%20MT5')
  expect(response?.status()).toBe(200)
  await expect(page.locator('#copyOriginBtn')).toHaveCount(1)
  await expect(page.locator('#eaCommentBtn')).toHaveCount(1)
  await expect(page.locator('#toxicBtn')).toHaveCount(1)
  await expect(page.locator('#orderDetails')).toHaveCount(1)
  await expect(page.locator('#app')).toHaveCount(0)
})
