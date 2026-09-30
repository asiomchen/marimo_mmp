import { hideTooltip } from "./tooltips";
import type { AnywidgetModel, ViewRefs } from "./types";

const expandedMarimoOutputs = new WeakMap<HTMLElement, {
  views: number;
  maxHeight: string;
  maxHeightPriority: string;
  overflow: string;
  overflowPriority: string;
}>();

export function updateHeight(model: AnywidgetModel, refs: ViewRefs): void {
  const requested = Number(model.get("height"));
  const height = Number.isFinite(requested) ? Math.max(480, Math.round(requested)) : 1220;
  refs.stage.style.setProperty("--mmp-graph-height", `${height}px`);
  refs.requestFrame(() => updatePanAvailability(refs));
}

export function releaseMarimoOutputHeightLimit(el: HTMLElement): () => void {
  const root = el.getRootNode();
  const rootHost = "host" in root ? (root as ShadowRoot).host : null;
  const host: Element = rootHost && typeof rootHost.closest === "function" ? rootHost : el;
  const outputArea = host.closest<HTMLElement>(".marimo-cell.interactive .output-area");
  if (!outputArea) return () => {};

  let state = expandedMarimoOutputs.get(outputArea);
  if (state) {
    state.views += 1;
  } else {
    state = {
      views: 1,
      maxHeight: outputArea.style.getPropertyValue("max-height"),
      maxHeightPriority: outputArea.style.getPropertyPriority("max-height"),
      overflow: outputArea.style.getPropertyValue("overflow"),
      overflowPriority: outputArea.style.getPropertyPriority("overflow"),
    };
    expandedMarimoOutputs.set(outputArea, state);
    outputArea.style.setProperty("max-height", "none");
    outputArea.style.setProperty("overflow", "visible");
  }

  let active = true;
  return () => {
    if (!active) return;
    active = false;
    state.views -= 1;
    if (state.views > 0) return;
    expandedMarimoOutputs.delete(outputArea);
    if (outputArea.style.getPropertyValue("max-height") === "none") {
      if (state.maxHeight) outputArea.style.setProperty("max-height", state.maxHeight, state.maxHeightPriority);
      else outputArea.style.removeProperty("max-height");
    }
    if (outputArea.style.getPropertyValue("overflow") === "visible") {
      if (state.overflow) outputArea.style.setProperty("overflow", state.overflow, state.overflowPriority);
      else outputArea.style.removeProperty("overflow");
    }
  };
}

export function updatePanAvailability(refs: ViewRefs): void {
  const canPan = refs.stage.scrollWidth > refs.stage.clientWidth || refs.stage.scrollHeight > refs.stage.clientHeight;
  refs.stage.classList.toggle("is-pannable", canPan);
}

export function attachDragPan(refs: ViewRefs, signal: AbortSignal): void {
  const threshold = 5;
  let drag: {
    pointerId: number;
    clientX: number;
    clientY: number;
    scrollLeft: number;
    scrollTop: number;
    moved: boolean;
  } | null = null;
  let suppressClick = false;

  refs.stage.addEventListener("pointerdown", (event) => {
    if (!event.isPrimary || event.button !== 0 || event.pointerType === "touch") return;
    drag = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      scrollLeft: refs.stage.scrollLeft,
      scrollTop: refs.stage.scrollTop,
      moved: false,
    };
  }, { signal });

  refs.stage.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const deltaX = event.clientX - drag.clientX;
    const deltaY = event.clientY - drag.clientY;
    if (!drag.moved && Math.hypot(deltaX, deltaY) < threshold) return;
    if (!drag.moved) {
      drag.moved = true;
      refs.stage.setPointerCapture(event.pointerId);
      refs.stage.classList.add("is-panning");
      hideTooltip(refs);
    }
    event.preventDefault();
    refs.stage.scrollLeft = drag.scrollLeft - deltaX;
    refs.stage.scrollTop = drag.scrollTop - deltaY;
  }, { signal });

  const finish = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    const moved = drag.moved;
    const pointerId = drag.pointerId;
    drag = null;
    refs.stage.classList.remove("is-panning");
    if (refs.stage.hasPointerCapture(pointerId)) refs.stage.releasePointerCapture(pointerId);
    if (moved) {
      suppressClick = true;
      refs.setViewTimeout(() => { suppressClick = false; }, 0);
    }
  };
  refs.stage.addEventListener("pointerup", finish, { signal });
  refs.stage.addEventListener("pointercancel", finish, { signal });
  refs.stage.addEventListener("lostpointercapture", finish, { signal });
  refs.stage.addEventListener("click", (event) => {
    if (!suppressClick) return;
    event.preventDefault();
    event.stopPropagation();
    suppressClick = false;
  }, { capture: true, signal });
}

export function updateCanvasSize(refs: ViewRefs, size: number): void {
  const previousSize = refs.layoutSize || size;
  const centerRatioX = refs.layoutSize ? (refs.stage.scrollLeft + refs.stage.clientWidth / 2) / previousSize : 0.5;
  const centerRatioY = refs.layoutSize ? (refs.stage.scrollTop + refs.stage.clientHeight / 2) / previousSize : 0.5;
  refs.layoutSize = size;
  refs.canvas.setAttribute("viewBox", `0 0 ${size} ${size}`);
  refs.canvas.style.setProperty("--mmp-canvas-size", `${size}px`);
  refs.requestFrame(() => {
    refs.stage.scrollLeft = Math.max(0, centerRatioX * size - refs.stage.clientWidth / 2);
    refs.stage.scrollTop = Math.max(0, centerRatioY * size - refs.stage.clientHeight / 2);
    updatePanAvailability(refs);
  });
}
