import { expect, test } from "@playwright/test";

import { expectNoAxeViolations, pngBytes, register } from "./helpers";

test.describe("cleanup workflow", () => {
  test("a project cannot be processed until ownership is confirmed", async ({ page }) => {
    await register(page);

    await page.goto("/projects/new?type=cleanup");
    await page.getByLabel("Project name").fill("Consent gate");
    await page.getByRole("button", { name: "Create project" }).click();
    await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+$/);

    await expect(page.getByText(/Confirmation needed/i)).toBeVisible();

    // The submit button stays disabled until the attestation is ticked.
    await page.setInputFiles('input[type="file"]', {
      name: "demo.png",
      mimeType: "image/png",
      buffer: pngBytes(),
    });
    const submit = page.getByRole("button", { name: /upload and continue/i });
    await expect(submit).toBeDisabled();

    await page
      .getByRole("checkbox", { name: /I own this image or have permission to edit it/i })
      .click();
    await expect(submit).toBeEnabled();
  });

  test("uploading records the attestation and unlocks the editor", async ({ page }) => {
    await register(page);
    await page.goto("/projects/new?type=cleanup");
    await page.getByLabel("Project name").fill("Date stamp removal");
    await page.getByRole("button", { name: "Create project" }).click();

    await page.setInputFiles('input[type="file"]', {
      name: "demo.png",
      mimeType: "image/png",
      buffer: pngBytes(),
    });
    await page
      .getByRole("checkbox", { name: /I own this image or have permission to edit it/i })
      .click();
    await page.getByRole("button", { name: /upload and continue/i }).click();

    await expect(page.getByText(/Confirmation needed/i)).toBeHidden();
    await expect(page.getByRole("heading", { name: "Source image" })).toBeVisible();
    await expect(page.getByRole("link", { name: /open the editor/i })).toBeEnabled();
  });

  test("the retention window is stated at upload time", async ({ page }) => {
    await register(page);
    await page.goto("/projects/new?type=cleanup");
    await page.getByLabel("Project name").fill("Retention copy");
    await page
      .getByRole("combobox", { name: /delete my files automatically after/i })
      .click();
    await page.getByRole("option", { name: "1 day" }).click();
    await page.getByRole("button", { name: "Create project" }).click();

    await page.setInputFiles('input[type="file"]', {
      name: "demo.png",
      mimeType: "image/png",
      buffer: pngBytes(),
    });
    await expect(page.getByText(/deleted automatically after 1 day/i).first()).toBeVisible();
  });

  test("the dashboard lists a created project and can filter by type", async ({ page }) => {
    await register(page);
    await page.goto("/projects/new?type=cleanup");
    await page.getByLabel("Project name").fill("Filterable cleanup");
    await page.getByRole("button", { name: "Create project" }).click();

    await page.goto("/dashboard");
    await expect(page.getByRole("link", { name: "Filterable cleanup" })).toBeVisible();

    await page.getByRole("combobox", { name: "Type" }).click();
    await page.getByRole("option", { name: "Timelapse" }).click();
    await expect(page.getByRole("link", { name: "Filterable cleanup" })).toBeHidden();
  });

  test("the dashboard has no accessibility violations", async ({ page }) => {
    await register(page);
    await expectNoAxeViolations(page);
  });
});
