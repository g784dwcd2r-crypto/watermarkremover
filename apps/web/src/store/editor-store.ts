/**
 * Editor state.
 *
 * Kept in Zustand rather than React state because the canvas, the toolbar, the
 * adjustment panel and the keyboard shortcut layer all read and write the same
 * document, and undo/redo has to snapshot it atomically.
 *
 * History stores whole region lists. Masks are small (a few hundred points at
 * most), so the simplicity is worth more than the bytes.
 */

"use client";

import type {
  MaskAdjustments,
  MaskEditorState,
  MaskPoint,
  MaskRegion,
  MaskRegionKind,
} from "@artrestore/types";
import { create } from "zustand";

export type EditorTool = "brush" | "eraser" | "rect" | "polygon" | "lasso" | "pan";
export type WorkspaceTheme = "light" | "dark";
export type ComparisonView = "single" | "split" | "slider" | "difference";

export const MAX_HISTORY = 60;
export const MIN_ZOOM = 0.05;
export const MAX_ZOOM = 12;

export interface BrushSettings {
  size: number;
  hardness: number;
  opacity: number;
}

interface EditorSnapshot {
  regions: MaskRegion[];
  adjustments: MaskAdjustments;
}

export interface EditorState {
  // document
  imageSize: { width: number; height: number };
  regions: MaskRegion[];
  adjustments: MaskAdjustments;

  // tools
  tool: EditorTool;
  brush: BrushSettings;
  activePoints: MaskPoint[];
  drawing: boolean;
  /** Vertices placed so far by the polygon tool, between clicks. */
  polygonPoints: MaskPoint[];

  // view
  zoom: number;
  pan: { x: number; y: number };
  theme: WorkspaceTheme;
  comparison: ComparisonView;
  sliderPosition: number;
  showMask: boolean;

  // history
  past: EditorSnapshot[];
  future: EditorSnapshot[];
  dirty: boolean;
  lastSavedVersion: number | null;

  // actions
  setImageSize: (size: { width: number; height: number }) => void;
  setTool: (tool: EditorTool) => void;
  setBrush: (patch: Partial<BrushSettings>) => void;
  setAdjustments: (patch: Partial<MaskAdjustments>) => void;
  beginStroke: (point: MaskPoint) => void;
  extendStroke: (point: MaskPoint) => void;
  endStroke: () => void;
  addPolygonPoint: (point: MaskPoint) => void;
  closePolygon: () => void;
  cancelPolygon: () => void;
  addRegion: (region: Omit<MaskRegion, "id">) => void;
  removeRegion: (id: string) => void;
  clearMask: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;
  setZoom: (zoom: number) => void;
  zoomBy: (factor: number) => void;
  setPan: (pan: { x: number; y: number }) => void;
  fitToScreen: (viewport: { width: number; height: number }) => void;
  actualSize: () => void;
  setTheme: (theme: WorkspaceTheme) => void;
  setComparison: (view: ComparisonView) => void;
  setSliderPosition: (value: number) => void;
  toggleMaskVisibility: () => void;
  markSaved: (version: number) => void;
  loadEditorState: (state: MaskEditorState) => void;
  toEditorState: () => MaskEditorState;
  reset: () => void;
}

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `region-${Math.random().toString(36).slice(2, 10)}`;
}

const DEFAULT_ADJUSTMENTS: MaskAdjustments = { expand: 1, feather: 2, blur: 0 };
const DEFAULT_BRUSH: BrushSettings = { size: 32, hardness: 0.8, opacity: 1 };

function snapshot(state: EditorState): EditorSnapshot {
  return {
    regions: state.regions.map((region) => ({ ...region })),
    adjustments: { ...state.adjustments },
  };
}

export const useEditorStore = create<EditorState>((set, get) => ({
  imageSize: { width: 0, height: 0 },
  regions: [],
  adjustments: { ...DEFAULT_ADJUSTMENTS },

  tool: "brush",
  brush: { ...DEFAULT_BRUSH },
  activePoints: [],
  drawing: false,
  polygonPoints: [],

  zoom: 1,
  pan: { x: 0, y: 0 },
  theme: "light",
  comparison: "single",
  sliderPosition: 0.5,
  showMask: true,

  past: [],
  future: [],
  dirty: false,
  lastSavedVersion: null,

  setImageSize: (imageSize) => set({ imageSize }),
  setTool: (tool) => set({ tool, activePoints: [], drawing: false, polygonPoints: [] }),
  setBrush: (patch) => set((state) => ({ brush: { ...state.brush, ...patch } })),

  setAdjustments: (patch) =>
    set((state) => ({
      past: [...state.past, snapshot(state)].slice(-MAX_HISTORY),
      future: [],
      adjustments: { ...state.adjustments, ...patch },
      dirty: true,
    })),

  beginStroke: (point) => set({ drawing: true, activePoints: [point] }),

  extendStroke: (point) =>
    set((state) => (state.drawing ? { activePoints: [...state.activePoints, point] } : {})),

  endStroke: () => {
    const state = get();
    if (!state.drawing || state.activePoints.length === 0) {
      set({ drawing: false, activePoints: [] });
      return;
    }
    const { tool, brush, activePoints } = state;
    let region: Omit<MaskRegion, "id"> | null = null;

    if (tool === "brush" || tool === "eraser") {
      region = {
        type: tool as MaskRegionKind,
        points: activePoints,
        size: brush.size,
        hardness: brush.hardness,
        opacity: brush.opacity,
        mode: tool === "eraser" ? "subtract" : "add",
      };
    } else if (tool === "lasso" && activePoints.length >= 3) {
      region = { type: "lasso", points: activePoints, mode: "add" };
    } else if (tool === "rect" && activePoints.length >= 2) {
      const start = activePoints[0]!;
      const end = activePoints[activePoints.length - 1]!;
      region = {
        type: "rect",
        x: Math.min(start.x, end.x),
        y: Math.min(start.y, end.y),
        width: Math.abs(end.x - start.x),
        height: Math.abs(end.y - start.y),
        mode: "add",
      };
    }

    if (!region) {
      set({ drawing: false, activePoints: [] });
      return;
    }
    set((current) => ({
      past: [...current.past, snapshot(current)].slice(-MAX_HISTORY),
      future: [],
      regions: [...current.regions, { id: newId(), ...region! }],
      drawing: false,
      activePoints: [],
      dirty: true,
    }));
  },

  // The polygon tool places vertices with individual clicks rather than a drag,
  // so it lives outside the stroke cycle entirely.
  addPolygonPoint: (point) => set((state) => ({ polygonPoints: [...state.polygonPoints, point] })),

  closePolygon: () => {
    const { polygonPoints } = get();
    if (polygonPoints.length < 3) {
      set({ polygonPoints: [] });
      return;
    }
    set((state) => ({
      past: [...state.past, snapshot(state)].slice(-MAX_HISTORY),
      future: [],
      regions: [
        ...state.regions,
        { id: newId(), type: "polygon", points: polygonPoints, mode: "add" },
      ],
      polygonPoints: [],
      dirty: true,
    }));
  },

  cancelPolygon: () => set({ polygonPoints: [] }),

  addRegion: (region) =>
    set((state) => ({
      past: [...state.past, snapshot(state)].slice(-MAX_HISTORY),
      future: [],
      regions: [...state.regions, { id: newId(), ...region }],
      dirty: true,
    })),

  removeRegion: (id) =>
    set((state) => ({
      past: [...state.past, snapshot(state)].slice(-MAX_HISTORY),
      future: [],
      regions: state.regions.filter((region) => region.id !== id),
      dirty: true,
    })),

  clearMask: () =>
    set((state) => ({
      past: [...state.past, snapshot(state)].slice(-MAX_HISTORY),
      future: [],
      regions: [],
      activePoints: [],
      drawing: false,
      dirty: true,
    })),

  undo: () =>
    set((state) => {
      const previous = state.past[state.past.length - 1];
      if (!previous) return {};
      return {
        past: state.past.slice(0, -1),
        future: [snapshot(state), ...state.future].slice(0, MAX_HISTORY),
        regions: previous.regions,
        adjustments: previous.adjustments,
        dirty: true,
      };
    }),

  redo: () =>
    set((state) => {
      const next = state.future[0];
      if (!next) return {};
      return {
        past: [...state.past, snapshot(state)].slice(-MAX_HISTORY),
        future: state.future.slice(1),
        regions: next.regions,
        adjustments: next.adjustments,
        dirty: true,
      };
    }),

  canUndo: () => get().past.length > 0,
  canRedo: () => get().future.length > 0,

  setZoom: (zoom) => set({ zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)) }),
  zoomBy: (factor) =>
    set((state) => ({ zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, state.zoom * factor)) })),
  setPan: (pan) => set({ pan }),

  fitToScreen: (viewport) => {
    const { imageSize } = get();
    if (!imageSize.width || !imageSize.height || !viewport.width || !viewport.height) return;
    const scale = Math.min(viewport.width / imageSize.width, viewport.height / imageSize.height);
    set({
      zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, scale)),
      pan: {
        x: (viewport.width - imageSize.width * scale) / 2,
        y: (viewport.height - imageSize.height * scale) / 2,
      },
    });
  },

  actualSize: () => set({ zoom: 1, pan: { x: 0, y: 0 } }),
  setTheme: (theme) => set({ theme }),
  setComparison: (comparison) => set({ comparison }),
  setSliderPosition: (sliderPosition) =>
    set({ sliderPosition: Math.min(1, Math.max(0, sliderPosition)) }),
  toggleMaskVisibility: () => set((state) => ({ showMask: !state.showMask })),
  markSaved: (version) => set({ dirty: false, lastSavedVersion: version }),

  loadEditorState: (state) =>
    set({
      imageSize: state.image,
      regions: state.regions.map((region) => ({ ...region, id: region.id || newId() })),
      polygonPoints: [],
      adjustments: { ...DEFAULT_ADJUSTMENTS, ...state.adjustments },
      past: [],
      future: [],
      dirty: false,
    }),

  toEditorState: () => {
    const { imageSize, regions, adjustments } = get();
    return {
      version: 1,
      image: imageSize,
      regions,
      adjustments,
    };
  },

  reset: () =>
    set({
      regions: [],
      adjustments: { ...DEFAULT_ADJUSTMENTS },
      activePoints: [],
      drawing: false,
      polygonPoints: [],
      past: [],
      future: [],
      dirty: false,
      lastSavedVersion: null,
      zoom: 1,
      pan: { x: 0, y: 0 },
    }),
}));

/** True when the mask has any content to process. */
export function hasMaskContent(state: Pick<EditorState, "regions">): boolean {
  return state.regions.some((region) => region.mode !== "subtract" && region.type !== "eraser");
}
