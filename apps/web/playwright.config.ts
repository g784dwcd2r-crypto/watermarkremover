import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.PORT ?? 3000);
// localhost, not 127.0.0.1: the API sets SameSite=Lax cookies, and a different
// host name would make every API call cross-site and drop the session.
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${PORT}`;

// Some CI images ship a Chromium build that does not match the version this
// Playwright expects. PLAYWRIGHT_CHROMIUM_EXECUTABLE points at the one that is
// actually present instead of downloading another copy.
const chromiumPath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
const launchOptions = chromiumPath ? { launchOptions: { executablePath: chromiumPath } } : {};

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], ...launchOptions } },
    { name: "mobile", use: { ...devices["Pixel 7"], ...launchOptions } },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "npm run start",
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
