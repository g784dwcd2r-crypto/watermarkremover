import type { ProtectionAssessment } from "@artrestore/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProtectionNotice } from "@/components/common/protection-notice";

function assessment(overrides: Partial<ProtectionAssessment> = {}): ProtectionAssessment {
  return {
    blocked: false,
    requires_acknowledgement: false,
    unacknowledged_kinds: [],
    regions: [],
    overlaps: [],
    explanation: "No attribution or provenance content was detected inside the selection.",
    ...overrides,
  };
}

describe("ProtectionNotice", () => {
  it("renders nothing when the selection is clean", () => {
    const { container } = render(<ProtectionNotice assessment={assessment()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a final refusal for a signature, with no way to override it", () => {
    render(
      <ProtectionNotice
        assessment={assessment({
          blocked: true,
          explanation: "The selection overlaps an artist signature.",
          overlaps: [
            {
              kind: "signature",
              severity: "block",
              confidence: 0.9,
              share_of_mask: 0.4,
              share_of_region: 0.8,
              acknowledged: false,
              reason: "Handwritten trace in the bottom-right corner.",
            },
          ],
        })}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("cannot be processed");
    expect(screen.getAllByText(/artist signature/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/no setting that changes this/i)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("offers an attestation for an ambiguous region", async () => {
    const onAcknowledgeChange = vi.fn();
    render(
      <ProtectionNotice
        assessment={assessment({
          blocked: true,
          requires_acknowledgement: true,
          unacknowledged_kinds: ["copyright_notice"],
          explanation: "The selection may overlap a copyright or credit line.",
          overlaps: [
            {
              kind: "copyright_notice",
              severity: "review",
              confidence: 0.62,
              share_of_mask: 0.9,
              share_of_region: 0.7,
              acknowledged: false,
              reason: "A short line of small glyphs in the bottom margin.",
            },
          ],
        })}
        acknowledged={[]}
        onAcknowledgeChange={onAcknowledgeChange}
      />,
    );

    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).toBeInTheDocument();
    await userEvent.click(checkbox);
    expect(onAcknowledgeChange).toHaveBeenCalledWith(["copyright_notice"]);
  });

  it("shows both messages when the selection hits each kind", () => {
    render(
      <ProtectionNotice
        assessment={assessment({
          blocked: true,
          requires_acknowledgement: true,
          unacknowledged_kinds: ["copyright_notice"],
          explanation: "Mixed findings.",
          overlaps: [
            {
              kind: "stock_watermark",
              severity: "block",
              confidence: 0.95,
              share_of_mask: 1,
              share_of_region: 1,
              acknowledged: false,
              reason: "Tiled licensing overlay.",
            },
            {
              kind: "copyright_notice",
              severity: "review",
              confidence: 0.6,
              share_of_mask: 0.2,
              share_of_region: 0.5,
              acknowledged: false,
              reason: "Small glyph line in a margin.",
            },
          ],
        })}
        acknowledged={[]}
        onAcknowledgeChange={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("alert")).toHaveLength(2);
    expect(screen.getByText(/stock-provider watermark/i)).toBeInTheDocument();
  });
});
