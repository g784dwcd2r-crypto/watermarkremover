import { expect, test } from "@playwright/test";

import { pngBytes, register } from "./helpers";

test.describe("timelapse reconstruction", () => {
  test("the disclosure is stated in the editor and is not presented as optional", async ({
    page,
  }) => {
    await register(page);
    await page.goto("/projects/new?type=timelapse");
    await page.getByLabel("Project name").fill("Process video");
    await page.getByRole("combobox", { name: /what are you doing/i }).click();
    await page.getByRole("option", { name: /reconstructed timelapse/i }).click();
    await page.getByRole("button", { name: "Create project" }).click();

    await page.setInputFiles('input[type="file"]', {
      name: "artwork.png",
      mimeType: "image/png",
      buffer: pngBytes(),
    });
    await page
      .getByRole("checkbox", { name: /I own this image or have permission to edit it/i })
      .click();
    await page.getByRole("button", { name: /upload and continue/i }).click();

    await page.getByRole("link", { name: /open the timelapse editor/i }).click();
    await expect(page).toHaveURL(/\/timelapse$/);

    await expect(
      page.getByText(/labelled a reconstruction in its file metadata/i),
    ).toBeVisible();

    // The metadata disclosure is explicitly described as non-optional.
    await expect(page.getByText(/cannot be turned off/i)).toBeVisible();

    // The visible end card defaults to on.
    const endCard = page.getByRole("switch", { name: /show the end card/i });
    await expect(endCard).toHaveAttribute("aria-checked", "true");
  });

  test("Real Intermediate Frames is unavailable without uploaded progress images", async ({
    page,
  }) => {
    await register(page);
    await page.goto("/projects/new?type=timelapse");
    await page.getByLabel("Project name").fill("No intermediates");
    await page.getByRole("combobox", { name: /what are you doing/i }).click();
    await page.getByRole("option", { name: /reconstructed timelapse/i }).click();
    await page.getByRole("button", { name: "Create project" }).click();

    await page.setInputFiles('input[type="file"]', {
      name: "artwork.png",
      mimeType: "image/png",
      buffer: pngBytes(),
    });
    await page
      .getByRole("checkbox", { name: /I own this image or have permission to edit it/i })
      .click();
    await page.getByRole("button", { name: /upload and continue/i }).click();
    await page.getByRole("link", { name: /open the timelapse editor/i }).click();

    await page.getByRole("combobox", { name: "Mode" }).click();
    await expect(
      page.getByRole("option", { name: /Real Intermediate Frames/i }),
    ).toHaveAttribute("data-disabled", "");
  });
});
