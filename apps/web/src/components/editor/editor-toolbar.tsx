"use client";

import { Button, Select, Slider, Switch, Tooltip, cn } from "@artrestore/ui";
import {
  Brush,
  Eraser,
  Expand,
  Eye,
  EyeOff,
  Hand,
  Lasso,
  Maximize,
  Redo2,
  Square,
  Sun,
  Moon,
  Trash2,
  Undo2,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import * as React from "react";

import { useEditorStore, type EditorTool } from "@/store/editor-store";

const TOOLS: Array<{ tool: EditorTool; label: string; icon: React.ElementType; shortcut: string }> =
  [
    { tool: "brush", label: "Brush", icon: Brush, shortcut: "B" },
    { tool: "eraser", label: "Eraser", icon: Eraser, shortcut: "E" },
    { tool: "rect", label: "Rectangle selection", icon: Square, shortcut: "R" },
    { tool: "lasso", label: "Lasso selection", icon: Lasso, shortcut: "L" },
    { tool: "polygon", label: "Polygon selection", icon: Expand, shortcut: "P" },
    { tool: "pan", label: "Pan", icon: Hand, shortcut: "H" },
  ];

export function EditorToolbar({
  onFitToScreen,
  className,
}: {
  onFitToScreen: () => void;
  className?: string;
}) {
  const store = useEditorStore();

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-1 rounded-[var(--radius-lg)] border border-[var(--color-line)] bg-[var(--color-paper-raised)] p-1.5",
        className,
      )}
      role="toolbar"
      aria-label="Mask tools"
    >
      {TOOLS.map(({ tool, label, icon: Icon, shortcut }) => (
        <Tooltip key={tool} label={label} shortcut={shortcut}>
          <Button
            variant={store.tool === tool ? "primary" : "ghost"}
            size="icon"
            aria-label={label}
            aria-pressed={store.tool === tool}
            onClick={() => store.setTool(tool)}
          >
            <Icon aria-hidden="true" />
          </Button>
        </Tooltip>
      ))}

      <span className="mx-1 h-6 w-px bg-[var(--color-line)]" aria-hidden="true" />

      <Tooltip label="Undo" shortcut="Ctrl+Z">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Undo"
          disabled={!store.canUndo()}
          onClick={store.undo}
        >
          <Undo2 aria-hidden="true" />
        </Button>
      </Tooltip>
      <Tooltip label="Redo" shortcut="Ctrl+Y">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Redo"
          disabled={!store.canRedo()}
          onClick={store.redo}
        >
          <Redo2 aria-hidden="true" />
        </Button>
      </Tooltip>
      <Tooltip label="Clear the mask">
        <Button variant="ghost" size="icon" aria-label="Clear the mask" onClick={store.clearMask}>
          <Trash2 aria-hidden="true" />
        </Button>
      </Tooltip>

      <span className="mx-1 h-6 w-px bg-[var(--color-line)]" aria-hidden="true" />

      <Tooltip label="Zoom out" shortcut="-">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Zoom out"
          onClick={() => store.zoomBy(1 / 1.2)}
        >
          <ZoomOut aria-hidden="true" />
        </Button>
      </Tooltip>
      <span className="min-w-12 text-center text-xs text-[var(--color-ink-muted)] tabular-nums">
        {Math.round(store.zoom * 100)}%
      </span>
      <Tooltip label="Zoom in" shortcut="+">
        <Button variant="ghost" size="icon" aria-label="Zoom in" onClick={() => store.zoomBy(1.2)}>
          <ZoomIn aria-hidden="true" />
        </Button>
      </Tooltip>
      <Tooltip label="Fit to screen" shortcut="0">
        <Button variant="ghost" size="icon" aria-label="Fit to screen" onClick={onFitToScreen}>
          <Maximize aria-hidden="true" />
        </Button>
      </Tooltip>
      <Tooltip label="Actual size (100%)" shortcut="1">
        <Button variant="ghost" size="sm" aria-label="Actual size" onClick={store.actualSize}>
          1:1
        </Button>
      </Tooltip>

      <span className="mx-1 h-6 w-px bg-[var(--color-line)]" aria-hidden="true" />

      <Tooltip label={store.showMask ? "Hide the mask" : "Show the mask"} shortcut="M">
        <Button
          variant="ghost"
          size="icon"
          aria-label={store.showMask ? "Hide the mask" : "Show the mask"}
          aria-pressed={store.showMask}
          onClick={store.toggleMaskVisibility}
        >
          {store.showMask ? <Eye aria-hidden="true" /> : <EyeOff aria-hidden="true" />}
        </Button>
      </Tooltip>
      <Tooltip label={store.theme === "dark" ? "Light workspace" : "Dark workspace"}>
        <Button
          variant="ghost"
          size="icon"
          aria-label={
            store.theme === "dark" ? "Switch to light workspace" : "Switch to dark workspace"
          }
          onClick={() => store.setTheme(store.theme === "dark" ? "light" : "dark")}
        >
          {store.theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
        </Button>
      </Tooltip>
    </div>
  );
}

/** Brush shaping and mask post-processing controls. */
export function BrushPanel() {
  const store = useEditorStore();
  const isBrush = store.tool === "brush" || store.tool === "eraser";

  return (
    <div className="flex flex-col gap-4">
      <Slider
        id="brush-size"
        label="Brush size"
        value={store.brush.size}
        min={2}
        max={400}
        onValueChange={(size) => store.setBrush({ size })}
        format={(value) => `${value} px`}
        disabled={!isBrush}
      />
      <Slider
        id="brush-hardness"
        label="Hardness"
        value={store.brush.hardness}
        min={0}
        max={1}
        step={0.05}
        onValueChange={(hardness) => store.setBrush({ hardness })}
        format={(value) => `${Math.round(value * 100)}%`}
        hint="Softer edges blend the repair into its surroundings."
        disabled={!isBrush}
      />
      <Slider
        id="brush-opacity"
        label="Opacity"
        value={store.brush.opacity}
        min={0.1}
        max={1}
        step={0.05}
        onValueChange={(opacity) => store.setBrush({ opacity })}
        format={(value) => `${Math.round(value * 100)}%`}
        disabled={!isBrush}
      />
    </div>
  );
}

export function MaskAdjustmentsPanel() {
  const { adjustments, setAdjustments } = useEditorStore();
  return (
    <div className="flex flex-col gap-4">
      <Slider
        id="mask-expand"
        label="Expand / contract"
        value={adjustments.expand}
        min={-40}
        max={40}
        onValueChange={(expand) => setAdjustments({ expand })}
        format={(value) => `${value > 0 ? "+" : ""}${value} px`}
        hint="Grow the selection to catch anti-aliased edges, or pull it back off nearby detail."
      />
      <Slider
        id="mask-feather"
        label="Feather"
        value={adjustments.feather}
        min={0}
        max={64}
        onValueChange={(feather) => setAdjustments({ feather })}
        format={(value) => `${value} px`}
        hint="Softens the boundary so the repair does not leave a seam."
      />
      <Slider
        id="mask-blur"
        label="Extra blur"
        value={adjustments.blur}
        min={0}
        max={64}
        onValueChange={(blur) => setAdjustments({ blur })}
        format={(value) => `${value} px`}
      />
    </div>
  );
}

export function ComparisonControls() {
  const { comparison, setComparison, sliderPosition, setSliderPosition } = useEditorStore();
  return (
    <div className="flex flex-col gap-3">
      <Select
        id="comparison-view"
        label="Comparison"
        value={comparison}
        onValueChange={(value) => setComparison(value as typeof comparison)}
        options={[
          { value: "single", label: "Result only" },
          { value: "split", label: "Split view", description: "Original beside the result" },
          { value: "slider", label: "Before / after slider" },
          {
            value: "difference",
            label: "Difference map",
            description: "Exactly which pixels changed",
          },
        ]}
      />
      {comparison === "slider" ? (
        <Slider
          id="comparison-position"
          label="Slider position"
          value={sliderPosition}
          min={0}
          max={1}
          step={0.01}
          onValueChange={setSliderPosition}
          format={(value) => `${Math.round(value * 100)}%`}
        />
      ) : null}
    </div>
  );
}

export function AutosaveIndicator({
  saving,
  dirty,
  version,
}: {
  saving: boolean;
  dirty: boolean;
  version: number | null;
}) {
  const message = saving
    ? "Saving mask..."
    : dirty
      ? "Unsaved changes"
      : version
        ? `Saved as version ${version}`
        : "No mask saved yet";
  return (
    <p className="text-xs text-[var(--color-ink-muted)]" aria-live="polite">
      {message}
    </p>
  );
}

export function WorkspaceToggle() {
  const { theme, setTheme } = useEditorStore();
  return (
    <Switch
      id="workspace-theme"
      label="Dark workspace"
      description="A neutral dark surround makes colour judgements easier."
      checked={theme === "dark"}
      onCheckedChange={(value) => setTheme(value ? "dark" : "light")}
    />
  );
}
