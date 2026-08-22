import * as React from "react";

import { cn } from "./utils";

const fieldClass =
  "w-full rounded-[var(--radius-md)] border border-[var(--color-line-strong)] bg-[var(--color-paper-raised)] px-3 py-2 text-sm text-[var(--color-ink)] placeholder:text-[var(--color-ink-subtle)] disabled:cursor-not-allowed disabled:opacity-60";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(fieldClass, "h-10", className)} {...props} />;
});

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(fieldClass, "min-h-24", className)} {...props} />;
});
