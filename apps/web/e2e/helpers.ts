import { expect, type Page } from "@playwright/test";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10_000)}@example.com`;
}

export const PASSWORD = "correct-horse-battery-staple";

export async function register(page: Page, email = uniqueEmail()): Promise<string> {
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Name").fill("E2E Artist");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("checkbox", { name: /authorized-use policy/i }).click();
  await page.getByRole("checkbox", { name: /terms and the privacy policy/i }).click();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  return email;
}

/** A tiny valid PNG, generated here rather than committed as a fixture. */
export function pngBytes(): Buffer {
  // 1x1 transparent PNG.
  return Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "base64",
  );
}

/** Run axe-core against the current page and fail on any violation. */
export async function expectNoAxeViolations(page: Page, disabledRules: string[] = []) {
  await page.addScriptTag({ path: require.resolve("axe-core") });
  const results = await page.evaluate(async (rules) => {
    const options = {
      rules: Object.fromEntries(rules.map((rule: string) => [rule, { enabled: false }])),
    };
    // @ts-expect-error axe is injected onto the page above.
    return await window.axe.run(document, options);
  }, disabledRules);

  const summary = (results.violations as Array<{ id: string; help: string; nodes: unknown[] }>).map(
    (violation) => `${violation.id}: ${violation.help} (${violation.nodes.length})`,
  );
  expect(summary, summary.join("\n")).toEqual([]);
}
