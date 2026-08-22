"use client";

import type { TimelapseStage } from "@artrestore/types";
import { Alert, Badge, Button, Slider, Switch, Tooltip, formatDuration } from "@artrestore/ui";
import { ArrowDown, ArrowUp, GripVertical } from "lucide-react";
import * as React from "react";

export interface EditableStage {
  stage_type: string;
  label: string;
  order_index: number;
  duration: number;
  enabled: boolean;
  settings: Record<string, unknown>;
}

export function toEditable(stages: TimelapseStage[]): EditableStage[] {
  return stages.map((stage) => ({
    stage_type: stage.stage_type,
    label: stage.label,
    order_index: stage.order_index,
    duration: stage.duration,
    enabled: stage.enabled,
    settings: stage.settings,
  }));
}

/**
 * The editable stage timeline.
 *
 * Reordering is done with explicit up/down buttons rather than drag-only, so
 * the timeline is fully operable from the keyboard. Each stage carries its own
 * duration slider; the total is shown live because the render endpoint enforces
 * a 5s-5min range.
 */
export function StageTimeline({
  stages,
  onChange,
  minSeconds = 5,
  maxSeconds = 300,
  authenticStageCount = 0,
}: {
  stages: EditableStage[];
  onChange: (stages: EditableStage[]) => void;
  minSeconds?: number;
  maxSeconds?: number;
  authenticStageCount?: number;
}) {
  const total = stages
    .filter((stage) => stage.enabled)
    .reduce((sum, stage) => sum + stage.duration, 0);
  const outOfRange = total < minSeconds || total > maxSeconds;

  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= stages.length) return;
    const next = [...stages];
    const a = next[index]!;
    const b = next[target]!;
    next[index] = b;
    next[target] = a;
    onChange(next.map((stage, position) => ({ ...stage, order_index: position })));
  };

  const update = (index: number, patch: Partial<EditableStage>) => {
    onChange(
      stages.map((stage, position) => (position === index ? { ...stage, ...patch } : stage)),
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">Stage timeline</h3>
        <Badge tone={outOfRange ? "danger" : "primary"}>Total {formatDuration(total)}</Badge>
      </div>

      {outOfRange ? (
        <Alert tone="warning" live>
          The timeline is {total.toFixed(1)}s. It must be between {minSeconds}s and {maxSeconds}s
          before it can be rendered.
        </Alert>
      ) : null}

      {authenticStageCount > 0 ? (
        <Alert tone="info">
          {authenticStageCount} of these stages are your own uploaded progress images. They are used
          as real keyframes in the order you uploaded them; only the transitions between them are
          generated.
        </Alert>
      ) : null}

      <ol className="flex flex-col gap-2">
        {stages.map((stage, index) => {
          const authentic = stage.stage_type === "real_intermediate";
          return (
            <li
              key={`${stage.stage_type}-${index}`}
              className={`rounded-[var(--radius-md)] border p-3 ${
                stage.enabled
                  ? "border-[var(--color-line)] bg-[var(--color-paper-raised)]"
                  : "border-dashed border-[var(--color-line)] bg-[var(--color-paper-sunken)] opacity-70"
              }`}
            >
              <div className="flex items-start gap-3">
                <GripVertical
                  className="mt-1 size-4 shrink-0 text-[var(--color-ink-subtle)]"
                  aria-hidden="true"
                />
                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-[var(--color-ink)]">
                      {index + 1}. {stage.label || stage.stage_type}
                    </span>
                    {authentic ? <Badge tone="success">Your artwork stage</Badge> : null}
                  </div>
                  <Slider
                    id={`stage-duration-${index}`}
                    label="Duration"
                    value={Number(stage.duration.toFixed(2))}
                    min={0.2}
                    max={60}
                    step={0.1}
                    onValueChange={(duration) => update(index, { duration })}
                    format={(value) => `${value.toFixed(1)}s`}
                  />
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <div className="flex gap-1">
                    <Tooltip label="Move earlier">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Move ${stage.label} earlier`}
                        disabled={index === 0}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp aria-hidden="true" />
                      </Button>
                    </Tooltip>
                    <Tooltip label="Move later">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Move ${stage.label} later`}
                        disabled={index === stages.length - 1}
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown aria-hidden="true" />
                      </Button>
                    </Tooltip>
                  </div>
                  <Switch
                    id={`stage-enabled-${index}`}
                    label=""
                    accessibleLabel={`Include ${stage.label || stage.stage_type} in the timeline`}
                    checked={stage.enabled}
                    onCheckedChange={(enabled) => update(index, { enabled })}
                  />
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
