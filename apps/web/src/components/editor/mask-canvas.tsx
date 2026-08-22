"use client";

import type { DetectedRegion, MaskPoint, MaskRegion } from "@artrestore/types";
import Konva from "konva";
import * as React from "react";
import { Circle, Group, Image as KonvaImage, Layer, Line, Rect, Stage } from "react-konva";

import { useEditorStore } from "@/store/editor-store";

const MASK_COLOUR = "#17b8b8";
const PROTECTED_COLOUR = "#d9534f";

/** Load an image element for Konva, tolerating cross-origin signed URLs. */
function useImageElement(src: string | null) {
  // The loaded element is stored with the src it came from, so a src change
  // reads as "not loaded yet" during render instead of needing a reset effect.
  const [loaded, setLoaded] = React.useState<{ src: string; element: HTMLImageElement } | null>(
    null,
  );

  React.useEffect(() => {
    if (!src) return;
    const element = new window.Image();
    element.crossOrigin = "anonymous";
    element.onload = () => setLoaded({ src, element });
    element.src = src;
    return () => {
      element.onload = null;
      element.onerror = null;
    };
  }, [src]);

  return loaded && loaded.src === src ? loaded.element : null;
}

function regionPoints(points: MaskPoint[] | undefined): number[] {
  if (!points) return [];
  return points.flatMap((point) => [point.x, point.y]);
}

/**
 * The interactive mask editor canvas.
 *
 * Drawing happens in image coordinates, so a mask is resolution-independent:
 * the same document rasterises identically at preview size and at full size,
 * which is what lets the server re-derive the mask from stored state.
 */
export function MaskCanvas({
  imageUrl,
  protectedRegions = [],
  suggestions = [],
  onSuggestionClick,
  className,
}: {
  imageUrl: string | null;
  protectedRegions?: DetectedRegion[];
  suggestions?: DetectedRegion[];
  onSuggestionClick?: (region: DetectedRegion) => void;
  className?: string;
}) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const stageRef = React.useRef<Konva.Stage>(null);
  const [viewport, setViewport] = React.useState({ width: 0, height: 0 });
  const image = useImageElement(imageUrl);

  const {
    imageSize,
    regions,
    activePoints,
    drawing,
    tool,
    brush,
    zoom,
    pan,
    theme,
    showMask,
    setImageSize,
    beginStroke,
    extendStroke,
    endStroke,
    setPan,
    zoomBy,
    fitToScreen,
  } = useEditorStore();

  React.useEffect(() => {
    if (!image) return;
    setImageSize({ width: image.naturalWidth, height: image.naturalHeight });
  }, [image, setImageSize]);

  React.useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      setViewport({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const fitted = React.useRef(false);
  React.useEffect(() => {
    if (fitted.current || !viewport.width || !imageSize.width) return;
    fitted.current = true;
    fitToScreen(viewport);
  }, [viewport, imageSize, fitToScreen]);

  const toImageCoords = React.useCallback((): MaskPoint | null => {
    const stage = stageRef.current;
    if (!stage) return null;
    const pointer = stage.getPointerPosition();
    if (!pointer) return null;
    return { x: (pointer.x - pan.x) / zoom, y: (pointer.y - pan.y) / zoom };
  }, [pan, zoom]);

  const handlePointerDown = () => {
    if (tool === "pan") return;
    const point = toImageCoords();
    if (point) beginStroke(point);
  };

  const handlePointerMove = () => {
    if (!drawing || tool === "pan") return;
    const point = toImageCoords();
    if (point) extendStroke(point);
  };

  const handlePointerUp = () => {
    if (tool === "pan") return;
    if (drawing) endStroke();
  };

  const handleWheel = (event: Konva.KonvaEventObject<WheelEvent>) => {
    event.evt.preventDefault();
    zoomBy(event.evt.deltaY < 0 ? 1.08 : 1 / 1.08);
  };

  const renderRegion = (region: MaskRegion, key: string, preview = false) => {
    const subtract = region.mode === "subtract" || region.type === "eraser";
    const common = {
      opacity: preview ? 0.55 : subtract ? 0.9 : 0.45,
      listening: false,
    };
    if (region.type === "brush" || region.type === "eraser") {
      return (
        <Line
          key={key}
          points={regionPoints(region.points)}
          stroke={subtract ? "#ffffff" : MASK_COLOUR}
          strokeWidth={region.size ?? brush.size}
          lineCap="round"
          lineJoin="round"
          tension={0.15}
          globalCompositeOperation={subtract ? "destination-out" : "source-over"}
          {...common}
        />
      );
    }
    if (region.type === "rect") {
      return (
        <Rect
          key={key}
          x={region.x ?? 0}
          y={region.y ?? 0}
          width={region.width ?? 0}
          height={region.height ?? 0}
          fill={MASK_COLOUR}
          globalCompositeOperation={subtract ? "destination-out" : "source-over"}
          {...common}
        />
      );
    }
    return (
      <Line
        key={key}
        points={regionPoints(region.points)}
        closed
        fill={MASK_COLOUR}
        globalCompositeOperation={subtract ? "destination-out" : "source-over"}
        {...common}
      />
    );
  };

  const previewRegion: MaskRegion | null = React.useMemo(() => {
    if (!drawing || activePoints.length === 0) return null;
    if (tool === "brush" || tool === "eraser") {
      return {
        id: "preview",
        type: tool,
        points: activePoints,
        size: brush.size,
        mode: tool === "eraser" ? "subtract" : "add",
      };
    }
    if (tool === "rect" && activePoints.length >= 2) {
      const start = activePoints[0]!;
      const end = activePoints[activePoints.length - 1]!;
      return {
        id: "preview",
        type: "rect",
        x: Math.min(start.x, end.x),
        y: Math.min(start.y, end.y),
        width: Math.abs(end.x - start.x),
        height: Math.abs(end.y - start.y),
      };
    }
    if (activePoints.length >= 2) {
      return { id: "preview", type: "lasso", points: activePoints };
    }
    return null;
  }, [drawing, activePoints, tool, brush.size]);

  return (
    <div
      ref={containerRef}
      className={className}
      data-testid="mask-canvas"
      style={{
        backgroundColor: theme === "dark" ? "var(--color-canvas-dark)" : "var(--color-canvas-light)",
        touchAction: "none",
      }}
    >
      {viewport.width > 0 ? (
        <Stage
          ref={stageRef}
          width={viewport.width}
          height={viewport.height}
          draggable={tool === "pan"}
          onDragEnd={(event) => setPan({ x: event.target.x(), y: event.target.y() })}
          x={pan.x}
          y={pan.y}
          scaleX={zoom}
          scaleY={zoom}
          onMouseDown={handlePointerDown}
          onMouseMove={handlePointerMove}
          onMouseUp={handlePointerUp}
          onTouchStart={handlePointerDown}
          onTouchMove={handlePointerMove}
          onTouchEnd={handlePointerUp}
          onWheel={handleWheel}
        >
          <Layer listening={false}>
            {image ? <KonvaImage image={image} x={0} y={0} /> : null}
          </Layer>

          {showMask ? (
            <Layer listening={false} opacity={1} className="mask-overlay">
              <Group>
                {regions.map((region) => renderRegion(region, region.id))}
                {previewRegion ? renderRegion(previewRegion, "preview", true) : null}
              </Group>
            </Layer>
          ) : null}

          <Layer>
            {protectedRegions.map((region, index) => (
              <Group key={`protected-${index}`} listening={false}>
                <Rect
                  x={region.x}
                  y={region.y}
                  width={region.width}
                  height={region.height}
                  stroke={PROTECTED_COLOUR}
                  strokeWidth={Math.max(1.5, 2 / zoom)}
                  dash={[8 / zoom, 6 / zoom]}
                  fill={`${PROTECTED_COLOUR}18`}
                />
              </Group>
            ))}
            {suggestions.map((region, index) => (
              <Rect
                key={`suggestion-${index}`}
                x={region.x}
                y={region.y}
                width={region.width}
                height={region.height}
                stroke="#f0b429"
                strokeWidth={Math.max(1, 1.5 / zoom)}
                dash={[5 / zoom, 5 / zoom]}
                onClick={() => onSuggestionClick?.(region)}
                onTap={() => onSuggestionClick?.(region)}
              />
            ))}
          </Layer>

          {tool === "brush" || tool === "eraser" ? (
            <Layer listening={false}>
              <BrushCursor stageRef={stageRef} zoom={zoom} pan={pan} size={brush.size} />
            </Layer>
          ) : null}
        </Stage>
      ) : null}
    </div>
  );
}

/** A ring showing the true brush footprint at the current zoom. */
function BrushCursor({
  stageRef,
  zoom,
  pan,
  size,
}: {
  stageRef: React.RefObject<Konva.Stage | null>;
  zoom: number;
  pan: { x: number; y: number };
  size: number;
}) {
  const [position, setPosition] = React.useState<MaskPoint | null>(null);

  React.useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const update = () => {
      const pointer = stage.getPointerPosition();
      setPosition(
        pointer ? { x: (pointer.x - pan.x) / zoom, y: (pointer.y - pan.y) / zoom } : null,
      );
    };
    stage.on("mousemove.brushcursor touchmove.brushcursor", update);
    stage.on("mouseleave.brushcursor", () => setPosition(null));
    return () => {
      stage.off(".brushcursor");
    };
  }, [stageRef, zoom, pan]);

  if (!position) return null;
  return (
    <Circle
      x={position.x}
      y={position.y}
      radius={size / 2}
      stroke="#ffffff"
      strokeWidth={1.5 / zoom}
      shadowColor="#000000"
      shadowBlur={2 / zoom}
      listening={false}
    />
  );
}
