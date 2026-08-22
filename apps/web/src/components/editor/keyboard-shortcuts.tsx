"use client";

import * as React from "react";

import { useEditorStore } from "@/store/editor-store";

export interface ShortcutHandlers {
  onSave?: () => void;
  onProcess?: () => void;
  onFit?: () => void;
}

/**
 * Editor keyboard shortcuts.
 *
 * Bound at the document level but ignored while focus is inside a text field,
 * so typing a project name never switches tools.
 */
export function useEditorShortcuts({ onSave, onProcess, onFit }: ShortcutHandlers = {}) {
  const store = useEditorStore();

  React.useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable ||
          target.getAttribute("role") === "slider")
      ) {
        return;
      }

      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) store.redo();
        else store.undo();
        return;
      }
      if (meta && event.key.toLowerCase() === "y") {
        event.preventDefault();
        store.redo();
        return;
      }
      if (meta && event.key.toLowerCase() === "s") {
        event.preventDefault();
        onSave?.();
        return;
      }
      if (meta && event.key === "Enter") {
        event.preventDefault();
        onProcess?.();
        return;
      }

      switch (event.key.toLowerCase()) {
        case "b":
          store.setTool("brush");
          break;
        case "e":
          store.setTool("eraser");
          break;
        case "r":
          store.setTool("rect");
          break;
        case "l":
          store.setTool("lasso");
          break;
        case "p":
          store.setTool("polygon");
          break;
        case "h":
        case " ":
          store.setTool("pan");
          break;
        case "m":
          store.toggleMaskVisibility();
          break;
        case "0":
          onFit?.();
          break;
        case "1":
          store.actualSize();
          break;
        case "+":
        case "=":
          store.zoomBy(1.2);
          break;
        case "-":
          store.zoomBy(1 / 1.2);
          break;
        case "[":
          store.setBrush({ size: Math.max(2, store.brush.size - 4) });
          break;
        case "]":
          store.setBrush({ size: Math.min(400, store.brush.size + 4) });
          break;
        default:
          break;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [store, onSave, onProcess, onFit]);
}

export const SHORTCUTS: Array<{ keys: string; action: string }> = [
  { keys: "B / E", action: "Brush / eraser" },
  { keys: "R / L / P", action: "Rectangle, lasso, polygon" },
  { keys: "H or Space", action: "Pan" },
  { keys: "[ / ]", action: "Smaller / larger brush" },
  { keys: "+ / -", action: "Zoom in / out" },
  { keys: "0 / 1", action: "Fit to screen / 100%" },
  { keys: "M", action: "Show or hide the mask" },
  { keys: "Ctrl+Z / Ctrl+Shift+Z", action: "Undo / redo" },
  { keys: "Ctrl+S", action: "Save the mask" },
  { keys: "Ctrl+Enter", action: "Process" },
];

export function ShortcutList() {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
      {SHORTCUTS.map((shortcut) => (
        <React.Fragment key={shortcut.keys}>
          <dt>
            <kbd className="rounded border border-[var(--color-line-strong)] bg-[var(--color-paper-sunken)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--color-ink-muted)]">
              {shortcut.keys}
            </kbd>
          </dt>
          <dd className="text-[var(--color-ink-muted)]">{shortcut.action}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}
