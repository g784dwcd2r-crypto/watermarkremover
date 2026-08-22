import { expect, test } from "@playwright/test";

import { expectNoAxeViolations } from "./helpers";

test.describe("marketing pages", () => {
  test("the landing page explains the authorized-use restriction", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: /clean up your own images/i })).toBeVisible();
    await expect(page.getByText(/I own this image or have permission to edit it/i)).toBeVisible();

    // The refusal list is on the landing page, not buried in a policy.
    await expect(page.getByRole("heading", { name: /what this app will not do/i })).toBeVisible();
    await expect(page.getByText(/Artist signatures/)).toBeVisible();
    await expect(page.getByText(/Content Credentials and C2PA provenance/)).toBeVisible();
  });

  test("the before/after comparison is keyboard operable", async ({ page }) => {
    await page.goto("/");
    const slider = page.getByRole("slider", { name: /comparison position/i }).first();
    await slider.focus();
    const before = await slider.inputValue();
    await slider.press("ArrowRight");
    await expect.poll(async () => await slider.inputValue()).not.toBe(before);
  });

  test("policy pages are reachable and dated", async ({ page }) => {
    await page.goto("/");
    // The link appears in both the header nav and the footer.
    await page.getByRole("link", { name: "Authorized-use policy" }).first().click();
    await expect(page.getByRole("heading", { name: "Authorized-use policy" })).toBeVisible();
    await expect(page.getByText(/Version 2026-01-15/)).toBeVisible();

    await page.goto("/privacy");
    await expect(page.getByText(/never used to train models/i).first()).toBeVisible();

    await page.goto("/terms");
    await expect(page.getByRole("heading", { name: "Terms of service" })).toBeVisible();
  });

  test("the landing page has no accessibility violations", async ({ page }) => {
    await page.goto("/");
    await expectNoAxeViolations(page);
  });

  test("the authorized-use policy has no accessibility violations", async ({ page }) => {
    await page.goto("/authorized-use-policy");
    await expectNoAxeViolations(page);
  });

  test("a skip link is the first thing keyboard users reach", async ({ page }) => {
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: /skip to main content/i })).toBeFocused();
  });
});
