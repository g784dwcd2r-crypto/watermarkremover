import { beforeEach, describe, expect, it } from "vitest";

import { hasMaskContent, useEditorStore } from "@/store/editor-store";

const store = () => useEditorStore.getState();

describe("editor store", () => {
  beforeEach(() => {
    store().reset();
    store().setImageSize({ width: 800, height: 600 });
  });

  it("starts empty", () => {
    expect(store().regions).toHaveLength(0);
    expect(store().canUndo()).toBe(false);
    expect(hasMaskContent(store())).toBe(false);
  });

  it("records a brush stroke as one region", () => {
    store().setTool("brush");
    store().beginStroke({ x: 10, y: 10 });
    store().extendStroke({ x: 40, y: 30 });
    store().endStroke();

    const [region] = store().regions;
    expect(store().regions).toHaveLength(1);
    expect(region?.type).toBe("brush");
    expect(region?.points).toHaveLength(2);
    expect(region?.size).toBe(store().brush.size);
    expect(hasMaskContent(store())).toBe(true);
  });

  it("records an eraser stroke as a subtractive region", () => {
    store().setTool("eraser");
    store().beginStroke({ x: 5, y: 5 });
    store().extendStroke({ x: 9, y: 9 });
    store().endStroke();

    expect(store().regions[0]?.mode).toBe("subtract");
    expect(hasMaskContent(store())).toBe(false);
  });

  it("normalises a rectangle drawn in any direction", () => {
    store().setTool("rect");
    store().beginStroke({ x: 90, y: 80 });
    store().extendStroke({ x: 30, y: 20 });
    store().endStroke();

    const [region] = store().regions;
    expect(region).toMatchObject({ type: "rect", x: 30, y: 20, width: 60, height: 60 });
  });

  it("ignores a lasso with too few points", () => {
    store().setTool("lasso");
    store().beginStroke({ x: 1, y: 1 });
    store().extendStroke({ x: 2, y: 2 });
    store().endStroke();
    expect(store().regions).toHaveLength(0);
  });

  it("undoes and redoes a stroke", () => {
    store().setTool("brush");
    store().beginStroke({ x: 1, y: 1 });
    store().extendStroke({ x: 2, y: 2 });
    store().endStroke();
    expect(store().regions).toHaveLength(1);

    store().undo();
    expect(store().regions).toHaveLength(0);
    expect(store().canRedo()).toBe(true);

    store().redo();
    expect(store().regions).toHaveLength(1);
  });

  it("treats an adjustment change as an undoable step", () => {
    store().setAdjustments({ feather: 12 });
    expect(store().adjustments.feather).toBe(12);
    store().undo();
    expect(store().adjustments.feather).toBe(2);
  });

  it("clamps zoom to the supported range", () => {
    store().setZoom(500);
    expect(store().zoom).toBeLessThanOrEqual(12);
    store().setZoom(0);
    expect(store().zoom).toBeGreaterThan(0);
  });

  it("fits the image to a viewport and centres it", () => {
    store().fitToScreen({ width: 400, height: 600 });
    expect(store().zoom).toBeCloseTo(0.5, 5);
    expect(store().pan.y).toBeCloseTo(150, 5);
  });

  it("round-trips through the editor-state document", () => {
    store().setTool("rect");
    store().beginStroke({ x: 0, y: 0 });
    store().extendStroke({ x: 50, y: 50 });
    store().endStroke();
    store().setAdjustments({ expand: 4 });

    const document = store().toEditorState();
    expect(document.image).toEqual({ width: 800, height: 600 });
    expect(document.regions).toHaveLength(1);

    store().reset();
    expect(store().regions).toHaveLength(0);

    store().loadEditorState(document);
    expect(store().regions).toHaveLength(1);
    expect(store().adjustments.expand).toBe(4);
    expect(store().dirty).toBe(false);
  });

  it("marks the document clean once saved", () => {
    store().setTool("brush");
    store().beginStroke({ x: 1, y: 1 });
    store().endStroke();
    expect(store().dirty).toBe(true);

    store().markSaved(3);
    expect(store().dirty).toBe(false);
    expect(store().lastSavedVersion).toBe(3);
  });

  it("caps the undo history", () => {
    store().setTool("brush");
    for (let index = 0; index < 80; index += 1) {
      store().beginStroke({ x: index, y: index });
      store().endStroke();
    }
    expect(store().past.length).toBeLessThanOrEqual(60);
  });
});
