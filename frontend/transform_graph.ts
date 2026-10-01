import "./transform_graph.css";

import { createControlSync } from "./transform_graph/controls";
import { renderGraph } from "./transform_graph/graph";
import { updateSelection } from "./transform_graph/selection";
import { buildShell } from "./transform_graph/shell";
import type { AnywidgetModel, FrameId, ModelCallback, TimerId, ViewRefs, WidgetState } from "./transform_graph/types";
import {
  attachDragPan,
  releaseMarimoOutputHeightLimit,
  updateHeight,
  updatePanAvailability,
} from "./transform_graph/viewport";

export { resolveDepiction } from "./transform_graph/depiction";

export function render({
  model,
  el,
  signal,
}: {
  model: AnywidgetModel;
  el: HTMLElement;
  signal?: AbortSignal;
}): () => void {
  const viewController = new AbortController();
  const lifecycleSignal = viewController.signal;
  const forwardHostAbort = () => viewController.abort();
  if (signal) {
    if (signal.aborted) viewController.abort();
    else signal.addEventListener("abort", forwardHostAbort, { once: true });
  }
  const restoreMarimoOutput = releaseMarimoOutputHeightLimit(el);
  const timers = new Set<TimerId>();
  const frames = new Set<FrameId>();
  let refs: ViewRefs;
  const controlSync = createControlSync(model, () => refs);
  const shell = buildShell(model, el, lifecycleSignal, controlSync.submit, timers);
  const setViewTimeout = (callback: () => void, delay: number): TimerId => {
    const timer = setTimeout(() => {
      timers.delete(timer);
      if (!lifecycleSignal.aborted) callback();
    }, delay);
    timers.add(timer);
    return timer;
  };
  const requestFrame = (callback: () => void): FrameId => {
    const frame = requestAnimationFrame(() => {
      frames.delete(frame);
      if (!lifecycleSignal.aborted) callback();
    });
    frames.add(frame);
    return frame;
  };
  refs = { ...shell, controlSync, setViewTimeout, requestFrame };
  attachDragPan(refs, lifecycleSignal);
  refs.toggle.addEventListener("click", () => {
    const collapsed = refs.frame.classList.toggle("is-collapsed");
    refs.toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    refs.toggle.setAttribute(
      "aria-label",
      collapsed ? "Expand controls" : "Collapse controls",
    );
    refs.requestFrame(() => updatePanAvailability(refs));
  }, { signal: lifecycleSignal });
  let cleaned = false;
  let renderQueued = false;
  const scheduleGraphRender = () => {
    if (cleaned || renderQueued) return;
    renderQueued = true;
    queueMicrotask(() => {
      renderQueued = false;
      if (!cleaned) renderGraph(model, refs);
    });
  };
  const onSelectionChanged = () => updateSelection(model, refs);
  const onAcceptedControlsChanged = () => controlSync.acceptedChanged();
  const onDirectionChanged = () => {
    controlSync.acceptedChanged();
    scheduleGraphRender();
  };
  const onHeightChanged = () => updateHeight(model, refs);
  const modelListeners: Array<[`change:${keyof WidgetState}`, ModelCallback]> = [
    ["change:data", scheduleGraphRender],
    ["change:depictions", scheduleGraphRender],
    ["change:selected_id", onSelectionChanged],
    ["change:filters", onAcceptedControlsChanged],
    ["change:property_name", onAcceptedControlsChanged],
    ["change:direction", onDirectionChanged],
    ["change:max_nodes", onAcceptedControlsChanged],
    ["change:_control_request", controlSync.requestChanged],
    ["change:_control_response", controlSync.responseChanged],
    ["change:height", onHeightChanged],
  ];
  for (const [event, callback] of modelListeners) model.on(event, callback);

  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    signal?.removeEventListener("abort", forwardHostAbort);
    for (const [event, callback] of modelListeners) model.off(event, callback);
    for (const timer of timers) clearTimeout(timer);
    timers.clear();
    for (const frame of frames) cancelAnimationFrame(frame);
    frames.clear();
    el.replaceChildren();
    el.classList.remove("mmp-instrument");
    restoreMarimoOutput();
  };
  lifecycleSignal.addEventListener("abort", cleanup, { once: true });

  if (lifecycleSignal.aborted) cleanup();
  else {
    updateHeight(model, refs);
    scheduleGraphRender();
  }
  return () => {
    viewController.abort();
    cleanup();
  };
}

export default { render };
