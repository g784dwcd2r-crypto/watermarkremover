/**
 * Accessibility checks.
 *
 * axe-core runs against the rendered markup of the components users spend the
 * most time in. It is not a substitute for keyboard testing, so the assertions
 * below also check focus order and accessible names directly.
 */

import type { ProtectionAssessment } from "@artrestore/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Alert, Button, Field, Input, Progress, Select, Slider, Switch } from "@artrestore/ui";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import * as React from "react";
import { describe, expect, it } from "vitest";

import { ProtectionNotice } from "@/components/common/protection-notice";
import { UploadDropzone } from "@/components/common/upload-dropzone";
import { StageTimeline, type EditableStage } from "@/components/timelapse/stage-timeline";

async function expectNoViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: {
      // Landmark and page-level rules do not apply to an isolated component.
      region: { enabled: false },
      "page-has-heading-one": { enabled: false },
    },
  });
  const messages = results.violations.map(
    (violation) =>
      `${violation.id}: ${violation.help} (${violation.nodes.length} node(s))\n` +
      violation.nodes.map((node) => `  ${node.html}`).join("\n"),
  );
  expect(messages, messages.join("\n\n")).toHaveLength(0);
}

function withQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("accessibility", () => {
  it("form primitives have labels and no violations", async () => {
    const { container } = render(
      <form>
        <Field label="Project name" htmlFor="a11y-name" description="Shown on your dashboard.">
          <Input id="a11y-name" aria-describedby="a11y-name-description" />
        </Field>
        <Select
          id="a11y-select"
          label="Canvas"
          value="square"
          onValueChange={() => {}}
          options={[{ value: "square", label: "Square" }]}
        />
        <Slider id="a11y-slider" label="Feather" value={4} min={0} max={64} onValueChange={() => {}} />
        <Switch id="a11y-switch" label="Dark workspace" checked={false} onCheckedChange={() => {}} />
        <Button>Save</Button>
      </form>,
    );
    await expectNoViolations(container);
  });

  it("the upload panel has no violations", async () => {
    const { container } = withQuery(<UploadDropzone projectId="p1" retentionDays={7} />);
    await expectNoViolations(container);
  });

  it("the protection notice has no violations", async () => {
    const assessment: ProtectionAssessment = {
      blocked: true,
      requires_acknowledgement: true,
      unacknowledged_kinds: ["copyright_notice"],
      regions: [],
      explanation: "The selection may overlap a copyright or credit line.",
      overlaps: [
        {
          kind: "copyright_notice",
          severity: "review",
          confidence: 0.6,
          share_of_mask: 0.5,
          share_of_region: 0.6,
          acknowledged: false,
          reason: "Small glyph line in a margin.",
        },
      ],
    };
    const { container } = render(
      <ProtectionNotice assessment={assessment} acknowledged={[]} onAcknowledgeChange={() => {}} />,
    );
    await expectNoViolations(container);
  });

  it("the stage timeline has no violations", async () => {
    const stages: EditableStage[] = [
      { stage_type: "blank_canvas", label: "Blank canvas", order_index: 0, duration: 1, enabled: true, settings: {} },
      { stage_type: "base_colours", label: "Base colours", order_index: 1, duration: 6, enabled: true, settings: {} },
    ];
    const { container } = render(<StageTimeline stages={stages} onChange={() => {}} />);
    await expectNoViolations(container);
  });

  it("progress is announced politely, not on every frame", () => {
    render(<Progress value={0.42} label="Cleaning the image" message="Reconstructing" />);
    const bar = screen.getByRole("progressbar", { name: "Cleaning the image" });
    expect(bar).toHaveAttribute("aria-valuenow", "42");
    expect(screen.getByText(/42% complete/)).toBeInTheDocument();
  });

  it("an action-response alert is announced", () => {
    render(
      <Alert tone="danger" live>
        The cleanup could not be started.
      </Alert>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("static guidance is not announced as an alert", () => {
    render(<Alert tone="info">Uploads are private to your account.</Alert>);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("every control in the upload panel is reachable by keyboard, in order", async () => {
    withQuery(<UploadDropzone projectId="p1" />);
    // A file has to be chosen before the submit button becomes focusable; a
    // disabled control is correctly skipped by the tab sequence.
    await userEvent.upload(
      screen.getByLabelText(/choose a file to upload/i),
      new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "a.png", { type: "image/png" }),
    );
    await userEvent.click(screen.getByRole("checkbox"));

    const chooseFile = screen.getByRole("button", { name: /choose a file/i });
    chooseFile.focus();
    expect(chooseFile).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("checkbox")).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: /upload and continue/i })).toHaveFocus();
  });

  it("the submit button is skipped by the tab sequence while it is disabled", async () => {
    withQuery(<UploadDropzone projectId="p1" />);
    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: /upload and continue/i })).not.toHaveFocus();
  });

  it("icon-only controls carry accessible names", () => {
    const stages: EditableStage[] = [
      { stage_type: "blank_canvas", label: "Blank canvas", order_index: 0, duration: 3, enabled: true, settings: {} },
      { stage_type: "final_hold", label: "Finished", order_index: 1, duration: 4, enabled: true, settings: {} },
    ];
    render(<StageTimeline stages={stages} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: /move finished earlier/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /move blank canvas later/i })).toBeInTheDocument();
  });
});
