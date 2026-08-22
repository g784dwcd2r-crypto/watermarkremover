import { AlertTriangle, CheckCircle2, Info, ShieldAlert } from "lucide-react";
import * as React from "react";

import { cn } from "./utils";

export type AlertTone = "info" | "success" | "warning" | "danger" | "protected";

const toneStyles: Record<AlertTone, { box: string; icon: React.ElementType }> = {
  info: {
    box: "border-[var(--color-info)]/25 bg-[var(--color-info-soft)] text-[var(--color-info)]",
    icon: Info,
  },
  success: {
    box: "border-[var(--color-success)]/25 bg-[var(--color-success-soft)] text-[var(--color-success)]",
    icon: CheckCircle2,
  },
  warning: {
    box: "border-[var(--color-warning)]/30 bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
    icon: AlertTriangle,
  },
  danger: {
    box: "border-[var(--color-danger)]/30 bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
    icon: AlertTriangle,
  },
  protected: {
    box: "border-[var(--color-danger)]/35 bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
    icon: ShieldAlert,
  },
};

/**
 * A message block. `role="alert"` is used only for messages that appear in
 * response to an action, so routine page content is not announced twice.
 */
export function Alert({
  tone = "info",
  title,
  children,
  live = false,
  className,
  action,
}: {
  tone?: AlertTone;
  title?: React.ReactNode;
  children?: React.ReactNode;
  live?: boolean;
  className?: string;
  action?: React.ReactNode;
}) {
  const { box, icon: Icon } = toneStyles[tone];
  return (
    <div
      role={live ? "alert" : undefined}
      className={cn("flex gap-3 rounded-[var(--radius-md)] border p-3.5", box, className)}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {title ? <p className="text-sm font-semibold">{title}</p> : null}
        {children ? <div className="text-sm leading-relaxed opacity-95">{children}</div> : null}
        {action ? <div className="mt-1.5">{action}</div> : null}
      </div>
    </div>
  );
}
