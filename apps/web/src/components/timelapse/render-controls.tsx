"use client";

import type { CanvasPresetKey, TimelapseOptions, TimelapseRenderRequest } from "@artrestore/types";
import { Alert, Badge, Select, Slider, Switch } from "@artrestore/ui";
import * as React from "react";

export type RenderSettings = Omit<TimelapseRenderRequest, "idempotency_key">;

export const DEFAULT_RENDER_SETTINGS: RenderSettings = {
  mode: "sketch_to_colour",
  duration_seconds: 15,
  fps: 30,
  preset: "square",
  formats: ["mp4", "poster"],
  seed: 1,
  background_colour: "#F7F4EF",
  stroke_speed: 1,
  stroke_density: 1,
  brush_size_min: 6,
  brush_size_max: 48,
  transition_curve: "ease_in_out",
  hold_final_seconds: 1.5,
  zoom_pan: false,
  show_cursor: false,
  brand_watermark_asset_id: null,
  audio_asset_id: null,
  audio_start_seconds: 0,
  audio_volume: 0.8,
  end_card_disclosure: true,
  gif_fps: 12,
  gif_max_width: 480,
};

const FORMAT_OPTIONS: Array<{
  value: RenderSettings["formats"][number];
  label: string;
  hint: string;
}> = [
  { value: "mp4", label: "MP4 (H.264)", hint: "Best for social platforms" },
  { value: "webm", label: "WebM (VP9)", hint: "Smaller files for the web" },
  { value: "gif", label: "GIF preview", hint: "Short, low resolution" },
  { value: "poster", label: "Poster frame", hint: "Thumbnail still" },
  { value: "frames", label: "PNG frames", hint: "A zip for re-editing" },
  { value: "project_json", label: "Project JSON", hint: "Settings, seed and stage list" },
  { value: "svg", label: "Stroke SVG", hint: "Simulated stroke paths as vectors" },
];

export function RenderControls({
  options,
  settings,
  onChange,
  audioAssets,
  brandAssets,
}: {
  options: TimelapseOptions | undefined;
  settings: RenderSettings;
  onChange: (patch: Partial<RenderSettings>) => void;
  audioAssets?: Array<{ id: string; label: string }>;
  brandAssets?: Array<{ id: string; label: string }>;
}) {
  const presets = options?.presets ?? [];

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-4">
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">Output</h3>
        <Select
          id="render-preset"
          label="Canvas"
          value={settings.preset}
          onValueChange={(value) => onChange({ preset: value as CanvasPresetKey })}
          options={presets.map((preset) => ({
            value: preset.key,
            label: preset.label,
            description: preset.note,
          }))}
        />
        <Select
          id="render-fps"
          label="Frame rate"
          value={String(settings.fps)}
          onValueChange={(value) => onChange({ fps: Number(value) as 24 | 30 | 60 })}
          options={(options?.fps_options ?? [24, 30, 60]).map((fps) => ({
            value: String(fps),
            label: `${fps} fps`,
          }))}
        />
        <Slider
          id="render-duration"
          label="Duration"
          value={settings.duration_seconds}
          min={options?.duration_seconds.min ?? 5}
          max={options?.duration_seconds.max ?? 300}
          step={1}
          onValueChange={(duration_seconds) => onChange({ duration_seconds })}
          format={(value) =>
            `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2, "0")}`
          }
        />
        <Slider
          id="render-hold"
          label="Pause on the finished artwork"
          value={settings.hold_final_seconds}
          min={0}
          max={10}
          step={0.5}
          onValueChange={(hold_final_seconds) => onChange({ hold_final_seconds })}
          format={(value) => `${value.toFixed(1)}s`}
        />

        {settings.formats.includes("gif") ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Slider
              id="render-gif-fps"
              label="GIF frame rate"
              value={settings.gif_fps}
              min={4}
              max={30}
              onValueChange={(gif_fps) => onChange({ gif_fps })}
              format={(value) => `${value} fps`}
            />
            <Slider
              id="render-gif-width"
              label="GIF width"
              value={settings.gif_max_width}
              min={120}
              max={1080}
              step={20}
              onValueChange={(gif_max_width) => onChange({ gif_max_width })}
              format={(value) => `${value} px`}
            />
          </div>
        ) : null}

        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-[var(--color-ink)]">Formats</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {FORMAT_OPTIONS.map((format) => {
              const checked = settings.formats.includes(format.value);
              return (
                <label
                  key={format.value}
                  className="flex cursor-pointer items-start gap-2 rounded-[var(--radius-md)] border border-[var(--color-line)] p-2.5"
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    className="mt-1 accent-[var(--color-primary)]"
                    onChange={(event) => {
                      const next = new Set(settings.formats);
                      if (event.target.checked) next.add(format.value);
                      else next.delete(format.value);
                      onChange({ formats: [...next] as RenderSettings["formats"] });
                    }}
                  />
                  <span className="flex flex-col">
                    <span className="text-sm text-[var(--color-ink)]">{format.label}</span>
                    <span className="text-xs text-[var(--color-ink-muted)]">{format.hint}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">Motion</h3>
        <Select
          id="render-curve"
          label="Transition curve"
          value={settings.transition_curve}
          onValueChange={(transition_curve) => onChange({ transition_curve })}
          options={(
            options?.transition_curves ?? ["linear", "ease_in", "ease_out", "ease_in_out"]
          ).map((curve) => ({ value: curve, label: curve.replace(/_/g, " ") }))}
        />
        <Slider
          id="render-stroke-speed"
          label="Stroke speed"
          value={settings.stroke_speed}
          min={0.1}
          max={4}
          step={0.1}
          onValueChange={(stroke_speed) => onChange({ stroke_speed })}
          format={(value) => `${value.toFixed(1)}×`}
        />
        <Slider
          id="render-stroke-density"
          label="Stroke density"
          value={settings.stroke_density}
          min={0.1}
          max={4}
          step={0.1}
          onValueChange={(stroke_density) => onChange({ stroke_density })}
          format={(value) => `${value.toFixed(1)}×`}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Slider
            id="render-brush-min"
            label="Smallest brush"
            value={settings.brush_size_min}
            min={1}
            max={128}
            onValueChange={(brush_size_min) =>
              onChange({
                brush_size_min,
                brush_size_max: Math.max(brush_size_min, settings.brush_size_max),
              })
            }
            format={(value) => `${value} px`}
          />
          <Slider
            id="render-brush-max"
            label="Largest brush"
            value={settings.brush_size_max}
            min={1}
            max={256}
            onValueChange={(brush_size_max) =>
              onChange({
                brush_size_max,
                brush_size_min: Math.min(brush_size_max, settings.brush_size_min),
              })
            }
            format={(value) => `${value} px`}
          />
        </div>
        <Slider
          id="render-seed"
          label="Randomness seed"
          value={settings.seed}
          min={0}
          max={9999}
          onValueChange={(seed) => onChange({ seed })}
          hint="The same seed reproduces the same video exactly."
        />
        <Switch
          id="render-zoom-pan"
          label="Zoom and pan"
          description="A slow push toward the focal point."
          checked={settings.zoom_pan}
          onCheckedChange={(zoom_pan) => onChange({ zoom_pan })}
        />
        <Switch
          id="render-cursor"
          label="Show a brush cursor"
          description="Decorative. The export records that cursor motion is simulated, not real input history."
          checked={settings.show_cursor}
          onCheckedChange={(show_cursor) => onChange({ show_cursor })}
        />
      </section>

      <section className="flex flex-col gap-4">
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">Branding and audio</h3>
        <label htmlFor="render-background" className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-[var(--color-ink)]">Background colour</span>
          <input
            id="render-background"
            type="color"
            value={settings.background_colour}
            onChange={(event) => onChange({ background_colour: event.target.value.toUpperCase() })}
            className="h-9 w-16 cursor-pointer rounded-[var(--radius-sm)] border border-[var(--color-line-strong)]"
          />
        </label>

        <Select
          id="render-brand"
          label="Your brand mark"
          value={settings.brand_watermark_asset_id ?? "none"}
          onValueChange={(value) =>
            onChange({ brand_watermark_asset_id: value === "none" ? null : value })
          }
          options={[
            { value: "none", label: "None" },
            ...(brandAssets ?? []).map((asset) => ({ value: asset.id, label: asset.label })),
          ]}
          hint="Only your own branding. Upload it as a project asset first."
        />

        <Select
          id="render-audio"
          label="Music"
          value={settings.audio_asset_id ?? "none"}
          onValueChange={(value) => onChange({ audio_asset_id: value === "none" ? null : value })}
          options={[
            { value: "none", label: "No audio" },
            ...(audioAssets ?? []).map((asset) => ({ value: asset.id, label: asset.label })),
          ]}
          hint="Upload only audio you hold the rights to use."
        />
        {settings.audio_asset_id ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <Slider
              id="render-audio-start"
              label="Audio start"
              value={settings.audio_start_seconds}
              min={0}
              max={300}
              step={0.5}
              onValueChange={(audio_start_seconds) => onChange({ audio_start_seconds })}
              format={(value) => `${value.toFixed(1)}s`}
            />
            <Slider
              id="render-audio-volume"
              label="Volume"
              value={settings.audio_volume}
              min={0}
              max={1}
              step={0.05}
              onValueChange={(audio_volume) => onChange({ audio_volume })}
              format={(value) => `${Math.round(value * 100)}%`}
            />
          </div>
        ) : null}
      </section>

      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-[var(--color-ink)]">Disclosure</h3>
        <Switch
          id="render-end-card"
          label="Show the end card"
          description={
            options?.disclosure.end_card_text ?? "Timelapse reconstructed from finished artwork."
          }
          checked={settings.end_card_disclosure}
          onCheckedChange={(end_card_disclosure) => onChange({ end_card_disclosure })}
        />
        <Alert tone="info">
          <p>
            Every export is labelled{" "}
            <Badge tone="info">{options?.disclosure.reconstruction_type ?? "reconstruction"}</Badge>{" "}
            in its file metadata. That is written on every render and cannot be turned off. The
            visible end card above is on by default and is yours to switch off.
          </p>
        </Alert>
      </section>
    </div>
  );
}
