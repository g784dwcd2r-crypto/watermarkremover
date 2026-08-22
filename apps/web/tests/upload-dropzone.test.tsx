import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it } from "vitest";

import { UploadDropzone } from "@/components/common/upload-dropzone";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const pngFile = () =>
  new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "artwork.png", { type: "image/png" });

describe("UploadDropzone", () => {
  it("keeps the upload disabled until ownership is confirmed", async () => {
    renderWithQuery(<UploadDropzone projectId="p1" retentionDays={7} />);

    const input = screen.getByLabelText(/choose a file to upload/i);
    await userEvent.upload(input, pngFile());

    const button = screen.getByRole("button", { name: /upload and continue/i });
    expect(button).toBeDisabled();
    expect(screen.getByText(/confirm ownership to enable processing/i)).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("checkbox", { name: /i own this image or have permission to edit it/i }),
    );
    expect(button).toBeEnabled();
  });

  it("states the exact ownership wording", () => {
    renderWithQuery(<UploadDropzone projectId="p1" />);
    expect(screen.getByText("I own this image or have permission to edit it.")).toBeInTheDocument();
  });

  it("rejects an unsupported file type before any request is made", async () => {
    renderWithQuery(<UploadDropzone projectId="p1" />);
    const input = screen.getByLabelText(/choose a file to upload/i);
    // user-event honours the accept attribute, so the rejected type is fed in
    // directly - the component must not rely on the browser filter alone.
    fireEvent.change(input, {
      target: { files: [new File(["<svg/>"], "evil.svg", { type: "image/svg+xml" })] },
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(/not supported/i);
  });

  it("rejects a file over the size limit", async () => {
    renderWithQuery(<UploadDropzone projectId="p1" />);
    const big = new File([new Uint8Array(10)], "big.png", { type: "image/png" });
    Object.defineProperty(big, "size", { value: 999_999_999 });

    await userEvent.upload(screen.getByLabelText(/choose a file to upload/i), big);
    expect(await screen.findByRole("alert")).toHaveTextContent(/limit is/i);
  });

  it("states the retention window once a file is chosen", async () => {
    renderWithQuery(<UploadDropzone projectId="p1" retentionDays={1} />);
    await userEvent.upload(screen.getByLabelText(/choose a file to upload/i), pngFile());
    expect(await screen.findByText(/never used to train models/i)).toBeInTheDocument();
    expect(screen.getByText(/deleted automatically after 1 day/i)).toBeInTheDocument();
  });

  it("skips the ownership gate for supporting assets", () => {
    renderWithQuery(
      <UploadDropzone projectId="p1" assetType="intermediate" requireOwnership={false} />,
    );
    expect(screen.getByRole("button", { name: /upload and continue/i })).toBeDisabled();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});
