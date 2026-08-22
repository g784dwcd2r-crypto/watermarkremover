import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import { StageTimeline, type EditableStage } from "@/components/timelapse/stage-timeline";

const stages: EditableStage[] = [
  { stage_type: "blank_canvas", label: "Blank canvas", order_index: 0, duration: 1, enabled: true, settings: {} },
  { stage_type: "base_colours", label: "Base colours", order_index: 1, duration: 4, enabled: true, settings: {} },
  { stage_type: "final_hold", label: "Finished artwork", order_index: 2, duration: 2, enabled: true, settings: {} },
];

function Harness({ initial = stages }: { initial?: EditableStage[] }) {
  const [value, setValue] = React.useState(initial);
  return <StageTimeline stages={value} onChange={setValue} />;
}

describe("StageTimeline", () => {
  it("lists the stages in order with the running total", () => {
    render(<Harness />);
    expect(screen.getByText(/1\. Blank canvas/)).toBeInTheDocument();
    expect(screen.getByText(/3\. Finished artwork/)).toBeInTheDocument();
    expect(screen.getByText("Total 0:07")).toBeInTheDocument();
  });

  it("reorders with keyboard-operable controls", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: /move base colours earlier/i }));
    expect(screen.getByText(/1\. Base colours/)).toBeInTheDocument();
  });

  it("cannot move the first stage earlier", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: /move blank canvas earlier/i })).toBeDisabled();
  });

  it("warns when the timeline is shorter than the minimum", () => {
    render(
      <Harness
        initial={[
          { stage_type: "final_hold", label: "Hold", order_index: 0, duration: 2, enabled: true, settings: {} },
        ]}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/must be between 5s and 300s/i);
  });

  it("calls back when a stage is disabled", async () => {
    const onChange = vi.fn();
    render(<StageTimeline stages={stages} onChange={onChange} />);
    const switches = screen.getAllByRole("switch");
    await userEvent.click(switches[0]!);
    expect(onChange).toHaveBeenCalled();
    expect(onChange.mock.calls[0]?.[0][0].enabled).toBe(false);
  });

  it("marks the artist's own stages as authentic", () => {
    render(
      <Harness
        initial={[
          { stage_type: "blank_canvas", label: "Blank", order_index: 0, duration: 1, enabled: true, settings: {} },
          {
            stage_type: "real_intermediate",
            label: "Artist stage 1",
            order_index: 1,
            duration: 5,
            enabled: true,
            settings: {},
          },
        ]}
      />,
    );
    expect(screen.getByText("Your artwork stage")).toBeInTheDocument();
  });
});
