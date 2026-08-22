"use client";

import type { ProtectionAssessment, ProtectedKind } from "@artrestore/types";
import { PROTECTED_KIND_LABELS } from "@artrestore/types";
import { Alert, Badge, Button, ConsentCheckbox } from "@artrestore/ui";
import * as React from "react";

/**
 * The safeguard banner.
 *
 * Two very different messages share this component, and the difference matters:
 * a `block` finding is final and offers no override, while a `review` finding
 * asks the user to attest that an ambiguous shape is not attribution content.
 */
export function ProtectionNotice({
  assessment,
  acknowledged,
  onAcknowledgeChange,
  onAdjustMask,
}: {
  assessment: ProtectionAssessment;
  acknowledged?: ProtectedKind[];
  onAcknowledgeChange?: (kinds: ProtectedKind[]) => void;
  onAdjustMask?: () => void;
}) {
  const blocking = assessment.overlaps.filter((overlap) => overlap.severity === "block");
  const review = assessment.overlaps.filter((overlap) => overlap.severity === "review");

  if (blocking.length === 0 && review.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {blocking.length > 0 ? (
        <Alert tone="protected" title="This selection cannot be processed" live>
          <p>{assessment.explanation}</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {blocking.map((overlap) => (
              <li key={`${overlap.kind}-${overlap.share_of_region}`}>
                <Badge tone="danger">
                  {PROTECTED_KIND_LABELS[overlap.kind] ?? overlap.kind} ·{" "}
                  {Math.round(overlap.confidence * 100)}% confidence
                </Badge>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs opacity-90">
            Attribution and provenance content is out of scope for this product. There is no setting
            that changes this.
          </p>
          {onAdjustMask ? (
            <div className="mt-3">
              <Button size="sm" variant="secondary" onClick={onAdjustMask}>
                Adjust the mask
              </Button>
            </div>
          ) : null}
        </Alert>
      ) : null}

      {review.length > 0 ? (
        <Alert tone="warning" title="Check this region before continuing" live>
          <p>{assessment.explanation}</p>
          <div className="mt-3 flex flex-col gap-2">
            {review.map((overlap) => {
              const isAcknowledged = acknowledged?.includes(overlap.kind) ?? false;
              return (
                <div key={overlap.kind} className="flex flex-col gap-1.5">
                  <p className="text-xs opacity-90">{overlap.reason}</p>
                  <ConsentCheckbox
                    id={`acknowledge-${overlap.kind}`}
                    checked={isAcknowledged}
                    onCheckedChange={(value) => {
                      if (!onAcknowledgeChange) return;
                      const current = new Set(acknowledged ?? []);
                      if (value) current.add(overlap.kind);
                      else current.delete(overlap.kind);
                      onAcknowledgeChange([...current]);
                    }}
                    label={`This is not ${
                      PROTECTED_KIND_LABELS[overlap.kind] ?? overlap.kind
                    } — I am authorized to remove it`}
                    description="Your confirmation is recorded against this project."
                  />
                </div>
              );
            })}
          </div>
        </Alert>
      ) : null}
    </div>
  );
}

/** A compact read-only list, used on the upload and project screens. */
export function DetectedProtectedList({
  regions,
}: {
  regions: Array<{ kind: string; reason: string; confidence: number; severity?: string }>;
}) {
  if (regions.length === 0) return null;
  return (
    <ul className="flex flex-col gap-2">
      {regions.map((region, index) => (
        <li
          key={`${region.kind}-${index}`}
          className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--color-line)] bg-[var(--color-paper-sunken)] p-3 text-sm"
        >
          <Badge tone={region.severity === "review" ? "warning" : "danger"}>
            {PROTECTED_KIND_LABELS[region.kind as ProtectedKind] ?? region.kind}
          </Badge>
          <span className="text-[var(--color-ink-muted)]">{region.reason}</span>
        </li>
      ))}
    </ul>
  );
}
