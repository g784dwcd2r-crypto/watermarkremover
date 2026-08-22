import { expect, test } from "@playwright/test";

import { PASSWORD, expectNoAxeViolations, register, uniqueEmail } from "./helpers";

test.describe("authentication", () => {
  test("a new account can register, sign out and sign back in", async ({ page }) => {
    const email = await register(page);

    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/$/);

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("registration requires accepting both policies", async ({ page }) => {
    await page.goto("/register");
    await page.getByLabel("Email").fill(uniqueEmail());
    await page.getByLabel("Password").fill(PASSWORD);
    await expect(page.getByRole("button", { name: "Create account" })).toBeDisabled();

    await page.getByRole("checkbox", { name: /authorized-use policy/i }).click();
    await expect(page.getByRole("button", { name: "Create account" })).toBeDisabled();

    await page.getByRole("checkbox", { name: /terms and the privacy policy/i }).click();
    await expect(page.getByRole("button", { name: "Create account" })).toBeEnabled();
  });

  test("a wrong password is rejected with a clear message", async ({ page }) => {
    const email = await register(page);
    await page.getByRole("button", { name: "Sign out" }).click();

    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Log in" }).click();
    // Next renders a route announcer with role="alert"; scope to the form's own.
    await expect(page.locator("form").getByRole("alert")).toContainText(/not correct/i);
  });

  test("signed-out visitors are sent to the login page", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("the login page has no accessibility violations", async ({ page }) => {
    await page.goto("/login");
    await expectNoAxeViolations(page);
  });
});
